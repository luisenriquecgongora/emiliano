"""
Task traces: one record per executed task, in a local SQLite database
(~/.emiliano/traces.db by default, or EMILIANO_TRACES_DB).

A trace says which route ran a task, what was tried before it, how long it took (and how long until the
first output), how many tokens it used where the provider reports them, and how permission requests were
answered. Evals and routing improvements read these records; nothing leaves the machine.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import DateTime, Float, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("emiliano")

GOAL_PREVIEW = 500  # characters of the goal kept in a trace


def default_traces_url() -> str:
    path = Path(os.environ.get("EMILIANO_TRACES_DB") or Path.home() / ".emiliano" / "traces.db")
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path}"


@dataclass
class TaskTrace:
    """What happened while one task ran. Built up by the dispatcher, then saved once."""

    goal: str
    policy: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    route: Optional[str] = None  # capability that produced the answer, e.g. "ollama" or "claude_code"
    execution_type: Optional[str] = None  # "direct_model" or "agent_harness"
    model: Optional[str] = None  # litellm model id for direct models
    outcome: str = "failed"  # "succeeded" | "failed" | "cancelled"
    error: Optional[str] = None
    attempts: List[Dict[str, Any]] = field(default_factory=list)  # every route tried, in order
    duration_s: Optional[float] = None
    first_output_s: Optional[float] = None  # time to first streamed output
    output_chars: int = 0
    prompt_tokens: Optional[int] = None  # as reported by the provider; None when unknown
    completion_tokens: Optional[int] = None
    permissions: List[Dict[str, Any]] = field(default_factory=list)  # tool, decision
    _t0: float = field(default_factory=time.monotonic, repr=False)
    _first_token_s: Optional[float] = field(default=None, repr=False)  # first token of any kind, reasoning included

    def mark_output(self, text: str) -> None:
        if self.first_output_s is None and text:
            self.first_output_s = round(time.monotonic() - self._t0, 3)
        self.mark_reasoning(text)
        self.output_chars += len(text)

    def mark_reasoning(self, text: str) -> None:
        """Reasoning tokens count for speed: provider token counts include them."""
        if self._first_token_s is None and text:
            self._first_token_s = round(time.monotonic() - self._t0, 3)

    def finish(self, outcome: str, error: Optional[str] = None) -> None:
        self.outcome = outcome
        self.error = error[:2000] if error else None
        self.duration_s = round(time.monotonic() - self._t0, 3)

    @property
    def tokens_per_second(self) -> Optional[float]:
        """Generation speed from the first token (reasoning or answer) to the end; the number that matters
        most for local models."""
        first = self._first_token_s if self._first_token_s is not None else self.first_output_s
        if not self.completion_tokens or self.duration_s is None or first is None:
            return None
        generating = self.duration_s - first
        return round(self.completion_tokens / generating, 1) if generating > 0 else None

    def to_dict(self) -> Dict[str, Any]:
        data = {k: v for k, v in asdict(self).items() if not k.startswith("_")}
        data["started_at"] = self.started_at.isoformat()
        data["tokens_per_second"] = self.tokens_per_second
        return data


class Base(DeclarativeBase):
    pass


class TraceRow(Base):
    __tablename__ = "task_traces"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    goal: Mapped[str] = mapped_column(Text)
    policy: Mapped[str] = mapped_column(String)
    route: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    execution_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    outcome: Mapped[str] = mapped_column(String, index=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_s: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    first_output_s: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    output_chars: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tokens_per_second: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    attempts: Mapped[str] = mapped_column(Text, default="[]")  # JSON
    permissions: Mapped[str] = mapped_column(Text, default="[]")  # JSON

    def to_dict(self) -> Dict[str, Any]:
        started = self.started_at if self.started_at.tzinfo else self.started_at.replace(tzinfo=timezone.utc)
        return {
            "id": self.id, "started_at": started.isoformat(), "goal": self.goal, "policy": self.policy,
            "route": self.route, "execution_type": self.execution_type, "model": self.model,
            "outcome": self.outcome, "error": self.error, "duration_s": self.duration_s,
            "first_output_s": self.first_output_s, "output_chars": self.output_chars,
            "prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens,
            "tokens_per_second": self.tokens_per_second,
            "attempts": json.loads(self.attempts), "permissions": json.loads(self.permissions),
        }


class TraceStore:
    """Saves and lists task traces. Saving never raises: a broken trace database must not fail a task."""

    def __init__(self, url: Optional[str] = None):
        self._url = url
        self._session = None

    def _sessions(self):
        if self._session is None:
            engine = create_engine(self._url or default_traces_url())
            Base.metadata.create_all(engine)
            self._session = sessionmaker(engine, expire_on_commit=False)
        return self._session

    def save(self, trace: TaskTrace) -> None:
        try:
            with self._sessions()() as s, s.begin():
                s.add(TraceRow(
                    id=trace.id, started_at=trace.started_at, goal=trace.goal[:GOAL_PREVIEW],
                    policy=trace.policy, route=trace.route, execution_type=trace.execution_type,
                    model=trace.model, outcome=trace.outcome, error=trace.error, duration_s=trace.duration_s,
                    first_output_s=trace.first_output_s, output_chars=trace.output_chars,
                    prompt_tokens=trace.prompt_tokens, completion_tokens=trace.completion_tokens,
                    tokens_per_second=trace.tokens_per_second,
                    attempts=json.dumps(trace.attempts), permissions=json.dumps(trace.permissions),
                ))
        except Exception as e:
            logger.warning(f"[Traces] Could not save trace {trace.id}: {e}")

    def recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._sessions()() as s:
            rows = s.scalars(select(TraceRow).order_by(TraceRow.started_at.desc()).limit(limit)).all()
            return [r.to_dict() for r in rows]
