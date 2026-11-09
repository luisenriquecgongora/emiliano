"""
Tests for getting the first local reply ready ahead of time (ExecutionDispatcher.prewarm_local, warm_up)
and OllamaManager.preload. No real Ollama is contacted.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from emiliano.core.config import EmilianoConfig
from emiliano.core.dispatcher import ExecutionDispatcher
from emiliano.direct.ollama import OllamaManager


def make_dispatcher(**model_settings):
    cfg = EmilianoConfig()
    for key, value in model_settings.items():
        setattr(cfg.models, key, value)
    dispatcher = ExecutionDispatcher(config=cfg)
    mgr = dispatcher.registry.ollama_mgr
    mgr.list_installed_models = AsyncMock(return_value=["nomic-embed-text:latest", "qwen3.5:2b"])
    mgr.preload = AsyncMock(return_value=True)
    return dispatcher, mgr


@patch("emiliano.core.dispatcher.load_litellm")
class TestPrewarmLocal(unittest.TestCase):
    def test_loads_litellm_and_the_model_discovery_picks(self, load_litellm):
        dispatcher, mgr = make_dispatcher(ollama_num_ctx=16384)
        asyncio.run(dispatcher.prewarm_local())
        load_litellm.assert_called_once()
        # Same choice as the registry (qwen over the embedding model), same window as later calls
        mgr.preload.assert_awaited_once_with("qwen3.5:2b", 16384)

    def test_model_override_is_preloaded(self, load_litellm):
        dispatcher, mgr = make_dispatcher()
        mgr.list_installed_models.return_value = ["qwen3.5:2b", "llama3.2:3b"]
        asyncio.run(dispatcher.prewarm_local(model_override="llama3.2"))
        self.assertEqual(mgr.preload.await_args.args[0], "llama3.2:3b")

    def test_nothing_when_a_harness_will_answer(self, load_litellm):
        dispatcher, mgr = make_dispatcher()
        asyncio.run(dispatcher.prewarm_local(harness_override="claude_code"))
        asyncio.run(dispatcher.prewarm_local(policy="harness"))
        load_litellm.assert_not_called()
        mgr.preload.assert_not_awaited()

    def test_no_model_preload_for_remote_or_when_turned_off(self, load_litellm):
        dispatcher, mgr = make_dispatcher()
        asyncio.run(dispatcher.prewarm_local(provider_override="anthropic"))
        asyncio.run(dispatcher.prewarm_local(policy="api"))
        off, off_mgr = make_dispatcher(preload_local_model=False)
        asyncio.run(off.prewarm_local())
        self.assertEqual(load_litellm.call_count, 3)  # remote models still need litellm
        mgr.preload.assert_not_awaited()
        off_mgr.preload.assert_not_awaited()

    def test_local_only_requests_skip_litellm(self, load_litellm):
        # Ollama is called directly, so litellm is only needed when a remote provider could answer
        dispatcher, mgr = make_dispatcher()
        asyncio.run(dispatcher.prewarm_local(provider_override="ollama"))
        asyncio.run(dispatcher.prewarm_local(policy="local"))
        load_litellm.assert_not_called()
        self.assertEqual(mgr.preload.await_count, 2)

    def test_model_only_skips_litellm(self, load_litellm):
        # chat warms up while the user types; importing litellm there would hold the GIL and lag typing
        dispatcher, mgr = make_dispatcher()
        asyncio.run(dispatcher.prewarm_local(import_litellm=False))
        load_litellm.assert_not_called()
        mgr.preload.assert_awaited_once()

    def test_never_raises(self, load_litellm):
        load_litellm.side_effect = RuntimeError("LiteLLM is not installed")
        dispatcher, mgr = make_dispatcher()
        mgr.list_installed_models.side_effect = OSError("connection refused")
        asyncio.run(dispatcher.prewarm_local())
        asyncio.run(dispatcher.prewarm_local(policy="no-such-policy"))

    def test_no_installed_model_means_no_preload(self, load_litellm):
        dispatcher, mgr = make_dispatcher()
        mgr.list_installed_models.return_value = []
        asyncio.run(dispatcher.prewarm_local())
        mgr.preload.assert_not_awaited()


class TestWarmUp(unittest.TestCase):
    def test_discovery_and_prewarm_run_together(self):
        dispatcher, _ = make_dispatcher()
        started = []

        def slow(name):
            async def step(*args, **kwargs):
                started.append(name)
                await asyncio.sleep(0.2)
            return step

        with patch.object(dispatcher, "_discover", new=slow("discover")), \
             patch.object(dispatcher, "prewarm_local", new=slow("prewarm")):
            loop = asyncio.new_event_loop()
            try:
                start = loop.time()
                loop.run_until_complete(dispatcher.warm_up())
                elapsed = loop.time() - start
            finally:
                loop.close()
        self.assertEqual(sorted(started), ["discover", "prewarm"])
        self.assertLess(elapsed, 0.35)  # in parallel, not 0.4 s one after the other

    def test_request_settings_reach_prewarm(self):
        dispatcher, _ = make_dispatcher()
        with patch.object(dispatcher, "_discover", new=AsyncMock()), \
             patch.object(dispatcher, "prewarm_local", new=AsyncMock()) as prewarm:
            asyncio.run(dispatcher.warm_up("local", None, "ollama", "qwen3.5", import_litellm=False))
        prewarm.assert_awaited_once_with("local", None, "ollama", "qwen3.5", import_litellm=False)


class TestOllamaPreload(unittest.TestCase):
    def _client(self, status=200, error=None):
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.post = AsyncMock(side_effect=error, return_value=MagicMock(status_code=status))
        return client

    def test_posts_empty_prompt_with_context_window(self):
        client = self._client()
        with patch("emiliano.direct.ollama.httpx.AsyncClient", return_value=client):
            self.assertTrue(asyncio.run(OllamaManager().preload("qwen3.5:2b", 8192)))
        url, kwargs = client.post.await_args.args[0], client.post.await_args.kwargs
        self.assertTrue(url.endswith("/api/generate"))
        self.assertEqual(kwargs["json"], {"model": "qwen3.5:2b", "prompt": "", "options": {"num_ctx": 8192}})

    def test_failure_returns_false(self):
        with patch("emiliano.direct.ollama.httpx.AsyncClient", return_value=self._client(error=OSError("down"))):
            self.assertFalse(asyncio.run(OllamaManager().preload("qwen3.5:2b")))
        with patch("emiliano.direct.ollama.httpx.AsyncClient", return_value=self._client(status=404)):
            self.assertFalse(asyncio.run(OllamaManager().preload("missing:1b")))


if __name__ == "__main__":
    unittest.main()
