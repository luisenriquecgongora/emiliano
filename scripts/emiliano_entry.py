"""PyInstaller entry point for the standalone Emiliano.exe (double-click opens the chat)."""

import importlib
import os
import sys

from emiliano.cli import main


def _smoke_import(modules: str) -> None:
    """Imports modules the CLI loads lazily, so the release build can verify they were bundled."""
    for name in filter(None, (m.strip() for m in modules.split(","))):
        importlib.import_module(name)
    print("smoke-import ok")


if __name__ == "__main__":
    if os.environ.get("EMILIANO_SMOKE_IMPORT"):
        _smoke_import(os.environ["EMILIANO_SMOKE_IMPORT"])
        sys.exit(0)
    main()
