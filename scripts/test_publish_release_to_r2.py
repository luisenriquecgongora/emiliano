"""Tests for merging the macOS desktop entry into version.json (no R2 calls)."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from publish_release_to_r2 import merge_manifest_fragments  # noqa: E402

WINDOWS = {
    "name": "Emiliano",
    "version": "0.3.0",
    "platforms": {"windows-x64": {"zip": "Emiliano-v0.3.0-windows-x64.zip"}, "desktop-windows-x64": {"installer": "a.exe"}},
}
MAC = {"version": "0.3.0", "platforms": {"desktop-macos-arm64": {"installer": "Emiliano-Desktop-v0.3.0-macos-arm64.dmg"}}}


class TestMergeManifest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dist = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, data):
        (self.dist / name).write_text(json.dumps(data), encoding="utf-8")

    def read_manifest(self):
        return json.loads((self.dist / "version.json").read_text(encoding="utf-8"))

    def test_adds_the_mac_entry_and_keeps_windows(self):
        self.write("version.json", WINDOWS)
        self.write("desktop-macos-arm64.json", MAC)
        merged = merge_manifest_fragments(self.dist, "0.3.0")
        self.assertEqual([p.name for p in merged], ["desktop-macos-arm64.json"])
        platforms = self.read_manifest()["platforms"]
        self.assertEqual(set(platforms), {"windows-x64", "desktop-windows-x64", "desktop-macos-arm64"})
        self.assertEqual(platforms["desktop-macos-arm64"]["installer"], "Emiliano-Desktop-v0.3.0-macos-arm64.dmg")

    def test_no_fragment_leaves_manifest_unchanged(self):
        self.write("version.json", WINDOWS)
        self.assertEqual(merge_manifest_fragments(self.dist, "0.3.0"), [])
        self.assertEqual(self.read_manifest(), WINDOWS)

    def test_fragment_for_another_version_fails(self):
        self.write("version.json", WINDOWS)
        self.write("desktop-macos-arm64.json", {**MAC, "version": "0.2.0"})
        with self.assertRaises(SystemExit):
            merge_manifest_fragments(self.dist, "0.3.0")


if __name__ == "__main__":
    unittest.main()
