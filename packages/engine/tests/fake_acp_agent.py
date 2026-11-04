"""
Minimal ACP agent used by test_acp.py. Speaks newline-delimited JSON-RPC on stdio.
Behavior is picked by the prompt text:
- "edit": asks permission for an edit, then reports which option the client chose
- "hang": never answers session/prompt until cancelled
- "stubborn": ignores session/cancel and never answers (the client must kill it)
- anything else: streams two text chunks and ends the turn
Every message it receives is appended to the file named by FAKE_ACP_LOG, if set.
"""

import json
import os
import sys

LOG = os.environ.get("FAKE_ACP_LOG")
_next_id = 1000


def send(msg):
    msg["jsonrpc"] = "2.0"
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def read():
    line = sys.stdin.readline()
    if not line:
        sys.exit(0)
    msg = json.loads(line)
    if LOG:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(msg) + "\n")
    return msg


def update(session_id, upd):
    send({"method": "session/update", "params": {"sessionId": session_id, "update": upd}})


def chunk(session_id, text):
    update(session_id, {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": text}})


def main():
    global _next_id
    print("this line is not JSON and must be ignored", flush=True)
    while True:
        msg = read()
        method, params, req_id = msg.get("method"), msg.get("params") or {}, msg.get("id")
        if method == "initialize":
            send({"id": req_id, "result": {"protocolVersion": 1, "agentCapabilities": {}, "authMethods": []}})
        elif method == "session/new":
            send({"id": req_id, "result": {"sessionId": "sess_1"}})
        elif method == "session/prompt":
            sid = params["sessionId"]
            text = params["prompt"][0]["text"]
            if text == "stubborn":
                while True:
                    read()
            if text == "hang":
                while read().get("method") != "session/cancel":
                    pass
                send({"id": req_id, "result": {"stopReason": "cancelled"}})
            elif text == "edit":
                update(sid, {"sessionUpdate": "tool_call", "toolCallId": "call_1", "title": "Edit main.py", "kind": "edit", "status": "pending"})
                _next_id += 1
                send({"id": _next_id, "method": "session/request_permission", "params": {
                    "sessionId": sid,
                    "toolCall": {"toolCallId": "call_1", "title": "Edit main.py"},
                    "options": [
                        {"optionId": "yes", "name": "Allow once", "kind": "allow_once"},
                        {"optionId": "no", "name": "Reject", "kind": "reject_once"},
                    ],
                }})
                answer = read()
                outcome = answer["result"]["outcome"]
                chunk(sid, f"outcome={outcome['outcome']}:{outcome.get('optionId', '')}")
                send({"id": req_id, "result": {"stopReason": "end_turn"}})
            else:
                # An unadvertised client method must get a JSON-RPC error, not hang the agent
                _next_id += 1
                send({"id": _next_id, "method": "fs/read_text_file", "params": {"sessionId": sid, "path": "/x"}})
                reply = read()
                assert reply.get("error", {}).get("code") == -32601
                chunk(sid, "Hello ")
                chunk(sid, "world")
                send({"id": req_id, "result": {"stopReason": "end_turn"}})


if __name__ == "__main__":
    main()
