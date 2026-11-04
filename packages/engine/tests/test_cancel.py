"""
Tests that stopping a task stops the agent process, not just the chat.
"""

import asyncio
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import List
from unittest.mock import patch

from emiliano.core.capabilities import Capability, CapabilityStatus, ExecutionType
from emiliano.harnesses import acp
from emiliano.harnesses.acp import AcpSession
from emiliano.harnesses.base import BaseHarness, HarnessInvocation
from emiliano.server.app import get_dispatcher

AGENT_ARGS = [sys.executable, str(Path(__file__).with_name("fake_acp_agent.py"))]


def _cancel_after(target, delay: float) -> threading.Timer:
    timer = threading.Timer(delay, target.cancel)
    timer.start()
    return timer


class SleepHarness(BaseHarness):
    """A plain-CLI harness whose task is a long sleep."""

    def __init__(self):
        super().__init__(name="sleeper", command=sys.executable)

    def check_authentication(self):
        return True, "ok"

    def build_task_command(self, prompt: str) -> List[str]:
        return [sys.executable, "-c", "import time; time.sleep(60)"]

    def build_invocation(self, prompt: str) -> HarnessInvocation:
        return HarnessInvocation(args=self.build_task_command(prompt))


class TestAcpCancel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_agent_that_honors_cancel_stops_promptly(self):
        session = AcpSession(AGENT_ARGS, cwd=self.tmp.name)
        _cancel_after(session, 1.0)
        start = time.monotonic()
        code, _, err = session.run("hang", timeout=30)
        self.assertEqual(code, 130)
        self.assertIn("stopped by user", err)
        self.assertLess(time.monotonic() - start, acp.CANCEL_GRACE_S + 1)

    def test_agent_that_ignores_cancel_is_killed(self):
        with patch.object(acp, "CANCEL_GRACE_S", 0.5):
            session = AcpSession(AGENT_ARGS, cwd=self.tmp.name)
            _cancel_after(session, 1.0)
            start = time.monotonic()
            code, _, _ = session.run("stubborn", timeout=30)
        self.assertEqual(code, 130)
        self.assertLess(time.monotonic() - start, 10)
        self.assertIsNotNone(session.proc.poll())

    def test_cancel_before_start_is_harmless(self):
        AcpSession(AGENT_ARGS, cwd=self.tmp.name).cancel()


class TestHarnessCancel(unittest.TestCase):
    def test_cancel_kills_cli_process(self):
        harness = SleepHarness()
        _cancel_after(harness, 1.0)
        start = time.monotonic()
        code, _, err = harness.run_task("x", cwd=os.getcwd(), timeout=30)
        self.assertEqual(code, 130)
        self.assertIn("stopped by user", err)
        self.assertLess(time.monotonic() - start, 15)

    def test_cancel_reaches_acp_session(self):
        harness = SleepHarness()
        harness.acp_command = "fake"
        with patch.object(SleepHarness, "resolve_acp_executable", return_value=AGENT_ARGS[0]), \
             patch("emiliano.harnesses.base.AcpSession") as session_cls:
            started = threading.Event()

            def fake_run(prompt, timeout):
                started.set()
                time.sleep(0.5)
                return 130, "", "Task stopped by user."

            session_cls.return_value.run.side_effect = fake_run
            worker = threading.Thread(target=harness.run_task, args=("x",), kwargs={"timeout": 5})
            worker.start()
            started.wait(5)
            harness.cancel()
            worker.join(5)
        session_cls.return_value.cancel.assert_called_once()

    def test_cancel_when_idle_is_harmless(self):
        SleepHarness().cancel()


class TestDispatcherStopsHarness(unittest.TestCase):
    def test_cancelling_execute_task_cancels_harness(self):
        dispatcher = get_dispatcher()
        harness = SleepHarness()
        cap = Capability(name="sleeper", display_name="Sleeper", execution_type=ExecutionType.AGENT_HARNESS,
                         status=CapabilityStatus.READY)
        cancelled = threading.Event()
        original_cancel = harness.cancel

        def spy_cancel():
            cancelled.set()
            original_cancel()

        async def scenario():
            task = asyncio.create_task(dispatcher.execute_task(goal="fix the bug"))
            await asyncio.sleep(1.5)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        with patch.object(dispatcher, "route_task", return_value=[cap]), \
             patch.object(dispatcher.registry, "get_harness_instances", return_value={"sleeper": harness}), \
             patch.object(harness, "cancel", side_effect=spy_cancel):
            asyncio.run(scenario())
        self.assertTrue(cancelled.wait(5))


if __name__ == "__main__":
    unittest.main()
