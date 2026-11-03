"""
HTTP and WebSocket API for saved chats.

REST:
    GET    /api/chats            list chats, newest first
    POST   /api/chats            create a chat            {"title": optional}
    GET    /api/chats/{id}       a chat with its messages
    DELETE /api/chats/{id}       delete a chat and its messages
    DELETE /api/chats            delete every chat

WebSocket /api/chat:
    client -> {"type": "send", "chat_id": "...", "content": "...", "mode": "auto" | "direct" | <harness>}
              {"type": "cancel"}
    server -> {"type": "user_message", "message": {...}}
              {"type": "route", "name": "...", "display_name": "..."}
              {"type": "reasoning", "content": "..."}     model reasoning, shown collapsed
              {"type": "chunk", "content": "..."}         answer text
              {"type": "done", "message": {...}, "chat": {...}}
              {"type": "cancelled"} | {"type": "error", "message": "...", "code": "..."}
"""

from __future__ import annotations

import asyncio
from typing import Optional, Tuple

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


@router.get("/chats")
async def list_chats(request: Request, limit: int = 50, offset: int = 0):
    return _store(request.app).list_chats(limit=min(max(limit, 1), 200), offset=max(offset, 0))


@router.post("/chats", status_code=201)
async def create_chat(request: Request, body: NewChat):
    return _store(request.app).create_chat(body.title)


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


@router.post("/chats/{chat_id}/compact")
async def compact_chat(request: Request, chat_id: str):
    store = _store(request.app)
    chat = store.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")

    msgs = [{"role": m["role"], "content": m["content"]} for m in chat["messages"]]
    if len(msgs) < 4:
        return {"status": "noop", "message": "Chat history is too short to compact"}

    dispatcher = request.app.state.get_dispatcher()
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

    def emit(event: dict) -> None:
        # Dispatcher callbacks can run on a worker thread (harness runs), so hop to the loop
        loop.call_soon_threadsafe(outbox.put_nowait, event)

    async def sender() -> None:
        while True:
            await websocket.send_json(await outbox.get())

    async def respond(chat_id: str, content: str, mode: Optional[str]) -> None:
        policy, harness = resolve_mode(mode)
        answer = []

        def on_chunk(text: str) -> None:
            answer.append(text)
            emit({"type": "chunk", "content": text})

        try:
            cap, full = await websocket.app.state.get_dispatcher().execute_task(
                goal=content,
                policy=policy,
                harness_override=harness,
                messages=store.conversation(chat_id),
                on_chunk=on_chunk,
                on_reasoning=lambda text: emit({"type": "reasoning", "content": text}),
                on_route_selected=lambda c: emit({"type": "route", "name": c.name, "display_name": c.display_name}),
            )
            saved = store.add_message(chat_id, "assistant", full)
            emit({"type": "done", "message": saved, "chat": store.get_chat(chat_id)})
        except asyncio.CancelledError:
            # Keep what was already shown, so the saved chat matches the screen
            if answer:
                store.add_message(chat_id, "assistant", "".join(answer) + "\n\n[stopped]")
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
                if running and not running.done():
                    running.cancel()
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
            user_message = store.add_message(chat_id, "user", content) if chat_id else None
            if user_message is None:
                emit({"type": "error", "message": "Chat not found", "code": "CHAT_NOT_FOUND"})
                continue
            emit({"type": "user_message", "message": user_message})
            running = asyncio.create_task(respond(chat_id, content, data.get("mode")))
    except WebSocketDisconnect:
        pass
    finally:
        if running and not running.done():
            running.cancel()
        sending.cancel()
