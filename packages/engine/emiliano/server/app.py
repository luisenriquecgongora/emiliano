"""
FastAPI & WebSocket IPC Server for Emiliano Engine.
Bridges the Python core to the Electron desktop Cowork UI.
"""

from __future__ import annotations

import json
from typing import Dict, Set
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from loguru import logger

app = FastAPI(title="Emiliano Engine IPC")

# Set of connected UI clients (usually 1 desktop Electron client)
active_connections: Set[WebSocket] = set()


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "emiliano-engine"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.add(websocket)
    logger.info("[Server] Desktop UI connected via WebSocket.")

    try:
        while True:
            raw_data = await websocket.receive_text()
            try:
                event = json.loads(raw_data)
                event_type = event.get("type")
                payload = event.get("payload", {})

                logger.debug(f"[Server] Received event: {event_type}")

                if event_type == "PING":
                    await websocket.send_text(json.dumps({"type": "PONG", "payload": {}}))
                elif event_type == "TASK_START":
                    # Echo confirmation and start simulated thought stream
                    goal = payload.get("goal", "")
                    await broadcast_event("DAG_UPDATE", {
                        "stepId": "step-1",
                        "status": "running",
                        "title": f"Analyzing goal: {goal[:40]}...",
                        "assignedHarness": payload.get("harnessPreference", "auto")
                    })
                    await broadcast_event("THOUGHT_STREAM", {
                        "chunk": f"Synthesizing plan for: {goal}\nSelecting best harness...\n",
                        "harness": payload.get("harnessPreference", "auto")
                    })
            except json.JSONDecodeError:
                logger.warning(f"[Server] Invalid JSON received: {raw_data}")
    except WebSocketDisconnect:
        logger.info("[Server] Desktop UI disconnected.")
        active_connections.discard(websocket)
    except Exception as e:
        logger.error(f"[Server] WebSocket error: {e}")
        active_connections.discard(websocket)


async def broadcast_event(event_type: str, payload: Dict):
    """Sends structured events to all connected UI clients."""
    if not active_connections:
        return
    message = json.dumps({"type": event_type, "payload": payload})
    for ws in list(active_connections):
        try:
            await ws.send_text(message)
        except Exception:
            active_connections.discard(ws)
