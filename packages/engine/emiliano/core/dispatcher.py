"""
Execution Router and Dispatcher for Emiliano.
Routes tasks between Direct Model providers and External Agent Harnesses
based on configured policies (auto, local, harness, api) and explicit overrides.
Handles fallback and error classification.
"""

from __future__ import annotations

import asyncio
import os
import re
import threading
import time
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("emiliano")

from .capabilities import Capability, ExecutionType
from .config import EmilianoConfig, load_config
from .registry import CapabilityRegistry
from .workspace import WorkspaceSnapshot, changed_paths, workspace_snapshot
from .enhanced_context_manager import EnhancedContextManager
from .context_manager import TruncationStrategy
from .traces import TaskTrace, TraceStore
from ..direct.client import UnifiedLLMClient, load_litellm


class ExecutionAbortedError(RuntimeError):
    """A harness failed after the workspace may have changed, so no other route is attempted."""


# Discovery runs every harness's --version (several seconds in total), so routing reuses
# its result for a while instead of paying that on every message
DISCOVERY_TTL_SECONDS = 60.0

SYSTEM_PROMPT = (
    "You are Emiliano, a helpful desktop coworker. Reply to conversational messages "
    "naturally and briefly. For tasks, work step by step and be precise."
)


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
        # include_harnesses -> (time, capabilities); a full discovery (True) also serves direct-only requests
        self._discovered: Dict[bool, Tuple[float, Dict[str, Capability]]] = {}

        # Initialize enhanced context manager (Phase 1 features)
        self.context_manager = EnhancedContextManager(
            config=self.config,
            strategy=TruncationStrategy(self.config.context.truncation_strategy),
        )
        self.traces = TraceStore()
        self.last_trace: Optional[TaskTrace] = None  # the most recent task's trace (evals read it)

    async def route_task(
        self,
        goal: str,
        policy: Optional[str] = None,
        harness_override: Optional[str] = None,
        provider_override: Optional[str] = None,
        model_override: Optional[str] = None,
    ) -> List[Capability]:
        """
        Determines the ordered list of candidate capabilities to attempt.
        Filters out unconfigured, uninstalled, and unauthenticated options.
        """
        # A forced provider, or the local/api policy, never uses a harness: skip checking every agent CLI
        needs_harnesses = bool(harness_override) or (
            not provider_override
            and self._resolve_policy(policy) not in (RoutingPolicy.LOCAL.value, RoutingPolicy.API.value))
        caps = await self._discover(include_harnesses=needs_harnesses)
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
        policy_norm = self._resolve_policy(policy)
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
            harnesses.sort(key=self._harness_sort_key)
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
        usable_harnesses.sort(key=self._harness_sort_key)

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
        policy: Optional[str] = None,
        harness_override: Optional[str] = None,
        provider_override: Optional[str] = None,
        model_override: Optional[str] = None,
        messages: Optional[List[Dict[str, str]]] = None,
        on_chunk: Optional[Callable[[str], None]] = None,
        on_reasoning: Optional[Callable[[str], None]] = None,
        on_route_selected: Optional[Callable[[Capability], None]] = None,
        timeout: float = 300.0,
        on_permission: Optional[Callable[[Dict, List[Dict]], Optional[str]]] = None,
        reasoning: Optional[bool] = None,
    ) -> Tuple[Capability, str]:
        """
        Executes the goal using the best viable candidate, falling back on recoverable failures.
        on_permission answers ACP permission requests (tool_call, options) -> optionId or None.
        reasoning forces a local model's reasoning on or off; None decides per goal (off for conversation).
        Records a TaskTrace for the run (self.last_trace; saved when config.traces is on).
        Returns: (successful_capability, full_output_text)
        """
        trace = TaskTrace(goal=goal, policy=self._resolve_policy(policy))
        self.last_trace = trace

        def traced_chunk(chunk: str) -> None:
            trace.mark_output(chunk)
            if on_chunk:
                on_chunk(chunk)

        def traced_reasoning(chunk: str) -> None:
            trace.mark_reasoning(chunk)
            if on_reasoning:
                on_reasoning(chunk)

        traced_permission = None
        if on_permission:
            def traced_permission(tool_call: Dict, options: List[Dict]) -> Optional[str]:
                choice = on_permission(tool_call, options)
                kind = next((o.get("kind") for o in options if o.get("optionId") == choice), None)
                trace.permissions.append({"tool": tool_call.get("title") or tool_call.get("kind"),
                                          "decision": kind or ("rejected" if choice is None else choice)})
                return choice

        try:
            result = await self._execute_with_fallback(
                trace, goal, policy, harness_override, provider_override, model_override, messages,
                traced_chunk, traced_reasoning, on_route_selected, timeout, traced_permission, reasoning,
            )
            trace.finish("succeeded")
            return result
        except (KeyboardInterrupt, asyncio.CancelledError):
            trace.finish("cancelled")
            raise
        except ExecutionAbortedError as e:
            trace.finish("cancelled", str(e))
            raise
        except Exception as e:
            trace.finish("failed", str(e))
            raise
        finally:
            if self.config.traces:
                self.traces.save(trace)  # a quick local insert; synchronous so it survives cancellation

    async def _execute_with_fallback(
        self,
        trace: TaskTrace,
        goal: str,
        policy: Optional[str],
        harness_override: Optional[str],
        provider_override: Optional[str],
        model_override: Optional[str],
        messages: Optional[List[Dict[str, str]]],
        on_chunk: Optional[Callable[[str], None]],
        on_reasoning: Optional[Callable[[str], None]],
        on_route_selected: Optional[Callable[[Capability], None]],
        timeout: float,
        on_permission: Optional[Callable[[Dict, List[Dict]], Optional[str]]],
        reasoning: Optional[bool] = None,
    ) -> Tuple[Capability, str]:
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
            attempt_t0 = time.monotonic()

            try:
                if candidate.execution_type == ExecutionType.DIRECT_MODEL:
                    # Execute via Direct LLM Client
                    model_id = self._litellm_model_id(candidate)
                    client = UnifiedLLMClient(
                        ollama_base_url=self.config.models.ollama_base_url,
                        fallback_chain=[model_id],
                        config=self.config,
                    )
                    # Conversation (e.g. "hi") gets a fast, direct reply; tasks keep the model's
                    # reasoning and the project's context files (EMILIANO.md, CLAUDE.md)
                    is_task = self.requires_agent_harness(goal)
                    task_messages = list(messages) if messages else [{"role": "user", "content": goal}]
                    if not any(m.get("role") == "system" for m in task_messages):
                        task_messages.insert(0, {"role": "system", "content": SYSTEM_PROMPT})

                    # Apply enhanced context management if enabled (Phase 1 features)
                    if self.config.context.enabled:
                        task_messages, context_meta = await self.context_manager.manage_context(
                            task_messages,
                            model_id,
                            include_persistent=is_task,
                        )

                        # Log context operations
                        if context_meta.was_summarized and self.config.context.metrics.log_summarization:
                            logger.info(
                                f"[{candidate.display_name}] Conversation summarized: "
                                f"{context_meta.original_count} → {context_meta.truncated_count} messages"
                            )

                        if context_meta.was_truncated and self.config.context.metrics.log_truncation:
                            logger.info(
                                f"[{candidate.display_name}] Context truncated: "
                                f"saved {context_meta.tokens_saved} tokens"
                            )

                    output_parts = []
                    async for chunk in client.stream_completion(
                        messages=task_messages,
                        model_name=model_id,
                        timeout=timeout,
                        on_reasoning=on_reasoning,
                        think=reasoning if reasoning is not None else (None if is_task else False),
                    ):
                        output_parts.append(chunk)
                        if on_chunk:
                            on_chunk(chunk)
                    output = "".join(output_parts)
                    if not output.strip():
                        raise RuntimeError(f"{candidate.display_name} returned an empty response.")
                    if client.last_usage:
                        trace.prompt_tokens = client.last_usage["prompt_tokens"]
                        trace.completion_tokens = client.last_usage["completion_tokens"]
                    self._record_attempt(trace, candidate, attempt_t0, model=client.last_model or model_id)
                    return candidate, output

                elif candidate.execution_type == ExecutionType.AGENT_HARNESS:
                    # Execute via External Agent Harness
                    harness = harness_instances.get(candidate.name)
                    if not harness:
                        raise RuntimeError(f"Harness adapter '{candidate.name}' not found.")

                    # Snapshot the workspace so a failure can be checked for partial changes
                    workspace = os.getcwd()
                    before = await asyncio.to_thread(workspace_snapshot, workspace)

                    extra = {"permission_handler": on_permission} if on_permission else {}
                    try:
                        code, stdout, stderr = await asyncio.to_thread(
                            harness.run_task,
                            prompt=goal,
                            on_chunk=on_chunk,
                            timeout=timeout,
                            **extra,
                        )
                    except asyncio.CancelledError:
                        # Cancelling the await does not stop the worker thread: stop the agent itself.
                        # cancel() may wait on taskkill, so keep it off the event loop.
                        threading.Thread(target=harness.cancel, daemon=True).start()
                        raise
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
                        self._record_attempt(trace, candidate, attempt_t0)
                        return candidate, stdout
                    elif code == 0:
                        detail = f": {stderr.strip()}" if stderr.strip() else ""
                        failure = f"Harness '{candidate.display_name}' exited successfully but produced no output{detail}"
                    else:
                        err_msg = stderr.strip() or stdout.strip() or f"Process exited with code {code}"
                        failure = f"Harness '{candidate.display_name}' failed: {err_msg}"

                    after = await asyncio.to_thread(workspace_snapshot, workspace)
                    self._raise_harness_failure(candidate, failure, workspace, before, after)

            except ExecutionAbortedError as e:
                self._record_attempt(trace, candidate, attempt_t0, error=str(e), final=False)
                raise
            except (KeyboardInterrupt, asyncio.CancelledError):
                logger.info("[Dispatcher] Execution interrupted by user.")
                self._record_attempt(trace, candidate, attempt_t0, error="cancelled", final=False)
                raise
            except Exception as e:
                logger.warning(f"[Dispatcher] Execution via {candidate.display_name} failed: {e}")
                self._record_attempt(trace, candidate, attempt_t0, error=str(e), final=False)
                last_error = e

        raise RuntimeError(f"All execution routes failed. Last error: {last_error}")

    @staticmethod
    def _record_attempt(trace: TaskTrace, candidate: Capability, started: float, model: Optional[str] = None,
                        error: Optional[str] = None, final: bool = True) -> None:
        """Adds one tried route to the trace; final=True marks it as the route that answered."""
        trace.attempts.append({
            "route": candidate.name,
            "execution_type": str(getattr(candidate.execution_type, "value", candidate.execution_type)),
            "model": model,
            "duration_s": round(time.monotonic() - started, 3),
            "error": error[:500] if error else None,
        })
        if final:
            trace.route = candidate.name
            trace.execution_type = trace.attempts[-1]["execution_type"]
            trace.model = model

    @staticmethod
    def _raise_harness_failure(
        candidate: Capability,
        failure: str,
        workspace: str,
        before: Optional[WorkspaceSnapshot],
        after: Optional[WorkspaceSnapshot],
    ) -> None:
        """
        Raises a RuntimeError (the next route is tried) when the failed harness left the
        workspace untouched. Raises ExecutionAbortedError when it changed files, or when
        changes cannot be detected, because running the goal again could apply it twice.
        """
        if before is None or after is None:
            raise ExecutionAbortedError(
                f"{failure}\nNot retrying with another route: {workspace} is not a git repository, "
                "so Emiliano cannot tell whether the task was partly applied. Check the folder, then re-run."
            )
        changed = changed_paths(before, after)
        if not changed:
            raise RuntimeError(failure)
        shown = ", ".join(changed[:5]) + (f" and {len(changed) - 5} more" if len(changed) > 5 else "")
        raise ExecutionAbortedError(
            f"{failure}\nNot retrying with another route: {candidate.display_name} already changed "
            f"{len(changed)} path(s) ({shown}), and running the goal again could apply it twice. "
            "Review the changes, then re-run."
        )

    async def warm_up(
        self,
        policy: Optional[str] = None,
        harness_override: Optional[str] = None,
        provider_override: Optional[str] = None,
        model_override: Optional[str] = None,
        import_litellm: bool = True,
    ) -> None:
        """Runs discovery ahead of the first message, so that message does not wait for it, and in parallel
        gets the local model ready (prewarm_local, with the same arguments)."""
        async def discover() -> None:
            try:
                await self._discover()
            except Exception as e:
                logger.warning(f"[Dispatcher] Warm-up discovery failed: {e}")

        await asyncio.gather(discover(), self.prewarm_local(
            policy, harness_override, provider_override, model_override, import_litellm=import_litellm))

    async def prewarm_local(
        self,
        policy: Optional[str] = None,
        harness_override: Optional[str] = None,
        provider_override: Optional[str] = None,
        model_override: Optional[str] = None,
        import_litellm: bool = True,
    ) -> None:
        """Prepares a first reply ahead of time, in parallel: has Ollama load the model that would answer
        (~16 s cold) and, when a remote provider could answer, imports litellm (~13 s cold). Skips what the
        request cannot use: nothing when an agent harness is forced, no model preload when another provider is
        forced or models.preload_local_model is off, no litellm when only Ollama can answer. Never raises.
        import_litellm=False when this process has other work to do meanwhile: importing in a thread holds the
        GIL and slowed concurrent discovery from 9 s to 44 s. The model loads in Ollama's process, so it is free."""
        try:
            await self._prewarm_local(policy, harness_override, provider_override, model_override, import_litellm)
        except Exception as e:  # warming up is an optimization; the request itself reports real problems
            logger.debug(f"[Dispatcher] Prewarm skipped: {e}")

    async def _prewarm_local(self, policy: Optional[str], harness_override: Optional[str],
                             provider_override: Optional[str], model_override: Optional[str],
                             import_litellm: bool) -> None:
        policy_norm = self._resolve_policy(policy)
        if harness_override or policy_norm == RoutingPolicy.HARNESS.value:
            return
        # Only remote providers go through litellm; Ollama is called directly
        remote_possible = provider_override != "ollama" and policy_norm != RoutingPolicy.LOCAL.value
        steps = [asyncio.to_thread(load_litellm)] if import_litellm and remote_possible else []
        local_possible = provider_override in (None, "ollama") and policy_norm != RoutingPolicy.API.value
        if local_possible and self.config.models.preload_local_model:
            steps.append(self._preload_ollama_model(model_override))
        for result in await asyncio.gather(*steps, return_exceptions=True):
            if isinstance(result, Exception):
                logger.debug(f"[Dispatcher] Prewarm step failed: {result}")

    async def _preload_ollama_model(self, model_override: Optional[str]) -> None:
        mgr = self.registry.ollama_mgr
        installed = await mgr.list_installed_models()
        # The same choice discovery makes (registry), so the model loaded is the one that answers
        model = mgr.select_best_model(installed, model_override)
        if not model:
            return
        started = time.monotonic()
        if await mgr.preload(model, self.config.models.ollama_num_ctx):
            logger.info(f"[Dispatcher] Preloaded local model {model} in {time.monotonic() - started:.1f}s")

    async def _discover(self, include_harnesses: bool = True) -> Dict[str, Capability]:
        """Returns the capabilities, reusing a discovery from the last DISCOVERY_TTL_SECONDS.
        include_harnesses=False skips the agent CLIs' --version checks (~10 s cold) for requests that cannot
        use an agent harness; a recent full discovery serves those too."""
        now = time.monotonic()
        for full in (True,) if include_harnesses else (True, False):
            cached = self._discovered.get(full)
            if cached and now - cached[0] < DISCOVERY_TTL_SECONDS:
                return cached[1]
        caps = await self.registry.discover_all(test_harness_usability=True, include_harnesses=include_harnesses)
        self._discovered[include_harnesses] = (now, caps)
        return caps

    def _resolve_policy(self, policy: Optional[str]) -> str:
        """Uses the explicit policy, else the configured execution_policy, else auto."""
        resolved = (policy or self.config.execution_policy or RoutingPolicy.AUTO.value).lower()
        valid = [p.value for p in RoutingPolicy]
        if resolved not in valid:
            raise ValueError(
                f"Unknown execution policy '{resolved}'. Use one of: {', '.join(valid)} "
                "(check execution_policy in your Emiliano config)."
            )
        return resolved

    def _harness_sort_key(self, cap: Capability) -> Tuple[bool, int]:
        """Orders harnesses by priority, with the configured preferred_harness first."""
        preferred = (self.config.preferred_harness or "").lower().replace("-", "_")
        preferred = HARNESS_ALIASES.get(preferred, preferred)
        return (cap.name != preferred, cap.priority)

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
