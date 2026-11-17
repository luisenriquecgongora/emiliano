"""
Background Coworker Daemon Server for Emiliano.
Runs the RoutineScheduler and exposes local REST/Webhook endpoints (port 8766)
for external triggers, routine management, and Trust Gate approvals.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.middleware.cors import CORSMiddleware
    import uvicorn
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("emiliano.routines.daemon")

from .models import (
    Routine,
    StagedActionStatus,
    TriggerType,
)
from .scheduler import RoutineScheduler
from .store import RoutineStore
from .synthesizer import SkillSynthesizer


def get_pid_file() -> Path:
    base = Path.home() / ".emiliano"
    base.mkdir(parents=True, exist_ok=True)
    return base / "daemon.pid"


def create_daemon_app(scheduler: RoutineScheduler) -> Any:
    """Builds FastAPI application for daemon management."""
    if not HAS_FASTAPI:
        raise RuntimeError("FastAPI and uvicorn are required to run the routines daemon.")

    app = FastAPI(title="Emiliano Routines Daemon", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    synthesizer = SkillSynthesizer()
    active_recordings: Dict[str, Dict[str, Any]] = {}

    @app.get("/health")
    async def health():
        return {
            "status": "healthy",
            "time": time.time(),
            "active_routines": len(scheduler.store.list_routines(enabled_only=True)),
            "pending_approvals": len(scheduler.store.list_staged_actions(status=StagedActionStatus.PENDING)),
        }

    @app.get("/routines")
    async def list_routines(enabled_only: bool = False):
        routines = scheduler.store.list_routines(enabled_only=enabled_only)
        return [r.model_dump() for r in routines]

    @app.post("/routines")
    async def create_routine(payload: Dict[str, Any]):
        try:
            routine = Routine.model_validate(payload)
            saved = scheduler.schedule_routine(routine)
            return saved.model_dump()
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/routines/{routine_id}/trigger")
    async def trigger_routine(routine_id: str, request: Request):
        body = await request.json() if (await request.body()) else {}
        try:
            record = await scheduler.execute_routine(
                routine_id,
                trigger_type=TriggerType.MANUAL,
                override_inputs=body.get("inputs"),
            )
            return record.model_dump()
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/webhooks/{routine_id}")
    async def webhook_trigger(routine_id: str, request: Request):
        payload = await request.json() if (await request.body()) else {}
        try:
            record = await scheduler.execute_routine(
                routine_id,
                trigger_type=TriggerType.WEBHOOK,
                override_inputs={"webhook_payload": payload},
            )
            return {"status": "triggered", "run_id": record.id}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/staged")
    async def list_staged(status: Optional[str] = "pending"):
        filter_status = StagedActionStatus(status) if status else None
        actions = scheduler.store.list_staged_actions(status=filter_status)
        return [a.model_dump() for a in actions]

    @app.post("/staged/{action_id}/approve")
    async def approve_staged(action_id: str):
        action = scheduler.store.resolve_staged_action(action_id, StagedActionStatus.APPROVED)
        if not action:
            raise HTTPException(status_code=404, detail="Staged action not found")
        # In production, dispatch action execution
        return action.model_dump()

    @app.post("/staged/{action_id}/reject")
    async def reject_staged(action_id: str, payload: Dict[str, Any] = None):
        notes = (payload or {}).get("notes", "Rejected by user")
        action = scheduler.store.resolve_staged_action(action_id, StagedActionStatus.REJECTED, notes=notes)
        if not action:
            raise HTTPException(status_code=404, detail="Staged action not found")
        return action.model_dump()

    @app.post("/teach/start")
    async def teach_start(payload: Dict[str, Any]):
        goal = payload.get("goal", "Teach Task Demonstration")
        session_id = payload.get("session_id", "default_recording")
        active_recordings[session_id] = {
            "goal": goal,
            "events": [],
            "started_at": time.time(),
        }
        return {"status": "recording", "session_id": session_id}

    @app.post("/teach/event")
    async def teach_event(payload: Dict[str, Any]):
        session_id = payload.get("session_id", "default_recording")
        if session_id not in active_recordings:
            raise HTTPException(status_code=404, detail="Recording session not found")
        event = payload.get("event", {})
        active_recordings[session_id]["events"].append(event)
        return {"status": "ok", "count": len(active_recordings[session_id]["events"])}

    @app.post("/teach/stop")
    async def teach_stop(payload: Dict[str, Any]):
        session_id = payload.get("session_id", "default_recording")
        skill_id = payload.get("skill_id", f"skill_{int(time.time())}")
        title = payload.get("title", "Synthesized Workflow")

        session = active_recordings.pop(session_id, None)
        if not session:
            raise HTTPException(status_code=404, detail="No active recording session found")

        events = session["events"]
        if not events and "events" in payload:
            events = payload["events"]

        skill = synthesizer.compile_trace(
            skill_id=skill_id,
            title=title,
            user_goal=session["goal"],
            events=events,
        )
        return {"status": "synthesized", "skill": skill.to_dict()}

    return app


class DaemonService:
    """Manages daemon lifecycle, PID files, and running server."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8766):
        self.host = host
        self.port = port
        self.pid_file = get_pid_file()

    def is_running(self) -> Optional[int]:
        if not self.pid_file.exists():
            return None
        try:
            pid = int(self.pid_file.read_text().strip())
            # Check if process is still alive on Windows/Unix
            if sys.platform == "win32":
                import ctypes
                kernel32 = ctypes.windll.kernel32
                SYNCHRONIZE = 0x00100000
                process = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
                if process:
                    kernel32.CloseHandle(process)
                    return pid
                return None
            else:
                os.kill(pid, 0)
                return pid
        except Exception:
            return None

    def start_foreground(self):
        """Starts daemon in current foreground process."""
        self.pid_file.write_text(str(os.getpid()))
        store = RoutineStore()
        scheduler = RoutineScheduler(store=store)

        async def _run():
            await scheduler.start()
            app = create_daemon_app(scheduler)
            config = uvicorn.Config(app, host=self.host, port=self.port, log_level="info")
            server = uvicorn.Server(config)
            try:
                await server.serve()
            finally:
                await scheduler.stop()
                if self.pid_file.exists():
                    self.pid_file.unlink()

        try:
            asyncio.run(_run())
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            if self.pid_file.exists():
                self.pid_file.unlink()

    def stop(self) -> bool:
        pid = self.is_running()
        if not pid:
            return False
        try:
            if sys.platform == "win32":
                import ctypes
                PROCESS_TERMINATE = 0x0001
                handle = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
                if handle:
                    ctypes.windll.kernel32.TerminateProcess(handle, 0)
                    ctypes.windll.kernel32.CloseHandle(handle)
            else:
                os.kill(pid, signal.SIGTERM)
            if self.pid_file.exists():
                self.pid_file.unlink()
            return True
        except Exception as e:
            logger.error(f"Failed to stop daemon PID {pid}: {e}")
            return False
