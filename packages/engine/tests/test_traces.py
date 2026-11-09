"""
Tests for task traces (emiliano/core/traces.py) and how the dispatcher records them.
"""

import asyncio
import os
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

from emiliano.core.capabilities import Capability, CapabilityStatus, ExecutionType
from emiliano.core.config import EmilianoConfig
from emiliano.core.dispatcher import ExecutionDispatcher
from emiliano.core.traces import TaskTrace, TraceStore


def temp_store() -> TraceStore:
    return TraceStore(f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'traces.db')}")


def direct_cap(name, model):
    return Capability(name=name, display_name=name, execution_type=ExecutionType.DIRECT_MODEL,
                      status=CapabilityStatus.READY, selected_model=model)


class FakeClient:
    """Stands in for UnifiedLLMClient: fails for models named 'broken', else streams two chunks."""

    def __init__(self, *args, **kwargs):
        self.last_model, self.last_usage = None, None

    async def stream_completion(self, messages, model_name=None, **kwargs):
        self.last_model = model_name
        if "broken" in model_name:
            raise RuntimeError("model crashed")
        await asyncio.sleep(0.05)
        yield "Hello "
        await asyncio.sleep(0.05)
        yield "there"
        self.last_usage = {"prompt_tokens": 12, "completion_tokens": 20}


def dispatcher_with(candidates, store):
    cfg = EmilianoConfig()
    cfg.context.enabled = False
    dispatcher = ExecutionDispatcher(config=cfg)
    dispatcher.traces = store
    dispatcher.route_task = AsyncMock(return_value=candidates)
    return dispatcher


class TestTaskTrace(unittest.TestCase):
    def test_timings_and_speed(self):
        trace = TaskTrace(goal="g", policy="auto")
        time.sleep(0.02)
        trace.mark_output("abc")
        trace.mark_output("de")
        time.sleep(0.1)
        trace.completion_tokens = 50
        trace.finish("succeeded")
        self.assertEqual(trace.output_chars, 5)
        self.assertGreater(trace.first_output_s, 0)
        self.assertGreater(trace.duration_s, trace.first_output_s)
        self.assertGreater(trace.tokens_per_second, 0)

    def test_speed_counts_reasoning_time(self):
        # Token counts include reasoning, so speed is timed from the first reasoning token, not the answer
        trace = TaskTrace(goal="g", policy="auto")
        trace.mark_reasoning("thinking")
        time.sleep(0.3)
        trace.mark_output("4")
        trace.completion_tokens = 30
        trace.finish("succeeded")
        self.assertLess(trace.tokens_per_second, 150)  # ~30 tokens over >=0.3 s, not over a few ms
        self.assertGreater(trace.first_output_s, 0.25)  # time to the answer itself is still reported

    def test_speed_unknown_without_tokens(self):
        trace = TaskTrace(goal="g", policy="auto")
        trace.finish("failed", "boom")
        self.assertIsNone(trace.tokens_per_second)


class TestTraceStore(unittest.TestCase):
    def test_round_trip_newest_first(self):
        store = temp_store()
        for goal in ("first", "second"):
            trace = TaskTrace(goal=goal, policy="local")
            trace.attempts.append({"route": "ollama"})
            trace.finish("succeeded")
            store.save(trace)
            time.sleep(0.01)
        rows = store.recent()
        self.assertEqual([r["goal"] for r in rows], ["second", "first"])
        self.assertEqual(rows[0]["attempts"], [{"route": "ollama"}])

    def test_save_never_raises(self):
        store = TraceStore("sqlite:///Z:/no/such/dir/traces.db")
        store.save(TaskTrace(goal="g", policy="auto"))  # logged, not raised


@patch("emiliano.core.dispatcher.UnifiedLLMClient", FakeClient)
class TestDispatcherTraces(unittest.TestCase):
    def test_fallback_and_tokens_are_recorded(self):
        store = temp_store()
        dispatcher = dispatcher_with([direct_cap("ollama", "broken:1b"), direct_cap("ollama", "qwen3.5:2b")], store)
        chunks = []
        cap, out = asyncio.run(dispatcher.execute_task("hi", policy="local", on_chunk=chunks.append))
        self.assertEqual(out, "Hello there")
        self.assertEqual(chunks, ["Hello ", "there"])

        row = store.recent(1)[0]
        self.assertEqual(row["outcome"], "succeeded")
        self.assertEqual(row["policy"], "local")
        self.assertEqual((row["route"], row["model"]), ("ollama", "ollama/qwen3.5:2b"))
        self.assertEqual([a["error"] is None for a in row["attempts"]], [False, True])
        self.assertIn("model crashed", row["attempts"][0]["error"])
        self.assertEqual((row["prompt_tokens"], row["completion_tokens"]), (12, 20))
        self.assertGreater(row["tokens_per_second"], 0)
        self.assertEqual(row["output_chars"], len("Hello there"))

    def test_failure_is_recorded(self):
        store = temp_store()
        dispatcher = dispatcher_with([direct_cap("ollama", "broken:1b")], store)
        with self.assertRaises(RuntimeError):
            asyncio.run(dispatcher.execute_task("hi"))
        row = store.recent(1)[0]
        self.assertEqual(row["outcome"], "failed")
        self.assertIn("All execution routes failed", row["error"])
        self.assertIsNone(row["route"])

    def test_traces_can_be_turned_off(self):
        store = temp_store()
        dispatcher = dispatcher_with([direct_cap("ollama", "qwen3.5:2b")], store)
        dispatcher.config.traces = False
        asyncio.run(dispatcher.execute_task("hi"))
        self.assertEqual(store.recent(), [])
        self.assertEqual(dispatcher.last_trace.outcome, "succeeded")  # still available in memory


class TestPermissionTraces(unittest.TestCase):
    def test_permission_decisions_are_recorded(self):
        class FakeHarness:
            def run_task(self, prompt, on_chunk=None, timeout=None, permission_handler=None):
                options = [{"optionId": "a1", "kind": "allow_once"}, {"optionId": "r1", "kind": "reject_once"}]
                permission_handler({"title": "Edit main.py"}, options)
                permission_handler({"title": "Run rm -rf build"}, options)
                on_chunk("done")
                return 0, "done", ""

            def cancel(self):
                pass

        harness_cap = Capability(name="claude_code", display_name="Claude Code",
                                 execution_type=ExecutionType.AGENT_HARNESS, status=CapabilityStatus.READY)
        store = temp_store()
        dispatcher = dispatcher_with([harness_cap], store)
        answers = iter(["a1", "r1"])
        with patch.object(dispatcher.registry, "get_harness_instances", return_value={"claude_code": FakeHarness()}):
            asyncio.run(dispatcher.execute_task("edit main.py", on_permission=lambda tool, opts: next(answers)))
        row = store.recent(1)[0]
        self.assertEqual(row["route"], "claude_code")
        self.assertEqual(row["permissions"], [{"tool": "Edit main.py", "decision": "allow_once"},
                                              {"tool": "Run rm -rf build", "decision": "reject_once"}])


if __name__ == "__main__":
    unittest.main()
