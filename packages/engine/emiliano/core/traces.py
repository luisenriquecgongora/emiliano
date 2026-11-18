"""
Task traces & OpenTelemetry Distributed Spans:
Records executed tasks and granular execution spans in a local SQLite database
(~/.emiliano/traces.db by default, or EMILIANO_TRACES_DB).

Features:
- TaskTrace: Course-grained task outcome, duration, routing path, token metrics, permissions.
- TraceSpan: Fine-grained OpenTelemetry-compatible span recording for LLM calls, tool execution,
  context pruning, and guardrail validations adhering to OpenTelemetry GenAI Semantic Conventions.
- TraceStore: Local persistence, recent trace lookup, and telemetry metric aggregation (p50/p95/p99 latency,
  token efficiency, guardrail block rate).
"""

from __future__ import annotations

import json
import math
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
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
class TraceSpan:
    """
    Fine-grained execution span (e.g. llm.generate, tool.execute, guardrail.check).
    Adheres to OpenTelemetry GenAI and Tracing semantic conventions.
    """

    name: str
    trace_id: str
    span_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    parent_span_id: Optional[str] = None
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    duration_ms: Optional[float] = None
    status: str = "ok"  # "ok" | "error"
    error: Optional[str] = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)
    _t0: float = field(default_factory=time.monotonic, repr=False)

    def finish(self, status: str = "ok", error: Optional[str] = None) -> None:
        """Closes the span and calculates duration."""
        self.status = status
        if error:
            self.error = str(error)[:1000]
        self.end_time = time.time()
        self.duration_ms = round((time.monotonic() - self._t0) * 1000, 2)

    def add_event(self, name: str, attributes: Optional[Dict[str, Any]] = None) -> None:
        """Adds a timed event annotation to the span."""
        self.events.append({
            "name": name,
            "timestamp": time.time(),
            "attributes": attributes or {},
        })

    def set_attribute(self, key: str, value: Any) -> None:
        """Sets a span attribute."""
        self.attributes[key] = value

    def to_dict(self) -> Dict[str, Any]:
        data = {k: v for k, v in asdict(self).items() if not k.startswith("_")}
        return data

    def to_otel_span(self) -> Dict[str, Any]:
        """
        Maps span to OpenTelemetry Semantic Conventions for Generative AI.
        """
        otel_attrs = dict(self.attributes)
        if self.name.startswith("llm."):
            model = str(self.attributes.get("model", ""))
            system = "openai" if any(k in model for k in ["gpt", "o1", "o3"]) else "custom"
            otel_attrs.setdefault("gen_ai.system", system)
            if "model" in self.attributes:
                otel_attrs["gen_ai.request.model"] = self.attributes["model"]
            if "prompt_tokens" in self.attributes:
                otel_attrs["gen_ai.usage.input_tokens"] = self.attributes["prompt_tokens"]
            if "completion_tokens" in self.attributes:
                otel_attrs["gen_ai.usage.output_tokens"] = self.attributes["completion_tokens"]
            if "cached_tokens" in self.attributes:
                otel_attrs["gen_ai.usage.cached_tokens"] = self.attributes["cached_tokens"]
            if "first_output_s" in self.attributes:
                otel_attrs["gen_ai.server.time_to_first_token_s"] = self.attributes["first_output_s"]
        elif self.name.startswith("tool."):
            if "tool_name" in self.attributes:
                otel_attrs["gen_ai.tool.name"] = self.attributes["tool_name"]

        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "start_time_unix_nano": int(self.start_time * 1e9),
            "end_time_unix_nano": int((self.end_time or time.time()) * 1e9),
            "status": {"code": 1 if self.status == "ok" else 2, "description": self.error or ""},
            "attributes": otel_attrs,
            "events": self.events,
        }


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
    cached_tokens: Optional[int] = None  # prompt tokens served from provider cache (50% discount)
    permissions: List[Dict[str, Any]] = field(default_factory=list)  # tool, decision
    spans: List[TraceSpan] = field(default_factory=list)  # fine-grained execution spans
    guardrails: List[Dict[str, Any]] = field(default_factory=list)  # guardrail verdicts and events
    executed_tools: List[Dict[str, Any]] = field(default_factory=list)  # structured tool calls & MCP receipts
    _t0: float = field(default_factory=time.monotonic, repr=False)
    _first_token_s: Optional[float] = field(default=None, repr=False)  # first token of any kind, reasoning included

    def start_span(
        self,
        name: str,
        parent_span_id: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> TraceSpan:
        """Creates, registers, and returns a new span belonging to this task trace."""
        span = TraceSpan(
            name=name,
            trace_id=self.id,
            parent_span_id=parent_span_id,
            attributes=attributes or {},
        )
        self.spans.append(span)
        return span

    def record_guardrail(self, verdict: Any) -> None:
        """Records a guardrail check verdict."""
        if hasattr(verdict, "to_dict"):
            self.guardrails.append(verdict.to_dict())
        elif isinstance(verdict, dict):
            self.guardrails.append(verdict)

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
    def duration_seconds(self) -> Optional[float]:
        """Alias for duration_s for backward compatibility with blackboard/dispatcher."""
        return self.duration_s

    @property
    def tokens_per_second(self) -> Optional[float]:
        """Generation speed from the first token (reasoning or answer) to the end."""
        first = self._first_token_s if self._first_token_s is not None else self.first_output_s
        if not self.completion_tokens or self.duration_s is None or first is None:
            return None
        generating = self.duration_s - first
        return round(self.completion_tokens / generating, 1) if generating > 0 else None

    def to_dict(self) -> Dict[str, Any]:
        data = {k: v for k, v in asdict(self).items() if not k.startswith("_")}
        data["started_at"] = self.started_at.isoformat()
        data["tokens_per_second"] = self.tokens_per_second
        data["spans"] = [s.to_dict() if hasattr(s, "to_dict") else s for s in self.spans]
        data["guardrails"] = self.guardrails
        return data

    def to_otel_trace(self) -> Dict[str, Any]:
        """Exports the trace and all nested spans in OpenTelemetry format."""
        return {
            "resource": {"service.name": "emiliano", "service.version": "0.1.0"},
            "trace_id": self.id,
            "goal": self.goal[:GOAL_PREVIEW],
            "outcome": self.outcome,
            "duration_s": self.duration_s,
            "spans": [s.to_otel_span() for s in self.spans],
            "guardrail_events": self.guardrails,
        }


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
    cached_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tokens_per_second: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    attempts: Mapped[str] = mapped_column(Text, default="[]")  # JSON
    permissions: Mapped[str] = mapped_column(Text, default="[]")  # JSON
    spans: Mapped[str] = mapped_column(Text, default="[]")  # JSON
    guardrails: Mapped[str] = mapped_column(Text, default="[]")  # JSON

    def to_dict(self) -> Dict[str, Any]:
        started = self.started_at if self.started_at.tzinfo else self.started_at.replace(tzinfo=timezone.utc)
        return {
            "id": self.id, "started_at": started.isoformat(), "goal": self.goal, "policy": self.policy,
            "route": self.route, "execution_type": self.execution_type, "model": self.model,
            "outcome": self.outcome, "error": self.error, "duration_s": self.duration_s,
            "first_output_s": self.first_output_s, "output_chars": self.output_chars,
            "prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens,
            "cached_tokens": self.cached_tokens,
            "tokens_per_second": self.tokens_per_second,
            "attempts": json.loads(self.attempts) if self.attempts else [],
            "permissions": json.loads(self.permissions) if self.permissions else [],
            "spans": json.loads(self.spans) if self.spans else [],
            "guardrails": json.loads(self.guardrails) if self.guardrails else [],
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
            # Ensure new columns exist if running on an older SQLite schema
            self._ensure_schema(engine)
            self._session = sessionmaker(engine, expire_on_commit=False)
        return self._session

    def _ensure_schema(self, engine) -> None:
        """Adds missing columns to SQLite table if upgrading an existing db."""
        try:
            with engine.connect() as conn:
                res = conn.exec_driver_sql("PRAGMA table_info(task_traces);")
                existing_cols = {row[1] for row in res.fetchall()}
                if "spans" not in existing_cols:
                    conn.exec_driver_sql("ALTER TABLE task_traces ADD COLUMN spans TEXT DEFAULT '[]';")
                if "guardrails" not in existing_cols:
                    conn.exec_driver_sql("ALTER TABLE task_traces ADD COLUMN guardrails TEXT DEFAULT '[]';")
                if "cached_tokens" not in existing_cols:
                    conn.exec_driver_sql("ALTER TABLE task_traces ADD COLUMN cached_tokens INTEGER;")
                conn.commit()
        except Exception:
            pass

    def save(self, trace: TaskTrace) -> None:
        try:
            spans_json = json.dumps([s.to_dict() if hasattr(s, "to_dict") else s for s in trace.spans])
            guardrails_json = json.dumps(trace.guardrails)
            with self._sessions()() as s, s.begin():
                s.add(TraceRow(
                    id=trace.id, started_at=trace.started_at, goal=trace.goal[:GOAL_PREVIEW],
                    policy=trace.policy, route=trace.route, execution_type=trace.execution_type,
                    model=trace.model, outcome=trace.outcome, error=trace.error, duration_s=trace.duration_s,
                    first_output_s=trace.first_output_s, output_chars=trace.output_chars,
                    prompt_tokens=trace.prompt_tokens, completion_tokens=trace.completion_tokens,
                    cached_tokens=trace.cached_tokens,
                    tokens_per_second=trace.tokens_per_second,
                    attempts=json.dumps(trace.attempts), permissions=json.dumps(trace.permissions),
                    spans=spans_json, guardrails=guardrails_json,
                ))
        except Exception as e:
            logger.warning(f"[Traces] Could not save trace {trace.id}: {e}")

    def recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._sessions()() as s:
            rows = s.scalars(select(TraceRow).order_by(TraceRow.started_at.desc()).limit(limit)).all()
            return [r.to_dict() for r in rows]

    def get_telemetry_metrics(self, hours: int = 24) -> Dict[str, Any]:
        """
        Calculates aggregate operational metrics: p50/p95/p99 latency, token consumption,
        success rate, and guardrail block counts.
        """
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        with self._sessions()() as s:
            rows = s.scalars(select(TraceRow).where(TraceRow.started_at >= since)).all()

        if not rows:
            return {
                "window_hours": hours,
                "total_tasks": 0,
                "success_rate": 0.0,
                "p50_latency_s": None,
                "p95_latency_s": None,
                "p99_latency_s": None,
                "avg_first_output_s": None,
                "total_prompt_tokens": 0,
                "total_completion_tokens": 0,
                "total_cached_tokens": 0,
                "cache_hit_ratio": 0.0,
                "guardrail_blocked_count": 0,
                "models_breakdown": {},
                "routes_breakdown": {},
            }

        total_tasks = len(rows)
        succeeded = sum(1 for r in rows if r.outcome == "succeeded")
        success_rate = round(succeeded / total_tasks, 3)

        durations = sorted([r.duration_s for r in rows if r.duration_s is not None])
        p50 = durations[math.floor(0.50 * len(durations))] if durations else None
        p95 = durations[math.floor(0.95 * len(durations))] if durations else None
        p99 = durations[math.floor(0.99 * len(durations))] if durations else None

        first_outputs = [r.first_output_s for r in rows if r.first_output_s is not None]
        avg_first_output = round(sum(first_outputs) / len(first_outputs), 3) if first_outputs else None

        total_prompt_tokens = sum(r.prompt_tokens or 0 for r in rows)
        total_completion_tokens = sum(r.completion_tokens or 0 for r in rows)
        total_cached_tokens = sum(r.cached_tokens or 0 for r in rows)
        cache_hit_ratio = round(total_cached_tokens / total_prompt_tokens, 3) if total_prompt_tokens > 0 else 0.0

        models: Dict[str, int] = {}
        routes: Dict[str, int] = {}
        blocked_count = 0

        for r in rows:
            if r.model:
                models[r.model] = models.get(r.model, 0) + 1
            if r.route:
                routes[r.route] = routes.get(r.route, 0) + 1
            try:
                gr = json.loads(r.guardrails) if r.guardrails else []
                blocked_count += sum(1 for g in gr if not g.get("allowed", True))
            except Exception:
                pass

        return {
            "window_hours": hours,
            "total_tasks": total_tasks,
            "success_rate": success_rate,
            "p50_latency_s": p50,
            "p95_latency_s": p95,
            "p99_latency_s": p99,
            "avg_first_output_s": avg_first_output,
            "total_prompt_tokens": total_prompt_tokens,
            "total_completion_tokens": total_completion_tokens,
            "total_cached_tokens": total_cached_tokens,
            "cache_hit_ratio": cache_hit_ratio,
            "guardrail_blocked_count": blocked_count,
            "models_breakdown": models,
            "routes_breakdown": routes,
        }
