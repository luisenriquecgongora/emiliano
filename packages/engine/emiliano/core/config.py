"""
Configuration manager for Emiliano.
Loads settings from emiliano.yaml, environment variables, or sensible defaults.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional
import yaml
from pydantic import BaseModel, Field


class SummarizationConfig(BaseModel):
    """Configuration for conversation summarization (Phase 1)."""
    enabled: bool = True  # Enable LLM-based summarization (vs simple truncation)
    strategy: str = "recursive"  # "recursive" | "simple"
    threshold_tokens: int = 8000  # Summarize when history exceeds this
    max_summary_tokens: int = 500  # Maximum tokens in generated summary


class PersistentContextConfig(BaseModel):
    """Configuration for persistent context files (Phase 1)."""
    enabled: bool = True  # Load persistent context files
    filenames: List[str] = Field(
        default_factory=lambda: ["EMILIANO.md", "CLAUDE.md", ".emiliano/context.md"]
    )  # Filenames to check for persistent context


class MetricsConfig(BaseModel):
    """Configuration for context metrics and logging (Phase 1)."""
    enabled: bool = True  # Collect context usage metrics
    log_truncation: bool = True  # Log when truncation occurs
    log_summarization: bool = True  # Log when summarization occurs


class ContextConfig(BaseModel):
    """Configuration for conversation context window management."""
    enabled: bool = True  # Enable automatic context management
    max_tokens: Optional[int] = None  # Override model's default limit (None = use model default)
    truncation_strategy: str = "sliding_window"  # "sliding_window" | "drop_middle"
    safety_margin: float = 0.85  # Use 85% of context window (0.0-1.0)
    reserve_tokens: int = 2000  # Tokens reserved for model response

    # Phase 1 features
    summarization: SummarizationConfig = Field(default_factory=SummarizationConfig)
    persistent: PersistentContextConfig = Field(default_factory=PersistentContextConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)


class ModelConfig(BaseModel):
    default_provider: str = "ollama"  # "ollama" | "anthropic" | "openai" | "deepseek" | "gemini"
    ollama_base_url: str = "http://localhost:11434"
    local_model: str = "qwen2.5-coder:32b"
    remote_model: str = "claude-opus-5-5"
    auto_start_ollama: bool = False
    ollama_timeout: float = 120.0
    fallback_chain: List[str] = Field(
        default_factory=lambda: [
            "ollama/qwen2.5-coder:32b",
            "deepseek/deepseek-chat",
            "anthropic/claude-opus-5-5",
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
    context: ContextConfig = Field(default_factory=ContextConfig)


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
