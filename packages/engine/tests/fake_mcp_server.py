"""
Minimal MCP server used by test_mcp.py. Speaks newline-delimited JSON-RPC on stdio.
Tools (listed over two pages, to exercise pagination):
- echo(text): returns the text
- fail(): returns a tool error (isError)
- roots(): asks the client for roots/list and returns the first root's name
- search-issues(query): a name with a dash, to check name cleaning
FAKE_MCP_CRASH=1 makes it exit right after starting.
"""

import json
import os
import sys

if os.environ.get("FAKE_MCP_CRASH"):
    sys.stderr.write("fake server: crashing on purpose\n")
    sys.stderr.flush()
    sys.exit(3)

PAGE_1 = [
    {"name": "echo", "description": "Echo the text back.",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "fail", "description": "Always fails.", "inputSchema": {"type": "object", "properties": {}}},
]
PAGE_2 = [
    {"name": "roots", "description": "Report the client's first root.", "inputSchema": {"type": "object"}},
    {"name": "search-issues", "description": "Search issues.",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
                     "required": ["query"]}},
]


def send(msg):
    msg["jsonrpc"] = "2.0"
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def read():
    line = sys.stdin.readline()
    if not line:
        sys.exit(0)
    return json.loads(line)


def text(req_id, value, is_error=False):
    send({"id": req_id, "result": {"content": [{"type": "text", "text": value}], "isError": is_error}})


while True:
    msg = read()
    method, req_id, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if method == "initialize":
        send({"method": "notifications/message", "params": {"level": "info", "data": "starting"}})
        send({"id": req_id, "result": {"protocolVersion": params.get("protocolVersion"),
                                       "capabilities": {"tools": {}},
                                       "serverInfo": {"name": "fake", "version": "1.0"}}})
    elif method == "notifications/initialized":
        continue
    elif method == "tools/list":
        if params.get("cursor") == "page2":
            send({"id": req_id, "result": {"tools": PAGE_2}})
        else:
            send({"id": req_id, "result": {"tools": PAGE_1, "nextCursor": "page2"}})
    elif method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        if name == "echo":
            text(req_id, args.get("text", ""))
        elif name == "fail":
            text(req_id, "something broke", is_error=True)
        elif name == "roots":
            send({"id": 9001, "method": "roots/list"})
            answer = read()
            while answer.get("id") != 9001:
                answer = read()
            text(req_id, answer["result"]["roots"][0]["name"])
        elif name == "search-issues":
            text(req_id, f"found 2 issues for {args.get('query')}")
        else:
            send({"id": req_id, "error": {"code": -32602, "message": f"Unknown tool {name}"}})
    elif req_id is not None:
        send({"id": req_id, "error": {"code": -32601, "message": f"Unknown method {method}"}})
