"""Cloudflare R2 Release Publisher for Emiliano.

Uploads the files from build_windows_release.py to two places in the bucket:
  emiliano/v<version>/  immutable, cached for a year
  emiliano/latest/      short cache, always the newest release
then enforces the retention cap (at most 5 versioned releases). A failed prune fails the
publish, so the cap can never be silently skipped.

Usage:
    set R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY (and optionally R2_BUCKET_NAME)
    python scripts/publish_release_to_r2.py --version 0.1.0
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prune_r2_releases import MAX_RELEASES, get_r2_client, prune_prefix_releases, validate_max_keep  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s]: %(message)s")
logger = logging.getLogger("r2.publisher")

ROOT_DIR = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT_DIR / "dist"
PRODUCT = "Emiliano"
DEFAULT_PUBLIC_DOMAIN = "https://pub-091afdf4a9bd47fa9b641aae923852e1.r2.dev"


def upload_with_retry(s3, src: Path, bucket: str, key: str, content_type: str, cache_control: str) -> None:
    for attempt in range(1, 4):
        try:
            s3.upload_file(str(src), bucket, key, ExtraArgs={"ContentType": content_type, "CacheControl": cache_control})
            logger.info("Uploaded %s -> %s (%.1f MB)", src.name, key, src.stat().st_size / 2**20)
            return
        except Exception as exc:
            if attempt == 3:
                raise
            logger.warning("Upload %d/3 of %s failed (%s); retrying in 2s...", attempt, key, exc)
            time.sleep(2)


def publish_release(version: str, prefix: str = "emiliano", max_keep: int = MAX_RELEASES) -> None:
    validate_max_keep(max_keep)
    bucket = os.environ.get("R2_BUCKET_NAME", "plaatoos-downloads")
    public = os.environ.get("R2_CUSTOM_DOMAIN", DEFAULT_PUBLIC_DOMAIN).rstrip("/")

    exe_file = DIST_DIR / f"{PRODUCT}.exe"
    zip_file = DIST_DIR / f"{PRODUCT}-v{version}-windows-x64.zip"
    manifest_file = DIST_DIR / "version.json"
    for required in (exe_file, zip_file, manifest_file):
        if not required.exists():
            raise SystemExit(f"Missing {required.name} in {DIST_DIR}. Run build_windows_release.py first.")

    s3 = get_r2_client()
    version_dir, latest_dir = f"{prefix}/v{version}", f"{prefix}/latest"
    immutable, short = "public, max-age=31536000, immutable", "public, max-age=300"
    uploads = [
        (exe_file, f"{version_dir}/{exe_file.name}", "application/octet-stream", immutable),
        (zip_file, f"{version_dir}/{zip_file.name}", "application/zip", immutable),
        (manifest_file, f"{version_dir}/version.json", "application/json", "public, max-age=86400"),
        (exe_file, f"{latest_dir}/{exe_file.name}", "application/octet-stream", short),
        (zip_file, f"{latest_dir}/{PRODUCT}-windows-x64.zip", "application/zip", short),
        (manifest_file, f"{latest_dir}/version.json", "application/json", "no-cache, must-revalidate"),
    ]
    logger.info("Uploading %d objects to s3://%s/%s ...", len(uploads), bucket, prefix)
    for src, key, content_type, cache_control in uploads:
        upload_with_retry(s3, src, bucket, key, content_type, cache_control)

    logger.info("Versioned download: %s/%s/%s", public, version_dir, zip_file.name)
    logger.info("Latest download:    %s/%s/%s-windows-x64.zip", public, latest_dir, PRODUCT)
    logger.info("Update manifest:    %s/%s/version.json", public, latest_dir)

    logger.info("Enforcing retention cap (max %d releases)...", max_keep)
    prune_prefix_releases(s3, bucket, prefix, max_keep=max_keep, protect_version=version)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Publish an Emiliano release to Cloudflare R2")
    parser.add_argument("--version", required=True, help="Release version (e.g. 0.1.0)")
    parser.add_argument("--prefix", default="emiliano", help="Bucket folder for Emiliano releases")
    parser.add_argument("--max-keep", type=int, default=MAX_RELEASES, help=f"Releases to keep, 1-{MAX_RELEASES}")
    args = parser.parse_args()
    publish_release(version=args.version.lstrip("v"), prefix=args.prefix, max_keep=args.max_keep)
