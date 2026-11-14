"""
FastAPI & WebSocket IPC Server for Emiliano Engine.
Bridges the Python core to the Tauri desktop Cowork UI.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Dict, Optional, Set
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from loguru import logger

from ..core.dispatcher import ExecutionDispatcher
from ..history import HistoryStore
from ..history.api import router as history_router
from ..cowork import WindowPinManager, ScreenPerceiver, ActionSynthesizer, CoworkAgentLoop, SafetyInterruptedError
from ..direct import UnifiedLLMClient
from .security import get_allowed_origins, is_origin_allowed

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Discover models and harnesses in the background at startup, so the first message
    # does not wait several seconds for every harness's --version
    warm_up = asyncio.create_task(get_dispatcher().warm_up())
    yield
    warm_up.cancel()


app = FastAPI(title="Emiliano Engine IPC", lifespan=lifespan)

# Only accept requests addressed to this machine. Checking Host blocks DNS rebinding, where a
# website points its own domain at 127.0.0.1 so the browser treats the engine as same-origin.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])


@app.middleware("http")
async def reject_foreign_origins(request: Request, call_next):
    # Browsers attach Origin to cross-site requests: refuse pages other than the desktop app
    if not is_origin_allowed(request.headers.get("origin")):
        return JSONResponse({"detail": "Origin not allowed"}, status_code=403)
    return await call_next(request)


# The desktop app's pages are served from their own origin, so its REST calls need CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(get_allowed_origins()),
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["content-type"],
)

# Connected UI clients (usually the desktop dock and HUD overlay windows)
active_connections: Set[WebSocket] = set()

# Global dispatcher instance (lazily initialized or created on startup)
_dispatcher: Optional[ExecutionDispatcher] = None

# Active running background tasks keyed by task ID
active_tasks: Dict[str, asyncio.Task] = {}


_history: Optional[HistoryStore] = None


def get_dispatcher() -> ExecutionDispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = ExecutionDispatcher()
    return _dispatcher


def get_history_store() -> HistoryStore:
    global _history
    if _history is None:
        _history = HistoryStore()
    return _history


# Saved chats (/api/chats, /api/chat); the routes find these through app.state
app.state.get_dispatcher = lambda: get_dispatcher()
app.state.get_history_store = lambda: get_history_store()
app.include_router(history_router)


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


@app.get("/api/models/recommendations")
async def model_recommendations():
    """
    Local models rated for this machine: {hardware, models: [{name, sizeBytes, tools, fit, recommended, loaded,
    vramBytes}], suggestions: [{name, sizeGb, fit, note, pull}]}. fit is fits_gpu | slow | too_big.
    """
    from ..direct.hardware import local_model_report

    return await local_model_report(get_dispatcher().registry.ollama_mgr)


class ConnectPayload(BaseModel):
    service: str
    token: Optional[str] = None  # a pak_ agent token instead of the browser sign-in


@app.get("/api/mcp/connections")
async def mcp_connections():
    """Known MCP services and whether each is connected: {"connections": [{service, title, connected, auth}]}."""
    from ..mcp.connect import SERVICES, status
    return {"connections": [{**status(name), "title": info["title"]} for name, info in SERVICES.items()]}


@app.post("/api/mcp/connect")
async def mcp_connect(payload: ConnectPayload):
    """Connects a service. Without a token this opens the browser sign-in and waits (up to 5 minutes) for it."""
    from ..mcp.connect import SERVICES, connect
    if payload.service not in SERVICES:
        raise HTTPException(status_code=404, detail=f"Unknown service: {payload.service}")
    try:
        result = await asyncio.to_thread(connect, payload.service, payload.token or None)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    get_dispatcher().reload_mcp()
    return result


@app.post("/api/mcp/disconnect")
async def mcp_disconnect(payload: ConnectPayload):
    from ..mcp.connect import SERVICES, disconnect
    if payload.service not in SERVICES:
        raise HTTPException(status_code=404, detail=f"Unknown service: {payload.service}")
    result = await asyncio.to_thread(disconnect, payload.service)
    get_dispatcher().reload_mcp()
    return result


class ModelPayload(BaseModel):
    model: str


@app.post("/api/models/load")
async def load_model(payload: ModelPayload):
    """Loads a local model into memory and keeps it there until unloaded, so replies start at once."""
    dispatcher = get_dispatcher()
    mgr = dispatcher.registry.ollama_mgr
    if payload.model not in await mgr.list_installed_models():
        raise HTTPException(status_code=404, detail=f"Model not installed: {payload.model}")
    ok = await mgr.preload(payload.model, num_ctx=dispatcher.config.models.ollama_num_ctx, keep_alive=-1)
    if not ok:
        raise HTTPException(status_code=502, detail=f"Ollama could not load {payload.model}")
    return {"status": "loaded", "model": payload.model}


@app.post("/api/models/unload")
async def unload_model(payload: ModelPayload):
    """Frees the memory a loaded local model holds."""
    if not await get_dispatcher().registry.ollama_mgr.unload(payload.model):
        raise HTTPException(status_code=502, detail=f"Ollama could not unload {payload.model}")
    return {"status": "unloaded", "model": payload.model}


# Cowork singletons
pin_manager = WindowPinManager()
screen_perceiver = ScreenPerceiver(pin_manager=pin_manager)
action_synthesizer = ActionSynthesizer(pin_manager=pin_manager, uia_reader=screen_perceiver._uia)


class PinPayload(BaseModel):
    hwnd: int
    title: Optional[str] = None


class ClickPayload(BaseModel):
    x: float
    y: float
    button: str = "left"
    clicks: int = 1


class TypePayload(BaseModel):
    text: str
    x: Optional[float] = None
    y: Optional[float] = None


class CoworkRunPayload(BaseModel):
    goal: str
    hwnd: Optional[int] = None
    model: Optional[str] = None
    timeout: float = 120.0


@app.get("/api/cowork/windows")
async def get_windows():
    return {"windows": screen_perceiver.list_windows()}


@app.post("/api/cowork/pin")
async def pin_window(payload: PinPayload):
    pin_manager.pin(payload.hwnd, payload.title)
    return {"status": "pinned", "hwnd": pin_manager.pinned_hwnd, "title": pin_manager.pinned_title}


@app.post("/api/cowork/unpin")
async def unpin_window():
    pin_manager.unpin()
    return {"status": "unpinned"}


@app.get("/api/cowork/elements")
async def get_elements(hwnd: Optional[int] = None):
    # Reading another app's UI tree can take seconds; keep it off the event loop
    return {"elements": await asyncio.to_thread(screen_perceiver.get_ui_elements, hwnd=hwnd)}


@app.post("/api/cowork/click")
async def click_element(payload: ClickPayload):
    try:
        action_synthesizer.click(x=payload.x, y=payload.y, button=payload.button, clicks=payload.clicks)
        return {"status": "ok", "x": payload.x, "y": payload.y}
    except SafetyInterruptedError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/cowork/type")
async def type_text(payload: TypePayload):
    try:
        action_synthesizer.type_text(payload.text, x=payload.x, y=payload.y)
        return {"status": "ok"}
    except SafetyInterruptedError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/cowork/run")
async def run_cowork_agent(payload: CoworkRunPayload):
    dispatcher = get_dispatcher()
    model_name = payload.model or "ollama/qwen2.5-coder:7b"
    client = UnifiedLLMClient(
        ollama_base_url=dispatcher.config.models.ollama_base_url,
        fallback_chain=[model_name],
        config=dispatcher.config,
    )
    from ..cowork.vision import vision_enabled
    vision = await vision_enabled(dispatcher.config.cowork.vision, model_name, dispatcher.registry.ollama_mgr)
    agent = CoworkAgentLoop(
        client=client,
        model_id=model_name,
        pin_manager=pin_manager,
        screen_perceiver=screen_perceiver,
        action_synthesizer=action_synthesizer,
        timeout=payload.timeout,
        vision=vision,
        # The HUD overlay window listens on /ws and draws each target before it is acted on
        on_highlight=lambda p: broadcast_event("HUD_HIGHLIGHT", p),
    )
    try:
        output = await agent.run(goal=payload.goal, hwnd=payload.hwnd)
        return {"status": "completed", "output": output}
    except Exception as e:
        logger.error(f"[Server] Cowork agent failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await broadcast_event("HUD_CLEAR", {})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    origin = websocket.headers.get("origin")
    if not is_origin_allowed(origin):
        logger.warning(f"[Server] Rejected WebSocket connection from origin: {origin}")
        # Closing before accept() rejects the handshake with HTTP 403
        await websocket.close(code=1008)
        return

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
                    policy = payload.get("policy")  # None: use execution_policy from config
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

        from ..core.artifacts import extract_artifacts
        for art in extract_artifacts(full_output):
            await broadcast_event("ARTIFACT", art)

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
