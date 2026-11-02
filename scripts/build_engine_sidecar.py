"""Builds the Python engine as the desktop app's Tauri sidecar.

Produces apps/desktop/src-tauri/binaries/emiliano-engine-<target triple>[.exe], the file
name Tauri's `externalBin` expects, with the same PyInstaller settings and smoke tests as
the standalone CLI release. The desktop app starts it as `emiliano-engine server`.

Usage:
    python scripts/build_engine_sidecar.py [--target x86_64-pc-windows-msvc]
"""

import argparse
import logging
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_windows_release import BUILD_DIR, ROOT_DIR, run_pyinstaller, smoke_test  # noqa: E402

logger = logging.getLogger("release.sidecar")

SIDECAR_NAME = "emiliano-engine"
SIDECAR_DIR = ROOT_DIR / "apps" / "desktop" / "src-tauri" / "binaries"


def host_target() -> str:
    """Returns the Rust target triple of this machine (what Tauri appends to sidecar names)."""
    res = subprocess.run(["rustc", "--print", "host-tuple"], capture_output=True, text=True)
    if res.returncode == 0 and res.stdout.strip():
        return res.stdout.strip()
    # rustc before 1.84 has no host-tuple; read the host line of `rustc -Vv`
    res = subprocess.run(["rustc", "-Vv"], capture_output=True, text=True)
    for line in res.stdout.splitlines():
        if line.startswith("host:"):
            return line.split(":", 1)[1].strip()
    raise SystemExit("Could not determine the Rust target triple. Install Rust or pass --target.")


def build_sidecar(target: str) -> Path:
    exe = run_pyinstaller(name=SIDECAR_NAME, dist_dir=BUILD_DIR / "sidecar")
    smoke_test(exe)
    SIDECAR_DIR.mkdir(parents=True, exist_ok=True)
    dest = SIDECAR_DIR / f"{SIDECAR_NAME}-{target}{exe.suffix}"
    shutil.copy2(exe, dest)
    logger.info("Sidecar ready: %s (%.1f MB)", dest, dest.stat().st_size / 2**20)
    return dest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the Python engine as the Tauri sidecar")
    parser.add_argument("--target", help="Rust target triple (default: this machine's)")
    args = parser.parse_args()
    build_sidecar(args.target or host_target())
