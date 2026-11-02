"""
Tests for harness authentication detection: only real credentials count as logged in,
never the mere presence of a harness's config folder.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from emiliano.harnesses.base import ClaudeCodeHarness, CodexHarness

AUTH_ENV_VARS = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR", "CODEX_API_KEY", "OPENAI_API_KEY", "CODEX_HOME")


class _FakeHome(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        env = {k: v for k, v in os.environ.items() if k not in AUTH_ENV_VARS}
        self.patches = [patch.object(Path, "home", return_value=self.home), patch.dict(os.environ, env, clear=True)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def write(self, rel, data):
        path = self.home / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data) if not isinstance(data, str) else data, encoding="utf-8")


class TestClaudeCodeAuth(_FakeHome):
    def check(self):
        return ClaudeCodeHarness().check_authentication()[0]

    def test_bare_config_folder_is_not_logged_in(self):
        (self.home / ".claude").mkdir()
        self.write(".claude.json", {"numStartups": 3})
        self.assertFalse(self.check())

    def test_account_in_claude_json(self):
        self.write(".claude.json", {"oauthAccount": {"emailAddress": "x@example.com"}})
        self.assertTrue(self.check())

    def test_stored_oauth_credentials(self):
        self.write(".claude/.credentials.json", {"claudeAiOauth": {"accessToken": "t"}})
        self.assertTrue(self.check())

    def test_custom_config_dir(self):
        self.write("alt/.credentials.json", {"claudeAiOauth": {"accessToken": "t"}})
        with patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.home / "alt")}):
            self.assertTrue(self.check())

    def test_env_credentials(self):
        for var in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"):
            with self.subTest(var=var), patch.dict(os.environ, {var: "x"}):
                self.assertTrue(self.check())

    def test_corrupt_files_are_not_logged_in(self):
        self.write(".claude.json", "{not json")
        self.write(".claude/.credentials.json", "[]")
        self.assertFalse(self.check())


class TestCodexAuth(_FakeHome):
    def check(self):
        return CodexHarness().check_authentication()[0]

    def test_bare_config_folder_is_not_logged_in(self):
        self.write(".codex/config.toml", "model = 'x'")
        self.assertFalse(self.check())

    def test_auth_mode_without_credentials_is_not_logged_in(self):
        self.write(".codex/auth.json", {"auth_mode": "chatgpt", "tokens": None, "OPENAI_API_KEY": None})
        self.assertFalse(self.check())

    def test_chatgpt_login_tokens(self):
        self.write(".codex/auth.json", {"auth_mode": "chatgpt", "tokens": {"access_token": "t"}})
        self.assertTrue(self.check())

    def test_api_key_in_auth_file(self):
        self.write(".codex/auth.json", {"OPENAI_API_KEY": "sk-x"})
        self.assertTrue(self.check())

    def test_custom_codex_home(self):
        self.write("codexhome/auth.json", {"tokens": {"access_token": "t"}})
        with patch.dict(os.environ, {"CODEX_HOME": str(self.home / "codexhome")}):
            self.assertTrue(self.check())


if __name__ == "__main__":
    unittest.main()
