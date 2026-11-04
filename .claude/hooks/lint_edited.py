"""PostToolUse hook: lint the file an agent just edited.

Runs the linter that EDIT_LINTERS in scripts/verify.py lists for the file's extension and
reports findings back to the agent (exit code 2) so it fixes them in the same turn.
Lint only: it never reformats, per the "No Unsolicited Formatting" rule.
Stays silent when no linter is configured for the file type or the tool is not installed.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import verify  # noqa: E402  (single source for linters and tool lookup)

# Repos whose verify.py predates EDIT_LINTERS keep the original behavior: ruff on Python files.
DEFAULT_LINTERS = {".py": ["{ruff}", "check", "--quiet", "{file}"]}


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    file_path = (payload.get("tool_input") or {}).get("file_path", "")
    command = getattr(verify, "EDIT_LINTERS", DEFAULT_LINTERS).get(Path(file_path).suffix)
    if not command or not Path(file_path).exists():
        return 0

    try:
        tokens = verify.tool_tokens(verify.python_interpreter())
    except SystemExit:  # e.g. VERIFY_PYTHON points nowhere; verify.py itself reports that
        return 0
    parts = [[file_path] if part == "{file}" else verify.resolve(part, tokens) for part in command]
    if None in parts:
        return 0
    try:
        result = subprocess.run(
            [arg for part in parts for arg in part],
            cwd=ROOT, capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 0
    if result.returncode == 0:
        return 0

    tool = Path(parts[0][0]).stem
    print(f"{tool} found issues in {file_path}:\n{result.stdout}{result.stderr}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
