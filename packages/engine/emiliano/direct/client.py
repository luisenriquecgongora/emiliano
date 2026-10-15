"""
Unified LLM Client supporting local models (Ollama, vLLM) and remote APIs (Anthropic, OpenAI, DeepSeek, Gemini).
Uses LiteLLM with streaming and dynamic fallback chains based on actual installed/configured capabilities.
"""

from __future__ import annotations

import os
from typing import AsyncGenerator, Dict, List, Optional, Tuple

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("emiliano")

from ..core.config import EmilianoConfig
from .credentials import CredentialManager
from .ollama import OllamaManager


class UnifiedLLMClient:
    def __init__(
        self,
        ollama_base_url: str = "http://localhost:11434",
        fallback_chain: Optional[List[str]] = None,
        auto_start_ollama: bool = False,
        config: Optional[EmilianoConfig] = None,
    ):
        self.ollama_base_url = ollama_base_url.rstrip("/")
        self.fallback_chain = fallback_chain
        self.ollama_mgr = OllamaManager(
            base_url=self.ollama_base_url,
            auto_start=auto_start_ollama,
        )
        # Pass config so API keys stored in emiliano.yaml are found, not just env vars
        self.cred_mgr = CredentialManager(config=config)

    async def list_local_ollama_models(self) -> List[str]:
        """Queries local Ollama instance for installed models."""
        return await self.ollama_mgr.list_installed_models()

    async def get_viable_candidates(self, model_name: Optional[str] = None) -> List[Tuple[str, Optional[str]]]:
        """
        Determines viable (model_identifier, api_base) candidates.
        Skips remote providers that do not have credentials configured,
        and uses actual installed Ollama models instead of nonexistent hardcoded ones.
        """
        candidates: List[Tuple[str, Optional[str]]] = []

        # If user explicitly requested a model
        if model_name:
            target = model_name
            api_base = None
            if target.startswith("ollama/"):
                api_base = self.ollama_base_url
            elif "/" not in target:
                # Only treat a bare name as local when it really matches an installed model;
                # otherwise remote names like "gpt-4o" would be silently rerouted to Ollama.
                installed = await self.list_local_ollama_models()
                matched = self.ollama_mgr.match_installed(installed, target)
                if matched:
                    target = f"ollama/{matched}"
                    api_base = self.ollama_base_url
            candidates.append((target, api_base))
            return candidates

        # If explicit fallback chain was provided, filter it by viability
        if self.fallback_chain:
            installed = await self.list_local_ollama_models()
            for item in self.fallback_chain:
                if item.startswith("ollama/"):
                    model_part = item.removeprefix("ollama/")
                    # If this exact model is installed, or pick best installed
                    if model_part in installed:
                        candidates.append((item, self.ollama_base_url))
                    elif installed:
                        best = self.ollama_mgr.select_best_model(installed)
                        candidate_str = f"ollama/{best}"
                        if (candidate_str, self.ollama_base_url) not in candidates:
                            candidates.append((candidate_str, self.ollama_base_url))
                elif "deepseek" in item:
                    if self.cred_mgr.get_deepseek_key():
                        candidates.append((item, None))
                elif "anthropic" in item or "claude" in item:
                    if self.cred_mgr.get_anthropic_key():
                        candidates.append((item, None))
                elif "openai" in item or "gpt" in item:
                    if self.cred_mgr.get_openai_key():
                        candidates.append((item, None))
                elif "gemini" in item or "google" in item:
                    if self.cred_mgr.get_gemini_key():
                        candidates.append((item, None))

        # Dynamic fallback if candidates is still empty:
        if not candidates:
            # 1. Try local Ollama installed model
            installed = await self.list_local_ollama_models()
            if installed:
                best = self.ollama_mgr.select_best_model(installed)
                if best:
                    candidates.append((f"ollama/{best}", self.ollama_base_url))

            # 2. Check available API providers
            if self.cred_mgr.get_deepseek_key():
                candidates.append(("deepseek/deepseek-chat", None))
            if self.cred_mgr.get_anthropic_key():
                candidates.append(("anthropic/claude-3-7-sonnet-20250219", None))
            if self.cred_mgr.get_openai_key():
                candidates.append(("openai/gpt-4o", None))
            if self.cred_mgr.get_gemini_key():
                candidates.append(("gemini/gemini-2.5-pro", None))

        return candidates

    async def stream_completion(
        self,
        messages: List[Dict[str, str]],
        model_name: Optional[str] = None,
        temperature: float = 0.2,
        timeout: float = 120.0,
    ) -> AsyncGenerator[str, None]:
        """
        Streams completion tokens, trying the requested model first or cascading down viable candidates.
        """
        # Lazy import litellm to avoid blocking CLI startup
        os.environ["LITELLM_TELEMETRY"] = "False"
        # Use the bundled cost map instead of downloading it on every run
        os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
        try:
            import litellm
            litellm.telemetry = False
        except ImportError:
            raise RuntimeError("LiteLLM is not installed. Please install it with: uv pip install litellm")

        candidates = await self.get_viable_candidates(model_name=model_name)

        if not candidates:
            # Provide clear, actionable diagnostic
            installed_ollama = await self.list_local_ollama_models()
            ollama_ready = await self.ollama_mgr.is_service_ready()
            msg = (
                "No viable model providers available.\n"
                f"  • Ollama service status: {'Responding' if ollama_ready else 'Not responding at ' + self.ollama_base_url}\n"
                f"  • Ollama installed models: {installed_ollama if installed_ollama else 'None'}\n"
                "  • Remote API keys: None detected (set ANTHROPIC_API_KEY, OPENAI_API_KEY, DEEPSEEK_API_KEY, or GEMINI_API_KEY)\n"
                "To fix:\n"
                "  - Run: ollama pull qwen2.5-coder:7b (or any preferred local model)\n"
                "  - Or set an API key in your environment or emiliano.yaml"
            )
            raise RuntimeError(msg)

        last_error = None
        for target_model, api_base in candidates:
            logger.info(f"[LLM] Attempting completion with model: {target_model} (api_base={api_base})")
            try:
                # Pass the key per call rather than via os.environ, so it never leaks
                # into harness subprocesses (e.g. switching Claude Code to API billing)
                response = await litellm.acompletion(
                    model=target_model,
                    messages=messages,
                    stream=True,
                    temperature=temperature,
                    api_base=api_base,
                    api_key=self._provider_key(target_model),
                    timeout=timeout,
                )
                produced_content = False
                reasoning_chars = 0
                async for chunk in response:
                    delta = chunk.choices[0].delta
                    content = delta.content or ""
                    reasoning_chars += len(getattr(delta, "reasoning_content", None) or "")
                    if content:
                        produced_content = True
                        yield content
                if not produced_content:
                    # Thinking models (e.g. qwen3.5) can spend the whole run reasoning and never answer
                    detail = f" (it produced {reasoning_chars} chars of reasoning but no answer)" if reasoning_chars else ""
                    raise RuntimeError(f"Model {target_model} returned an empty response{detail}")
                return
            except Exception as e:
                logger.warning(f"[LLM] Model {target_model} failed: {e}. Trying next viable candidate...")
                last_error = e

        if last_error:
            raise RuntimeError(f"All viable models failed. Last error: {last_error}")

    def _provider_key(self, model_name: str) -> Optional[str]:
        """Returns the API key for the model's provider (env or config), or None for local models."""
        m = model_name.lower()
        if m.startswith("ollama/"):
            return None
        if "anthropic" in m or "claude" in m:
            return self.cred_mgr.get_anthropic_key()
        if "deepseek" in m:
            return self.cred_mgr.get_deepseek_key()
        if "openai" in m or "gpt" in m:
            return self.cred_mgr.get_openai_key()
        if "gemini" in m:
            return self.cred_mgr.get_gemini_key()
        return None
