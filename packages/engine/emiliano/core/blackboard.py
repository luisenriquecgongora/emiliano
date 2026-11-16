"""
Unified Blackboard: Shared Persistent SQLite Memory Layer for Emiliano.
Implements inter-harness context exchange, event logging, entity tracking,
and long-horizon cross-session continuity.
Licensed under PolyForm Shield 1.0.0. Uses Python standard library (sqlite3, json).
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional
from loguru import logger

DEFAULT_BLACKBOARD_PATH = Path(os.path.expanduser("~/.emiliano/blackboard.db"))


class Blackboard:
    """
    Lightweight, thread-safe SQLite-backed memory store.
    Accessible by desktop cowork agents, harnesses, and direct models.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DEFAULT_BLACKBOARD_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        """Initializes database schema with WAL mode for fast concurrent reads/writes."""
        with self._get_connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS entities (
                    key TEXT PRIMARY KEY,
                    category TEXT NOT NULL DEFAULT 'general',
                    value_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    source TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL DEFAULT 'general',
                    subject TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    object_text TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS session_summaries (
                    session_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    metadata_json TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_entities_cat ON entities(category);
                CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
                CREATE INDEX IF NOT EXISTS idx_facts_cat ON facts(category);
                """
            )
            conn.commit()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    # -----------------------------------------------------------------------
    # Entity Storage (Key-Value with JSON values and category indexing)
    # -----------------------------------------------------------------------

    def set_entity(self, key: str, value: Any, category: str = "general") -> None:
        """Stores or updates an entity in the blackboard."""
        now = self._now()
        val_json = json.dumps(value, ensure_ascii=False)
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO entities (key, category, value_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    category=excluded.category,
                    value_json=excluded.value_json,
                    updated_at=excluded.updated_at
                """,
                (key, category, val_json, now, now),
            )
            conn.commit()
        logger.debug(f"[Blackboard] Set entity '{key}' in category '{category}'")

    def get_entity(self, key: str) -> Optional[Any]:
        """Retrieves an entity by key, deserializing from JSON."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT value_json FROM entities WHERE key = ?", (key,)).fetchone()
            if row:
                return json.loads(row["value_json"])
        return None

    def delete_entity(self, key: str) -> bool:
        """Deletes an entity by key."""
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM entities WHERE key = ?", (key,))
            conn.commit()
            return cursor.rowcount > 0

    def list_entities(self, category: Optional[str] = None) -> Dict[str, Any]:
        """Lists entities, optionally filtered by category."""
        results: Dict[str, Any] = {}
        with self._get_connection() as conn:
            if category:
                rows = conn.execute("SELECT key, value_json FROM entities WHERE category = ?", (category,)).fetchall()
            else:
                rows = conn.execute("SELECT key, value_json FROM entities").fetchall()

            for r in rows:
                results[r["key"]] = json.loads(r["value_json"])
        return results

    # -----------------------------------------------------------------------
    # Event Stream (Inter-Harness Notifications & Triggers)
    # -----------------------------------------------------------------------

    def post_event(self, source: str, event_type: str, payload: Any, session_id: Optional[str] = None) -> int:
        """Publishes an event to the blackboard event stream."""
        now = self._now()
        payload_str = json.dumps(payload, ensure_ascii=False)
        with self._get_connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO events (session_id, source, event_type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, source, event_type, payload_str, now),
            )
            conn.commit()
            return cur.lastrowid

    def get_events(self, limit: int = 50, event_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Reads recent events from the blackboard stream."""
        with self._get_connection() as conn:
            if event_type:
                rows = conn.execute(
                    "SELECT * FROM events WHERE event_type = ? ORDER BY id DESC LIMIT ?",
                    (event_type, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM events ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()

            events = []
            for r in rows:
                events.append({
                    "id": r["id"],
                    "session_id": r["session_id"],
                    "source": r["source"],
                    "event_type": r["event_type"],
                    "payload": json.loads(r["payload_json"]),
                    "created_at": r["created_at"],
                })
            return events

    # -----------------------------------------------------------------------
    # Long-Horizon Facts & Session Summaries
    # -----------------------------------------------------------------------

    def add_fact(self, category: str, subject: str, predicate: str, object_text: str) -> int:
        """Records a persistent declarative fact (e.g. 'instagram', 'PL-142', 'status', 'sent')."""
        now = self._now()
        with self._get_connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO facts (category, subject, predicate, object_text, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (category, subject, predicate, object_text, now),
            )
            conn.commit()
            return cur.lastrowid

    def query_facts(self, category: Optional[str] = None, subject: Optional[str] = None) -> List[Dict[str, Any]]:
        """Queries declarative facts."""
        with self._get_connection() as conn:
            query = "SELECT * FROM facts WHERE 1=1"
            params: List[Any] = []
            if category:
                query += " AND category = ?"
                params.append(category)
            if subject:
                query += " AND subject = ?"
                params.append(subject)
            query += " ORDER BY id DESC"

            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def record_session_summary(
        self,
        session_id: str,
        title: str,
        summary: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Stores a compacted session summary for cross-session continuity."""
        now = self._now()
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO session_summaries (session_id, title, summary, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    title=excluded.title,
                    summary=excluded.summary,
                    metadata_json=excluded.metadata_json,
                    created_at=excluded.created_at
                """,
                (session_id, title, summary, meta_json, now),
            )
            conn.commit()

    def get_last_session_summary(self) -> Optional[Dict[str, Any]]:
        """Returns the most recent compacted session summary."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM session_summaries ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if row:
                return {
                    "session_id": row["session_id"],
                    "title": row["title"],
                    "summary": row["summary"],
                    "metadata": json.loads(row["metadata_json"] or "{}"),
                    "created_at": row["created_at"],
                }
        return None

    def render_context_for_prompt(self) -> str:
        """
        Renders a concise, human-readable summary of active blackboard facts and entities
        suitable for automatic system prompt injection.
        """
        entities = self.list_entities()
        last_session = self.get_last_session_summary()

        parts = []
        if last_session:
            parts.append(f"### Previous Session Handoff ({last_session['title']}):\n{last_session['summary']}")

        if entities:
            parts.append("### Active Blackboard Entities:")
            for k, v in list(entities.items())[:15]:
                parts.append(f"- **{k}**: {v}")

        return "\n\n".join(parts) if parts else ""
