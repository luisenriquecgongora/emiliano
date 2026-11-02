"""Desktop Release Builder for Emiliano (Tauri app with the Python engine bundled inside).

Puts the engine into apps/desktop/src-tauri/binaries as the sidecar, runs `tauri build`,
copies the NSIS and MSI installers into dist/ under versioned names, and records them
with SHA-256 checksums in dist/version.json next to the CLI release.

Usage:
    python scripts/build_desktop_release.py --version 0.1.0 [--reuse-cli-exe]

--reuse-cli-exe copies dist/Emiliano.exe (from build_windows_release.py) as the sidecar
instead of building the engine again; both are the same PyInstaller build.
"""

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_engine_sidecar import SIDECAR_DIR, SIDECAR_NAME, build_sidecar, host_target  # noqa: E402
from build_windows_release import (  # noqa: E402
    DEFAULT_PUBLIC_DOMAIN,
    DIST_DIR,
    PRODUCT,
    R2_PREFIX,
    ROOT_DIR,
    compute_sha256,
)

logger = logging.getLogger("release.desktop")

DESKTOP_DIR = ROOT_DIR / "apps" / "desktop"
TAURI_CONF = DESKTOP_DIR / "src-tauri" / "tauri.conf.json"
BUNDLE_DIR = DESKTOP_DIR / "src-tauri" / "target" / "release" / "bundle"


def check_app_version(version: str) -> None:
    """The installer names come from tauri.conf.json, so it must match the release version."""
    app_version = json.loads(TAURI_CONF.read_text(encoding="utf-8"))["version"]
    if app_version != version:
        raise SystemExit(f"tauri.conf.json version is {app_version}, but this release is {version}. Bump it first.")


def install_sidecar(target: str, reuse_cli_exe: bool) -> Path:
    cli_exe = DIST_DIR / f"{PRODUCT}.exe"
    if not reuse_cli_exe:
        return build_sidecar(target)
    if not cli_exe.exists():
        raise SystemExit(f"--reuse-cli-exe needs {cli_exe}. Run build_windows_release.py first.")
    SIDECAR_DIR.mkdir(parents=True, exist_ok=True)
    dest = SIDECAR_DIR / f"{SIDECAR_NAME}-{target}.exe"
    shutil.copy2(cli_exe, dest)
    logger.info("Sidecar copied from %s", cli_exe.name)
    return dest


def run_tauri_build() -> None:
    yarn = shutil.which("yarn")
    if not yarn:
        raise SystemExit("yarn not found. Install Node.js and Yarn, then run `yarn install`.")
    logger.info("Running tauri build (first build compiles Rust dependencies and takes several minutes)...")
    res = subprocess.run([yarn, "tauri", "build"], cwd=str(DESKTOP_DIR))
    if res.returncode != 0:
        raise RuntimeError(f"tauri build failed with exit code {res.returncode}")


def find_bundle(subdir: str, pattern: str) -> Path:
    matches = sorted((BUNDLE_DIR / subdir).glob(pattern))
    if len(matches) != 1:
        raise FileNotFoundError(f"Expected one {pattern} in {BUNDLE_DIR / subdir}, found {len(matches)}")
    return matches[0]


def collect_installers(version: str) -> dict:
    """Copies the installers into dist/ with versioned names and returns their manifest entry."""
    public = os.environ.get("R2_CUSTOM_DOMAIN", DEFAULT_PUBLIC_DOMAIN).rstrip("/")
    names = {
        "installer": (find_bundle("nsis", f"{PRODUCT}_{version}_*-setup.exe"), f"{PRODUCT}-Desktop-v{version}-windows-x64-setup.exe"),
        "msi": (find_bundle("msi", f"{PRODUCT}_{version}_*.msi"), f"{PRODUCT}-Desktop-v{version}-windows-x64.msi"),
    }
    entry = {}
    for kind, (src, dest_name) in names.items():
        dest = DIST_DIR / dest_name
        shutil.copy2(src, dest)
        entry[kind] = dest_name
        entry[f"{kind}_sha256"] = compute_sha256(dest)
        logger.info("Packaged %s (%.1f MB)", dest_name, dest.stat().st_size / 2**20)
    entry["download_url"] = f"{public}/{R2_PREFIX}/v{version}/{entry['installer']}"
    entry["latest_url"] = f"{public}/{R2_PREFIX}/latest/{PRODUCT}-Desktop-windows-x64-setup.exe"
    return entry


def update_manifest(version: str, entry: dict) -> None:
    manifest_path = DIST_DIR / "version.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("version") != version:
            raise SystemExit(f"{manifest_path} is for {manifest.get('version')}, not {version}. Rebuild the CLI release first.")
    else:
        manifest = {"name": PRODUCT, "version": version, "platforms": {}}
    manifest["platforms"]["desktop-windows-x64"] = entry
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    logger.info("Added desktop installers to %s", manifest_path.name)


def build_desktop_release(version: str, reuse_cli_exe: bool = False) -> None:
    check_app_version(version)
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    install_sidecar(host_target(), reuse_cli_exe)
    run_tauri_build()
    update_manifest(version, collect_installers(version))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the Emiliano desktop installers")
    parser.add_argument("--version", required=True, help="Release version semver (e.g. 0.1.0)")
    parser.add_argument("--reuse-cli-exe", action="store_true", help="Copy dist/Emiliano.exe as the sidecar")
    args = parser.parse_args()
    build_desktop_release(args.version.lstrip("v"), reuse_cli_exe=args.reuse_cli_exe)
