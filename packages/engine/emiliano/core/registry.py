"""
Unified Capability Registry for Emiliano.
Discovers and categorizes all direct model providers and external agent harnesses,
evaluating their installation, usability, credentials, and models.
"""

from __future__ import annotations

import asyncio
from typing import Dict, List, Optional

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("emiliano")

from .capabilities import Capability, CapabilityStatus, ExecutionType
from .config import EmilianoConfig, load_config
from ..direct.credentials import CredentialManager, redact_key
from ..direct.ollama import OllamaManager
from ..harnesses.base import (
    AntigravityHarness,
    BaseHarness,
    ClaudeCodeHarness,
    CodexHarness,
    OpenCodeHarness,
)


class CapabilityRegistry:
    """Discovers, catalogs, and manages available model providers and agent harnesses."""

    def __init__(self, config: Optional[EmilianoConfig] = None):
        self.config = config or load_config()
        self.cred_mgr = CredentialManager(config=self.config)
        self.ollama_mgr = OllamaManager(
            base_url=self.config.models.ollama_base_url,
            auto_start=getattr(self.config.models, "auto_start_ollama", False),
        )
        self._capabilities: Dict[str, Capability] = {}

    def get_harness_instances(self) -> Dict[str, BaseHarness]:
        return {
            "claude_code": ClaudeCodeHarness(command=self.config.harnesses.claude_code_cmd),
            "codex": CodexHarness(command=self.config.harnesses.codex_cmd),
            "antigravity": AntigravityHarness(command=self.config.harnesses.antigravity_cmd),
            "opencode": OpenCodeHarness(command=self.config.harnesses.opencode_cmd),
        }

    async def discover_all(self, test_harness_usability: bool = True) -> Dict[str, Capability]:
        """Discovers all providers and harnesses and returns a dictionary of capabilities."""
        caps: Dict[str, Capability] = {}

        # 1. Discover Ollama (Local Model Provider)
        ollama_cap = await self._discover_ollama()
        caps[ollama_cap.name] = ollama_cap

        # 2. Discover Direct API Providers
        api_caps = self._discover_api_providers()
        for c in api_caps:
            caps[c.name] = c

        # 3. Discover External Agent Harnesses
        harness_caps = await self._discover_harnesses(test_usability=test_harness_usability)
        for c in harness_caps:
            caps[c.name] = c

        self._capabilities = caps
        return caps

    async def _discover_ollama(self) -> Capability:
        exe = self.ollama_mgr.find_executable()
        ready = await self.ollama_mgr.is_service_ready()

        if not ready and self.ollama_mgr.auto_start and exe:
            ready = await self.ollama_mgr.ensure_service_running()

        if not exe and not ready:
            return Capability(
                name="ollama",
                display_name="Ollama (Local)",
                execution_type=ExecutionType.DIRECT_MODEL,
                status=CapabilityStatus.NOT_INSTALLED,
                status_message="Ollama executable not found and endpoint not responding.",
                priority=10,
            )

        if not ready:
            return Capability(
                name="ollama",
                display_name="Ollama (Local)",
                execution_type=ExecutionType.DIRECT_MODEL,
                status=CapabilityStatus.UNAVAILABLE,
                status_message=f"Installed ({exe}), but service is not running at {self.ollama_mgr.base_url}.",
                executable_path=exe,
                priority=10,
            )

        installed_models = await self.ollama_mgr.list_installed_models()
        best_model = self.ollama_mgr.select_best_model(installed_models)

        if not installed_models:
            return Capability(
                name="ollama",
                display_name="Ollama (Local)",
                execution_type=ExecutionType.DIRECT_MODEL,
                status=CapabilityStatus.UNAVAILABLE,
                status_message=f"Service running at {self.ollama_mgr.base_url}, but no models are installed. Run 'ollama pull <model>'.",
                executable_path=exe,
                priority=10,
            )

        return Capability(
            name="ollama",
            display_name="Ollama (Local)",
            execution_type=ExecutionType.DIRECT_MODEL,
            status=CapabilityStatus.READY,
            status_message=f"Ready at {self.ollama_mgr.base_url} (Selected: {best_model})",
            executable_path=exe,
            available_models=installed_models,
            selected_model=best_model,
            priority=10,
        )

    def _discover_api_providers(self) -> List[Capability]:
        results: List[Capability] = []
        providers = [
            ("anthropic", "Anthropic (Claude)", self.cred_mgr.get_anthropic_key, "claude-3-7-sonnet-20250219", "ANTHROPIC_API_KEY", 20),
            ("openai", "OpenAI (GPT)", self.cred_mgr.get_openai_key, "gpt-4o", "OPENAI_API_KEY", 25),
            ("deepseek", "DeepSeek", self.cred_mgr.get_deepseek_key, "deepseek-chat", "DEEPSEEK_API_KEY", 30),
            ("gemini", "Google Gemini", self.cred_mgr.get_gemini_key, "gemini-2.5-pro", "GEMINI_API_KEY", 35),
        ]

        for name, display, getter, def_model, env_name, prio in providers:
            key = getter()
            if key:
                cap = Capability(
                    name=name,
                    display_name=display,
                    execution_type=ExecutionType.DIRECT_MODEL,
                    status=CapabilityStatus.READY,
                    status_message=f"Credentials configured ({redact_key(key)})",
                    available_models=[def_model],
                    selected_model=def_model,
                    priority=prio,
                )
            else:
                cap = Capability(
                    name=name,
                    display_name=display,
                    execution_type=ExecutionType.DIRECT_MODEL,
                    status=CapabilityStatus.UNAUTHENTICATED,
                    status_message=f"Missing credential (set {env_name})",
                    available_models=[def_model],
                    priority=prio,
                )
            results.append(cap)
        return results

    async def _discover_harnesses(self, test_usability: bool = True) -> List[Capability]:
        results: List[Capability] = []
        harnesses = self.get_harness_instances()

        # Priority weights for harnesses
        prio_map = {
            "claude_code": 15,
            "antigravity": 16,
            "codex": 17,
            "opencode": 18,
        }

        for h_id, harness in harnesses.items():
            exe = harness.resolve_executable()
            prio = prio_map.get(h_id, 50)

            if not exe:
                results.append(Capability(
                    name=h_id,
                    display_name=harness.display_name,
                    execution_type=ExecutionType.AGENT_HARNESS,
                    status=CapabilityStatus.NOT_INSTALLED,
                    status_message=f"'{harness.command}' not found on PATH",
                    priority=prio,
                ))
                continue

            # Usability check
            usable = True
            version = None
            err = None
            if test_usability:
                # Run in executor to avoid blocking event loop
                loop = asyncio.get_running_loop()
                usable, version, err = await loop.run_in_executor(None, harness.check_usability)

            if not usable:
                results.append(Capability(
                    name=h_id,
                    display_name=harness.display_name,
                    execution_type=ExecutionType.AGENT_HARNESS,
                    status=CapabilityStatus.UNAVAILABLE,
                    status_message=f"Found ({exe}), but usability check failed: {err}",
                    executable_path=exe,
                    priority=prio,
                ))
                continue

            # Authentication check
            is_auth, auth_msg = harness.check_authentication()
            if not is_auth:
                results.append(Capability(
                    name=h_id,
                    display_name=harness.display_name,
                    execution_type=ExecutionType.AGENT_HARNESS,
                    status=CapabilityStatus.UNAUTHENTICATED,
                    status_message=f"Installed ({version or 'ok'}), but {auth_msg}",
                    executable_path=exe,
                    version=version,
                    priority=prio,
                ))
                continue

            # Ready
            results.append(Capability(
                name=h_id,
                display_name=harness.display_name,
                execution_type=ExecutionType.AGENT_HARNESS,
                status=CapabilityStatus.READY,
                status_message=f"Ready ({version or 'installed'}) - {auth_msg}",
                executable_path=exe,
                version=version,
                priority=prio,
            ))

        return results

    def get_ready_capabilities(self) -> List[Capability]:
        return [c for c in self._capabilities.values() if c.is_usable]

    def get_harnesses(self) -> List[Capability]:
        return [c for c in self._capabilities.values() if c.execution_type == ExecutionType.AGENT_HARNESS]

    def get_direct_models(self) -> List[Capability]:
        return [c for c in self._capabilities.values() if c.execution_type == ExecutionType.DIRECT_MODEL]
