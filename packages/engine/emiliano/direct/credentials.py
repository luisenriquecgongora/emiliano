"""
Credential detection and validation for direct AI model providers.
Safely detects and redacts credentials without logging or exposing secrets.
"""

from __future__ import annotations

import os
from typing import Dict, Optional
from ..core.config import EmilianoConfig


def redact_key(key: Optional[str]) -> str:
    """Safely redact an API key, showing only a small prefix and suffix if long enough."""
    if not key:
        return "[not configured]"
    stripped = key.strip()
    if len(stripped) <= 8:
        return "[configured]"
    return f"{stripped[:4]}...{stripped[-4:]}"


class CredentialManager:
    """Inspects and manages provider API credentials securely."""

    def __init__(self, config: Optional[EmilianoConfig] = None):
        self.config = config

    def get_anthropic_key(self) -> Optional[str]:
        # Env var takes precedence, then config if present
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key and self.config and hasattr(self.config.models, "anthropic_api_key"):
            key = getattr(self.config.models, "anthropic_api_key", None)
        return key.strip() if key and key.strip() else None

    def get_openai_key(self) -> Optional[str]:
        key = os.environ.get("OPENAI_API_KEY")
        if not key and self.config and hasattr(self.config.models, "openai_api_key"):
            key = getattr(self.config.models, "openai_api_key", None)
        return key.strip() if key and key.strip() else None

    def get_deepseek_key(self) -> Optional[str]:
        key = os.environ.get("DEEPSEEK_API_KEY")
        if not key and self.config and hasattr(self.config.models, "deepseek_api_key"):
            key = getattr(self.config.models, "deepseek_api_key", None)
        return key.strip() if key and key.strip() else None

    def get_gemini_key(self) -> Optional[str]:
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key and self.config and hasattr(self.config.models, "gemini_api_key"):
            key = getattr(self.config.models, "gemini_api_key", None)
        return key.strip() if key and key.strip() else None

    def check_provider(self, provider_name: str) -> Dict[str, any]:
        """
        Returns credential status for a given provider without leaking the key.
        """
        p = provider_name.lower()
        key = None
        env_var = ""

        if "anthropic" in p or "claude" in p:
            key = self.get_anthropic_key()
            env_var = "ANTHROPIC_API_KEY"
        elif "openai" in p or "gpt" in p:
            key = self.get_openai_key()
            env_var = "OPENAI_API_KEY"
        elif "deepseek" in p:
            key = self.get_deepseek_key()
            env_var = "DEEPSEEK_API_KEY"
        elif "gemini" in p or "google" in p:
            key = self.get_gemini_key()
            env_var = "GEMINI_API_KEY"

        configured = bool(key and len(key) > 5)
        return {
            "provider": provider_name,
            "configured": configured,
            "env_var": env_var,
            "redacted_key": redact_key(key) if configured else "[not configured]",
        }
