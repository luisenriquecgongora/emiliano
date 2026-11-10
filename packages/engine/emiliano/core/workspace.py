"""
Workspace change detection for Emiliano.
Lets the dispatcher tell whether a failed agent harness modified files before
deciding whether it is safe to retry the task with another route.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class WorkspaceSnapshot:
    """HEAD commit plus (mtime_ns, size) of every path git reports as changed or untracked."""
    head: Optional[str]
    files: Dict[str, Tuple[int, int]]


def _git(args: List[str], cwd: str, timeout: float) -> Optional[str]:
    try:
        res = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return res.stdout if res.returncode == 0 else None


def workspace_snapshot(path: str, timeout: float = 15.0) -> Optional[WorkspaceSnapshot]:
    """
    Snapshots the git working tree containing `path`. Returns None when `path` is not
    inside a git repository (or git is unavailable), meaning changes cannot be detected.
    """
    root = _git(["rev-parse", "--show-toplevel"], path, timeout)
    status = _git(["status", "--porcelain=v1", "-uall", "-z"], path, timeout)
    if root is None or status is None:
        return None
    root = root.strip()
    head = _git(["rev-parse", "HEAD"], path, timeout)  # None in a repo with no commits yet

    files: Dict[str, Tuple[int, int]] = {}
    entries = status.split("\0")
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        rel_path = entry[3:]
        if entry[0] in "RC":
            i += 1  # Renames and copies are followed by the original path
        try:
            st = os.stat(os.path.join(root, rel_path))
            files[rel_path] = (st.st_mtime_ns, st.st_size)
        except OSError:
            files[rel_path] = (-1, -1)  # Deleted
    return WorkspaceSnapshot(head=head.strip() if head else None, files=files)


def changed_paths(before: WorkspaceSnapshot, after: WorkspaceSnapshot) -> List[str]:
    """Lists paths that differ between two snapshots; a new commit is reported as 'HEAD'."""
    paths = sorted(p for p in before.files.keys() | after.files.keys() if before.files.get(p) != after.files.get(p))
    if before.head != after.head:
        paths.insert(0, "HEAD")
    return paths


class IsolatedWorkspace:
    """
    Manages an isolated Git worktree for an agent execution task.
    Allows running agents in an isolated temporary branch, diffing changes,
    and merging back or discarding.
    """

    def __init__(
        self,
        base_dir: str = ".",
        task_id: Optional[str] = None,
        branch_name: Optional[str] = None,
    ):
        self.base_dir = os.path.abspath(base_dir)
        self.repo_root: Optional[str] = None
        self.base_commit: Optional[str] = None
        self.task_id = task_id or uuid.uuid4().hex[:8]
        self.branch_name = branch_name or f"emiliano/task-{self.task_id}"
        self.worktree_dir: Optional[str] = None
        self._created = False

    def is_git_repo(self) -> bool:
        root = _git(["rev-parse", "--show-toplevel"], self.base_dir, timeout=5.0)
        if root:
            self.repo_root = root.strip()
            return True
        return False

    def create(self) -> str:
        """
        Creates a new git worktree in `.emiliano/worktrees/<task_id>`
        branched off HEAD. Returns the absolute path to the worktree.
        """
        if not self.is_git_repo():
            raise RuntimeError(f"Cannot isolate workspace: '{self.base_dir}' is not inside a Git repository.")

        assert self.repo_root is not None
        head = _git(["rev-parse", "HEAD"], self.repo_root, timeout=5.0)
        self.base_commit = head.strip() if head else None

        worktrees_root = os.path.join(self.repo_root, ".emiliano", "worktrees")
        os.makedirs(worktrees_root, exist_ok=True)
        self.worktree_dir = os.path.abspath(os.path.join(worktrees_root, self.task_id))

        if os.path.exists(self.worktree_dir):
            _git(["worktree", "remove", "--force", self.worktree_dir], self.repo_root, timeout=10.0)

        res = _git(["worktree", "add", "-b", self.branch_name, self.worktree_dir, "HEAD"], self.repo_root, timeout=15.0)
        if res is None and not os.path.isdir(self.worktree_dir):
            raise RuntimeError(f"Failed to create git worktree at {self.worktree_dir}")

        self._created = True
        return self.worktree_dir

    @property
    def path(self) -> str:
        if not self._created or not self.worktree_dir:
            raise RuntimeError("Worktree has not been created yet.")
        return self.worktree_dir

    def get_diff(self, base_ref: Optional[str] = None) -> str:
        """Returns the git diff of changes made inside the worktree against base_ref."""
        if not self.worktree_dir:
            return ""
        ref = base_ref or self.base_commit or "HEAD"
        _git(["add", "-N", "."], self.worktree_dir, timeout=5.0)
        diff = _git(["diff", ref], self.worktree_dir, timeout=10.0)
        return diff or ""

    def get_changed_files(self) -> List[str]:
        """Returns list of modified, added, or deleted files inside the worktree."""
        if not self.worktree_dir:
            return []
        status = _git(["status", "--porcelain=v1"], self.worktree_dir, timeout=10.0)
        if not status:
            return []
        files = []
        for line in status.splitlines():
            line = line.strip()
            if len(line) > 3:
                files.append(line[3:].strip())
        return files

    def commit(self, message: str) -> bool:
        """Stages all changes and creates a commit on the task branch."""
        if not self.worktree_dir:
            return False
        _git(["add", "-A"], self.worktree_dir, timeout=10.0)
        res = _git(["commit", "-m", message], self.worktree_dir, timeout=10.0)
        return res is not None

    def merge_back(self, target_branch: Optional[str] = None) -> bool:
        """Merges the task branch back into the target branch (or original current branch)."""
        if not self.repo_root or not self._created:
            return False
        target = target_branch or _git(["branch", "--show-current"], self.repo_root, timeout=5.0)
        if not target:
            return False
        target = target.strip()
        current = _git(["branch", "--show-current"], self.repo_root, timeout=5.0)
        if current and current.strip() != target:
            _git(["checkout", target], self.repo_root, timeout=10.0)

        changed = self.get_changed_files()
        if changed:
            self.commit(f"chore: changes from {self.task_id}")
        res = _git(["merge", "--no-ff", self.branch_name, "-m", f"feat: apply task {self.task_id}"], self.repo_root, timeout=15.0)
        if res is None:
            _git(["merge", "--abort"], self.repo_root, timeout=5.0)
            return False
        return True

    def discard(self) -> None:
        """Removes the worktree and deletes the temporary task branch."""
        if self._created and self.worktree_dir and self.repo_root:
            _git(["worktree", "remove", "--force", self.worktree_dir], self.repo_root, timeout=15.0)
            if os.path.exists(self.worktree_dir):
                shutil.rmtree(self.worktree_dir, ignore_errors=True)
            _git(["worktree", "prune"], self.repo_root, timeout=5.0)
            _git(["branch", "-D", self.branch_name], self.repo_root, timeout=10.0)
            self._created = False
            self.worktree_dir = None

    def __enter__(self) -> "IsolatedWorkspace":
        self.create()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.discard()
