"""
Workspace change detection for Emiliano.
Lets the dispatcher tell whether a failed agent harness modified files before
deciding whether it is safe to retry the task with another route.
"""

from __future__ import annotations

import os
import subprocess
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
