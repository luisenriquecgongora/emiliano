"""PostToolUse hook: lint the Python file an agent just edited.

Reports ruff findings back to the agent (exit code 2) so it fixes them in the same
turn. Lint only: it never reformats, per the "No Unsolicited Formatting" rule.
Stays silent when the file is not Python or ruff is unavailable.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from verify import python_interpreter, ruff_command  # noqa: E402  (single source for tool lookup)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    file_path = (payload.get("tool_input") or {}).get("file_path", "")
    if not file_path.endswith(".py") or not Path(file_path).exists():
        return 0

    ruff = ruff_command(python_interpreter())
    if ruff is None:
        return 0
    try:
        result = subprocess.run(
            [*ruff, "check", "--quiet", file_path],
            cwd=ROOT, capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 0
    if result.returncode == 0:
        return 0

    print(f"ruff found issues in {file_path}:\n{result.stdout}{result.stderr}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
