"""
Autonomous Scheduler & Execution Engine for Emiliano Routines.
Schedules, evaluates, and dispatches standing autonomous tasks,
enforces Trust Gates (Draft vs. Execute), and records executions.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("emiliano.routines")

from .cron_evaluator import get_next_cron_run
from .models import (
    ExecutionRecord,
    ExecutionStatus,
    Routine,
    StagedAction,
    StagedActionStatus,
    TriggerType,
)
from .store import RoutineStore


class RoutineScheduler:
    """Evaluates and dispatches standing routines across cron schedules, intervals, and webhooks."""

    def __init__(
        self,
        store: Optional[RoutineStore] = None,
        dispatcher: Optional[Any] = None,
        tick_interval_seconds: float = 2.0,
    ):
        self.store = store or RoutineStore()
        self.dispatcher = dispatcher
        self.tick_interval_seconds = tick_interval_seconds
        self._running = False
        self._loop_task: Optional[asyncio.Task] = None
        self._active_runs: Dict[str, asyncio.Task] = {}
        self.on_staged_action: Optional[Callable[[StagedAction], None]] = None

    def calculate_next_run(self, routine: Routine, from_timestamp: Optional[float] = None) -> Optional[float]:
        """Calculates next execution timestamp based on routine trigger config."""
        base_ts = from_timestamp if from_timestamp is not None else time.time()
        trigger = routine.trigger

        if trigger.type == TriggerType.CRON:
            if not trigger.cron_expression:
                return None
            try:
                return get_next_cron_run(trigger.cron_expression, after_timestamp=base_ts)
            except Exception as e:
                logger.error(f"Failed to calculate next cron run for routine {routine.id}: {e}")
                return None

        elif trigger.type == TriggerType.INTERVAL:
            if not trigger.interval_seconds or trigger.interval_seconds <= 0:
                return None
            return base_ts + trigger.interval_seconds

        elif trigger.type in (TriggerType.WEBHOOK, TriggerType.MANUAL):
            return None

        return None

    def schedule_routine(self, routine: Routine) -> Routine:
        """Computes next_run_at and persists routine."""
        if routine.enabled and routine.next_run_at is None:
            routine.next_run_at = self.calculate_next_run(routine)
        return self.store.save_routine(routine)

    async def start(self):
        """Starts the periodic background scheduler tick loop."""
        if self._running:
            return
        self._running = True
        logger.info("Starting Emiliano Routine Scheduler tick loop...")

        # Initialize missing next_run_at for enabled routines
        enabled_routines = self.store.list_routines(enabled_only=True)
        now = time.time()
        for r in enabled_routines:
            if r.next_run_at is None:
                r.next_run_at = self.calculate_next_run(r, from_timestamp=now)
                self.store.save_routine(r)

        self._loop_task = asyncio.create_task(self._tick_loop())

    async def stop(self):
        """Stops the scheduler and cancels in-flight ticks."""
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None
        logger.info("Routine Scheduler stopped.")

    async def _tick_loop(self):
        while self._running:
            try:
                await self._evaluate_due_routines()
            except Exception as e:
                logger.error(f"Error during routine scheduler tick: {e}")
            await asyncio.sleep(self.tick_interval_seconds)

    async def _evaluate_due_routines(self):
        now = time.time()
        routines = self.store.list_routines(enabled_only=True)

        for routine in routines:
            if routine.next_run_at is not None and routine.next_run_at <= now:
                # Routine is due!
                logger.info(f"Routine '{routine.name}' ({routine.id}) is due for execution.")
                task = asyncio.create_task(self.execute_routine(routine.id, trigger_type=routine.trigger.type))
                self._active_runs[f"{routine.id}_{int(now)}"] = task

    async def execute_routine(
        self,
        routine_id: str,
        trigger_type: TriggerType = TriggerType.MANUAL,
        override_inputs: Optional[Dict[str, Any]] = None,
    ) -> ExecutionRecord:
        """Executes a routine, checks approval boundaries, and updates execution records."""
        routine = self.store.get_routine(routine_id)
        if not routine:
            raise ValueError(f"Routine '{routine_id}' not found.")

        run_id = f"run_{uuid.uuid4().hex[:12]}"
        record = ExecutionRecord(
            id=run_id,
            routine_id=routine_id,
            trigger_type=trigger_type,
            status=ExecutionStatus.RUNNING,
            started_at=time.time(),
        )
        self.store.create_execution_record(record)

        start_time = time.time()
        staged_ids: List[str] = []
        status = ExecutionStatus.SUCCEEDED
        output_text = ""
        error_text: Optional[str] = None

        try:
            # 1. Check for bound skill or goal template
            goal = routine.render_goal(override_inputs)
            logger.info(f"Executing Routine '{routine.name}' [ID: {routine_id}, Run: {run_id}]: {goal}")

            # 2. Check Trust Gate: If routine defines approval boundaries for specific actions
            # We inspect if the goal or action requests side-effect operations
            for boundary in routine.approval_boundaries:
                if boundary.requires_human and boundary.draft_mode:
                    # Stage an action before external mutation
                    staged_id = f"stage_{uuid.uuid4().hex[:8]}"
                    staged = StagedAction(
                        id=staged_id,
                        routine_id=routine_id,
                        run_id=run_id,
                        action_type=boundary.action_type,
                        target=routine.inputs.get("target", "external_system"),
                        payload={"goal": goal, "inputs": {**routine.inputs, **(override_inputs or {})}},
                        status=StagedActionStatus.PENDING,
                        notes=boundary.description or f"Requires human approval before {boundary.action_type}",
                    )
                    self.store.create_staged_action(staged)
                    staged_ids.append(staged_id)
                    if self.on_staged_action:
                        self.on_staged_action(staged)

            if staged_ids:
                status = ExecutionStatus.AWAITING_APPROVAL
                output_text = f"Routine paused at Trust Gate. {len(staged_ids)} action(s) staged for approval."
                logger.info(output_text)
            else:
                # 3. Direct execution via Dispatcher if available, or direct agent
                if self.dispatcher:
                    res = await self.dispatcher.execute_task(
                        goal=goal,
                        policy="auto",
                    )
                    output_text = res[1] if isinstance(res, tuple) else str(res)
                else:
                    output_text = f"Simulated execution for goal: {goal}"

        except Exception as e:
            logger.error(f"Routine '{routine_id}' execution failed: {e}")
            status = ExecutionStatus.FAILED
            error_text = str(e)
            output_text = "Execution failed."

        duration = time.time() - start_time
        finished_at = time.time()

        # Update execution record
        self.store.update_execution_record(
            run_id=run_id,
            status=status,
            output=output_text,
            error=error_text,
            duration_s=round(duration, 3),
            finished_at=finished_at,
            staged_action_ids=staged_ids,
        )

        # Update routine schedule & stats
        next_run = self.calculate_next_run(routine, from_timestamp=finished_at)
        failures = 0 if status == ExecutionStatus.SUCCEEDED else routine.consecutive_failures + 1
        self.store.update_routine_schedule(
            routine_id=routine_id,
            last_run_at=start_time,
            next_run_at=next_run,
            failures=failures,
            increment_runs=True,
        )

        record.status = status
        record.output = output_text
        record.error = error_text
        record.duration_s = round(duration, 3)
        record.finished_at = finished_at
        record.staged_action_ids = staged_ids
        return record
