"""
FastAPI & WebSocket IPC Server for Emiliano Engine.
Bridges the Python core to the Electron desktop Cowork UI.
"""

from __future__ import annotations

import asyncio
import json
from typing import Dict, Optional, Set
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from loguru import logger

from ..core.dispatcher import ExecutionDispatcher

app = FastAPI(title="Emiliano Engine IPC")

# Connected UI clients (usually 1 desktop Electron client)
active_connections: Set[WebSocket] = set()

# Global dispatcher instance (lazily initialized or created on startup)
_dispatcher: Optional[ExecutionDispatcher] = None

# Active running background tasks keyed by task ID
active_tasks: Dict[str, asyncio.Task] = {}


def get_dispatcher() -> ExecutionDispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = ExecutionDispatcher()
    return _dispatcher


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "emiliano-engine"}


@app.get("/api/models")
async def list_models():
    """Returns detected local Ollama models and available API providers."""
    dispatcher = get_dispatcher()
    caps = await dispatcher.registry.discover_all(test_harness_usability=False)
    results = []
    for cap in caps.values():
        results.append({
            "name": cap.name,
            "displayName": cap.display_name,
            "executionType": cap.execution_type.value,
            "status": cap.status.value,
            "selectedModel": cap.selected_model,
            "availableModels": cap.available_models,
        })
    return {"models": results}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.add(websocket)
    logger.info("[Server] Desktop UI connected via WebSocket.")

    dispatcher = get_dispatcher()
    loop = asyncio.get_running_loop()

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
                    goal = payload.get("goal", "").strip()
                    if not goal:
                        await websocket.send_text(json.dumps({
                            "type": "ERROR",
                            "payload": {"message": "Goal cannot be empty."}
                        }))
                        continue

                    task_id = payload.get("taskId") or "task-1"
                    harness_pref = payload.get("harnessPreference", "auto")
                    policy = payload.get("policy", "auto")
                    model = payload.get("model")

                    # Cancel any existing task
                    if task_id in active_tasks and not active_tasks[task_id].done():
                        logger.info(f"[Server] Cancelling existing task {task_id} before starting new one.")
                        active_tasks[task_id].cancel()
                        try:
                            await active_tasks[task_id]
                        except (asyncio.CancelledError, Exception):
                            pass

                    # Map harnessPreference to dispatcher overrides
                    harness_override = None
                    if harness_pref == "claude_code":
                        harness_override = "claude"
                    elif harness_pref in ("antigravity", "agy"):
                        harness_override = "agy"
                    elif harness_pref == "codex":
                        harness_override = "codex"
                    elif harness_pref == "opencode":
                        harness_override = "opencode"
                    elif harness_pref == "direct":
                        policy = "local"

                    # Spawn async task runner
                    task = asyncio.create_task(
                        _run_dispatched_task(
                            task_id=task_id,
                            goal=goal,
                            policy=policy,
                            harness_override=harness_override,
                            model_override=model,
                            dispatcher=dispatcher,
                            loop=loop,
                        )
                    )
                    active_tasks[task_id] = task

                elif event_type in ("TASK_CANCEL", "TASK_PAUSE"):
                    task_id = payload.get("taskId") or "task-1"
                    if task_id in active_tasks and not active_tasks[task_id].done():
                        logger.info(f"[Server] Cancelling task {task_id} per {event_type}.")
                        active_tasks[task_id].cancel()
                    else:
                        # Cancel all running tasks if none specified
                        for tid, t in list(active_tasks.items()):
                            if not t.done():
                                t.cancel()

                elif event_type == "GET_CAPABILITIES":
                    caps = await dispatcher.registry.discover_all(test_harness_usability=False)
                    summary = [
                        {
                            "name": c.name,
                            "displayName": c.display_name,
                            "type": c.execution_type.value,
                            "status": c.status.value,
                            "selectedModel": c.selected_model,
                        }
                        for c in caps.values()
                    ]
                    await websocket.send_text(json.dumps({
                        "type": "CAPABILITIES_RESPONSE",
                        "payload": {"capabilities": summary}
                    }))

            except json.JSONDecodeError:
                logger.warning(f"[Server] Invalid JSON received: {raw_data}")
    except WebSocketDisconnect:
        logger.info("[Server] Desktop UI disconnected.")
        active_connections.discard(websocket)
    except Exception as e:
        logger.error(f"[Server] WebSocket error: {e}")
        active_connections.discard(websocket)


async def _run_dispatched_task(
    task_id: str,
    goal: str,
    policy: str,
    harness_override: Optional[str],
    model_override: Optional[str],
    dispatcher: ExecutionDispatcher,
    loop: asyncio.AbstractEventLoop,
):
    """Executes a task via dispatcher and streams events back over WebSocket."""
    current_harness = ["auto"]

    def _threadsafe_broadcast(event_type: str, p: dict):
        try:
            try:
                running = asyncio.get_running_loop()
                if running is loop:
                    asyncio.create_task(broadcast_event(event_type, p))
                    return
            except RuntimeError:
                pass
            asyncio.run_coroutine_threadsafe(broadcast_event(event_type, p), loop)
        except Exception:
            pass

    def _on_route(cap):
        current_harness[0] = cap.name
        _threadsafe_broadcast("DAG_UPDATE", {
            "stepId": task_id,
            "status": "running",
            "title": f"Executing via {cap.display_name}",
            "assignedHarness": cap.name,
        })

    def _on_chunk(chunk: str):
        _threadsafe_broadcast("THOUGHT_STREAM", {
            "stepId": task_id,
            "chunk": chunk,
            "harness": current_harness[0],
        })

    def _on_reasoning(chunk: str):
        _threadsafe_broadcast("THOUGHT_STREAM", {
            "stepId": task_id,
            "chunk": chunk,
            "harness": current_harness[0],
        })

    try:
        await broadcast_event("DAG_UPDATE", {
            "stepId": task_id,
            "status": "running",
            "title": f"Goal: {goal[:50]}",
            "assignedHarness": harness_override or "auto",
        })

        cap, full_output = await dispatcher.execute_task(
            goal=goal,
            policy=policy,
            harness_override=harness_override,
            model_override=model_override,
            on_chunk=_on_chunk,
            on_reasoning=_on_reasoning,
            on_route_selected=_on_route,
        )

        await broadcast_event("DAG_UPDATE", {
            "stepId": task_id,
            "status": "completed",
            "title": f"Completed via {cap.display_name}",
            "assignedHarness": cap.name,
            "output": full_output,
        })
        await broadcast_event("THOUGHT_STREAM", {
            "stepId": task_id,
            "chunk": f"\n\n[Completed successfully via {cap.display_name}]\n",
            "harness": cap.name,
        })

    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.info(f"[Server] Task {task_id} was cancelled.")
        await broadcast_event("DAG_UPDATE", {
            "stepId": task_id,
            "status": "paused",
            "title": "Task cancelled by user",
            "assignedHarness": current_harness[0],
            "error": "Task stopped by user",
        })
        await broadcast_event("THOUGHT_STREAM", {
            "stepId": task_id,
            "chunk": "\n[Task stopped by user]\n",
            "harness": current_harness[0],
        })
    except Exception as e:
        logger.exception(f"[Server] Task {task_id} failed: {e}")
        await broadcast_event("DAG_UPDATE", {
            "stepId": task_id,
            "status": "failed",
            "title": "Task failed",
            "assignedHarness": current_harness[0],
            "error": str(e),
        })
        await broadcast_event("THOUGHT_STREAM", {
            "stepId": task_id,
            "chunk": f"\n[Task failed: {e}]\n",
            "harness": current_harness[0],
        })


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
