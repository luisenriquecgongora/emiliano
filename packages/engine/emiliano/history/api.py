"""
HTTP and WebSocket API for saved chats.

REST:
    GET    /api/chats            list chats, newest first
    POST   /api/chats            create a chat            {"title": optional}
    GET    /api/chats/{id}       a chat with its messages
    DELETE /api/chats/{id}       delete a chat and its messages
    DELETE /api/chats            delete every chat

WebSocket /api/chat:
    client -> {"type": "send", "chat_id": "...", "content": "...", "mode": "auto" | "direct" | <harness>,
               "provider": optional, "model": optional}   provider (e.g. "ollama") + model pick one model,
               overriding mode; see GET /api/models
              {"type": "cancel"}
              {"type": "permission_response", "request_id": "...", "option_id": "..." | null}   null = reject
    server -> {"type": "user_message", "message": {...}}
              {"type": "permission_request", "request_id": "...", "title": "...", "kind": "...",
               "options": [{"optionId", "name", "kind"}]}   an agent asks before running a tool;
               unanswered requests are rejected after PERMISSION_TIMEOUT_S
              {"type": "route", "name": "...", "display_name": "..."}
              {"type": "reasoning", "content": "..."}     model reasoning, shown collapsed
              {"type": "chunk", "content": "..."}         answer text
              {"type": "done", "message": {...}, "chat": {...}}
              {"type": "cancelled"} | {"type": "error", "message": "...", "code": "..."}
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import itertools
import os
import subprocess
import time
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from loguru import logger
from pydantic import BaseModel

from ..server.security import is_origin_allowed
from .store import HistoryStore

router = APIRouter(prefix="/api")

# Desktop mode selector values -> (routing policy, harness override)
MODES = {
    "auto": (None, None),
    "direct": ("local", None),
    "claude_code": (None, "claude"),
    "codex": (None, "codex"),
    "antigravity": (None, "agy"),
    "opencode": (None, "opencode"),
}


def resolve_mode(mode: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    return MODES.get(mode or "auto", MODES["auto"])


def _store(app) -> HistoryStore:
    return app.state.get_history_store()


class NewChat(BaseModel):
    title: Optional[str] = None
    project_id: Optional[str] = None


class NewProject(BaseModel):
    name: str
    root_path: Optional[str] = ""
    description: Optional[str] = ""
    system_prompt: Optional[str] = ""


class UpdateProject(BaseModel):
    name: Optional[str] = None
    root_path: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None


class NewArtifact(BaseModel):
    title: str
    kind: Optional[str] = "code"
    content: str
    chat_id: Optional[str] = None
    project_id: Optional[str] = None
    file_path: Optional[str] = None


@router.get("/chats")
async def list_chats(request: Request, limit: int = 50, offset: int = 0, project_id: Optional[str] = None):
    return _store(request.app).list_chats(limit=min(max(limit, 1), 200), offset=max(offset, 0), project_id=project_id)


@router.post("/chats", status_code=201)
async def create_chat(request: Request, body: NewChat):
    return _store(request.app).create_chat(title=body.title, project_id=body.project_id)


@router.get("/chats/{chat_id}")
async def get_chat(request: Request, chat_id: str):
    chat = _store(request.app).get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat


@router.delete("/chats/{chat_id}", status_code=204)
async def delete_chat(request: Request, chat_id: str):
    if not _store(request.app).delete_chat(chat_id):
        raise HTTPException(status_code=404, detail="Chat not found")


@router.delete("/chats")
async def delete_all_chats(request: Request):
    return {"deleted": _store(request.app).delete_all()}


# -------------------------------------------------------------
# PROJECTS REST API (Local Workspaces)
# -------------------------------------------------------------
@router.get("/projects")
async def list_projects(request: Request):
    return _store(request.app).list_projects()


@router.post("/projects", status_code=201)
async def create_project(request: Request, body: NewProject):
    return _store(request.app).create_project(
        name=body.name,
        root_path=body.root_path,
        description=body.description or "",
        system_prompt=body.system_prompt or "",
    )


@router.get("/projects/{project_id}")
async def get_project(request: Request, project_id: str):
    project = _store(request.app).get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.patch("/projects/{project_id}")
async def update_project(request: Request, project_id: str, body: UpdateProject):
    updated = _store(request.app).update_project(
        project_id=project_id,
        name=body.name,
        root_path=body.root_path,
        description=body.description,
        system_prompt=body.system_prompt,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return updated


@router.post("/projects/{project_id}/open-folder")
async def open_project_folder(request: Request, project_id: str):
    project = _store(request.app).get_project(project_id)
    if not project or not project.get("root_path"):
        raise HTTPException(status_code=404, detail="Project or root path not found")
    path = os.path.abspath(project["root_path"])
    if not os.path.exists(path):
        raise HTTPException(status_code=400, detail="Folder does not exist on disk")
    if os.name == "nt":
        os.startfile(path)
    else:
        subprocess.Popen(["open" if os.name == "posix" else "xdg-open", path])
    return {"opened": True, "path": path}


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(request: Request, project_id: str):
    if not _store(request.app).delete_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")


# -------------------------------------------------------------
# ARTIFACTS REST API (Local Deliverable Registry)
# -------------------------------------------------------------
@router.get("/artifacts")
async def list_artifacts(
    request: Request,
    chat_id: Optional[str] = None,
    project_id: Optional[str] = None,
    kind: Optional[str] = None,
):
    return _store(request.app).list_artifacts(chat_id=chat_id, project_id=project_id, kind=kind)


@router.post("/artifacts", status_code=201)
async def create_artifact(request: Request, body: NewArtifact):
    return _store(request.app).create_artifact(
        title=body.title,
        kind=body.kind,
        content=body.content,
        chat_id=body.chat_id,
        project_id=body.project_id,
        file_path=body.file_path,
    )


@router.get("/artifacts/{artifact_id}")
async def get_artifact(request: Request, artifact_id: str):
    artifact = _store(request.app).get_artifact(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return artifact


@router.delete("/artifacts/{artifact_id}", status_code=204)
async def delete_artifact(request: Request, artifact_id: str):
    if not _store(request.app).delete_artifact(artifact_id):
        raise HTTPException(status_code=404, detail="Artifact not found")


@router.post("/artifacts/{artifact_id}/open")
async def open_artifact_file(request: Request, artifact_id: str):
    artifact = _store(request.app).get_artifact(artifact_id)
    if not artifact or not artifact.get("file_path"):
        raise HTTPException(status_code=404, detail="Artifact or file path not found")
    path = os.path.abspath(artifact["file_path"])
    if not os.path.exists(path):
        raise HTTPException(status_code=400, detail="File does not exist on disk")
    if os.name == "nt":
        os.startfile(path)
    else:
        subprocess.Popen(["open" if os.name == "posix" else "xdg-open", path])
    return {"opened": True, "path": path}


@router.get("/chats/{chat_id}/context")
async def get_chat_context(request: Request, chat_id: str, model_id: Optional[str] = None):
    chat = _store(request.app).get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")

    dispatcher = request.app.state.get_dispatcher()
    msgs = [{"role": m["role"], "content": m["content"]} for m in chat["messages"]]
    metrics = dispatcher.context_manager.get_metrics(
        messages=msgs,
        model_id=model_id or "claude-3-7-sonnet",
    )
    if metrics.usage_percentage > 90:
        status = "CRITICAL"
    elif metrics.usage_percentage > 75:
        status = "HIGH"
    elif metrics.usage_percentage > 50:
        status = "MODERATE"
    else:
        status = "GOOD"

    return {
        "chat_id": chat_id,
        "total_tokens": metrics.total_tokens,
        "history_tokens": metrics.history_tokens,
        "system_tokens": metrics.system_tokens,
        "persistent_tokens": metrics.persistent_tokens,
        "available_tokens": metrics.available_tokens,
        "max_tokens": metrics.max_tokens,
        "usage_percentage": round(metrics.usage_percentage, 1),
        "message_count": metrics.message_count,
        "status": status,
    }


async def _do_compact(app, chat_id: str) -> dict:
    store = _store(app)
    chat = store.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")

    msgs = [{"role": m["role"], "content": m["content"]} for m in chat["messages"]]
    if len(msgs) < 4:
        return {"status": "noop", "message": "Chat history is too short to compact"}

    dispatcher = app.state.get_dispatcher()
    before_tokens = dispatcher.context_manager.count_messages_tokens(msgs)

    # Summarize older messages, keep the most recent 2 turns (4 messages)
    older = msgs[:-4]
    recent = msgs[-4:]

    summary_msg = await dispatcher.context_manager.summarizer.summarize(older)
    new_msgs = [summary_msg] + recent
    after_tokens = dispatcher.context_manager.count_messages_tokens(new_msgs)

    store.replace_messages(chat_id, new_msgs)
    return {
        "status": "compacted",
        "tokens_saved": max(0, before_tokens - after_tokens),
        "message_count": len(new_msgs),
        "summary": summary_msg.get("content", ""),
    }


@router.post("/chats/{chat_id}/compact")
async def compact_chat(request: Request, chat_id: str):
    return await _do_compact(request.app, chat_id)


@router.post("/chats/{chat_id}/clear")
async def clear_chat_messages(request: Request, chat_id: str):
    """Flushes active conversation messages while keeping the chat container."""
    store = _store(request.app)
    chat = store.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    store.replace_messages(chat_id, [])
    return {"status": "cleared", "chat_id": chat_id}


PERMISSION_TIMEOUT_S = 120.0


@router.websocket("/chat")
async def chat_socket(websocket: WebSocket):
    if not is_origin_allowed(websocket.headers.get("origin")):
        await websocket.close(code=1008)  # Rejects the handshake with HTTP 403
        return
    await websocket.accept()

    store = _store(websocket.app)
    loop = asyncio.get_running_loop()
    outbox: asyncio.Queue = asyncio.Queue()
    running: Optional[asyncio.Task] = None
    # Permission requests waiting for the user, by request_id; answered from the receive loop
    pending: Dict[str, concurrent.futures.Future] = {}
    request_ids = itertools.count(1)

    def emit(event: dict) -> None:
        # Dispatcher callbacks can run on a worker thread (harness runs), so hop to the loop
        loop.call_soon_threadsafe(outbox.put_nowait, event)

    def ask_permission(tool_call: dict, options: List[dict]) -> Optional[str]:
        """Runs on the harness worker thread: shows the request in the dock and waits for the answer."""
        request_id = f"perm-{next(request_ids)}"
        answer: concurrent.futures.Future = concurrent.futures.Future()
        pending[request_id] = answer
        emit({
            "type": "permission_request",
            "request_id": request_id,
            "title": tool_call.get("title") or "Run a tool",
            "kind": tool_call.get("kind") or "other",
            "options": [{k: o.get(k) for k in ("optionId", "name", "kind")} for o in options],
        })
        try:
            return answer.result(timeout=PERMISSION_TIMEOUT_S)
        except concurrent.futures.TimeoutError:
            logger.info(f"[History] Permission {request_id} unanswered; rejecting")
            emit({"type": "permission_closed", "request_id": request_id})
            return None
        finally:
            pending.pop(request_id, None)

    def reject_pending() -> None:
        for answer in list(pending.values()):
            if not answer.done():
                answer.set_result(None)

    async def sender() -> None:
        while True:
            await websocket.send_json(await outbox.get())

    async def respond(chat_id: str, content: str, mode: Optional[str],
                      provider: Optional[str] = None, model: Optional[str] = None) -> None:
        # A model picked in the dock answers directly, whatever the mode says
        policy, harness = (None, None) if provider else resolve_mode(mode)
        answer = []
        reasoning_parts = []

        def on_chunk(text: str) -> None:
            answer.append(text)
            emit({"type": "chunk", "content": text})

        def on_reason(text: str) -> None:
            reasoning_parts.append(text)
            emit({"type": "reasoning", "content": text})

        try:
            chat_obj = store.get_chat(chat_id) or {}
            chat_proj_id = chat_obj.get("project_id")
            project = store.get_project(chat_proj_id) if chat_proj_id else None
            project_workspace = project.get("root_path") if project else None
            project_prompt = project.get("system_prompt") if project else None

            conv_msgs = store.conversation(chat_id)
            if project_prompt:
                has_proj_prompt = any(m.get("role") == "system" and project_prompt in m.get("content", "") for m in conv_msgs)
                if not has_proj_prompt:
                    conv_msgs = [{"role": "system", "content": f"Workspace Project Guidelines:\n{project_prompt}"}] + conv_msgs

            cap, full = await websocket.app.state.get_dispatcher().execute_task(
                goal=content,
                policy=policy,
                harness_override=harness,
                provider_override=provider,
                model_override=model if provider else None,
                messages=conv_msgs,
                on_chunk=on_chunk,
                on_reasoning=on_reason,
                on_route_selected=lambda c: emit({"type": "route", "name": c.name, "display_name": c.display_name}),
                on_permission=ask_permission,
                reasoning=True,
                workspace=project_workspace,
            )
            from ..core.artifacts import extract_artifacts
            for art in extract_artifacts(full):
                emit({"type": "artifact", **art})
                try:
                    store.create_artifact(
                        title=art.get("title") or "Deliverable",
                        kind=art.get("kind") or "markdown",
                        content=art.get("content") or "",
                        chat_id=chat_id,
                        project_id=chat_proj_id,
                    )
                except Exception as art_err:
                    logger.warning(f"[Artifact] Failed to save artifact: {art_err}")
            full_reasoning = "".join(reasoning_parts).strip() if reasoning_parts else None
            saved = store.add_message(chat_id, "assistant", full, reasoning=full_reasoning)
            emit({"type": "done", "message": saved, "chat": store.get_chat(chat_id)})
        except asyncio.CancelledError:
            # Keep what was already shown, so the saved chat matches the screen
            full_reasoning = "".join(reasoning_parts).strip() if reasoning_parts else None
            if answer:
                store.add_message(chat_id, "assistant", "".join(answer) + "\n\n[stopped]", reasoning=full_reasoning)
            emit({"type": "cancelled"})
        except Exception as e:
            logger.warning(f"[History] Reply failed: {e}")
            emit({"type": "error", "message": str(e), "code": "EXECUTION_ERROR"})

    sending = asyncio.create_task(sender())
    try:
        while True:
            data = await websocket.receive_json()
            kind = data.get("type")
            if kind == "cancel":
                reject_pending()
                if running and not running.done():
                    running.cancel()
                continue
            if kind == "permission_response":
                answer = pending.get(str(data.get("request_id")))
                if answer and not answer.done():
                    option = data.get("option_id")
                    answer.set_result(str(option) if option else None)
                continue
            if kind != "send":
                emit({"type": "error", "message": f"Unknown message type: {kind}", "code": "INVALID_TYPE"})
                continue

            chat_id, content = data.get("chat_id"), (data.get("content") or "").strip()
            if running and not running.done():
                emit({"type": "error", "message": "A reply is still running.", "code": "BUSY"})
                continue
            if not content:
                emit({"type": "error", "message": "Message cannot be empty.", "code": "EMPTY"})
                continue

            # Direct slash command interception for state-of-the-art context flushing
            if content.lower() == "/compact" and chat_id:
                try:
                    c_res = await _do_compact(websocket.app, chat_id)
                    emit({
                        "type": "done",
                        "message": {
                            "id": f"compact-{int(time.time()*1000)}",
                            "chat_id": chat_id,
                            "role": "assistant",
                            "content": f"✨ **Context Compacted**\n\n• Tokens saved: **{c_res.get('tokens_saved', 0):,}**\n• Messages remaining: **{c_res.get('message_count', 0)}**\n• Status: {c_res.get('status')}",
                        },
                        "chat": store.get_chat(chat_id),
                    })
                except Exception as comp_err:
                    emit({"type": "error", "message": f"Compaction failed: {comp_err}", "code": "COMPACT_ERROR"})
                continue

            if content.lower() == "/clear" and chat_id:
                store.replace_messages(chat_id, [])
                emit({
                    "type": "done",
                    "message": {
                        "id": f"clear-{int(time.time()*1000)}",
                        "chat_id": chat_id,
                        "role": "assistant",
                        "content": "🧹 **Context Flushed**\n\nActive conversation context has been reset to 0 tokens.",
                    },
                    "chat": store.get_chat(chat_id),
                })
                continue

            user_message = store.add_message(chat_id, "user", content) if chat_id else None
            if user_message is None:
                emit({"type": "error", "message": "Chat not found", "code": "CHAT_NOT_FOUND"})
                continue
            emit({"type": "user_message", "message": user_message})
            running = asyncio.create_task(respond(
                chat_id, content, data.get("mode"), data.get("provider") or None, data.get("model") or None))
    except WebSocketDisconnect:
        pass
    finally:
        reject_pending()
        if running and not running.done():
            running.cancel()
        sending.cancel()
