"""
Tests for the eval runner (emiliano/evals/runner.py) and the built-in suites. No model is called:
the dispatcher is replaced by fakes.
"""

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path

from emiliano.core.dispatcher import ExecutionDispatcher
from emiliano.core.traces import TaskTrace
from emiliano.evals.runner import (
    EvalRunner,
    Target,
    TaskResult,
    check_answer,
    combine_runs,
    goal_text,
    list_suites,
    load_suite,
    save_report,
)


class FakeDispatcher:
    """Answers with a fixed reply, or runs `edit(cwd)` to change files like a coding agent would."""

    requires_agent_harness = staticmethod(ExecutionDispatcher.requires_agent_harness)

    def __init__(self, reply="", edit=None, error=None, replies=None):
        self.reply, self.edit, self.error = reply, edit, error
        self.replies = list(replies) if replies else None  # one reply per call, in order
        self.calls = []
        self.last_trace = None

    async def execute_task(self, goal, timeout=None, **kwargs):
        self.calls.append({"goal": goal, "cwd": os.getcwd(), **kwargs})
        if self.replies:
            self.reply = self.replies.pop(0)
        trace = TaskTrace(goal=goal, policy="auto")
        trace.mark_output(self.reply or "x")
        trace.completion_tokens = 10
        trace.model = "ollama/fake:1b"
        trace.finish("succeeded")
        self.last_trace = trace
        if self.error:
            raise RuntimeError(self.error)
        if self.edit:
            self.edit(os.getcwd())
        return None, self.reply


def run(runner, task, target="ollama"):
    return asyncio.run(runner.run_task(task, Target.parse(target)))


class TestTarget(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(Target.parse("ollama").dispatch_args(),
                         {"provider_override": "ollama", "harness_override": None, "model_override": None})
        self.assertEqual(Target.parse("ollama:qwen3.5:2b").model, "qwen3.5:2b")
        t = Target.parse("claude_code")
        self.assertFalse(t.is_direct)
        self.assertEqual(t.harness, "claude_code")
        self.assertEqual(Target.parse("anthropic:claude-opus-5-5").provider, "anthropic")


class TestCheckAnswer(unittest.TestCase):
    def test_expectations(self):
        self.assertIsNone(check_answer("The answer is 391.", {"regex": r"\b391\b"}))
        self.assertIn("missing", check_answer("blue", {"contains": "red"}))
        self.assertIsNone(check_answer("Red, Blue, Yellow", {"all_of": ["red", "blue", "yellow"], "max_chars": 60}))
        self.assertIn("limit", check_answer("x" * 100, {"max_chars": 60}))
        self.assertIsNone(check_answer("Blue.", {"equals": "blue"}))
        self.assertIsNone(check_answer("verde", {"any_of": ["green", "verde"]}))
        self.assertIn("should not", check_answer("I cannot", {"not_contains": "cannot"}))

    def test_json(self):
        fenced = '```json\n{"name": "Maria Lopez", "age": 34}\n```'
        self.assertIsNone(check_answer(fenced, {"json": {"name": "Maria Lopez", "age": 34}}))
        self.assertIn("differ", check_answer('{"name": "Maria", "age": 34}', {"json": {"name": "Maria Lopez"}}))
        self.assertEqual(check_answer("not json", {"json": {"a": 1}}), "not valid JSON")

    def test_filler(self):
        task = {"goal": "start {filler} end", "filler": {"text": "ab", "repeat": 3}}
        self.assertEqual(goal_text(task), "start ab ab ab end")


class TestRunner(unittest.TestCase):
    def test_route_task_calls_no_model(self):
        dispatcher = FakeDispatcher()
        runner = EvalRunner(dispatcher=dispatcher)
        ok = run(runner, {"id": "g", "kind": "route", "goal": "git status", "expect": {"route": "harness"}})
        bad = run(runner, {"id": "h", "kind": "route", "goal": "hi", "expect": {"route": "harness"}})
        self.assertEqual((ok.status, bad.status, bad.detail), ("passed", "failed", "routed to direct"))
        self.assertEqual(dispatcher.calls, [])

    def test_answer_task_runs_in_empty_folder_and_reads_trace(self):
        dispatcher = FakeDispatcher(reply="391")
        before = os.getcwd()
        result = run(EvalRunner(dispatcher=dispatcher),
                     {"id": "a", "goal": "17*23?", "expect": {"regex": r"\b391\b"}}, target="ollama:fake:1b")
        self.assertEqual(result.status, "passed")
        self.assertEqual(result.route, "ollama/fake:1b")
        self.assertIsNotNone(result.first_output_s)
        call = dispatcher.calls[0]
        self.assertEqual((call["provider_override"], call["model_override"]), ("ollama", "fake:1b"))
        self.assertNotEqual(os.path.realpath(call["cwd"]), os.path.realpath(before))
        self.assertEqual(os.listdir(call["cwd"]) if os.path.exists(call["cwd"]) else [], [])
        self.assertEqual(os.getcwd(), before)  # restored

    def test_dispatch_error_is_reported(self):
        result = run(EvalRunner(dispatcher=FakeDispatcher(error="Ollama is not running")),
                     {"id": "a", "goal": "q", "expect": {"contains": "x"}})
        self.assertEqual(result.status, "error")
        self.assertIn("Ollama is not running", result.detail)

    def test_code_task_passes_when_agent_fixes_files(self):
        task = {"id": "c", "kind": "code", "goal": "fix calc.py",
                "files": {"calc.py": "def total(n):\n    return sum(range(n))\n",
                          "check.py": "from calc import total\nassert total(5) == 15\n"},
                "check": "python check.py"}

        def fix(cwd):
            Path(cwd, "calc.py").write_text("def total(n):\n    return sum(range(n + 1))\n")

        self.assertEqual(run(EvalRunner(dispatcher=FakeDispatcher(edit=fix)), task, "claude_code").status, "passed")
        unfixed = run(EvalRunner(dispatcher=FakeDispatcher()), task, "claude_code")
        self.assertEqual(unfixed.status, "failed")
        self.assertIn("check failed", unfixed.detail)

    def test_code_task_skipped_for_direct_models(self):
        dispatcher = FakeDispatcher()
        result = run(EvalRunner(dispatcher=dispatcher), {"id": "c", "kind": "code", "goal": "x", "check": "python -V"})
        self.assertEqual(result.status, "skipped")
        self.assertEqual(dispatcher.calls, [])

    def test_report_summary_and_file(self):
        suite = {"name": "mini", "tasks": [
            {"id": "a", "goal": "q", "expect": {"contains": "yes"}},
            {"id": "b", "goal": "q", "expect": {"contains": "no"}},
            {"id": "c", "kind": "code", "goal": "x", "check": "python -V"},
        ]}
        report = asyncio.run(EvalRunner(dispatcher=FakeDispatcher(reply="yes")).run_suite(suite, Target.parse("ollama")))
        summary = report.to_dict()["summary"]
        self.assertEqual((summary["passed"], summary["failed"], summary["skipped"]), (1, 1, 1))
        self.assertEqual(summary["pass_rate"], 0.5)
        path = save_report(report, Path(tempfile.mkdtemp()))
        self.assertEqual(json.loads(path.read_text())["suite"], "mini")


class TestRepeat(unittest.TestCase):
    def test_combine_runs(self):
        def result(status, duration):
            return TaskResult("t", "answer", status, detail="" if status == "passed" else "wrong",
                              duration_s=duration, output=status)

        flaky = combine_runs([result("passed", 1.0), result("failed", 3.0), result("passed", 2.0)])
        self.assertEqual((flaky.status, flaky.passes, flaky.runs), ("flaky", 2, 3))
        self.assertEqual((flaky.duration_s, flaky.detail, flaky.output), (2.0, "wrong", "failed"))
        self.assertEqual(combine_runs([result("passed", 1.0)] * 2).status, "passed")
        self.assertEqual(combine_runs([result("failed", 1.0)] * 2).status, "failed")
        self.assertEqual(combine_runs([result("error", 1.0)] * 2).status, "error")

    def test_repeat_runs_model_tasks_and_rates_runs(self):
        suite = {"name": "mini", "tasks": [
            {"id": "route", "kind": "route", "goal": "git status", "expect": {"route": "harness"}},
            {"id": "answer", "goal": "q", "expect": {"contains": "yes"}},
        ]}
        dispatcher = FakeDispatcher(replies=["yes", "no", "yes", "yes"])
        report = asyncio.run(EvalRunner(dispatcher=dispatcher).run_suite(suite, Target.parse("ollama"), repeat=4))
        self.assertEqual(len(dispatcher.calls), 4)  # the route task calls no model and runs once
        route, answer = report.results
        self.assertEqual((route.runs, route.status), (1, "passed"))
        self.assertEqual((answer.status, answer.passes, answer.runs), ("flaky", 3, 4))
        summary = report.to_dict()["summary"]
        self.assertEqual((summary["flaky"], summary["runs_per_task"]), (1, 4))
        self.assertEqual(summary["pass_rate"], 0.8)  # 4 of 5 runs passed

    def test_reasoning_reaches_the_dispatcher(self):
        target = Target.parse("ollama")
        self.assertNotIn("reasoning", target.dispatch_args())  # auto: the dispatcher decides
        target.reasoning = True
        dispatcher = FakeDispatcher(reply="391")
        asyncio.run(EvalRunner(dispatcher=dispatcher).run_task({"id": "a", "goal": "q", "expect": {}}, target))
        self.assertIs(dispatcher.calls[-1]["reasoning"], True)


class TestBuiltinSuites(unittest.TestCase):
    def test_suites_load_and_are_well_formed(self):
        self.assertTrue({"routing", "local-basics", "coding"} <= set(list_suites()))
        for name in list_suites():
            for task in load_suite(name)["tasks"]:
                kind = task.get("kind", "answer")
                self.assertIn(kind, ("route", "answer", "code"), f"{name}/{task['id']}")
                if kind == "code":
                    self.assertTrue(task.get("check") and task.get("files"), f"{name}/{task['id']}")
                else:
                    self.assertTrue(task.get("expect"), f"{name}/{task['id']}")

    def test_coding_fixtures_fail_before_any_fix(self):
        # Each coding task must start broken, or it measures nothing
        runner = EvalRunner(dispatcher=FakeDispatcher())
        for task in load_suite("coding")["tasks"]:
            self.assertEqual(run(runner, task, "claude_code").status, "failed", task["id"])


if __name__ == "__main__":
    unittest.main()
