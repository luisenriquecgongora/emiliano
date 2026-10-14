"""
Configuration manager for Emiliano.
Loads settings from emiliano.yaml, environment variables, or sensible defaults.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional
import yaml
from pydantic import BaseModel, Field


class ModelConfig(BaseModel):
    default_provider: str = "ollama"  # "ollama" | "anthropic" | "openai" | "deepseek" | "gemini"
    ollama_base_url: str = "http://localhost:11434"
    local_model: str = "qwen2.5-coder:32b"
    remote_model: str = "claude-3-7-sonnet-20250219"
    auto_start_ollama: bool = False
    ollama_timeout: float = 120.0
    fallback_chain: List[str] = Field(
        default_factory=lambda: [
            "ollama/qwen2.5-coder:32b",
            "deepseek/deepseek-chat",
            "anthropic/claude-3-7-sonnet-20250219",
        ]
    )
    anthropic_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    deepseek_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None


class HarnessPathsConfig(BaseModel):
    claude_code_cmd: str = "claude"
    antigravity_cmd: str = "agy"
    opencode_cmd: str = "opencode"
    codex_cmd: str = "codex"


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8765
    mutex_port: int = 51838


class EmilianoConfig(BaseModel):
    execution_policy: str = "auto"  # "auto" | "harness" | "local" | "api"
    preferred_harness: Optional[str] = None
    models: ModelConfig = Field(default_factory=ModelConfig)
    harnesses: HarnessPathsConfig = Field(default_factory=HarnessPathsConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)


def get_default_config_path() -> Path:
    # Look in working directory, or ~/.emiliano/config.yaml
    local_path = Path("emiliano.yaml")
    if local_path.exists():
        return local_path
    user_home_path = Path.home() / ".emiliano" / "config.yaml"
    return user_home_path


def load_config(custom_path: Optional[str] = None) -> EmilianoConfig:
    config_file = Path(custom_path) if custom_path else get_default_config_path()
    if config_file.exists():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                return EmilianoConfig(**data)
        except Exception as e:
            print(f"[Warning] Failed to load config from {config_file}: {e}. Using defaults.")
    return EmilianoConfig()


def save_default_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cfg = EmilianoConfig()
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(cfg.model_dump(), f, default_flow_style=False)
