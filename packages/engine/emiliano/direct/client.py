"""
Unified LLM Client supporting local models (Ollama, vLLM) and remote APIs (Anthropic, OpenAI, DeepSeek).
Uses LiteLLM with streaming and automated fallback chains.
"""

from __future__ import annotations

import httpx
try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("emiliano")

try:
    import litellm
    # Disable litellm verbose telemetry
    litellm.telemetry = False
except ImportError:
    litellm = None


class UnifiedLLMClient:
    def __init__(
        self,
        ollama_base_url: str = "http://localhost:11434",
        fallback_chain: Optional[List[str]] = None,
    ):
        self.ollama_base_url = ollama_base_url
        self.fallback_chain = fallback_chain or [
            "ollama/qwen2.5-coder:32b",
            "deepseek/deepseek-chat",
            "anthropic/claude-3-7-sonnet-20250219",
        ]

    async def list_local_ollama_models(self) -> List[str]:
        """Queries local Ollama instance for installed models."""
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                res = await client.get(f"{self.ollama_base_url}/api/tags")
                if res.status_code == 200:
                    models = [m.get("name") for m in res.json().get("models", [])]
                    return [m for m in models if m]
        except Exception as e:
            logger.debug(f"[LLM] Ollama not reachable at {self.ollama_base_url}: {e}")
        return []

    async def stream_completion(
        self,
        messages: List[Dict[str, str]],
        model_name: Optional[str] = None,
        temperature: float = 0.2,
    ) -> AsyncGenerator[str, None]:
        """
        Streams completion tokens, trying the requested model first or cascading down the fallback chain.
        """
        if litellm is None:
            raise RuntimeError("LiteLLM is not installed. Please install it with: pip install litellm")

        candidates = [model_name] if model_name else list(self.fallback_chain)

        last_error = None
        for candidate in candidates:
            if not candidate:
                continue

            # Format Ollama model for litellm if needed
            api_base = None
            target_model = candidate
            if candidate.startswith("ollama/"):
                api_base = self.ollama_base_url
            elif not "/" in candidate and await self._is_local_ollama(candidate):
                target_model = f"ollama/{candidate}"
                api_base = self.ollama_base_url

            logger.info(f"[LLM] Attempting completion with model: {target_model}")
            try:
                response = await litellm.acompletion(
                    model=target_model,
                    messages=messages,
                    stream=True,
                    temperature=temperature,
                    api_base=api_base,
                )
                async for chunk in response:
                    content = chunk.choices[0].delta.content or ""
                    if content:
                        yield content
                return
            except Exception as e:
                logger.warning(f"[LLM] Model {target_model} failed: {e}. Trying next fallback...")
                last_error = e

        if last_error:
            raise RuntimeError(f"All models in fallback chain failed. Last error: {last_error}")

    async def _is_local_ollama(self, model_name: str) -> bool:
        local_models = await self.list_local_ollama_models()
        return any(model_name in m for m in local_models)
