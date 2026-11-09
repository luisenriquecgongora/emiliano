"""
Eval runner: runs a suite of fixed tasks against one target (a local or remote model, or a coding agent)
and scores each task automatically, so changes to routing, prompts or context handling can be measured.

Task kinds (see suites/*.yaml):
- route:  is the goal sent to a direct model or to an agent harness? Calls no model.
- answer: the target answers a question; the reply is checked (contains, regex, equals, ...).
- code:   files are written to an empty folder, the target is asked to change them, then a check command
          must exit 0. Direct models cannot edit files yet, so these are skipped for them.

Every task runs in its own empty temporary folder, so a project's EMILIANO.md or CLAUDE.md never leaks in.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

SUITES_DIR = Path(__file__).parent / "suites"
PROVIDERS = {"ollama", "anthropic", "openai", "deepseek", "gemini"}
CHECK_TIMEOUT_S = 120


@dataclass
class Target:
    """What answers the tasks: 'ollama', 'ollama:qwen3.5:2b', 'anthropic:claude-opus-5-5' or 'claude_code'."""

    spec: str
    provider: Optional[str] = None
    harness: Optional[str] = None
    model: Optional[str] = None
    reasoning: Optional[bool] = None  # force a local model's reasoning on/off; None = Emiliano decides per goal

    @classmethod
    def parse(cls, spec: str) -> "Target":
        name, _, model = spec.partition(":")
        name = name.strip().lower()
        if name in PROVIDERS:
            return cls(spec=spec, provider=name, model=model or None)
        return cls(spec=spec, harness=name, model=model or None)

    @property
    def is_direct(self) -> bool:
        return self.provider is not None

    def dispatch_args(self) -> Dict[str, Any]:
        args: Dict[str, Any] = {"provider_override": self.provider, "harness_override": self.harness,
                                "model_override": self.model}
        if self.reasoning is not None:
            args["reasoning"] = self.reasoning
        return args


@dataclass
class TaskResult:
    id: str
    kind: str
    status: str  # "passed" | "failed" | "flaky" (passed some repeats) | "skipped" | "error"
    detail: str = ""
    runs: int = 1
    passes: Optional[int] = None  # how many of the runs passed; None for a single run (see status)
    duration_s: Optional[float] = None
    first_output_s: Optional[float] = None
    tokens_per_second: Optional[float] = None
    route: Optional[str] = None
    output: str = ""  # start of the target's reply, to see why a task failed


OUTPUT_PREVIEW = 500


@dataclass
class SuiteReport:
    suite: str
    target: str
    started_at: str
    results: List[TaskResult] = field(default_factory=list)

    def count(self, status: str) -> int:
        return sum(1 for r in self.results if r.status == status)

    @property
    def pass_rate(self) -> Optional[float]:
        """Passed runs over all scored runs (skipped tasks do not count)."""
        scored = [r for r in self.results if r.status != "skipped"]
        runs = sum(r.runs for r in scored)
        passed = sum(r.passes if r.passes is not None else int(r.status == "passed") for r in scored)
        return round(passed / runs, 3) if runs else None

    def median(self, attr: str) -> Optional[float]:
        values = [getattr(r, attr) for r in self.results if getattr(r, attr) is not None]
        return round(statistics.median(values), 2) if values else None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "suite": self.suite, "target": self.target, "started_at": self.started_at,
            "summary": {
                "passed": self.count("passed"), "failed": self.count("failed"), "flaky": self.count("flaky"),
                "errors": self.count("error"), "skipped": self.count("skipped"), "pass_rate": self.pass_rate,
                "runs_per_task": max((r.runs for r in self.results), default=1),
                "median_duration_s": self.median("duration_s"),
                "median_first_output_s": self.median("first_output_s"),
                "median_tokens_per_second": self.median("tokens_per_second"),
            },
            "results": [asdict(r) for r in self.results],
        }


def list_suites() -> List[str]:
    return sorted(p.stem for p in SUITES_DIR.glob("*.yaml"))


def load_suite(name_or_path: str) -> Dict[str, Any]:
    path = Path(name_or_path)
    if not path.exists():
        path = SUITES_DIR / f"{name_or_path}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No eval suite '{name_or_path}'. Built-in suites: {', '.join(list_suites())}")
    suite = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    suite.setdefault("name", path.stem)
    ids = [t.get("id") for t in suite.get("tasks", [])]
    if None in ids or len(ids) != len(set(ids)):
        raise ValueError(f"Suite {path}: every task needs a unique id")
    return suite


def check_answer(output: str, expect: Dict[str, Any]) -> Optional[str]:
    """None when the output meets every expectation, else why it does not."""
    text = output.strip()
    low = text.lower()
    for key, value in expect.items():
        if key == "contains" and str(value).lower() not in low:
            return f"missing {value!r}"
        if key == "all_of":
            missing = [v for v in value if str(v).lower() not in low]
            if missing:
                return f"missing {missing}"
        if key == "any_of" and not any(str(v).lower() in low for v in value):
            return f"none of {value}"
        if key == "not_contains" and str(value).lower() in low:
            return f"should not contain {value!r}"
        if key == "regex" and not re.search(value, text, re.IGNORECASE | re.MULTILINE):
            return f"no match for /{value}/"
        if key == "equals" and low.strip(" .\n") != str(value).lower():
            return f"expected exactly {value!r}"
        if key == "json":
            try:
                parsed = json.loads(_strip_code_fence(text))
            except ValueError:
                return "not valid JSON"
            wrong = {k: parsed.get(k) for k, v in value.items() if not isinstance(parsed, dict) or parsed.get(k) != v}
            if wrong:
                return f"JSON fields differ: {wrong}"
        if key == "max_chars" and len(text) > value:
            return f"{len(text)} chars, limit {value}"
    return None


def combine_runs(runs: List[TaskResult]) -> TaskResult:
    """One result for repeated runs of a task: passes counted, timings as medians, the first failure kept."""
    if len(runs) == 1:
        return runs[0]
    first = runs[0]
    if all(r.status == "skipped" for r in runs):
        return first
    passes = sum(r.status == "passed" for r in runs)
    if passes == len(runs):
        status = "passed"
    elif passes:
        status = "flaky"
    else:
        status = "error" if all(r.status == "error" for r in runs) else "failed"
    failure = next((r for r in runs if r.status != "passed"), None)

    def median(attr):
        values = [getattr(r, attr) for r in runs if getattr(r, attr) is not None]
        return round(statistics.median(values), 2) if values else None

    return TaskResult(
        first.id, first.kind, status, detail=failure.detail if failure else "", runs=len(runs), passes=passes,
        duration_s=median("duration_s"), first_output_s=median("first_output_s"),
        tokens_per_second=median("tokens_per_second"), route=first.route,
        output=failure.output if failure else first.output,
    )


def goal_text(task: Dict[str, Any]) -> str:
    """The task's goal, with {filler} replaced by filler.text repeated filler.repeat times (long prompts)."""
    goal = task["goal"]
    filler = task.get("filler")
    if filler:
        goal = goal.replace("{filler}", " ".join([filler["text"]] * int(filler.get("repeat", 1))))
    return goal


def _strip_code_fence(text: str) -> str:
    match = re.match(r"^```[a-zA-Z]*\s*\n(.*)\n```$", text.strip(), re.DOTALL)
    return match.group(1) if match else text


def _check_command(command: str) -> List[str]:
    """Runs 'python ...' checks with this interpreter, so they work without python on PATH."""
    parts = shlex.split(command, posix=True)
    if parts and parts[0] in ("python", "python3"):
        parts[0] = sys.executable
    return parts


class EvalRunner:
    def __init__(self, dispatcher=None, timeout: float = 180.0):
        if dispatcher is None:
            from ..core.dispatcher import ExecutionDispatcher
            dispatcher = ExecutionDispatcher()
        self.dispatcher = dispatcher
        self.timeout = timeout

    async def run_suite(self, suite: Dict[str, Any], target: Target, on_result=None, repeat: int = 1) -> SuiteReport:
        """Runs every task; repeat > 1 runs model tasks that many times (route tasks are deterministic: once)."""
        report = SuiteReport(suite=suite["name"], target=target.spec,
                             started_at=datetime.now(timezone.utc).isoformat())
        for task in suite.get("tasks", []):
            times = 1 if task.get("kind") == "route" else max(1, repeat)
            result = combine_runs([await self.run_task(task, target) for _ in range(times)])
            report.results.append(result)
            if on_result:
                on_result(result)
        return report

    async def run_task(self, task: Dict[str, Any], target: Target) -> TaskResult:
        kind = task.get("kind", "answer")
        if kind == "route":
            return self._run_route(task)
        if kind == "code" and target.is_direct:
            return TaskResult(task["id"], kind, "skipped", "direct models cannot edit files yet")
        if kind not in ("answer", "code"):
            return TaskResult(task["id"], kind, "error", f"unknown task kind {kind!r}")

        previous_cwd = os.getcwd()
        with tempfile.TemporaryDirectory(prefix=f"emiliano-eval-{task['id']}-") as workdir:
            for rel, content in (task.get("files") or {}).items():
                path = Path(workdir, rel)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            os.chdir(workdir)  # harnesses work in, and context files are read from, the current folder
            try:
                result = await self._run_in_workdir(task, kind, target, workdir)
            finally:
                os.chdir(previous_cwd)
        return result

    def _run_route(self, task: Dict[str, Any]) -> TaskResult:
        expected = task["expect"]["route"]
        actual = "harness" if self.dispatcher.requires_agent_harness(task["goal"]) else "direct"
        status = "passed" if actual == expected else "failed"
        return TaskResult(task["id"], "route", status, "" if status == "passed" else f"routed to {actual}",
                          route=actual)

    async def _run_in_workdir(self, task: Dict[str, Any], kind: str, target: Target, workdir: str) -> TaskResult:
        started = time.monotonic()
        try:
            _, output = await self.dispatcher.execute_task(goal_text(task), timeout=self.timeout,
                                                           **target.dispatch_args())
        except Exception as e:
            result = TaskResult(task["id"], kind, "error", str(e)[:300])
        else:
            if kind == "answer":
                problem = check_answer(output, task.get("expect") or {})
            else:
                problem = self._run_check(task["check"], workdir)
            result = TaskResult(task["id"], kind, "failed" if problem else "passed", problem or "",
                                output=output[:OUTPUT_PREVIEW])
        trace = getattr(self.dispatcher, "last_trace", None)
        result.duration_s = round(time.monotonic() - started, 2)
        if trace is not None:
            result.first_output_s = trace.first_output_s
            result.tokens_per_second = trace.tokens_per_second
            result.route = trace.model or trace.route
        return result

    @staticmethod
    def _run_check(command: str, workdir: str) -> Optional[str]:
        try:
            proc = subprocess.run(_check_command(command), cwd=workdir, capture_output=True, text=True,
                                  timeout=CHECK_TIMEOUT_S)
        except (OSError, subprocess.TimeoutExpired) as e:
            return f"check could not run: {e}"
        if proc.returncode == 0:
            return None
        tail = (proc.stdout + proc.stderr).strip().splitlines()[-3:]
        return f"check failed: {' | '.join(tail)}"[:300]


def default_results_dir() -> Path:
    path = Path(os.environ.get("EMILIANO_EVALS_DIR") or Path.home() / ".emiliano" / "evals")
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_report(report: SuiteReport, out_dir: Optional[Path] = None) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_target = re.sub(r"[^A-Za-z0-9._-]+", "_", report.target)
    path = (out_dir or default_results_dir()) / f"{stamp}-{report.suite}-{safe_target}.json"
    path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return path
