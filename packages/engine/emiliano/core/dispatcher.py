"""
Execution Router and Dispatcher for Emiliano.
Routes tasks between Direct Model providers and External Agent Harnesses
based on configured policies (auto, local, harness, api) and explicit overrides.
Handles fallback and error classification.
"""

from __future__ import annotations

import asyncio
import re
from enum import Enum
from typing import Callable, List, Optional, Tuple

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("emiliano")

from .capabilities import Capability, ExecutionType
from .config import EmilianoConfig, load_config
from .registry import CapabilityRegistry
from ..direct.client import UnifiedLLMClient


class RoutingPolicy(str, Enum):
    AUTO = "auto"
    LOCAL = "local"
    HARNESS = "harness"
    API = "api"


# CLI names accepted by --harness, mapped to capability names
HARNESS_ALIASES = {
    "claude": "claude_code",
    "claude_code": "claude_code",
    "codex": "codex",
    "agy": "antigravity",
    "antigravity": "antigravity",
    "opencode": "opencode",
}


class ExecutionDispatcher:
    """Selects and executes the best route for a given user goal."""

    def __init__(self, config: Optional[EmilianoConfig] = None):
        self.config = config or load_config()
        self.registry = CapabilityRegistry(config=self.config)

    async def route_task(
        self,
        goal: str,
        policy: str = "auto",
        harness_override: Optional[str] = None,
        provider_override: Optional[str] = None,
        model_override: Optional[str] = None,
    ) -> List[Capability]:
        """
        Determines the ordered list of candidate capabilities to attempt.
        Filters out unconfigured, uninstalled, and unauthenticated options.
        """
        caps = await self.registry.discover_all(test_harness_usability=True)
        ready_caps = [c for c in caps.values() if c.is_usable]

        # 1. Explicit Harness Override
        if harness_override:
            h_key = harness_override.lower().replace("-", "_")
            target = caps.get(HARNESS_ALIASES.get(h_key, h_key))
            if not target:
                raise ValueError(f"Unknown harness override '{harness_override}'. Available: claude, codex, agy, opencode")
            if not target.is_usable:
                raise RuntimeError(f"Harness '{target.display_name}' is not usable: {target.status_message}")
            return [target]

        # 2. Explicit Provider Override
        if provider_override:
            p_key = provider_override.lower()
            target = caps.get(p_key)
            if not target:
                raise ValueError(f"Unknown provider override '{provider_override}'. Available: ollama, anthropic, openai, deepseek, gemini")
            if not target.is_usable:
                raise RuntimeError(f"Provider '{target.display_name}' is not usable: {target.status_message}")
            if model_override:
                target = target.model_copy(update={"selected_model": model_override})
            return [target]

        # 3. Policy: LOCAL (only local model)
        policy_norm = policy.lower()
        if policy_norm == RoutingPolicy.LOCAL.value:
            ollama_cap = caps.get("ollama")
            if not ollama_cap or not ollama_cap.is_usable:
                msg = ollama_cap.status_message if ollama_cap else "Ollama not installed."
                raise RuntimeError(f"Local policy requested, but Ollama is unavailable: {msg}")
            if model_override:
                ollama_cap = ollama_cap.model_copy(update={"selected_model": model_override})
            return [ollama_cap]

        # 4. Policy: HARNESS (prefer harnesses)
        if policy_norm == RoutingPolicy.HARNESS.value:
            harnesses = [c for c in ready_caps if c.execution_type == ExecutionType.AGENT_HARNESS]
            if not harnesses:
                # Diagnostics on why harnesses failed
                reasons = [f"  • {c.display_name}: {c.status_message}" for c in caps.values() if c.execution_type == ExecutionType.AGENT_HARNESS]
                raise RuntimeError("Harness policy requested, but no external harnesses are usable:\n" + "\n".join(reasons))
            # Sort by priority
            harnesses.sort(key=lambda c: c.priority)
            return harnesses

        # 5. Policy: API (remote API providers)
        if policy_norm == RoutingPolicy.API.value:
            apis = [c for c in ready_caps if c.execution_type == ExecutionType.DIRECT_MODEL and c.name != "ollama"]
            if not apis:
                raise RuntimeError("API policy requested, but no remote API credentials configured (set ANTHROPIC_API_KEY, OPENAI_API_KEY, DEEPSEEK_API_KEY, or GEMINI_API_KEY).")
            apis.sort(key=lambda c: c.priority)
            if model_override and apis:
                apis[0] = apis[0].model_copy(update={"selected_model": model_override})
            return apis

        # 6. Policy: AUTO (Default)
        # Intent-Aware Automatic routing:
        # If the goal requires tools, filesystem inspection, compiling, testing, or editing,
        # prioritize ready agent harnesses. Otherwise, use local Ollama first (local-first principle).
        needs_harness = self.requires_agent_harness(goal)

        candidates: List[Capability] = []

        ollama_cap = caps.get("ollama")
        if ollama_cap and ollama_cap.is_usable:
            if model_override:
                ollama_cap = ollama_cap.model_copy(update={"selected_model": model_override})

        usable_harnesses = [c for c in ready_caps if c.execution_type == ExecutionType.AGENT_HARNESS]
        usable_harnesses.sort(key=lambda c: c.priority)

        usable_apis = [c for c in ready_caps if c.execution_type == ExecutionType.DIRECT_MODEL and c.name != "ollama"]
        usable_apis.sort(key=lambda c: c.priority)

        if needs_harness and usable_harnesses:
            logger.info("[Dispatcher] Detected coding/filesystem task. Prioritizing agent harnesses.")
            candidates.extend(usable_harnesses)
            if ollama_cap and ollama_cap.is_usable:
                candidates.append(ollama_cap)
            candidates.extend(usable_apis)
        else:
            if ollama_cap and ollama_cap.is_usable:
                candidates.append(ollama_cap)
            candidates.extend(usable_harnesses)
            candidates.extend(usable_apis)

        if not candidates:
            # Generate detailed actionable report
            diag_lines = [
                "No execution candidates are currently usable in 'auto' mode:",
                f"  • Local Ollama: {caps.get('ollama', Capability(name='ollama', display_name='Ollama', execution_type=ExecutionType.DIRECT_MODEL)).status_message}",
            ]
            for c in caps.values():
                if c.name != "ollama":
                    diag_lines.append(f"  • {c.display_name}: {c.status_message}")
            diag_lines.extend([
                "",
                "To resolve, choose one of:",
                "  1. Start Ollama and pull a model: 'ollama run qwen2.5-coder:7b'",
                "  2. Authenticate an external harness (e.g. 'claude login' or 'codex login')",
                "  3. Set an API key in your environment (e.g. ANTHROPIC_API_KEY, OPENAI_API_KEY, DEEPSEEK_API_KEY)",
            ])
            raise RuntimeError("\n".join(diag_lines))

        return candidates

    async def execute_task(
        self,
        goal: str,
        policy: str = "auto",
        harness_override: Optional[str] = None,
        provider_override: Optional[str] = None,
        model_override: Optional[str] = None,
        messages: Optional[List[Dict[str, str]]] = None,
        on_chunk: Optional[Callable[[str], None]] = None,
        on_reasoning: Optional[Callable[[str], None]] = None,
        on_route_selected: Optional[Callable[[Capability], None]] = None,
        timeout: float = 300.0,
    ) -> Tuple[Capability, str]:
        """
        Executes the goal using the best viable candidate, falling back on recoverable failures.
        Returns: (successful_capability, full_output_text)
        """
        candidates = await self.route_task(
            goal=goal,
            policy=policy,
            harness_override=harness_override,
            provider_override=provider_override,
            model_override=model_override,
        )

        harness_instances = self.registry.get_harness_instances()
        last_error = None

        for candidate in candidates:
            if on_route_selected:
                on_route_selected(candidate)
            logger.info(f"[Dispatcher] Attempting execution via: {candidate.display_name} ({candidate.execution_type})")

            try:
                if candidate.execution_type == ExecutionType.DIRECT_MODEL:
                    # Execute via Direct LLM Client
                    model_id = self._litellm_model_id(candidate)
                    client = UnifiedLLMClient(
                        ollama_base_url=self.config.models.ollama_base_url,
                        fallback_chain=[model_id],
                        config=self.config,
                    )
                    task_messages = messages or [
                        {"role": "system", "content": "You are Emiliano, an expert autonomous coding and execution engine."},
                        {"role": "user", "content": goal},
                    ]
                    output_parts = []
                    async for chunk in client.stream_completion(
                        messages=task_messages,
                        model_name=model_id,
                        timeout=timeout,
                        on_reasoning=on_reasoning,
                    ):
                        output_parts.append(chunk)
                        if on_chunk:
                            on_chunk(chunk)
                    output = "".join(output_parts)
                    if not output.strip():
                        raise RuntimeError(f"{candidate.display_name} returned an empty response.")
                    return candidate, output

                elif candidate.execution_type == ExecutionType.AGENT_HARNESS:
                    # Execute via External Agent Harness
                    harness = harness_instances.get(candidate.name)
                    if not harness:
                        raise RuntimeError(f"Harness adapter '{candidate.name}' not found.")

                    code, stdout, stderr = await asyncio.to_thread(
                        harness.run_task,
                        prompt=goal,
                        on_chunk=on_chunk,
                        timeout=timeout,
                    )
                    if code == 0 and stdout.strip():
                        lower_out = stdout.lower()
                        if any(phrase in lower_out for phrase in [
                            "permission policy blocks",
                            "i can't read this workspace",
                            "i can’t read this workspace",
                            "you've hit your weekly limit",
                            "rate limit exceeded",
                        ]):
                            raise RuntimeError(f"Harness '{candidate.display_name}' reported soft failure: {stdout.strip()[:140]}...")
                        return candidate, stdout
                    elif code == 0:
                        detail = f": {stderr.strip()}" if stderr.strip() else ""
                        raise RuntimeError(f"Harness '{candidate.display_name}' exited successfully but produced no output{detail}")
                    else:
                        err_msg = stderr.strip() or stdout.strip() or f"Process exited with code {code}"
                        raise RuntimeError(f"Harness '{candidate.display_name}' failed: {err_msg}")

            except (KeyboardInterrupt, asyncio.CancelledError):
                logger.info("[Dispatcher] Execution interrupted by user.")
                raise
            except Exception as e:
                logger.warning(f"[Dispatcher] Execution via {candidate.display_name} failed: {e}")
                last_error = e

        raise RuntimeError(f"All execution routes failed. Last error: {last_error}")

    @staticmethod
    def _litellm_model_id(candidate: Capability) -> str:
        """Builds a provider-qualified LiteLLM model id, e.g. 'anthropic/<model>' or 'ollama/<model>'."""
        model = candidate.selected_model or ""
        if not model:
            raise RuntimeError(f"No model selected for {candidate.display_name}.")
        # Ollama names may contain "/" themselves (e.g. hf.co/user/model), so check the exact prefix
        if model.startswith(f"{candidate.name}/"):
            return model
        return f"{candidate.name}/{model}"

    @staticmethod
    def requires_agent_harness(goal: str) -> bool:
        """
        Determines whether a user goal requires an agent harness (filesystem access,
        compiling, testing, or modifying local code).
        """
        g = goal.lower()

        # Specific local filesystem or project context markers
        fs_markers = [
            "this folder", "this directory", "this repo", "this project", "this codebase",
            "our files", "my files", "local files", "the files in", "files in this",
            "in this folder", "in this directory", "in this repo", "on this folder",
            "in the current folder", "in current directory",
        ]
        if any(marker in g for marker in fs_markers):
            return True

        # Compilation, build, and test keywords
        build_markers = [
            "compile", "compiling", "will compile", "does it compile", "can it compile",
            "build the project", "build the code",
            "run test", "run tests", "pytest", "npm test", "cargo test",
            "git status", "git diff", "git commit", "git push",
            "refactor the file", "edit the file", "fix the bug", "fix the test",
        ]
        if any(marker in g for marker in build_markers):
            return True

        # Action verb + target combination (e.g. "check files", "inspect files")
        words = set(re.findall(r"\b[a-zA-Z]+\b", g))
        action_verbs = {"check", "chekc", "inspect", "audit", "scan", "list"}
        file_targets = {"files", "folders", "directories"}
        if (action_verbs & words) and (file_targets & words):
            return True

        return False
