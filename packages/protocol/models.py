"""
Pydantic v2 Models mirroring @emiliano/protocol contracts.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class HarnessType(str, Enum):
    AUTO = "auto"
    DIRECT = "direct"
    CLAUDE_CODE = "claude_code"
    ANTIGRAVITY = "antigravity"
    OPENCODE = "opencode"
    CODEX = "codex"
    COWORK = "cowork"
    MCP = "mcp"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class BoundingBox(BaseModel):
    x: float
    y: float
    width: float
    height: float


class UIElementTarget(BaseModel):
    id: Optional[str] = None
    name: str
    role: Optional[str] = None
    bounds: BoundingBox
    confidence: Optional[float] = 1.0
    action: Literal["click", "double_click", "right_click", "type", "hover", "scroll"] = "click"


class DAGStep(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    status: TaskStatus = TaskStatus.PENDING
    assignedHarness: HarnessType = HarnessType.AUTO
    dependencies: List[str] = Field(default_factory=list)
    output: Optional[str] = None
    error: Optional[str] = None


class ModelConfigPayload(BaseModel):
    provider: Optional[str] = "ollama"
    modelName: Optional[str] = "qwen2.5-coder:32b"
    temperature: Optional[float] = 0.2
    fallbackChain: List[str] = Field(default_factory=list)


class TaskDefinition(BaseModel):
    id: str
    goal: str
    harnessPreference: HarnessType = HarnessType.AUTO
    modelConfig: Optional[ModelConfigPayload] = None
    steps: List[DAGStep] = Field(default_factory=list)
    currentStepId: Optional[str] = None
    status: TaskStatus = TaskStatus.PENDING
    createdAt: str
    updatedAt: str


# WebSocket Message Models
class TaskStartPayload(BaseModel):
    taskId: Optional[str] = None
    goal: str
    harnessPreference: Optional[HarnessType] = HarnessType.AUTO
    localModel: Optional[str] = None
    remoteModel: Optional[str] = None


class HUDHighlightPayload(BaseModel):
    element: UIElementTarget
    reasoning: str
    durationMs: Optional[int] = 2000


class ThoughtStreamPayload(BaseModel):
    stepId: Optional[str] = None
    chunk: str
    harness: HarnessType


class ApprovalRequestPayload(BaseModel):
    requestId: str
    title: str
    description: str
    dangerous: bool = False
    actionType: str


class ApprovalResponsePayload(BaseModel):
    requestId: str
    approved: bool
    feedback: Optional[str] = None
