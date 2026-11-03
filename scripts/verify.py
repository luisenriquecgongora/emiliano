"""Run every check CI runs, in one command. This is the definition of done.

Usage:
    python scripts/verify.py              # everything
    python scripts/verify.py --only python
    python scripts/verify.py --only desktop

Uses the engine's virtualenv (packages/engine/.venv) when it exists, so nothing has
to be activated first; set EMILIANO_PYTHON to use another interpreter. Exits non-zero
on the first failing check.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "packages" / "engine"


def engine_python() -> str:
    # Worktrees have no virtualenv of their own: point EMILIANO_PYTHON at the main checkout's.
    if os.environ.get("EMILIANO_PYTHON"):
        return os.environ["EMILIANO_PYTHON"]
    for candidate in (ENGINE / ".venv" / "Scripts" / "python.exe", ENGINE / ".venv" / "bin" / "python"):
        if candidate.exists():
            return str(candidate)
    return sys.executable


def python_checks() -> list[tuple[str, list[str], Path]]:
    py = engine_python()
    return [
        ("ruff", [py, "-m", "ruff", "check", "packages/engine", "scripts"], ROOT),
        ("engine tests", [py, "-m", "pytest", "tests", "-q"], ENGINE),
        ("release retention tests", [py, "-m", "unittest", "scripts/test_prune_r2_releases.py"], ROOT),
        ("cli sanity", [py, "-m", "emiliano.cli", "--help"], ROOT),
    ]


def desktop_checks() -> list[tuple[str, list[str], Path]]:
    yarn = shutil.which("yarn") or "yarn"
    return [("desktop typecheck", [yarn, "workspace", "@emiliano/desktop", "tsc", "--noEmit"], ROOT)]


def secret_checks() -> list[tuple[str, list[str], Path]]:
    gitleaks = shutil.which("gitleaks")
    if not gitleaks:
        print("-- gitleaks not installed; skipping secret scan (CI still runs it)")
        return []
    return [("secret scan", [gitleaks, "git", "--no-banner", "--redact", "."], ROOT)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", choices=["python", "desktop", "secrets"])
    args = parser.parse_args()

    groups = {"python": python_checks, "desktop": desktop_checks, "secrets": secret_checks}
    selected = [groups[args.only]] if args.only else list(groups.values())

    for group in selected:
        for name, cmd, cwd in group():
            print(f"-- {name}", flush=True)
            if subprocess.run(cmd, cwd=cwd).returncode != 0:
                print(f"FAILED: {name}", file=sys.stderr)
                return 1
    print("verify: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
