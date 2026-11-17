"""
Pydantic Data Models for Emiliano Routines & Autonomous Automation.
Inspired by xAI Grok Bot's Skills vs. Routines decoupling,
and strict Trust Gates (Draft vs. Execute).
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class TriggerType(str, Enum):
    CRON = "cron"
    INTERVAL = "interval"
    WEBHOOK = "webhook"
    MANUAL = "manual"


class TriggerConfig(BaseModel):
    type: TriggerType = TriggerType.MANUAL
    cron_expression: Optional[str] = None  # e.g. "0 8 * * 1-5", "*/15 * * * *", "@daily"
    interval_seconds: Optional[int] = None  # e.g. 3600
    webhook_path: Optional[str] = None  # e.g. "/webhook/github-pr"
    secret: Optional[str] = None


class ApprovalBoundary(BaseModel):
    action_type: str  # e.g. "send_message", "make_payment", "delete_file", "deploy"
    requires_human: bool = True
    draft_mode: bool = True
    threshold: Optional[float] = None  # Optional numeric threshold
    description: Optional[str] = None


class ValidationRule(BaseModel):
    assertion: str
    on_failure: str = "abort"  # "abort", "retry", "notify"


class StagedActionStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"


class StagedAction(BaseModel):
    id: str
    routine_id: str
    run_id: str
    action_type: str
    target: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    status: StagedActionStatus = StagedActionStatus.PENDING
    created_at: float = Field(default_factory=time.time)
    resolved_at: Optional[float] = None
    notes: Optional[str] = None


class ExecutionStatus(str, Enum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    AWAITING_APPROVAL = "awaiting_approval"
    CANCELLED = "cancelled"


class ExecutionRecord(BaseModel):
    id: str
    routine_id: str
    trigger_type: TriggerType
    status: ExecutionStatus = ExecutionStatus.RUNNING
    started_at: float = Field(default_factory=time.time)
    finished_at: Optional[float] = None
    output: Optional[str] = None
    error: Optional[str] = None
    duration_s: Optional[float] = None
    staged_action_ids: List[str] = Field(default_factory=list)


class Routine(BaseModel):
    id: str
    name: str
    description: str = ""
    bot_persona: str = "emiliano"  # e.g. "emiliano", "browser", "researcher", "coder"
    skill_id: Optional[str] = None  # Bound skill from SkillManager
    goal_template: Optional[str] = None  # Prompt or goal template (interpolates inputs)
    inputs: Dict[str, Any] = Field(default_factory=dict)
    trigger: TriggerConfig = Field(default_factory=TriggerConfig)
    approval_boundaries: List[ApprovalBoundary] = Field(default_factory=list)
    enabled: bool = True
    last_run_at: Optional[float] = None
    next_run_at: Optional[float] = None
    total_runs: int = 0
    consecutive_failures: int = 0
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    def render_goal(self, extra_inputs: Optional[Dict[str, Any]] = None) -> str:
        """Renders goal template with inputs."""
        template = self.goal_template or ""
        merged = {**self.inputs, **(extra_inputs or {})}
        for k, v in merged.items():
            template = template.replace(f"{{{{{k}}}}}", str(v))
            template = template.replace(f"{{{{inputs.{k}}}}}", str(v))
        return template
