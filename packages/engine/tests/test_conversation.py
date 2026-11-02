"""
Tests that plain conversation gets a fast, direct reply while tasks keep reasoning and
the project's context files.
"""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from emiliano.core.capabilities import Capability, CapabilityStatus, ExecutionType
from emiliano.core.dispatcher import SYSTEM_PROMPT, ExecutionDispatcher
from emiliano.direct.client import UnifiedLLMClient

OLLAMA = Capability(
    name="ollama", display_name="Ollama (Local)", execution_type=ExecutionType.DIRECT_MODEL,
    status=CapabilityStatus.READY, selected_model="qwen3.5:2b",
)


class TestConversationRouting(unittest.TestCase):
    def _run(self, goal, messages=None):
        dispatcher = ExecutionDispatcher()
        seen = {}

        async def fake_stream(self_client, **kwargs):
            seen["stream"] = kwargs
            yield "Hello!"

        async def fake_manage(msgs, model_id, include_persistent=True):
            seen["context"] = {"messages": msgs, "include_persistent": include_persistent}
            return msgs, SimpleNamespace(was_summarized=False, was_truncated=False)

        with patch.object(dispatcher, "route_task", new_callable=AsyncMock, return_value=[OLLAMA]), \
                patch.object(UnifiedLLMClient, "stream_completion", fake_stream), \
                patch.object(dispatcher.context_manager, "manage_context", side_effect=fake_manage):
            asyncio.run(dispatcher.execute_task(goal, messages=messages))
        return seen

    def test_greeting_skips_reasoning_and_project_context(self):
        seen = self._run("hi")
        self.assertIs(seen["stream"]["think"], False)
        self.assertFalse(seen["context"]["include_persistent"])
        self.assertEqual(seen["stream"]["messages"][0], {"role": "system", "content": SYSTEM_PROMPT})

    def test_coding_task_keeps_reasoning_and_project_context(self):
        seen = self._run("fix the failing tests in this repo")
        self.assertIsNone(seen["stream"]["think"])
        self.assertTrue(seen["context"]["include_persistent"])

    def test_history_without_system_prompt_gets_one(self):
        history = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "Hello!"},
            {"role": "user", "content": "how are you?"},
        ]
        seen = self._run("how are you?", messages=history)
        sent = seen["stream"]["messages"]
        self.assertEqual(sent[0]["role"], "system")
        self.assertEqual(sent[1:], history)
        self.assertEqual(len(history), 3)  # The caller's list is not modified


async def _one_chunk_stream():
    yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="ok", reasoning_content=None))])


async def _drain(agen):
    return [c async for c in agen]


class TestThinkOption(unittest.TestCase):
    def test_think_is_only_sent_to_ollama(self):
        client = UnifiedLLMClient()
        for model, expected in (("ollama/qwen3.5:2b", {"think": False}), ("anthropic/claude-opus-5-5", {})):
            with self.subTest(model=model):
                with patch("litellm.acompletion", new_callable=AsyncMock, return_value=_one_chunk_stream()) as mock:
                    asyncio.run(_drain(client.stream_completion([{"role": "user", "content": "hi"}], model_name=model, think=False)))
                kwargs = mock.call_args.kwargs
                self.assertEqual({k: kwargs[k] for k in ("think",) if k in kwargs}, expected)


class TestDiscoveryCache(unittest.TestCase):
    def test_discovery_is_reused_then_refreshed(self):
        dispatcher = ExecutionDispatcher()
        clock = MagicMock()
        clock.monotonic.side_effect = [1000.0, 1030.0, 1061.0]
        # Patch only the dispatcher's clock: asyncio's event loop reads time.monotonic too
        with patch.object(dispatcher.registry, "discover_all", new_callable=AsyncMock, return_value={"ollama": OLLAMA}) as discover, \
                patch("emiliano.core.dispatcher.time", clock):
            for _ in range(3):
                asyncio.run(dispatcher.route_task("hi", policy="local"))
        # Second call is within 60s of the first and reuses it; the third is past it
        self.assertEqual(discover.await_count, 2)


if __name__ == "__main__":
    unittest.main()
