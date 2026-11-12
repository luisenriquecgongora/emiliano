"""Cloudflare R2 Release Retention Pruner for Emiliano.

Keeps at most MAX_RELEASES (5) versioned releases under the emiliano/ prefix and deletes
older ones so the bucket does not grow without bound. The canonical latest/ folder is
never touched. Same rule as the Yapper release flow, with a hard ceiling: the limit
cannot be raised above 5 or switched off.

Usage:
    python scripts/prune_r2_releases.py --dry-run
    python scripts/prune_r2_releases.py --max-keep 5
"""

import argparse
import logging
import os
import re
from typing import List, Optional, Tuple

from packaging.version import InvalidVersion, Version

try:
    import boto3
    from botocore.config import Config
except ImportError:
    boto3 = None  # Only needed to talk to R2; the retention logic works without it

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s]: %(message)s")
logger = logging.getLogger("r2.pruner")

MAX_RELEASES = 3
DEFAULT_PREFIX = "emiliano"
PROTECTED_FOLDERS = {"latest"}


def get_r2_client():
    if boto3 is None:
        raise SystemExit("Missing 'boto3'. Run: pip install boto3")

    account_id = os.environ.get("R2_ACCOUNT_ID")
    access_key = os.environ.get("R2_ACCESS_KEY_ID")
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")
    if not all([account_id, access_key, secret_key]):
        raise SystemExit("Missing R2 credentials. Set R2_ACCOUNT_ID, R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY.")

    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4", retries={"max_attempts": 5, "mode": "standard"}),
        region_name="auto",
    )


def validate_max_keep(max_keep: int) -> int:
    if not 1 <= max_keep <= MAX_RELEASES:
        raise SystemExit(f"--max-keep must be between 1 and {MAX_RELEASES} (got {max_keep}).")
    return max_keep


def parse_version_folder(folder: str) -> Optional[Tuple["Version", str]]:
    """Parses a folder name like 'v1.2.0' into (Version, '1.2.0'); None if it is not a version."""
    m = re.fullmatch(r"v(\d+(?:\.\d+)+[A-Za-z0-9.\-]*)", folder)
    if not m:
        return None
    try:
        return Version(m.group(1)), m.group(1)
    except InvalidVersion:
        return None


def list_version_folders(s3_client, bucket: str, prefix: str) -> List[Tuple["Version", str, str]]:
    """Returns (version, version_string, folder_prefix) for every versioned folder, newest first."""
    entries = []
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix, Delimiter="/"):
        for cp in page.get("CommonPrefixes", []):
            folder = cp["Prefix"][len(prefix):].rstrip("/")
            if folder in PROTECTED_FOLDERS:
                continue
            parsed = parse_version_folder(folder)
            if parsed:
                entries.append((parsed[0], parsed[1], cp["Prefix"]))
    entries.sort(key=lambda e: e[0], reverse=True)
    return entries


def prune_prefix_releases(
    s3_client,
    bucket: str,
    base_prefix: str = DEFAULT_PREFIX,
    max_keep: int = MAX_RELEASES,
    dry_run: bool = False,
    protect_version: Optional[str] = None,
) -> int:
    """
    Deletes every versioned release under base_prefix beyond the newest max_keep.
    protect_version (the release just published) is never deleted, even if it is older.
    Returns the number of objects deleted (or that would be deleted in a dry run).
    """
    validate_max_keep(max_keep)
    prefix = base_prefix.rstrip("/") + "/"
    versions = list_version_folders(s3_client, bucket, prefix)
    logger.info("Found %d release(s) in s3://%s/%s (keeping at most %d).", len(versions), bucket, prefix, max_keep)

    protected = protect_version.lstrip("v") if protect_version else None
    keep, prune = [], []
    for entry in versions:
        (keep if len(keep) < max_keep or entry[1] == protected else prune).append(entry)
    # If the protected release pushed the count over the cap, drop the oldest other one instead
    while len(keep) > max_keep:
        victim = next(e for e in reversed(keep) if e[1] != protected)
        keep.remove(victim)
        prune.append(victim)

    for _, v, _ in keep:
        logger.info("  KEEP   v%s", v)
    if not prune:
        logger.info("Within the retention limit; nothing to prune.")
        return 0

    deleted = 0
    paginator = s3_client.get_paginator("list_objects_v2")
    for _, v, folder in prune:
        keys = [
            {"Key": obj["Key"]}
            for page in paginator.paginate(Bucket=bucket, Prefix=folder)
            for obj in page.get("Contents", [])
        ]
        logger.info("  %s v%s (%d objects)", "WOULD DELETE" if dry_run else "DELETE", v, len(keys))
        if not dry_run:
            for i in range(0, len(keys), 1000):
                res = s3_client.delete_objects(Bucket=bucket, Delete={"Objects": keys[i:i + 1000]})
                if res.get("Errors"):
                    raise RuntimeError(f"Failed to delete objects in {folder}: {res['Errors'][:3]}")
        deleted += len(keys)
    logger.info("Pruned %d release(s), %d objects%s.", len(prune), deleted, " (dry run)" if dry_run else "")
    return deleted


def main():
    parser = argparse.ArgumentParser(description=f"Keep at most {MAX_RELEASES} Emiliano releases in Cloudflare R2.")
    parser.add_argument("--prefix", default=DEFAULT_PREFIX, help="Bucket folder holding the releases")
    parser.add_argument("--max-keep", type=int, default=MAX_RELEASES, help=f"Releases to keep, 1-{MAX_RELEASES}")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted without deleting")
    args = parser.parse_args()

    validate_max_keep(args.max_keep)
    bucket = os.environ.get("R2_BUCKET_NAME", "luisenrique-releases")
    prune_prefix_releases(get_r2_client(), bucket, args.prefix, max_keep=args.max_keep, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
