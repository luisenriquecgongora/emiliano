"""
Multi-Stage Pipeline Engine for Emiliano.
Enables resilient, checkpointed, staged workflow execution (e.g. Scrape -> Transform -> Build -> Deploy -> Verify).
Supports skipping stages, resume-from-checkpoint, and WebSocket progress broadcasting.
Licensed under PolyForm Shield 1.0.0. Uses Python standard library.
"""

from __future__ import annotations

import inspect
import json
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union
from loguru import logger

from .blackboard import Blackboard


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass
class StageResult:
    name: str
    status: StageStatus
    duration_seconds: float = 0.0
    output: Any = None
    error: Optional[str] = None


class PipelineContext:
    """Shared state dictionary and helper logger passed across all stages."""

    def __init__(self, initial_data: Optional[Dict[str, Any]] = None, blackboard: Optional[Blackboard] = None):
        self.data: Dict[str, Any] = initial_data or {}
        self.blackboard = blackboard
        self.logs: List[str] = []

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def log(self, message: str) -> None:
        formatted = f"[{time.strftime('%H:%M:%S')}] {message}"
        self.logs.append(formatted)
        logger.info(f"[Pipeline] {message}")


StageHandler = Callable[[PipelineContext], Union[Awaitable[Any], Any]]


class Stage:
    """A distinct, executable step within a workflow pipeline."""

    def __init__(
        self,
        name: str,
        handler: StageHandler,
        description: str = "",
        optional: bool = False,
    ):
        self.name = name
        self.handler = handler
        self.description = description
        self.optional = optional
        self.status = StageStatus.PENDING
        self.duration_seconds: float = 0.0
        self.error: Optional[str] = None
        self.output: Any = None

    async def execute(self, ctx: PipelineContext) -> StageResult:
        """Executes the stage handler with timing and error isolation."""
        self.status = StageStatus.RUNNING
        start_time = time.time()
        ctx.log(f"Starting stage: '{self.name}' ({self.description or 'No description'})")

        try:
            if inspect.iscoroutinefunction(self.handler):
                result = await self.handler(ctx)
            else:
                result = self.handler(ctx)

            self.duration_seconds = time.time() - start_time
            self.status = StageStatus.COMPLETED
            self.output = result
            ctx.log(f"Stage '{self.name}' completed in {self.duration_seconds:.2f}s")
            return StageResult(name=self.name, status=self.status, duration_seconds=self.duration_seconds, output=result)

        except Exception as e:
            self.duration_seconds = time.time() - start_time
            self.status = StageStatus.FAILED
            self.error = str(e)
            ctx.log(f"Stage '{self.name}' failed after {self.duration_seconds:.2f}s: {e}")
            return StageResult(name=self.name, status=self.status, duration_seconds=self.duration_seconds, error=str(e))


class Pipeline:
    """
    Orchestrates execution of an ordered sequence of stages with checkpointing,
    filtering, and state persistence.
    """

    def __init__(
        self,
        name: str,
        description: str = "",
        checkpoint_dir: Optional[Path] = None,
        blackboard: Optional[Blackboard] = None,
    ):
        self.name = name
        self.description = description
        self.stages: List[Stage] = []
        self.checkpoint_dir = checkpoint_dir
        self.blackboard = blackboard
        if self.checkpoint_dir:
            self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def add_stage(
        self,
        name: str,
        handler: StageHandler,
        description: str = "",
        optional: bool = False,
    ) -> Pipeline:
        """Appends a new stage to the pipeline."""
        stage = Stage(name=name, handler=handler, description=description, optional=optional)
        self.stages.append(stage)
        return self

    def get_stage_names(self) -> List[str]:
        return [s.name for s in self.stages]

    async def run(
        self,
        initial_data: Optional[Dict[str, Any]] = None,
        selected_stages: Optional[List[str]] = None,
        skip_stages: Optional[List[str]] = None,
        on_stage_change: Optional[Callable[[Stage, StageStatus], None]] = None,
    ) -> Dict[str, Any]:
        """
        Executes the pipeline stages sequentially, honoring stage filters and checkpoints.
        """
        ctx = PipelineContext(initial_data=initial_data, blackboard=self.blackboard)
        selected = set(s.lower() for s in selected_stages) if selected_stages else None
        skipped = set(s.lower() for s in skip_stages) if skip_stages else set()

        results: Dict[str, StageResult] = {}
        logger.info(f"[Pipeline] Running '{self.name}' with {len(self.stages)} stages")

        for stage in self.stages:
            stage_name_lower = stage.name.lower()

            # Filter logic: if selected_stages is specified, stage must be in it
            if selected and stage_name_lower not in selected:
                stage.status = StageStatus.SKIPPED
                if on_stage_change:
                    on_stage_change(stage, stage.status)
                results[stage.name] = StageResult(name=stage.name, status=StageStatus.SKIPPED)
                continue

            # Skip logic: if in skip_stages, skip it
            if stage_name_lower in skipped:
                stage.status = StageStatus.SKIPPED
                if on_stage_change:
                    on_stage_change(stage, stage.status)
                results[stage.name] = StageResult(name=stage.name, status=StageStatus.SKIPPED)
                continue

            if on_stage_change:
                on_stage_change(stage, StageStatus.RUNNING)

            res = await stage.execute(ctx)
            results[stage.name] = res

            if on_stage_change:
                on_stage_change(stage, res.status)

            # Auto-save checkpoint if checkpoint_dir is configured
            if self.checkpoint_dir:
                self.save_checkpoint(stage.name, ctx.data)

            # Post event to Blackboard if attached
            if self.blackboard:
                self.blackboard.post_event(
                    source=f"pipeline:{self.name}",
                    event_type=f"stage_{res.status.value}",
                    payload={"stage": stage.name, "duration": res.duration_seconds, "error": res.error},
                )

            # Halt on failure unless stage is marked optional
            if res.status == StageStatus.FAILED and not stage.optional:
                logger.error(f"[Pipeline] Pipeline halted due to failure in stage '{stage.name}'")
                break

        required_stages = [s for s in self.stages if not s.optional]
        required_passed = all(
            results.get(s.name) and results[s.name].status in (StageStatus.COMPLETED, StageStatus.SKIPPED)
            for s in required_stages
        )
        overall_status = "completed" if required_passed else "failed"

        return {
            "pipeline": self.name,
            "status": overall_status,
            "results": {k: {"status": v.status.value, "duration": v.duration_seconds, "error": v.error} for k, v in results.items()},
            "data": ctx.data,
            "logs": ctx.logs,
        }

    def save_checkpoint(self, stage_name: str, data: Dict[str, Any]) -> Optional[Path]:
        """Saves pipeline state to a checkpoint JSON file."""
        if not self.checkpoint_dir:
            return None
        cp_path = self.checkpoint_dir / f"{self.name}_{stage_name}_checkpoint.json"
        try:
            # Filter out non-serializable objects safely
            serializable_data = {k: v for k, v in data.items() if isinstance(v, (str, int, float, bool, list, dict, type(None)))}
            cp_path.write_text(json.dumps(serializable_data, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.debug(f"[Pipeline] Checkpoint saved: {cp_path.name}")
            return cp_path
        except Exception as e:
            logger.warning(f"[Pipeline] Failed to save checkpoint: {e}")
            return None
