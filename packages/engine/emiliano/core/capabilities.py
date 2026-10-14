"""
Capability and provider discovery definitions for Emiliano.
Distinguishes between Direct Model providers (Ollama, LiteLLM APIs)
and External Agent Harnesses (Claude Code, Codex, Antigravity, OpenCode).
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class ExecutionType(str, Enum):
    DIRECT_MODEL = "direct_model"
    AGENT_HARNESS = "agent_harness"


class CapabilityStatus(str, Enum):
    NOT_INSTALLED = "not_installed"
    UNAVAILABLE = "unavailable"
    UNAUTHENTICATED = "unauthenticated"
    READY = "ready"


class Capability(BaseModel):
    name: str
    display_name: str
    execution_type: ExecutionType
    status: CapabilityStatus = CapabilityStatus.UNAVAILABLE
    status_message: str = ""
    executable_path: Optional[str] = None
    version: Optional[str] = None
    available_models: List[str] = Field(default_factory=list)
    selected_model: Optional[str] = None
    priority: int = 100

    @property
    def is_usable(self) -> bool:
        return self.status == CapabilityStatus.READY
