"""Tests for the R2 release retention cap. Run: python -m unittest scripts/test_prune_r2_releases.py"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prune_r2_releases import MAX_RELEASES, prune_prefix_releases, validate_max_keep  # noqa: E402


class FakeBucket:
    """Minimal in-memory stand-in for the boto3 S3 client calls the pruner uses."""

    def __init__(self, keys):
        self.keys = set(keys)

    def get_paginator(self, _name):
        return self

    def paginate(self, Bucket, Prefix, Delimiter=None):
        matching = sorted(k for k in self.keys if k.startswith(Prefix))
        if Delimiter:
            folders = sorted({Prefix + k[len(Prefix):].split(Delimiter)[0] + Delimiter for k in matching if Delimiter in k[len(Prefix):]})
            yield {"CommonPrefixes": [{"Prefix": f} for f in folders]}
        else:
            yield {"Contents": [{"Key": k} for k in matching]}

    def delete_objects(self, Bucket, Delete):
        for obj in Delete["Objects"]:
            self.keys.discard(obj["Key"])
        return {}

    def versions(self):
        return sorted({k.split("/")[1] for k in self.keys})


def bucket_with(*versions):
    keys = ["emiliano/latest/Emiliano.exe", "emiliano/latest/version.json"]
    for v in versions:
        keys += [f"emiliano/v{v}/Emiliano.exe", f"emiliano/v{v}/version.json"]
    return FakeBucket(keys)


class TestRetentionCap(unittest.TestCase):
    def test_keeps_only_newest_five(self):
        s3 = bucket_with("0.1.0", "0.2.0", "0.3.0", "0.4.0", "0.5.0", "0.6.0", "0.7.0")
        deleted = prune_prefix_releases(s3, "b", "emiliano")
        self.assertEqual(deleted, 4)
        self.assertEqual(s3.versions(), ["latest", "v0.3.0", "v0.4.0", "v0.5.0", "v0.6.0", "v0.7.0"])

    def test_orders_by_semver_not_text(self):
        s3 = bucket_with("0.9.0", "0.10.0", "0.11.0", "0.12.0", "0.13.0", "0.8.0")
        prune_prefix_releases(s3, "b", "emiliano")
        self.assertNotIn("v0.8.0", s3.versions())
        self.assertIn("v0.10.0", s3.versions())

    def test_within_limit_deletes_nothing(self):
        s3 = bucket_with("0.1.0", "0.2.0")
        self.assertEqual(prune_prefix_releases(s3, "b", "emiliano"), 0)
        self.assertEqual(len(s3.versions()), 3)

    def test_just_published_older_hotfix_is_kept(self):
        s3 = bucket_with("1.0.0", "1.1.0", "1.2.0", "1.3.0", "1.4.0", "0.9.1")
        prune_prefix_releases(s3, "b", "emiliano", protect_version="v0.9.1")
        versions = s3.versions()
        self.assertIn("v0.9.1", versions)
        self.assertNotIn("v1.0.0", versions)
        self.assertEqual(len(versions) - 1, MAX_RELEASES)  # minus latest/

    def test_dry_run_deletes_nothing(self):
        s3 = bucket_with("0.1.0", "0.2.0", "0.3.0", "0.4.0", "0.5.0", "0.6.0")
        self.assertEqual(prune_prefix_releases(s3, "b", "emiliano", dry_run=True), 2)
        self.assertEqual(len(s3.versions()), 7)

    def test_latest_and_unrelated_folders_untouched(self):
        s3 = bucket_with("0.1.0", "0.2.0", "0.3.0", "0.4.0", "0.5.0", "0.6.0")
        s3.keys.add("emiliano/notes/readme.txt")
        prune_prefix_releases(s3, "b", "emiliano", max_keep=1)
        self.assertEqual(s3.versions(), ["latest", "notes", "v0.6.0"])

    def test_cap_cannot_be_raised_or_disabled(self):
        for bad in (0, -1, MAX_RELEASES + 1):
            with self.subTest(max_keep=bad), self.assertRaises(SystemExit):
                validate_max_keep(bad)


if __name__ == "__main__":
    unittest.main()
