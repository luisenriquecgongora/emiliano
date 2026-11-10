"""
Unit tests for IsolatedWorkspace (emiliano/core/workspace.py).
Tests git worktree creation, diffing, commits, merging, and automatic cleanup.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from emiliano.core.workspace import IsolatedWorkspace


def _run_git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


class TestIsolatedWorkspace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo_dir = self.tmp.name

        # Initialize a temporary git repository with initial commit
        _run_git(["init", "-b", "main"], cwd=self.repo_dir)
        _run_git(["config", "user.email", "test@example.com"], cwd=self.repo_dir)
        _run_git(["config", "user.name", "Test Agent"], cwd=self.repo_dir)

        readme = Path(self.repo_dir, "README.md")
        readme.write_text("# Test Repo\n", encoding="utf-8")
        _run_git(["add", "README.md"], cwd=self.repo_dir)
        _run_git(["commit", "-m", "initial commit"], cwd=self.repo_dir)

    def tearDown(self):
        self.tmp.cleanup()

    def test_non_git_dir_rejected(self):
        with tempfile.TemporaryDirectory() as plain_dir:
            iso = IsolatedWorkspace(base_dir=plain_dir)
            self.assertFalse(iso.is_git_repo())
            with self.assertRaises(RuntimeError):
                iso.create()

    def test_worktree_lifecycle_diff_and_discard(self):
        iso = IsolatedWorkspace(base_dir=self.repo_dir, task_id="task01")
        self.assertTrue(iso.is_git_repo())

        # 1. Create worktree
        worktree_path = iso.create()
        self.assertTrue(os.path.isdir(worktree_path))
        self.assertEqual(iso.path, worktree_path)

        # 2. Modify a file inside the isolated worktree
        calc_file = Path(worktree_path, "calc.py")
        calc_file.write_text("def add(a, b): return a + b\n", encoding="utf-8")

        # 3. Check changes and diff
        changed = iso.get_changed_files()
        self.assertIn("calc.py", changed)

        diff = iso.get_diff()
        self.assertIn("def add(a, b): return a + b", diff)

        # 4. Verify main working directory is completely untouched!
        self.assertFalse(Path(self.repo_dir, "calc.py").exists())

        # 5. Discard worktree
        iso.discard()
        self.assertFalse(os.path.exists(worktree_path))

    def test_worktree_commit_and_merge_back(self):
        iso = IsolatedWorkspace(base_dir=self.repo_dir, task_id="task02")
        worktree_path = iso.create()

        # Add feature file in worktree
        feature_file = Path(worktree_path, "feature.txt")
        feature_file.write_text("isolated feature content\n", encoding="utf-8")

        # Merge back to main branch
        merged = iso.merge_back(target_branch="main")
        self.assertTrue(merged)

        # Clean up worktree
        iso.discard()

        # Verify the file is now in the main repository
        main_feature = Path(self.repo_dir, "feature.txt")
        self.assertTrue(main_feature.exists())
        self.assertEqual(main_feature.read_text(encoding="utf-8"), "isolated feature content\n")

    def test_context_manager_auto_discards(self):
        worktree_dir = None
        with IsolatedWorkspace(base_dir=self.repo_dir, task_id="task03") as iso:
            worktree_dir = iso.path
            self.assertTrue(os.path.isdir(worktree_dir))

        self.assertFalse(os.path.exists(worktree_dir))

    def test_dispatcher_isolate_workspace_lifecycle(self):
        import asyncio
        from unittest.mock import patch
        from emiliano.core.capabilities import Capability, ExecutionType
        from emiliano.core.dispatcher import ExecutionDispatcher

        disp = ExecutionDispatcher()
        cap = Capability(name="test_cap", display_name="Test", execution_type=ExecutionType.AGENT_HARNESS)

        async def _test():
            captured_ws = []

            async def fake_execute(*args, **kwargs):
                ws = kwargs.get("workspace")
                captured_ws.append(ws)
                Path(ws, "created_in_iso.txt").write_text("ok", encoding="utf-8")
                return cap, "done"

            with patch.object(disp, "_execute_with_fallback", side_effect=fake_execute):
                old_cwd = os.getcwd()
                os.chdir(self.repo_dir)
                try:
                    res_cap, out = await disp.execute_task(
                        goal="test goal",
                        isolate_workspace=True,
                        merge_on_success=True,
                    )
                finally:
                    os.chdir(old_cwd)

            self.assertEqual(out, "done")
            self.assertEqual(len(captured_ws), 1)
            self.assertIn(".emiliano", captured_ws[0])
            self.assertTrue(Path(self.repo_dir, "created_in_iso.txt").exists())

        asyncio.run(_test())

    def test_dispatcher_isolate_workspace_discards_on_error(self):
        import asyncio
        from unittest.mock import patch
        from emiliano.core.dispatcher import ExecutionDispatcher

        disp = ExecutionDispatcher()

        async def _test():
            captured_ws = []

            async def failing_execute(*args, **kwargs):
                ws = kwargs.get("workspace")
                captured_ws.append(ws)
                Path(ws, "dirty.txt").write_text("bad", encoding="utf-8")
                raise RuntimeError("agent crashed")

            with patch.object(disp, "_execute_with_fallback", side_effect=failing_execute):
                old_cwd = os.getcwd()
                os.chdir(self.repo_dir)
                try:
                    with self.assertRaises(RuntimeError):
                        await disp.execute_task(
                            goal="test goal",
                            isolate_workspace=True,
                        )
                finally:
                    os.chdir(old_cwd)

            self.assertFalse(Path(self.repo_dir, "dirty.txt").exists())
            self.assertFalse(os.path.exists(captured_ws[0]))

        asyncio.run(_test())
