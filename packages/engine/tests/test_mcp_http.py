"""Remote MCP servers over HTTP (e.g. PlaatoOS at https://api.plaatoos.com/mcp with a pak_ token)."""

import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from pydantic import ValidationError

from emiliano.core.config import EmilianoConfig, McpServerConfig
from emiliano.mcp import McpError, McpHttpClient, McpManager, acp_server_list
from emiliano.mcp.client import _parse_sse, expand_env

TOKEN = "pak_test123"


class FakePlaatoHandler(BaseHTTPRequestHandler):
    """Answers like api-takient's HandleMcp: Bearer auth, one JSON reply per POST. server.sse switches replies to
    an event stream with a session id, like SDK-based servers."""

    def log_message(self, *args):
        pass

    def do_POST(self):
        self.server.seen.append(dict(self.headers))
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            return self._send(401, {"jsonrpc": "2.0", "id": None, "error": {"code": -32001, "message": "auth"}})
        rpc = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        method, rid = rpc.get("method"), rpc.get("id")
        if method == "initialize":
            result = {"protocolVersion": rpc["params"]["protocolVersion"], "serverInfo": {"name": "plaatoos-mcp"},
                      "capabilities": {"tools": {}}}
        elif method == "notifications/initialized":
            return self._send(202, None)
        elif method == "tools/list":
            result = {"tools": [{"name": "search_products", "description": "Search the storefront.",
                                 "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}}}]}
        elif method == "tools/call":
            q = rpc["params"]["arguments"].get("query")
            result = {"content": [{"type": "text", "text": f"3 products match {q}"}]}
        else:
            return self._send(200, {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "unknown"}})
        self._send(200, {"jsonrpc": "2.0", "id": rid, "result": result})

    def do_DELETE(self):
        self.server.deleted = True
        self._send(200, None)

    def _send(self, status, body):
        self.send_response(status)
        if body is None:
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.server.sse:
            payload = f"event: message\ndata: {json.dumps(body)}\n\n".encode()
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Mcp-Session-Id", "sess-1")
        else:
            payload = json.dumps(body).encode()
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class HttpServerCase(unittest.TestCase):
    sse = False

    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakePlaatoHandler)
        self.server.seen, self.server.sse, self.server.deleted = [], self.sse, False
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/mcp"


class TestJsonServer(HttpServerCase):
    def test_tools_through_the_manager_with_token_from_env(self):
        cfg = McpServerConfig(url=self.url, headers={"Authorization": "Bearer ${PLAATOOS_TOKEN}"})
        with patch.dict(os.environ, {"PLAATOOS_TOKEN": TOKEN}):
            manager = McpManager({"plaatoos": cfg})
            self.addCleanup(manager.close)
            manager.start()
            self.assertTrue(manager.statuses["plaatoos"].ok, manager.statuses["plaatoos"].error)
            self.assertEqual(manager.call("plaatoos__search_products", {"query": "vodka"}), "3 products match vodka")
        # After initialize, every request names the negotiated protocol version
        self.assertEqual(self.server.seen[-1].get("MCP-Protocol-Version"), "2025-06-18")
        self.assertIn("text/event-stream", self.server.seen[0]["Accept"])

    def test_wrong_token_is_reported_clearly(self):
        manager = McpManager({"plaatoos": McpServerConfig(url=self.url, headers={"Authorization": "Bearer nope"})})
        self.addCleanup(manager.close)
        manager.start()
        self.assertFalse(manager.statuses["plaatoos"].ok)
        self.assertIn("refused the credentials", manager.statuses["plaatoos"].error)

    def test_missing_env_var_is_reported(self):
        env = {k: v for k, v in os.environ.items() if k != "PLAATOOS_TOKEN"}
        with patch.dict(os.environ, env, clear=True):
            manager = McpManager({"p": McpServerConfig(url=self.url, headers={"Authorization": "Bearer ${PLAATOOS_TOKEN}"})})
            self.addCleanup(manager.close)
            manager.start()
        self.assertIn("PLAATOOS_TOKEN is not set", manager.statuses["p"].error)

    def test_unreachable_server(self):
        client = McpHttpClient("gone", "http://127.0.0.1:1/mcp")
        with self.assertRaises(McpError):
            client.start(timeout=3)
        self.assertFalse(client.is_alive())


class TestSseServer(HttpServerCase):
    sse = True

    def test_event_stream_replies_and_session_id(self):
        client = McpHttpClient("p", self.url, {"Authorization": f"Bearer {TOKEN}"})
        client.start()
        self.assertEqual(client.session_id, "sess-1")
        self.assertEqual(client.call_tool("search_products", {"query": "gin"}), "3 products match gin")
        self.assertEqual(self.server.seen[-1].get("Mcp-Session-Id"), "sess-1")
        client.close()
        self.assertTrue(self.server.deleted)  # the session is ended on close


class TestConfigAndHelpers(unittest.TestCase):
    def test_exactly_one_transport(self):
        with self.assertRaises(ValidationError):
            McpServerConfig()
        with self.assertRaises(ValidationError):
            McpServerConfig(command="npx", url="https://x/mcp")

    def test_remote_servers_are_not_given_to_acp_harnesses(self):
        config = EmilianoConfig(mcp_servers={"local": {"command": "npx"},
                                             "plaatoos": {"url": "https://api.plaatoos.com/mcp"}})
        self.assertEqual([s["name"] for s in acp_server_list(config.mcp_servers)], ["local"])

    def test_expand_env(self):
        with patch.dict(os.environ, {"T": "abc"}):
            self.assertEqual(expand_env("Bearer ${T}"), "Bearer abc")
        self.assertEqual(expand_env("no vars"), "no vars")

    def test_parse_sse(self):
        body = 'event: message\ndata: {"id": 1,\ndata:  "result": {}}\n\n: comment\n\ndata: {"id": 2, "result": {}}\n'
        self.assertEqual([m["id"] for m in _parse_sse(body)], [1, 2])


if __name__ == "__main__":
    unittest.main()
