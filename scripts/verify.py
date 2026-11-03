"""Run every check CI runs, in one command. This is the definition of done.

Usage:
    python scripts/verify.py                 # everything
    python scripts/verify.py --only <group>  # one group, see CHECKS below

Uses the project virtualenv (VENV below) when it exists, so nothing has to be
activated first; set VERIFY_PYTHON to use another interpreter (e.g. from a git
worktree, which has no virtualenv of its own). Exits non-zero on the first failure.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# --- Repo-specific configuration --------------------------------------------
VENV = ROOT / "packages/engine/.venv"
# (group, name, working directory relative to ROOT, command). "{py}" is the Python
# interpreter, "{yarn}" is yarn. A check whose directory is missing is skipped.
CHECKS: list[tuple[str, str, str, list[str]]] = [
    ("python", "ruff", ".", ["{py}", "-m", "ruff", "check", "packages/engine", "scripts"]),
    ("python", "engine tests", "packages/engine", ["{py}", "-m", "pytest", "tests", "-q"]),
    ("python", "release retention tests", ".", ["{py}", "-m", "unittest", "scripts/test_prune_r2_releases.py"]),
    ("python", "cli sanity", ".", ["{py}", "-m", "emiliano.cli", "--help"]),
    ("desktop", "desktop typecheck", ".", ["{yarn}", "workspace", "@emiliano/desktop", "tsc", "--noEmit"]),
]
# -----------------------------------------------------------------------------


def python_interpreter() -> str:
    if os.environ.get("VERIFY_PYTHON"):
        return os.environ["VERIFY_PYTHON"]
    for candidate in (VENV / "Scripts" / "python.exe", VENV / "bin" / "python"):
        if candidate.exists():
            return str(candidate)
    return sys.executable


def secret_scan() -> list[tuple[str, str, str, list[str]]]:
    # "{gitleaks}" resolves to None when it is not installed; CI always runs it.
    return [("secrets", "secret scan", ".", ["{gitleaks}", "git", "--no-banner", "--redact", "."])]


def main() -> int:
    groups = sorted({group for group, *_ in CHECKS} | {"secrets"})
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", choices=groups)
    args = parser.parse_args()

    tools = {"{py}": python_interpreter(), "{yarn}": shutil.which("yarn") or "yarn", "{gitleaks}": shutil.which("gitleaks")}
    skipped: list[str] = []
    for group, name, cwd, cmd in CHECKS + secret_scan():
        if args.only and group != args.only:
            continue
        workdir = ROOT / cwd
        reason = None
        if not workdir.exists():
            reason = f"{cwd} not found"
        elif "{yarn}" in cmd and not any((d / "node_modules").exists() for d in (workdir, ROOT)):
            reason = f"run `yarn install` in {cwd} first"
        elif "{gitleaks}" in cmd and not tools["{gitleaks}"]:
            reason = "gitleaks not installed"
        if reason:
            print(f"-- {name}: SKIPPED ({reason})")
            skipped.append(name)
            continue
        print(f"-- {name}", flush=True)
        argv = [tools.get(part, part) for part in cmd]
        if subprocess.run(argv, cwd=workdir).returncode != 0:
            print(f"FAILED: {name}", file=sys.stderr)
            return 1
    if skipped:
        print(f"verify: passed, but NOT COMPLETE. Skipped: {', '.join(skipped)}")
    else:
        print("verify: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
