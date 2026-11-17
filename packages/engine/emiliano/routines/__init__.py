"""
Emiliano Routines & Autonomous Coworker Subsystem.
Implements standing cron/webhook triggers, decoupled skills vs. routines,
Teach-a-Task demonstration synthesis, and Trust Gate staging cards.
"""

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
from .scheduler import RoutineScheduler
from .store import RoutineStore
from .synthesizer import SkillSynthesizer
from .daemon import DaemonService, create_daemon_app

__all__ = [
    "ApprovalBoundary",
    "ExecutionRecord",
    "ExecutionStatus",
    "Routine",
    "StagedAction",
    "StagedActionStatus",
    "TriggerConfig",
    "TriggerType",
    "RoutineScheduler",
    "RoutineStore",
    "SkillSynthesizer",
    "DaemonService",
    "create_daemon_app",
]
