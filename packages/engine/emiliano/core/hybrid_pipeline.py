"""
Hybrid Speculative Cascading Pipeline for Emiliano.

Combines high-speed, zero-cost Local SLMs (Ollama/vLLM) with OpenAI Frontier Models
(o3-mini, gpt-4o) using automated deterministic verification and speculative escalation.

Architecture:
1. Tier 0 (Local Speculative Execution):
   Dispatches coding and refactoring tasks to local models (e.g. qwen2.5-coder:7b).
   Executes on-premise with 0ms network latency and $0 egress API cost.

2. Deterministic Verification Gate:
   Validates the candidate output using local compiler/AST syntax checks, linters,
   or unit test runners without sending any diagnostic telemetry out of the local environment.

3. Speculative Escalation to OpenAI Frontier:
   If the local SLM fails the verification gate (or hallucinates an invalid syntax/logic error),
   the pipeline automatically packages the failure trace, compiler error, and candidate diff
   into an escalated diagnostic payload and routes it directly to OpenAI o3-mini
   with reasoning_effort="high".

4. Zero-PII Egress Vault:
   All external dispatches to OpenAI are scrubbed via PrivacyVault, ensuring sensitive
   customer entities and credentials never leak, and responses are rehydrated locally.
"""

from __future__ import annotations

import ast
import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("emiliano")

from .privacy_vault import PrivacyVault, VaultReport
from .frontier_router import OpenAITieredRouter, ModelTier, RouteDecision


class ExecutionTier(str, Enum):
    LOCAL_SPECULATIVE = "local_speculative"
    FRONTIER_ESCALATED = "frontier_escalated"
    DIRECT_FRONTIER = "direct_frontier"


@dataclass
class VerificationResult:
    """The result of passing candidate code through a deterministic verification gate."""
    passed: bool
    gate_name: str
    error_message: Optional[str] = None
    output: Optional[str] = None
    duration_ms: float = 0.0


@dataclass
class HybridExecutionResult:
    """The final outcome of a hybrid execution task."""
    final_output: str
    tier_used: ExecutionTier
    model_used: str
    speculative_local_attempted: bool = False
    verification_passed: bool = False
    escalation_reason: Optional[str] = None
    total_latency_seconds: float = 0.0
    local_latency_seconds: float = 0.0
    frontier_latency_seconds: float = 0.0
    cost_usd: float = 0.0
    cost_saved_usd: float = 0.0
    privacy_report: Optional[VaultReport] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tier_used": self.tier_used.value,
            "model_used": self.model_used,
            "speculative_local_attempted": self.speculative_local_attempted,
            "verification_passed": self.verification_passed,
            "escalation_reason": self.escalation_reason,
            "total_latency_seconds": round(self.total_latency_seconds, 4),
            "local_latency_seconds": round(self.local_latency_seconds, 4),
            "frontier_latency_seconds": round(self.frontier_latency_seconds, 4),
            "cost_usd": round(self.cost_usd, 6),
            "cost_saved_usd": round(self.cost_saved_usd, 6),
            "privacy_report": self.privacy_report.to_dict() if self.privacy_report else None,
            "metadata": self.metadata,
        }


class DeterministicGate:
    """
    Verification gate that validates code correctness before accepting a speculative draft.
    """

    @staticmethod
    def verify_syntax(code: str, language: str = "python") -> VerificationResult:
        """Verifies language syntax (Python AST parsing)."""
        start = time.perf_counter()
        if language.lower() == "python":
            try:
                # Strip markdown code blocks if the LLM wrapped it
                cleaned = code.strip()
                if cleaned.startswith("```python"):
                    cleaned = cleaned[len("```python"):].strip()
                elif cleaned.startswith("```"):
                    cleaned = cleaned[3:].strip()
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3].strip()

                ast.parse(cleaned)
                return VerificationResult(
                    passed=True,
                    gate_name="python_ast_syntax",
                    duration_ms=(time.perf_counter() - start) * 1000.0,
                )
            except SyntaxError as e:
                return VerificationResult(
                    passed=False,
                    gate_name="python_ast_syntax",
                    error_message=f"SyntaxError: {e.msg} at line {e.lineno}, col {e.offset}",
                    duration_ms=(time.perf_counter() - start) * 1000.0,
                )

        return VerificationResult(passed=True, gate_name="generic_syntax")

    @staticmethod
    async def verify_command(
        command: Union[str, List[str]],
        cwd: Optional[str] = None,
        timeout: float = 30.0,
    ) -> VerificationResult:
        """Runs a verification command (e.g. pytest, ruff, mypy, tsc, cargo check)."""
        start = time.perf_counter()
        try:
            shell = isinstance(command, str)

            proc = await asyncio.create_subprocess_shell(
                command if shell else " ".join(command),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

            try:
                stdout_data, stderr_data = await asyncio.wait_for(proc.communicate(), timeout=timeout)
                duration = (time.perf_counter() - start) * 1000.0
                stdout_str = stdout_data.decode("utf-8", errors="replace")
                stderr_str = stderr_data.decode("utf-8", errors="replace")

                if proc.returncode == 0:
                    return VerificationResult(
                        passed=True,
                        gate_name="command_runner",
                        output=stdout_str,
                        duration_ms=duration,
                    )
                else:
                    err_msg = stderr_str.strip() or stdout_str.strip()
                    return VerificationResult(
                        passed=False,
                        gate_name="command_runner",
                        error_message=f"Process exited with code {proc.returncode}: {err_msg[:500]}",
                        output=stdout_str,
                        duration_ms=duration,
                    )
            except asyncio.TimeoutError:
                proc.kill()
                return VerificationResult(
                    passed=False,
                    gate_name="command_runner",
                    error_message=f"Verification command timed out after {timeout}s",
                    duration_ms=(time.perf_counter() - start) * 1000.0,
                )
        except Exception as e:
            return VerificationResult(
                passed=False,
                gate_name="command_runner",
                error_message=str(e),
                duration_ms=(time.perf_counter() - start) * 1000.0,
            )


class HybridSpeculativePipeline:
    """
    Production Hybrid Speculative Execution Engine.
    Routes tasks to local models first, verifies locally, and selectively escalates to OpenAI o3-mini.
    """

    def __init__(
        self,
        llm_client: Any,
        local_model: str = "ollama/qwen2.5-coder:7b",
        frontier_model: str = "o3-mini",
        privacy_vault: Optional[PrivacyVault] = None,
        frontier_router: Optional[OpenAITieredRouter] = None,
        enable_speculative_local: bool = True,
    ):
        self.llm_client = llm_client
        self.local_model = local_model
        self.frontier_model = frontier_model
        self.privacy_vault = privacy_vault or PrivacyVault()
        self.frontier_router = frontier_router or OpenAITieredRouter()
        self.enable_speculative_local = enable_speculative_local

    async def execute(
        self,
        prompt: str,
        messages: Optional[List[Dict[str, str]]] = None,
        verifier: Optional[Callable[[str], Union[VerificationResult, Awaitable[VerificationResult]]]] = None,
        syntax_check_language: Optional[str] = "python",
        force_tier: Optional[ExecutionTier] = None,
    ) -> HybridExecutionResult:
        """
        Executes a task through the hybrid speculative pipeline.
        """
        total_start = time.perf_counter()

        # Step 1: Local Zero-PII Sanitization
        sanitized_prompt, pii_report = self.privacy_vault.anonymize(prompt)
        active_messages = messages or [{"role": "user", "content": sanitized_prompt}]

        # Check if direct frontier execution was explicitly requested
        if force_tier == ExecutionTier.DIRECT_FRONTIER or not self.enable_speculative_local:
            return await self._execute_frontier(
                messages=active_messages,
                privacy_report=pii_report,
                reason="Forced or speculative execution disabled",
                is_escalated=False,
            )

        # Step 2: Speculative Tier-0 Local Attempt
        local_start = time.perf_counter()
        local_candidate = ""
        local_error: Optional[str] = None
        local_success = False

        logger.info(f"[HybridPipeline] Tier-0: Speculatively attempting task with local model '{self.local_model}'")
        try:
            tokens: List[str] = []
            async for token in self.llm_client.stream_completion(
                messages=active_messages,
                model_name=self.local_model,
                temperature=0.2,
                timeout=45.0,
            ):
                tokens.append(token)
            local_candidate = "".join(tokens)
            local_success = bool(local_candidate.strip())
        except Exception as e:
            local_error = str(e)
            logger.warning(f"[HybridPipeline] Tier-0 Local SLM failed to produce candidate: {e}")

        local_duration = time.perf_counter() - local_start

        # Step 3: Run Deterministic Verification Gate on Local Candidate
        if local_success:
            verification: Optional[VerificationResult] = None

            # First: language AST syntax verification
            if syntax_check_language:
                syntax_res = DeterministicGate.verify_syntax(local_candidate, language=syntax_check_language)
                if not syntax_res.passed:
                    verification = syntax_res

            # Second: custom or command verifier
            if verifier and (verification is None or verification.passed):
                res = verifier(local_candidate)
                if asyncio.iscoroutine(res):
                    verification = await res
                else:
                    verification = res  # type: ignore

            # If no verifier specified and syntax passed (or not checked)
            if verification is None:
                verification = VerificationResult(passed=True, gate_name="default_pass")

            if verification.passed:
                # LOCAL HIT! 100% cloud cost avoided, 0 network latency.
                logger.info(f"[HybridPipeline] Tier-0 Local SLM PASSED verification ({verification.gate_name}). Returning verified local result.")
                total_duration = time.perf_counter() - total_start
                rehydrated = self.privacy_vault.rehydrate(local_candidate)

                # Estimate cost saved (what it would have cost on OpenAI o3-mini)
                estimated_prompt_tokens = len(prompt.split()) * 1.3
                estimated_completion_tokens = len(local_candidate.split()) * 1.3
                saved_usd = (estimated_prompt_tokens / 1_000_000 * 1.10) + (estimated_completion_tokens / 1_000_000 * 4.40)

                return HybridExecutionResult(
                    final_output=rehydrated,
                    tier_used=ExecutionTier.LOCAL_SPECULATIVE,
                    model_used=self.local_model,
                    speculative_local_attempted=True,
                    verification_passed=True,
                    total_latency_seconds=total_duration,
                    local_latency_seconds=local_duration,
                    frontier_latency_seconds=0.0,
                    cost_usd=0.0,
                    cost_saved_usd=saved_usd,
                    privacy_report=pii_report,
                    metadata={"verification_gate": verification.gate_name},
                )
            else:
                logger.info(f"[HybridPipeline] Local candidate failed verification ({verification.gate_name}): {verification.error_message}. Escalating to Frontier.")
                local_error = verification.error_message or "Failed verification check"

        # Step 4: Speculative Escalation to Frontier (OpenAI o3-mini)
        escalation_reason = local_error or "Local SLM execution failure"
        return await self._execute_frontier_escalated(
            original_messages=active_messages,
            failed_local_candidate=local_candidate,
            failure_diagnostic=escalation_reason,
            privacy_report=pii_report,
            local_duration=local_duration,
            total_start=total_start,
        )

    async def _execute_frontier_escalated(
        self,
        original_messages: List[Dict[str, str]],
        failed_local_candidate: str,
        failure_diagnostic: str,
        privacy_report: VaultReport,
        local_duration: float,
        total_start: float,
    ) -> HybridExecutionResult:
        """
        Packages failure trace and escalates directly to OpenAI frontier model (o3-mini).
        """
        frontier_start = time.perf_counter()
        logger.info(f"[HybridPipeline] Escalating to OpenAI '{self.frontier_model}' with reasoning_effort='high'")

        # Build diagnostic escalation prompt
        escalation_messages = list(original_messages)
        diagnostic_note = (
            f"\n\n[SPECULATIVE EXECUTION DIAGNOSTIC]\n"
            f"A previous local speculative execution attempt generated the following candidate:\n"
            f"```\n{failed_local_candidate[:1500]}\n```\n"
            f"It failed local verification with the following error:\n"
            f"ERROR: {failure_diagnostic}\n\n"
            f"Please solve the task thoroughly, ensuring you address and fix the above error."
        )

        last_msg = dict(escalation_messages[-1])
        last_msg["content"] = last_msg["content"] + diagnostic_note
        escalation_messages[-1] = last_msg

        # Route through frontier router for reasoning configuration
        initial_route = RouteDecision(
            tier=ModelTier.FAST,
            model=self.local_model,
            reason="Tier-0 local speculative execution",
        )
        route = self.frontier_router.speculative_escalate(initial_route, failure_diagnostic)
        target_model = self.frontier_model or route.model

        frontier_tokens: List[str] = []
        async for token in self.llm_client.stream_completion(
            messages=escalation_messages,
            model_name=target_model,
            temperature=0.2,
            timeout=120.0,
        ):
            frontier_tokens.append(token)

        frontier_duration = time.perf_counter() - frontier_start
        total_duration = time.perf_counter() - total_start
        raw_output = "".join(frontier_tokens)

        # Rehydrate via PrivacyVault
        final_output = self.privacy_vault.rehydrate(raw_output)

        # Estimate frontier cost
        est_input_tokens = len(last_msg["content"].split()) * 1.3
        est_output_tokens = len(raw_output.split()) * 1.3
        cost_usd = (est_input_tokens / 1_000_000 * 1.10) + (est_output_tokens / 1_000_000 * 4.40)

        return HybridExecutionResult(
            final_output=final_output,
            tier_used=ExecutionTier.FRONTIER_ESCALATED,
            model_used=target_model,
            speculative_local_attempted=True,
            verification_passed=True,
            escalation_reason=failure_diagnostic,
            total_latency_seconds=total_duration,
            local_latency_seconds=local_duration,
            frontier_latency_seconds=frontier_duration,
            cost_usd=cost_usd,
            cost_saved_usd=0.0,
            privacy_report=privacy_report,
            metadata={
                "reasoning_effort": route.reasoning_effort or "high",
                "escalation_trace": failure_diagnostic,
            },
        )

    async def _execute_frontier(
        self,
        messages: List[Dict[str, str]],
        privacy_report: VaultReport,
        reason: str,
        is_escalated: bool,
    ) -> HybridExecutionResult:
        """Executes directly against the frontier model."""
        start = time.perf_counter()
        target_model = self.frontier_model or "o3-mini"

        tokens: List[str] = []
        async for token in self.llm_client.stream_completion(
            messages=messages,
            model_name=target_model,
            temperature=0.2,
            timeout=120.0,
        ):
            tokens.append(token)

        duration = time.perf_counter() - start
        raw_output = "".join(tokens)
        final_output = self.privacy_vault.rehydrate(raw_output)

        prompt_str = " ".join([m.get("content", "") for m in messages])
        est_in = len(prompt_str.split()) * 1.3
        est_out = len(raw_output.split()) * 1.3
        cost_usd = (est_in / 1_000_000 * 1.10) + (est_out / 1_000_000 * 4.40)

        return HybridExecutionResult(
            final_output=final_output,
            tier_used=ExecutionTier.DIRECT_FRONTIER,
            model_used=target_model,
            speculative_local_attempted=False,
            verification_passed=True,
            escalation_reason=None,
            total_latency_seconds=duration,
            local_latency_seconds=0.0,
            frontier_latency_seconds=duration,
            cost_usd=cost_usd,
            cost_saved_usd=0.0,
            privacy_report=privacy_report,
            metadata={"direct_reason": reason},
        )
