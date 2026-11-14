"""Signing in to OAuth MCP servers (PlaatoOS): PKCE login, token storage and refresh, and `emiliano connect`."""

import base64
import hashlib
import json
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import yaml

from emiliano.mcp import McpError, McpHttpClient, auth, connect


class MemoryCredentials:
    """Stands in for Windows Credential Manager so tests never touch the real one."""

    def __init__(self):
        self.store = {}

    def __enter__(self):
        self.patches = [patch.object(auth.credentials, "save", lambda s, r: self.store.__setitem__(s, r)),
                        patch.object(auth.credentials, "load", lambda s: self.store.get(s)),
                        patch.object(auth.credentials, "delete", lambda s: self.store.pop(s, None))]
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self.patches:
            p.stop()


class FakeAuthServer(BaseHTTPRequestHandler):
    """Discovery, token and revoke endpoints like api-takient's /oauth, plus an MCP endpoint that only accepts
    the current access token."""

    def log_message(self, *args):
        pass

    def _json(self, status, body):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        base = f"http://127.0.0.1:{self.server.server_address[1]}"
        if self.path == "/.well-known/oauth-authorization-server":
            return self._json(200, {"authorization_endpoint": f"{base}/authorize",
                                    "token_endpoint": f"{base}/oauth/token"})
        self._json(404, {})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        srv = self.server
        if self.path == "/oauth/token":
            srv.token_requests.append(body)
            if body["grant_type"] == "authorization_code":
                challenge = base64.urlsafe_b64encode(hashlib.sha256(body["code_verifier"].encode()).digest())
                if body["code"] != "the-code" or challenge.rstrip(b"=").decode() != srv.challenge:
                    return self._json(400, {"error": "invalid_grant", "error_description": "PKCE verification failed."})
                return self._json(200, {"access_token": "access-1", "refresh_token": "refresh-1", "expires_in": 3600})
            if body["grant_type"] == "refresh_token":
                if body["refresh_token"] != "refresh-1" or srv.revoked:
                    return self._json(400, {"error": "invalid_grant", "error_description": "Grant has been revoked or expired."})
                srv.access = f"access-{len(srv.token_requests)}"
                return self._json(200, {"access_token": srv.access, "expires_in": 3600})
        if self.path == "/oauth/revoke":
            srv.revoked = True
            return self._json(200, {"status": "revoked"})
        if self.path == "/mcp":
            if self.headers.get("Authorization") != f"Bearer {srv.access}":
                return self._json(401, {"jsonrpc": "2.0", "id": None, "error": {"code": -32001, "message": "expired"}})
            result = {"protocolVersion": "2025-06-18", "serverInfo": {"name": "plaatoos-mcp"}} \
                if body.get("method") == "initialize" else {}
            return self._json(200, {"jsonrpc": "2.0", "id": body.get("id"), "result": result})
        self._json(404, {})


class AuthCase(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeAuthServer)
        self.server.token_requests, self.server.revoked, self.server.access, self.server.challenge = [], False, "", ""
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.creds = MemoryCredentials().__enter__()
        self.addCleanup(self.creds.__exit__)

    def browser(self, state_override=None, error=None):
        """Plays the consent page: reads the login URL, then redirects to Emiliano's callback."""
        def open_browser(url):
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
            self.server.challenge = q["code_challenge"]
            self.assertEqual((q["client_id"], q["redirect_uri"], q["code_challenge_method"]),
                             ("emiliano", "http://localhost:3333/callback", "S256"))
            params = {"state": state_override or q["state"]}
            params.update({"error": error, "error_description": "User cancelled"} if error else {"code": "the-code"})

            def hit():
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:3333/callback?{urllib.parse.urlencode(params)}", timeout=5)
                except Exception:
                    pass
            threading.Thread(target=hit, daemon=True).start()
        return open_browser


class TestLogin(AuthCase):
    def test_full_sign_in_stores_only_the_refresh_token(self):
        record = auth.login("plaatoos", api_base=self.base, open_browser=self.browser())
        self.assertEqual(record["refresh_token"], "refresh-1")
        self.assertNotIn("access_token", json.dumps(self.creds.store["plaatoos"]))
        self.assertEqual(self.server.token_requests[0]["grant_type"], "authorization_code")

    def test_forged_state_is_rejected(self):
        with self.assertRaises(McpError) as ctx:
            auth.login("plaatoos", api_base=self.base, open_browser=self.browser(state_override="attacker"))
        self.assertIn("state mismatch", str(ctx.exception))
        self.assertNotIn("plaatoos", self.creds.store)

    def test_cancelled_consent(self):
        with self.assertRaises(McpError) as ctx:
            auth.login("plaatoos", api_base=self.base, open_browser=self.browser(error="access_denied"))
        self.assertIn("User cancelled", str(ctx.exception))

    def test_pkce_challenge_matches_verifier(self):
        verifier, challenge = auth.pkce_pair()
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(challenge, expected)
        self.assertGreaterEqual(len(verifier), 43)


class TestTokens(AuthCase):
    def sign_in(self):
        auth.login("plaatoos", api_base=self.base, open_browser=self.browser())

    def test_client_refreshes_and_retries_once_on_401(self):
        self.sign_in()
        provider = auth.TokenProvider("plaatoos")
        provider._access, provider._expires_at = "stale", 9e12  # looks valid locally, server rejects it
        self.server.access = "never-matches-yet"
        client = McpHttpClient("plaatoos", f"{self.base}/mcp", token_provider=provider)
        client.start(timeout=10)  # first request 401s, the provider refreshes, the retry succeeds
        self.addCleanup(client.close)
        self.assertEqual(client.server_info["name"], "plaatoos-mcp")
        self.assertEqual(self.server.token_requests[-1]["grant_type"], "refresh_token")

    def test_revoked_sign_in_says_how_to_fix_it(self):
        self.sign_in()
        self.server.revoked = True
        with self.assertRaises(McpError) as ctx:
            auth.TokenProvider("plaatoos").token()
        self.assertIn("emiliano connect plaatoos", str(ctx.exception))

    def test_static_token(self):
        auth.save_static_token("plaatoos", " pak_abc ")
        provider = auth.TokenProvider("plaatoos")
        self.assertEqual(provider.token(), "pak_abc")
        self.assertFalse(provider.can_refresh())

    def test_not_connected(self):
        with self.assertRaises(McpError) as ctx:
            auth.TokenProvider("nothing").token()
        self.assertIn("emiliano connect nothing", str(ctx.exception))

    def test_logout_revokes_and_forgets(self):
        self.sign_in()
        self.creds.store["plaatoos"]["revocation_endpoint"] = f"{self.base}/oauth/revoke"
        self.assertTrue(auth.logout("plaatoos"))
        self.assertTrue(self.server.revoked)
        self.assertNotIn("plaatoos", self.creds.store)
        self.assertFalse(auth.logout("plaatoos"))


class TestConnectCommand(unittest.TestCase):
    def test_config_entry_is_added_and_removed_keeping_other_settings(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, "config.yaml")
            path.write_text("models:\n  local_model: qwen3:4b\nmcp_servers:\n  files: {command: npx}\n", encoding="utf-8")
            connect.set_server("plaatoos", {"url": "https://x/mcp", "auth": "oauth"}, path)
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertEqual(data["models"]["local_model"], "qwen3:4b")
            self.assertEqual(set(data["mcp_servers"]), {"files", "plaatoos"})
            connect.set_server("plaatoos", None, path)
            self.assertEqual(set(yaml.safe_load(path.read_text(encoding="utf-8"))["mcp_servers"]), {"files"})

    def test_connect_with_token_writes_config_and_checks_tools(self):
        with MemoryCredentials() as creds, tempfile.TemporaryDirectory() as d, \
                patch.object(connect, "config_path", return_value=Path(d, "config.yaml")), \
                patch.object(connect, "check", return_value={"ok": True, "tools": 120, "hidden": 0, "error": ""}):
            result = connect.connect("plaatoos", token="pak_123")
            entry = yaml.safe_load(Path(d, "config.yaml").read_text(encoding="utf-8"))["mcp_servers"]["plaatoos"]
        self.assertEqual(creds.store["plaatoos"], {"kind": "token", "token": "pak_123"})
        self.assertEqual(entry, {"url": "https://api-takient.onrender.com/mcp", "auth": "token"})
        self.assertEqual((result["auth"], result["tools"]), ("token", 120))
        self.assertNotIn("pak_123", json.dumps(entry))  # the token never lands in the config file


class TestConnectEndpoints(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from emiliano.server.app import app, get_dispatcher
        self.client = TestClient(app, base_url="http://127.0.0.1")
        self.dispatcher = get_dispatcher()

    def test_connect_runs_the_flow_and_reloads_servers(self):
        result = {"service": "plaatoos", "auth": "oauth", "config": "x", "ok": True, "tools": 7, "hidden": 0, "error": ""}
        with patch("emiliano.mcp.connect.connect", return_value=result) as run, \
                patch.object(self.dispatcher, "reload_mcp") as reload:
            res = self.client.post("/api/mcp/connect", json={"service": "plaatoos"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["tools"], 7)
        run.assert_called_once_with("plaatoos", None)
        reload.assert_called_once()

    def test_connect_failure_is_a_400_with_the_reason(self):
        with patch("emiliano.mcp.connect.connect", side_effect=McpError("Sign-in did not complete: timed out.")):
            res = self.client.post("/api/mcp/connect", json={"service": "plaatoos"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("timed out", res.json()["detail"])

    def test_unknown_service(self):
        self.assertEqual(self.client.post("/api/mcp/connect", json={"service": "nope"}).status_code, 404)

    def test_connections_lists_plaatoos(self):
        with patch("emiliano.mcp.connect.status", return_value={"service": "plaatoos", "connected": False, "auth": None}):
            body = self.client.get("/api/mcp/connections").json()
        self.assertEqual(body["connections"][0]["title"], "PlaatoOS")


if __name__ == "__main__":
    unittest.main()
