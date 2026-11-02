"""
Tests for harness fallback safety: a harness that fails after changing the workspace
must not be retried through another route, since that could apply the task twice.
"""

import asyncio
import os
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

from emiliano.core.capabilities import Capability, CapabilityStatus, ExecutionType
from emiliano.core.dispatcher import ExecutionAbortedError, ExecutionDispatcher
from emiliano.core.workspace import changed_paths, workspace_snapshot
from emiliano.harnesses.base import ClaudeCodeHarness, CodexHarness


@contextmanager
def _chdir(path):
    old = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


def _git(repo, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, check=True, capture_output=True)


def _make_repo():
    tmp = tempfile.TemporaryDirectory()
    _git(tmp.name, "init", "-q")
    _write(tmp.name, "tracked.txt", "v1")
    _git(tmp.name, "add", ".")
    _git(tmp.name, "commit", "-q", "-m", "init")
    return tmp


def _write(repo, name, text):
    with open(os.path.join(repo, name), "w", encoding="utf-8") as f:
        f.write(text)


class TestWorkspaceSnapshot(unittest.TestCase):
    def setUp(self):
        self.tmp = _make_repo()
        self.repo = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_unchanged_workspace_has_no_changes(self):
        self.assertEqual(changed_paths(workspace_snapshot(self.repo), workspace_snapshot(self.repo)), [])

    def test_detects_modified_untracked_and_deleted_files(self):
        before = workspace_snapshot(self.repo)
        _write(self.repo, "tracked.txt", "v2 changed")
        _write(self.repo, "new.txt", "hello")
        self.assertEqual(changed_paths(before, workspace_snapshot(self.repo)), ["new.txt", "tracked.txt"])

        before = workspace_snapshot(self.repo)
        os.remove(os.path.join(self.repo, "new.txt"))
        self.assertEqual(changed_paths(before, workspace_snapshot(self.repo)), ["new.txt"])

    def test_detects_further_edits_to_already_dirty_file(self):
        _write(self.repo, "tracked.txt", "dirty before the run")
        before = workspace_snapshot(self.repo)
        _write(self.repo, "tracked.txt", "edited again by the harness")
        self.assertEqual(changed_paths(before, workspace_snapshot(self.repo)), ["tracked.txt"])

    def test_detects_new_commit(self):
        before = workspace_snapshot(self.repo)
        _write(self.repo, "tracked.txt", "v2")
        _git(self.repo, "commit", "-q", "-am", "harness commit")
        self.assertEqual(changed_paths(before, workspace_snapshot(self.repo)), ["HEAD"])

    def test_outside_git_repository_returns_none(self):
        with tempfile.TemporaryDirectory() as plain:
            self.assertIsNone(workspace_snapshot(plain))


def _harness_cap(name, display):
    return Capability(name=name, display_name=display, execution_type=ExecutionType.AGENT_HARNESS, status=CapabilityStatus.READY)


class TestHarnessFallbackSafety(unittest.TestCase):
    def setUp(self):
        self.tmp = _make_repo()
        self.repo = self.tmp.name
        self.dispatcher = ExecutionDispatcher()
        routes = [_harness_cap("claude_code", "Claude Code"), _harness_cap("codex", "Codex")]
        self.route_patch = patch.object(self.dispatcher, "route_task", new_callable=AsyncMock, return_value=routes)
        self.route_patch.start()

    def tearDown(self):
        self.route_patch.stop()
        self.tmp.cleanup()

    def _run(self, claude_result, codex_result=(0, "codex did it\n", "")):
        with _chdir(self.repo), \
                patch.object(ClaudeCodeHarness, "run_task", side_effect=claude_result) as claude, \
                patch.object(CodexHarness, "run_task", return_value=codex_result) as codex:
            try:
                return asyncio.run(self.dispatcher.execute_task("fix the bug")), codex
            except Exception as e:
                return e, codex

    def test_failure_without_changes_falls_back(self):
        result, codex = self._run(lambda **kw: (1, "", "crashed on startup"))
        self.assertEqual(result[0].name, "codex")
        codex.assert_called_once()

    def test_failure_after_editing_files_does_not_retry(self):
        def edits_then_fails(**kw):
            _write(self.repo, "tracked.txt", "half-applied change")
            return 1, "", "connection lost"

        result, codex = self._run(edits_then_fails)
        self.assertIsInstance(result, ExecutionAbortedError)
        self.assertIn("tracked.txt", str(result))
        self.assertIn("connection lost", str(result))
        codex.assert_not_called()

    def test_timeout_after_creating_files_does_not_retry(self):
        def creates_then_times_out(**kw):
            _write(self.repo, "generated.py", "print('partial')")
            return 124, "", "Task timed out after 300 seconds."

        result, codex = self._run(creates_then_times_out)
        self.assertIsInstance(result, ExecutionAbortedError)
        self.assertIn("generated.py", str(result))
        codex.assert_not_called()

    def test_soft_failure_still_falls_back(self):
        result, codex = self._run(lambda **kw: (0, "Error: rate limit exceeded, try later", ""))
        self.assertEqual(result[0].name, "codex")
        codex.assert_called_once()

    def test_outside_git_repository_does_not_retry(self):
        with tempfile.TemporaryDirectory() as plain:
            self.repo = plain
            result, codex = self._run(lambda **kw: (1, "", "crashed"))
        self.assertIsInstance(result, ExecutionAbortedError)
        self.assertIn("not a git repository", str(result))
        codex.assert_not_called()


if __name__ == "__main__":
    unittest.main()
