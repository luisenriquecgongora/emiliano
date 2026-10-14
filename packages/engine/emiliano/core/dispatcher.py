"""
Execution Router and Dispatcher for Emiliano.
Routes tasks between Direct Model providers and External Agent Harnesses
based on configured policies (auto, local, harness, api) and explicit overrides.
Handles fallback and error classification.
"""

from __future__ import annotations

import asyncio
from enum import Enum
from typing import AsyncGenerator, Callable, Dict, List, Optional, Tuple

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("emiliano")

from .capabilities import Capability, CapabilityStatus, ExecutionType
from .config import EmilianoConfig, load_config
from .registry import CapabilityRegistry
from ..direct.client import UnifiedLLMClient
from ..harnesses.base import BaseHarness


class RoutingPolicy(str, Enum):
    AUTO = "auto"
    LOCAL = "local"
    HARNESS = "harness"
    API = "api"


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
            target = caps.get(h_key) or caps.get(f"{h_key}_code")
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
        # Automatic routing priority:
        # 1) If local Ollama is ready with an installed model -> use local Ollama (local-first principle)
        # 2) If an external agent harness is ready and authenticated -> use harness
        # 3) If remote API is configured -> use direct remote API
        candidates: List[Capability] = []

        ollama_cap = caps.get("ollama")
        if ollama_cap and ollama_cap.is_usable:
            if model_override:
                ollama_cap = ollama_cap.model_copy(update={"selected_model": model_override})
            candidates.append(ollama_cap)

        # Usable harnesses
        usable_harnesses = [c for c in ready_caps if c.execution_type == ExecutionType.AGENT_HARNESS]
        usable_harnesses.sort(key=lambda c: c.priority)
        candidates.extend(usable_harnesses)

        # Usable direct APIs
        usable_apis = [c for c in ready_caps if c.execution_type == ExecutionType.DIRECT_MODEL and c.name != "ollama"]
        usable_apis.sort(key=lambda c: c.priority)
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
        on_chunk: Optional[Callable[[str], None]] = None,
        on_route_selected: Optional[Callable[[Capability], None]] = None,
        timeout: float = 180.0,
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
                    client = UnifiedLLMClient(
                        ollama_base_url=self.config.models.ollama_base_url,
                        fallback_chain=[f"ollama/{candidate.selected_model}"] if candidate.name == "ollama" else [candidate.selected_model or candidate.name],
                    )
                    messages = [
                        {"role": "system", "content": "You are Emiliano, an expert autonomous coding and execution engine."},
                        {"role": "user", "content": goal},
                    ]
                    output_parts = []
                    async for chunk in client.stream_completion(
                        messages=messages,
                        model_name=f"ollama/{candidate.selected_model}" if candidate.name == "ollama" and candidate.selected_model else candidate.selected_model,
                        timeout=timeout,
                    ):
                        output_parts.append(chunk)
                        if on_chunk:
                            on_chunk(chunk)
                    return candidate, "".join(output_parts)

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
                    if code == 0:
                        return candidate, stdout
                    else:
                        err_msg = stderr.strip() or stdout.strip() or f"Process exited with code {code}"
                        raise RuntimeError(f"Harness '{candidate.display_name}' failed: {err_msg}")

            except Exception as e:
                logger.warning(f"[Dispatcher] Execution via {candidate.display_name} failed: {e}")
                last_error = e

        raise RuntimeError(f"All execution routes failed. Last error: {last_error}")
