"""
FastAPI & WebSocket IPC Server for Emiliano Engine.
Bridges the Python core to the Tauri desktop Cowork UI.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Set, Union
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
from ..cowork.voice import VoiceTranscriber
from ..core.blackboard import Blackboard
from ..direct import UnifiedLLMClient
from ..routines.store import RoutineStore
from ..routines.scheduler import RoutineScheduler
from ..routines.models import Routine, TriggerType, StagedActionStatus
from .security import get_allowed_origins, is_origin_allowed, get_ipc_token, verify_ipc_token

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
    # 1. Reject disallowed browser origins (checked first on ALL endpoints)
    if not is_origin_allowed(request.headers.get("origin")):
        return JSONResponse({"detail": "Origin not allowed"}, status_code=403)

    # Allow unauthenticated health checks for monitoring
    if request.url.path == "/health":
        return await call_next(request)

    # 2. Enforce IPC token authentication when configured
    expected_token = get_ipc_token()
    if expected_token:
        auth_header = request.headers.get("authorization", "")
        token = None
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
        elif "token" in request.query_params:
            token = request.query_params["token"]

        if not verify_ipc_token(token):
            return JSONResponse({"detail": "Invalid or missing IPC authorization token"}, status_code=401)

    return await call_next(request)


# The desktop app's pages are served from their own origin, so its REST calls need CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(get_allowed_origins()),
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["content-type", "authorization"],
)

# Connected UI clients (usually the desktop dock and HUD overlay windows)
active_connections: Set[WebSocket] = set()

# Global dispatcher instance (lazily initialized or created on startup)
_dispatcher: Optional[ExecutionDispatcher] = None

# Active running background tasks keyed by task ID
active_tasks: Dict[str, asyncio.Task] = {}


_history: Optional[HistoryStore] = None
_routine_store: Optional[RoutineStore] = None
_routine_scheduler: Optional[RoutineScheduler] = None


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


def get_routine_store() -> RoutineStore:
    global _routine_store
    if _routine_store is None:
        _routine_store = RoutineStore()
    return _routine_store


def get_routine_scheduler() -> RoutineScheduler:
    global _routine_scheduler
    if _routine_scheduler is None:
        store = get_routine_store()
        disp = get_dispatcher()
        _routine_scheduler = RoutineScheduler(store=store, dispatcher=disp)
        _routine_scheduler.on_staged_action = lambda action: asyncio.create_task(
            broadcast_event("STAGED_ACTION_PROMPT", action.model_dump())
        )
    return _routine_scheduler


# Saved chats (/api/chats, /api/chat); the routes find these through app.state
app.state.get_dispatcher = lambda: get_dispatcher()
app.state.get_history_store = lambda: get_history_store()
app.include_router(history_router)


# ---------------------------------------------------------------------------
# Routines & Trust Gate REST API (Grok Bot Architecture)
# ---------------------------------------------------------------------------

@app.get("/api/routines")
async def api_list_routines(enabled_only: bool = False):
    routines = get_routine_store().list_routines(enabled_only=enabled_only)
    return {"routines": [r.model_dump() for r in routines]}


@app.post("/api/routines")
async def api_create_routine(payload: Dict[str, Any]):
    try:
        routine = Routine.model_validate(payload)
        saved = get_routine_scheduler().schedule_routine(routine)
        return saved.model_dump()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/routines/{routine_id}/trigger")
async def api_trigger_routine(routine_id: str, request: Request):
    body = await request.json() if (await request.body()) else {}
    try:
        record = await get_routine_scheduler().execute_routine(
            routine_id,
            trigger_type=TriggerType.MANUAL,
            override_inputs=body.get("inputs"),
        )
        return record.model_dump()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/routines/staged")
async def api_list_staged(status: Optional[str] = "pending"):
    filter_status = StagedActionStatus(status) if status else None
    actions = get_routine_store().list_staged_actions(status=filter_status)
    return {"staged_actions": [a.model_dump() for a in actions]}


@app.post("/api/routines/staged/{action_id}/approve")
async def api_approve_staged(action_id: str):
    action = get_routine_store().resolve_staged_action(action_id, StagedActionStatus.APPROVED)
    if not action:
        raise HTTPException(status_code=404, detail="Staged action not found")
    await broadcast_event("STAGED_ACTION_RESOLVED", {"id": action_id, "status": "approved"})
    return action.model_dump()


@app.post("/api/routines/staged/{action_id}/reject")
async def api_reject_staged(action_id: str, request: Request):
    body = await request.json() if (await request.body()) else {}
    action = get_routine_store().resolve_staged_action(action_id, StagedActionStatus.REJECTED, notes=body.get("notes"))
    if not action:
        raise HTTPException(status_code=404, detail="Staged action not found")
    await broadcast_event("STAGED_ACTION_RESOLVED", {"id": action_id, "status": "rejected"})
    return action.model_dump()


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
    keep_alive: Optional[Union[int, str]] = None


@app.post("/api/models/load")
async def load_model(payload: ModelPayload):
    """Loads a local model into memory and keeps it there until unloaded or expired."""
    dispatcher = get_dispatcher()
    mgr = dispatcher.registry.ollama_mgr
    if payload.model not in await mgr.list_installed_models():
        raise HTTPException(status_code=404, detail=f"Model not installed: {payload.model}")

    # Enforce VRAM headroom and perform LRU eviction if needed
    from ..direct.lifecycle import ModelLifecycleGovernor
    governor = ModelLifecycleGovernor.get_instance(config=dispatcher.config, ollama_mgr=mgr)
    evicted = await governor.ensure_vram_headroom(payload.model)

    keep_alive = (
        payload.keep_alive
        if payload.keep_alive is not None
        else -1
    )
    ok = await mgr.preload(payload.model, num_ctx=dispatcher.config.models.ollama_num_ctx, keep_alive=keep_alive)
    if not ok:
        raise HTTPException(status_code=502, detail=f"Ollama could not load {payload.model}")
    governor.touch(payload.model)
    return {"status": "loaded", "model": payload.model, "keep_alive": keep_alive, "evicted": evicted}


@app.get("/api/models/memory")
async def get_models_memory():
    """Returns real-time VRAM and RAM telemetry and loaded model statistics."""
    dispatcher = get_dispatcher()
    from ..direct.lifecycle import ModelLifecycleGovernor
    governor = ModelLifecycleGovernor.get_instance(config=dispatcher.config, ollama_mgr=dispatcher.registry.ollama_mgr)
    return await governor.get_memory_telemetry()


@app.post("/api/models/unload")
async def unload_model(payload: ModelPayload):
    """Frees the memory a loaded local model holds."""
    if not await get_dispatcher().registry.ollama_mgr.unload(payload.model):
        raise HTTPException(status_code=502, detail=f"Ollama could not unload {payload.model}")
    return {"status": "unloaded", "model": payload.model}


@app.post("/api/models/unload-all")
async def unload_all_models():
    """Frees memory for all currently loaded local models."""
    unloaded = await get_dispatcher().registry.ollama_mgr.unload_all()
    return {"status": "unloaded_all", "unloaded": unloaded}


active_downloads: Dict[str, Dict[str, Any]] = {}


class PullModelPayload(BaseModel):
    model: str


@app.post("/api/models/pull")
async def start_pull_model(payload: PullModelPayload):
    """Starts downloading/pulling a model from the Ollama library in the background."""
    model_name = payload.model.strip()
    if not model_name:
        raise HTTPException(status_code=400, detail="Model name required")

    current = active_downloads.get(model_name)
    if current and current.get("status") in ("starting", "downloading"):
        return {"status": "already_downloading", "model": model_name}

    active_downloads[model_name] = {
        "status": "starting",
        "step": "Connecting to Ollama registry...",
        "progress": 0,
        "completed": 0,
        "total": 0,
        "error": None,
    }

    async def _download():
        mgr = get_dispatcher().registry.ollama_mgr
        try:
            async for chunk in mgr.pull_model_stream(model_name):
                status_text = chunk.get("status", "")
                completed = chunk.get("completed", 0)
                total = chunk.get("total", 0)
                pct = int((completed / total) * 100) if total > 0 else 0
                active_downloads[model_name] = {
                    "status": "downloading" if pct < 100 else "finalizing",
                    "step": status_text,
                    "progress": pct,
                    "completed": completed,
                    "total": total,
                    "error": None,
                }
            active_downloads[model_name] = {
                "status": "completed",
                "step": "Download complete",
                "progress": 100,
                "error": None,
            }
        except Exception as e:
            logger.error(f"[Ollama] Pull {model_name} failed: {e}")
            active_downloads[model_name] = {
                "status": "error",
                "step": f"Failed: {e}",
                "progress": 0,
                "error": str(e),
            }

    asyncio.create_task(_download())
    return {"status": "started", "model": model_name}


@app.get("/api/models/pull/status")
async def get_pull_status(model: Optional[str] = None):
    """Returns the progress of active model downloads."""
    if model:
        return {"downloads": {model: active_downloads.get(model, {"status": "idle"})}}
    return {"downloads": active_downloads}


@app.delete("/api/models/delete")
async def delete_model_endpoint(payload: Optional[PullModelPayload] = None, model: Optional[str] = None):
    """Deletes an installed model to reclaim disk space."""
    target = (payload.model if payload else None) or model
    if not target:
        raise HTTPException(status_code=400, detail="Model name required")
    mgr = get_dispatcher().registry.ollama_mgr
    ok = await mgr.delete_model(target)
    if not ok:
        raise HTTPException(status_code=500, detail=f"Failed to delete {target}")
    return {"status": "deleted", "model": target}


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


class BrowserCommandPayload(BaseModel):
    action: str
    params: Optional[Dict[str, Any]] = None
    timeout: float = 20.0


class SynthesizeSkillPayload(BaseModel):
    id: str
    title: str
    description: str
    instructions_md: str
    triggers: Optional[List[str]] = None
    requirements: Optional[List[str]] = None
    selectors: Optional[Dict[str, str]] = None
    category: Optional[str] = "workflow"


class PatchSkillPayload(BaseModel):
    selectors: Optional[Dict[str, str]] = None
    append_notes: Optional[str] = None


BrowserCommandPayload.model_rebuild()
SynthesizeSkillPayload.model_rebuild()
PatchSkillPayload.model_rebuild()


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


class ResizeHudPayload(BaseModel):
    width: Optional[int] = None
    height: Optional[int] = None
    x: Optional[int] = None
    y: Optional[int] = None
    direction: Optional[str] = "West"


@app.post("/api/cowork/resize_hud")
async def resize_hud(payload: ResizeHudPayload):
    """Dynamically resizes the Emiliano HUD window on Windows across any border/corner."""
    import sys
    if sys.platform != "win32":
        return {"status": "unsupported", "platform": sys.platform}
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32

        target_hwnd = None
        def enum_windows_callback(hwnd, _lparam):
            nonlocal target_hwnd
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value.strip()
                if "emiliano" in title.lower():
                    target_hwnd = hwnd
                    return False
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        cb = WNDENUMPROC(enum_windows_callback)
        hdesk = user32.OpenInputDesktop(0, False, 0x0100)
        if hdesk:
            user32.EnumDesktopWindows(hdesk, cb, 0)
            user32.CloseDesktop(hdesk)
        if not target_hwnd:
            user32.EnumWindows(cb, 0)

        if not target_hwnd:
            return {"status": "not_found", "message": "Emiliano HUD window not found"}

        rect = wintypes.RECT()
        user32.GetWindowRect(target_hwnd, ctypes.byref(rect))
        current_w = rect.right - rect.left
        current_h = rect.bottom - rect.top
        current_x = rect.left
        current_y = rect.top

        new_w = max(360, min(2400, payload.width)) if payload.width else current_w
        new_h = max(320, min(1800, payload.height)) if payload.height else current_h

        direction = (payload.direction or "West").lower()

        # Calculate new_x and new_y based on resize direction
        if payload.x is not None:
            new_x = payload.x
        elif "east" in direction:
            new_x = current_x # right edge dragged: left edge remains fixed
        elif "west" in direction:
            new_x = rect.right - new_w # left edge dragged: right edge remains fixed
        else:
            new_x = current_x

        if payload.y is not None:
            new_y = payload.y
        elif "south" in direction:
            new_y = current_y # bottom edge dragged: top edge remains fixed
        elif "north" in direction:
            new_y = rect.bottom - new_h # top edge dragged: bottom edge remains fixed
        else:
            new_y = current_y

        user32.SetWindowPos(target_hwnd, 0, new_x, new_y, new_w, new_h, 0x0004) # SWP_NOZORDER
        return {"status": "ok", "width": new_w, "height": new_h, "x": new_x, "y": new_y}
    except Exception as e:
        logger.error(f"[Server] Failed to resize HUD: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/api/skills")
async def list_skills():
    """Discovered companion skills and workflow extensions available to the desktop agent."""
    from ..core.extensions import ExtensionManager
    from ..core.skills import SkillManager

    skill_mgr = SkillManager.get_instance()
    all_skills = skill_mgr.get_all_skills()

    # Also discover extensions and map them if not already in SkillManager
    ext_mgr = ExtensionManager()
    for name, ext in ext_mgr.extensions.items():
        if not any(s.get("id") == ext.name for s in all_skills):
            all_skills.append({
                "id": ext.name,
                "title": ext.title,
                "description": ext.description,
                "triggers": ext.intents[:6],
                "category": "workflow",
                "status": "active",
                "badge": "Hospitality & Nightlife",
                "path": str(ext.path),
                "quickActions": [
                    "outreach 1 restaurant lead",
                    "outreach autonomous",
                    "crm status",
                ],
            })

    # Add email outreach engine quick action if not present
    if not any(s.get("id") == "email-outreach-engine" for s in all_skills):
        all_skills.append({
            "id": "email-outreach-engine",
            "title": "B2B Waterfall Email Enrichment",
            "description": "Multi-source waterfall email enrichment and vertical-tailored 3-paragraph pitch drafting",
            "triggers": ["send email", "email leads", "enrich emails"],
            "category": "workflow",
            "status": "active",
            "badge": "Email + Phone Waterfall",
            "path": "emiliano-cowork-plaatoos.email_outreach",
            "quickActions": [
                "send email leads",
                "enrich next 5 lead emails",
            ],
        })

    return {"skills": all_skills}


@app.get("/api/skills/{skill_id}/content")
async def get_skill_content(skill_id: str):
    from ..core.skills import SkillManager
    skill_mgr = SkillManager.get_instance()
    skill = skill_mgr.get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")
    return {"skill": skill.to_dict()}


@app.post("/api/skills/synthesize")
async def synthesize_skill_endpoint(payload: SynthesizeSkillPayload):
    from ..core.skills import SkillManager
    skill_mgr = SkillManager.get_instance()
    try:
        skill = skill_mgr.synthesize_skill(
            id=payload.id,
            title=payload.title,
            description=payload.description,
            instructions_md=payload.instructions_md,
            triggers=payload.triggers,
            requirements=payload.requirements,
            selectors=payload.selectors,
            category=payload.category or "workflow"
        )
        return {"status": "ok", "skill": skill.to_dict()}
    except Exception as e:
        logger.error(f"[Server] Failed to synthesize skill: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/skills/{skill_id}/approve")
async def approve_skill_endpoint(skill_id: str):
    from ..core.skills import SkillManager
    skill_mgr = SkillManager.get_instance()
    success = skill_mgr.approve_skill(skill_id)
    if not success:
        raise HTTPException(status_code=400, detail=f"Could not approve '{skill_id}'")
    return {"status": "ok", "skill_id": skill_id, "state": "active"}


@app.post("/api/skills/{skill_id}/discard")
async def discard_skill_endpoint(skill_id: str):
    from ..core.skills import SkillManager
    skill_mgr = SkillManager.get_instance()
    success = skill_mgr.discard_skill(skill_id)
    if not success:
        raise HTTPException(status_code=400, detail=f"Could not discard '{skill_id}'")
    return {"status": "ok", "skill_id": skill_id, "state": "discarded"}


@app.post("/api/skills/{skill_id}/patch")
async def patch_skill_endpoint(skill_id: str, payload: PatchSkillPayload):
    from ..core.skills import SkillManager
    skill_mgr = SkillManager.get_instance()
    success = skill_mgr.patch_skill(
        skill_id=skill_id,
        selectors=payload.selectors,
        append_notes=payload.append_notes
    )
    if not success:
        raise HTTPException(status_code=400, detail=f"Could not patch '{skill_id}'")
    return {"status": "ok", "skill_id": skill_id, "state": "patched"}


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


voice_transcriber = VoiceTranscriber()
blackboard = Blackboard()


@app.get("/api/voice/status")
async def get_voice_status():
    return {
        "status": "ok",
        "local_available": voice_transcriber.is_local_available,
        "whisper_binary": voice_transcriber.whisper_binary,
    }


@app.post("/api/voice/transcribe")
async def transcribe_voice(request: Request):
    audio_bytes = await request.body()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio payload")
    language = request.query_params.get("lang")
    text = voice_transcriber.transcribe(audio_bytes=audio_bytes, language=language)
    return {"status": "ok", "text": text}


@app.get("/api/blackboard/context")
async def get_blackboard_context():
    return {
        "context": blackboard.render_context_for_prompt(),
        "entities": blackboard.list_entities(),
        "last_session": blackboard.get_last_session_summary(),
    }


@app.websocket("/ws/browser")
async def browser_websocket_endpoint(websocket: WebSocket):
    origin = websocket.headers.get("origin")
    if not is_origin_allowed(origin):
        logger.warning(f"[Server] Rejected Browser Extension WebSocket connection from origin: {origin}")
        await websocket.close(code=1008)
        return

    expected_token = get_ipc_token()
    if expected_token:
        token = websocket.query_params.get("token") or websocket.headers.get("authorization", "").replace("Bearer ", "")
        if not verify_ipc_token(token):
            logger.warning("[Server] Rejected Browser Extension WebSocket: unauthorized token")
            await websocket.close(code=1008)
            return

    await websocket.accept()
    from emiliano.cowork.browser_bridge import get_browser_bridge
    bridge = get_browser_bridge()
    await bridge.handle_connection(websocket)


@app.get("/api/browser/status")
async def get_browser_status():
    from emiliano.cowork.browser_bridge import BrowserBridge
    bridge = BrowserBridge.get_instance()
    return {
        "connected": bridge.is_connected,
        "extension_info": bridge.extension_info
    }


@app.post("/api/browser/command")
async def execute_browser_command(payload: BrowserCommandPayload):
    from emiliano.cowork.browser_bridge import BrowserBridge
    bridge = BrowserBridge.get_instance()
    if not bridge.is_connected:
        raise HTTPException(status_code=503, detail="Browser extension is not connected.")
    try:
        res = await bridge.send_command(payload.action, payload.params, timeout=payload.timeout)
        return {"status": "ok", "result": res}
    except Exception as e:
        logger.error(f"[Server] Browser command failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    origin = websocket.headers.get("origin")
    if not is_origin_allowed(origin):
        logger.warning(f"[Server] Rejected WebSocket connection from origin: {origin}")
        # Closing before accept() rejects the handshake with HTTP 403
        await websocket.close(code=1008)
        return

    expected_token = get_ipc_token()
    if expected_token:
        token = websocket.query_params.get("token") or websocket.headers.get("authorization", "").replace("Bearer ", "")
        if not verify_ipc_token(token):
            logger.warning("[Server] Rejected UI WebSocket: unauthorized token")
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
