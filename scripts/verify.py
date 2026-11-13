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
# (group, name, working directory relative to ROOT, command). Tokens: "{py}" is the
# Python interpreter, "{ruff}", "{yarn}". A check whose tool or directory is missing
# is skipped and reported.
CHECKS: list[tuple[str, str, str, list[str]]] = [
    ("python", "ruff", ".", ["{ruff}", "check", "packages/engine", "scripts"]),
    ("python", "engine tests", "packages/engine", ["{py}", "-m", "pytest", "tests", "-q"]),
    ("python", "release retention tests", ".", ["{py}", "-m", "unittest", "scripts/test_prune_r2_releases.py"]),
    ("python", "release manifest tests", ".", ["{py}", "-m", "unittest", "scripts/test_publish_release_to_r2.py"]),
    ("python", "cli sanity", ".", ["{py}", "-m", "emiliano.cli", "--help"]),
    ("desktop", "desktop typecheck", ".", ["{yarn}", "workspace", "@emiliano/desktop", "tsc", "--noEmit"]),
    # Node 22+ runs .ts tests directly (type stripping), so the desktop needs no test runner dependency.
    ("desktop", "desktop tests", ".", ["node", "--test", "apps/desktop/src/**/*.test.ts"]),
]
# Linter run on each file an agent edits, by file extension ("{file}" is the file);
# findings go back to the agent. Lint only, never formatters.
EDIT_LINTERS: dict[str, list[str]] = {
    ".py": ["{ruff}", "check", "--quiet", "{file}"],
}
# Skill folders of harnesses that do not read the shared .agents/skills: each needs a
# symlink to every shared skill. Add a folder here when adding such a harness.
SKILL_MIRRORS = [".claude/skills"]
# -----------------------------------------------------------------------------


def python_interpreter() -> str:
    override = os.environ.get("VERIFY_PYTHON")
    if override:
        found = shutil.which(override)
        if not found:
            raise SystemExit(
                f"verify: VERIFY_PYTHON is set to {override}, which is not a program that exists. "
                "Point it at a Python interpreter, or unset it to use the project virtualenv."
            )
        return found
    for candidate in (VENV / "Scripts" / "python.exe", VENV / "bin" / "python"):
        if candidate.exists():
            return str(candidate)
    return sys.executable


def ruff_command(py: str) -> list[str] | None:
    """ruff from the project interpreter if installed there, else from PATH."""
    probe = subprocess.run([py, "-m", "ruff", "--version"], capture_output=True)
    if probe.returncode == 0:
        return [py, "-m", "ruff"]
    on_path = shutil.which("ruff")
    return [on_path] if on_path else None


def tool_tokens(py: str) -> dict[str, list[str] | None]:
    """What the special command tokens run; None means not installed."""
    gitleaks = shutil.which("gitleaks")
    return {
        "{py}": [py],
        "{yarn}": [shutil.which("yarn") or "yarn"],
        "{ruff}": ruff_command(py),
        "{gitleaks}": [gitleaks] if gitleaks else None,
    }


def resolve(part: str, tokens: dict[str, list[str] | None]) -> list[str] | None:
    """One command part: a special token, any other "{tool}" from PATH (None if missing), or itself."""
    if part in tokens:
        return tokens[part]
    if part.startswith("{") and part.endswith("}"):
        found = shutil.which(part[1:-1])
        return [found] if found else None
    return [part]


def secret_scan() -> list[tuple[str, str, str, list[str]]]:
    # "{gitleaks}" resolves to None when it is not installed; CI always runs it.
    return [("secrets", "secret scan", ".", ["{gitleaks}", "git", "--no-banner", "--redact", "."])]


def skill_problems(fix: bool = False) -> list[str]:
    """Agent skills live once in .agents/skills (read by Codex, OpenCode, Cursor, ...).
    Every SKILL_MIRRORS folder needs a symlink to each of them; fix=True creates missing ones."""
    shared = ROOT / ".agents" / "skills"
    problems: list[str] = []
    for skill in sorted(p for p in shared.glob("*") if p.is_dir()):
        md = skill / "SKILL.md"
        text = md.read_text(encoding="utf-8") if md.is_file() else ""
        parts = text.split("---", 2) if text.startswith("---") else []
        front = parts[1] if len(parts) == 3 else ""
        fields = dict(line.split(":", 1) for line in front.splitlines() if ":" in line)
        if fields.get("name", "").strip() != skill.name:
            problems.append(f"{md.relative_to(ROOT)}: frontmatter needs name: {skill.name}")
        if not fields.get("description", "").strip():
            problems.append(f"{md.relative_to(ROOT)}: frontmatter needs a description")
        for mirror in SKILL_MIRRORS:
            link = ROOT / mirror / skill.name
            if fix and not link.exists() and not link.is_symlink():
                link.parent.mkdir(parents=True, exist_ok=True)
                os.symlink(os.path.relpath(skill, link.parent), link, target_is_directory=True)
                print(f"   linked {mirror}/{skill.name}")
            if not (link / "SKILL.md").is_file() or link.resolve() != skill.resolve():
                problems.append(
                    f"{mirror}/{skill.name}: must be a symlink to .agents/skills/{skill.name} "
                    "(create it with --fix; on Windows enable Developer Mode and core.symlinks=true)"
                )
    return problems


def main() -> int:
    groups = sorted({group for group, *_ in CHECKS} | {"secrets", "skills"})
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", choices=groups)
    parser.add_argument("--fix", action="store_true", help="create missing agent skill symlinks")
    args = parser.parse_args()

    if args.only in (None, "skills"):
        print("-- agent skills", flush=True)
        problems = skill_problems(fix=args.fix)
        if problems:
            print("\n".join(problems), file=sys.stderr)
            print("FAILED: agent skills", file=sys.stderr)
            return 1

    tokens = tool_tokens(python_interpreter())
    skipped: list[str] = []
    for group, name, cwd, cmd in CHECKS + secret_scan():
        if args.only and group != args.only:
            continue
        workdir = ROOT / cwd
        parts = [resolve(part, tokens) for part in cmd]
        reason = None
        if not workdir.exists():
            reason = f"{cwd} not found"
        elif "{yarn}" in cmd and not any((d / "node_modules").exists() for d in (workdir, ROOT)):
            reason = f"run `yarn install` in {cwd} first"
        elif None in parts:
            reason = f"{cmd[parts.index(None)].strip('{}')} not installed"
        if reason:
            print(f"-- {name}: SKIPPED ({reason})")
            skipped.append(name)
            continue
        print(f"-- {name}", flush=True)
        argv = [arg for part in parts for arg in part]
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
