"""Windows Release Builder for Emiliano.

Compiles the engine CLI into a standalone Emiliano.exe with PyInstaller, smoke-tests it,
packages a versioned release ZIP, and writes a version.json manifest (with SHA-256
checksums) for Cloudflare R2 distribution. Mirrors the Yapper release flow.

Usage:
    python scripts/build_windows_release.py --version 0.1.0 [--notes "What changed"]
"""

import argparse
import hashlib
import json
import logging
import os
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s]: %(message)s")
logger = logging.getLogger("release.builder")

ROOT_DIR = Path(__file__).resolve().parent.parent
ENTRY_FILE = ROOT_DIR / "scripts" / "emiliano_entry.py"
DIST_DIR = ROOT_DIR / "dist"
BUILD_DIR = ROOT_DIR / "build"

PRODUCT = "Emiliano"
R2_PREFIX = "emiliano"
DEFAULT_PUBLIC_DOMAIN = "https://pub-091afdf4a9bd47fa9b641aae923852e1.r2.dev"

# Packages that load data files, plugins, or submodules dynamically, which
# PyInstaller's static analysis would otherwise miss.
COLLECT_ALL = ["litellm", "tiktoken", "tiktoken_ext", "winpty"]
COLLECT_SUBMODULES = ["emiliano", "uvicorn"]
COPY_METADATA = ["litellm"]


def compute_sha256(filepath: Path) -> str:
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()


def run_pyinstaller() -> Path:
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--console",  # Emiliano is a terminal chat, so it needs a console window
        "--name", PRODUCT,
        "--clean",
        "--noconfirm",
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR),
        "--specpath", str(BUILD_DIR),
    ]
    for pkg in COLLECT_ALL:
        cmd += ["--collect-all", pkg]
    for pkg in COLLECT_SUBMODULES:
        cmd += ["--collect-submodules", pkg]
    for pkg in COPY_METADATA:
        cmd += ["--copy-metadata", pkg]
    cmd.append(str(ENTRY_FILE))

    logger.info("Running PyInstaller...")
    res = subprocess.run(cmd, cwd=str(ROOT_DIR))
    if res.returncode != 0:
        raise RuntimeError(f"PyInstaller build failed with exit code {res.returncode}")

    exe_path = DIST_DIR / f"{PRODUCT}.exe"
    if not exe_path.exists():
        raise FileNotFoundError(f"Expected binary not found at: {exe_path}")
    return exe_path


def smoke_test(exe_path: Path) -> None:
    """Runs the frozen binary to catch modules PyInstaller failed to bundle."""
    env = {**os.environ, "PYTHONUTF8": "1"}
    for args in (["--help"], ["doctor"]):
        logger.info("Smoke test: %s %s", exe_path.name, " ".join(args))
        res = subprocess.run(
            [str(exe_path), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL, timeout=180, env=env,
        )
        if res.returncode != 0:
            raise RuntimeError(f"Smoke test '{' '.join(args)}' failed (exit {res.returncode}):\n{res.stdout}\n{res.stderr}")
    # These are imported lazily (on the first model call or `emiliano server`), so --help
    # and doctor would not notice if they were missing from the bundle
    lazy = "litellm,tiktoken,emiliano.direct.client,emiliano.core.dispatcher,emiliano.server.app"
    logger.info("Smoke test: importing %s", lazy)
    res = subprocess.run(
        [str(exe_path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        stdin=subprocess.DEVNULL, timeout=180, env={**env, "EMILIANO_SMOKE_IMPORT": lazy},
    )
    if res.returncode != 0 or "smoke-import ok" not in res.stdout:
        raise RuntimeError(f"Bundled module import failed (exit {res.returncode}):\n{res.stdout}\n{res.stderr}")
    logger.info("Smoke tests passed.")


def build_release(version: str, notes: str = "") -> Path:
    logger.info("Building %s v%s", PRODUCT, version)
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    exe_path = run_pyinstaller()
    smoke_test(exe_path)
    exe_sha256 = compute_sha256(exe_path)
    logger.info("Built %s (%.1f MB) sha256=%s", exe_path.name, exe_path.stat().st_size / 2**20, exe_sha256)

    zip_name = f"{PRODUCT}-v{version}-windows-x64.zip"
    zip_path = DIST_DIR / zip_name
    readme = (
        f"EMILIANO v{version}\n"
        "==================================================================\n"
        "HOW TO USE:\n"
        "1. Double-click Emiliano.exe to open the chat in the folder it is in.\n"
        "   To work on a project, open a terminal in that project and run Emiliano.exe.\n"
        "2. Emiliano routes each request to a local Ollama model, an installed agent\n"
        "   (Claude Code, Codex, Antigravity, OpenCode), or an API key you have set.\n"
        "3. Run 'Emiliano.exe doctor' to see which of these are ready.\n"
        "==================================================================\n"
    )
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        zipf.write(exe_path, arcname=exe_path.name)
        zipf.writestr("README.txt", readme)
    zip_sha256 = compute_sha256(zip_path)
    logger.info("Packaged %s sha256=%s", zip_name, zip_sha256)

    public = os.environ.get("R2_CUSTOM_DOMAIN", DEFAULT_PUBLIC_DOMAIN).rstrip("/")
    manifest = {
        "name": PRODUCT,
        "version": version,
        "release_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "platforms": {
            "windows-x64": {
                "binary": exe_path.name,
                "binary_sha256": exe_sha256,
                "zip": zip_name,
                "zip_sha256": zip_sha256,
                "download_url": f"{public}/{R2_PREFIX}/v{version}/{zip_name}",
                "latest_url": f"{public}/{R2_PREFIX}/latest/{PRODUCT}-windows-x64.zip",
            }
        },
        "changelog": notes or f"Release v{version}",
    }
    manifest_path = DIST_DIR / "version.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    logger.info("Wrote %s. Artifacts are in %s", manifest_path.name, DIST_DIR)
    return zip_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the Emiliano Windows release package")
    parser.add_argument("--version", required=True, help="Release version semver (e.g. 0.1.0)")
    parser.add_argument("--notes", default="", help="Changelog text for version.json")
    args = parser.parse_args()
    build_release(version=args.version.lstrip("v"), notes=args.notes)
