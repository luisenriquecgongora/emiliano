"""
SQLite Persistence Store for Emiliano Routines, Execution History,
and Staged Approval Actions.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, List, Optional

from .models import (
    ApprovalBoundary,
    ExecutionRecord,
    ExecutionStatus,
    Routine,
    StagedAction,
    StagedActionStatus,
    TriggerConfig,
    TriggerType,
)


class RoutineStore:
    """Manages routines, runs, and staged trust-gate actions in a local SQLite database."""

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            base_dir = Path.home() / ".emiliano"
            base_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = base_dir / "routines.db"
        else:
            self.db_path = Path(db_path)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS routines (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    bot_persona TEXT NOT NULL,
                    skill_id TEXT,
                    goal_template TEXT,
                    inputs_json TEXT,
                    trigger_json TEXT NOT NULL,
                    approval_boundaries_json TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_run_at REAL,
                    next_run_at REAL,
                    total_runs INTEGER DEFAULT 0,
                    consecutive_failures INTEGER DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS execution_records (
                    id TEXT PRIMARY KEY,
                    routine_id TEXT NOT NULL,
                    trigger_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at REAL NOT NULL,
                    finished_at REAL,
                    output TEXT,
                    error TEXT,
                    duration_s REAL,
                    staged_action_ids_json TEXT,
                    FOREIGN KEY(routine_id) REFERENCES routines(id) ON DELETE CASCADE
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS staged_actions (
                    id TEXT PRIMARY KEY,
                    routine_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    target TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    resolved_at REAL,
                    notes TEXT,
                    FOREIGN KEY(routine_id) REFERENCES routines(id) ON DELETE CASCADE,
                    FOREIGN KEY(run_id) REFERENCES execution_records(id) ON DELETE CASCADE
                )
            """)
            conn.commit()

    def save_routine(self, routine: Routine) -> Routine:
        routine.updated_at = time.time()
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO routines (
                    id, name, description, bot_persona, skill_id, goal_template,
                    inputs_json, trigger_json, approval_boundaries_json,
                    enabled, last_run_at, next_run_at, total_runs, consecutive_failures,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                routine.id,
                routine.name,
                routine.description,
                routine.bot_persona,
                routine.skill_id,
                routine.goal_template,
                json.dumps(routine.inputs),
                routine.trigger.model_dump_json(),
                json.dumps([b.model_dump() for b in routine.approval_boundaries]),
                1 if routine.enabled else 0,
                routine.last_run_at,
                routine.next_run_at,
                routine.total_runs,
                routine.consecutive_failures,
                routine.created_at,
                routine.updated_at,
            ))
            conn.commit()
        return routine

    def get_routine(self, routine_id: str) -> Optional[Routine]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM routines WHERE id = ?", (routine_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_routine(row)

    def list_routines(self, enabled_only: bool = False) -> List[Routine]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            if enabled_only:
                cursor.execute("SELECT * FROM routines WHERE enabled = 1 ORDER BY created_at DESC")
            else:
                cursor.execute("SELECT * FROM routines ORDER BY created_at DESC")
            rows = cursor.fetchall()
            return [self._row_to_routine(r) for r in rows]

    def delete_routine(self, routine_id: str) -> bool:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM routines WHERE id = ?", (routine_id,))
            deleted = cursor.rowcount > 0
            conn.commit()
            return deleted

    def update_routine_schedule(
        self,
        routine_id: str,
        last_run_at: float,
        next_run_at: Optional[float],
        failures: int = 0,
        increment_runs: bool = True,
    ):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE routines SET
                    last_run_at = ?,
                    next_run_at = ?,
                    total_runs = total_runs + ?,
                    consecutive_failures = ?,
                    updated_at = ?
                WHERE id = ?
            """, (
                last_run_at,
                next_run_at,
                1 if increment_runs else 0,
                failures,
                time.time(),
                routine_id,
            ))
            conn.commit()

    def create_execution_record(self, record: ExecutionRecord) -> ExecutionRecord:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO execution_records (
                    id, routine_id, trigger_type, status, started_at,
                    finished_at, output, error, duration_s, staged_action_ids_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.id,
                record.routine_id,
                record.trigger_type.value,
                record.status.value,
                record.started_at,
                record.finished_at,
                record.output,
                record.error,
                record.duration_s,
                json.dumps(record.staged_action_ids),
            ))
            conn.commit()
        return record

    def update_execution_record(
        self,
        run_id: str,
        status: ExecutionStatus,
        output: Optional[str] = None,
        error: Optional[str] = None,
        duration_s: Optional[float] = None,
        finished_at: Optional[float] = None,
        staged_action_ids: Optional[List[str]] = None,
    ):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            fields = ["status = ?"]
            vals: List[Any] = [status.value]

            if output is not None:
                fields.append("output = ?")
                vals.append(output)
            if error is not None:
                fields.append("error = ?")
                vals.append(error)
            if duration_s is not None:
                fields.append("duration_s = ?")
                vals.append(duration_s)
            if finished_at is not None:
                fields.append("finished_at = ?")
                vals.append(finished_at)
            if staged_action_ids is not None:
                fields.append("staged_action_ids_json = ?")
                vals.append(json.dumps(staged_action_ids))

            vals.append(run_id)
            query = f"UPDATE execution_records SET {', '.join(fields)} WHERE id = ?"
            cursor.execute(query, tuple(vals))
            conn.commit()

    def get_execution_record(self, run_id: str) -> Optional[ExecutionRecord]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM execution_records WHERE id = ?", (run_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_execution_record(row)

    def list_execution_records(self, routine_id: Optional[str] = None, limit: int = 50) -> List[ExecutionRecord]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            if routine_id:
                cursor.execute(
                    "SELECT * FROM execution_records WHERE routine_id = ? ORDER BY started_at DESC LIMIT ?",
                    (routine_id, limit),
                )
            else:
                cursor.execute(
                    "SELECT * FROM execution_records ORDER BY started_at DESC LIMIT ?",
                    (limit,),
                )
            rows = cursor.fetchall()
            return [self._row_to_execution_record(r) for r in rows]

    def create_staged_action(self, action: StagedAction) -> StagedAction:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO staged_actions (
                    id, routine_id, run_id, action_type, target,
                    payload_json, status, created_at, resolved_at, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                action.id,
                action.routine_id,
                action.run_id,
                action.action_type,
                action.target,
                json.dumps(action.payload),
                action.status.value,
                action.created_at,
                action.resolved_at,
                action.notes,
            ))
            conn.commit()
        return action

    def resolve_staged_action(
        self,
        action_id: str,
        status: StagedActionStatus,
        notes: Optional[str] = None,
    ) -> Optional[StagedAction]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE staged_actions SET
                    status = ?,
                    resolved_at = ?,
                    notes = ?
                WHERE id = ?
            """, (status.value, time.time(), notes, action_id))
            conn.commit()
        return self.get_staged_action(action_id)

    def get_staged_action(self, action_id: str) -> Optional[StagedAction]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM staged_actions WHERE id = ?", (action_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_staged_action(row)

    def list_staged_actions(
        self,
        status: Optional[StagedActionStatus] = None,
        routine_id: Optional[str] = None,
    ) -> List[StagedAction]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            conditions = []
            vals = []
            if status is not None:
                conditions.append("status = ?")
                vals.append(status.value)
            if routine_id is not None:
                conditions.append("routine_id = ?")
                vals.append(routine_id)

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            cursor.execute(f"SELECT * FROM staged_actions {where_clause} ORDER BY created_at DESC", tuple(vals))
            rows = cursor.fetchall()
            return [self._row_to_staged_action(r) for r in rows]

    def _row_to_routine(self, row: sqlite3.Row) -> Routine:
        inputs = json.loads(row["inputs_json"]) if row["inputs_json"] else {}
        trigger = TriggerConfig.model_validate_json(row["trigger_json"])
        raw_boundaries = json.loads(row["approval_boundaries_json"]) if row["approval_boundaries_json"] else []
        boundaries = [ApprovalBoundary.model_validate(b) for b in raw_boundaries]

        return Routine(
            id=row["id"],
            name=row["name"],
            description=row["description"] or "",
            bot_persona=row["bot_persona"],
            skill_id=row["skill_id"],
            goal_template=row["goal_template"],
            inputs=inputs,
            trigger=trigger,
            approval_boundaries=boundaries,
            enabled=bool(row["enabled"]),
            last_run_at=row["last_run_at"],
            next_run_at=row["next_run_at"],
            total_runs=row["total_runs"] or 0,
            consecutive_failures=row["consecutive_failures"] or 0,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_execution_record(self, row: sqlite3.Row) -> ExecutionRecord:
        staged_ids = json.loads(row["staged_action_ids_json"]) if row["staged_action_ids_json"] else []
        return ExecutionRecord(
            id=row["id"],
            routine_id=row["routine_id"],
            trigger_type=TriggerType(row["trigger_type"]),
            status=ExecutionStatus(row["status"]),
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            output=row["output"],
            error=row["error"],
            duration_s=row["duration_s"],
            staged_action_ids=staged_ids,
        )

    def _row_to_staged_action(self, row: sqlite3.Row) -> StagedAction:
        payload = json.loads(row["payload_json"]) if row["payload_json"] else {}
        return StagedAction(
            id=row["id"],
            routine_id=row["routine_id"],
            run_id=row["run_id"],
            action_type=row["action_type"],
            target=row["target"],
            payload=payload,
            status=StagedActionStatus(row["status"]),
            created_at=row["created_at"],
            resolved_at=row["resolved_at"],
            notes=row["notes"],
        )
