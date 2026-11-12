"""
Ollama service and model discovery manager.
Handles local executable detection, service readiness polling, auto-start,
and dynamic model selection from installed models.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Union

import httpx
try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("emiliano")


class OllamaManager:
    """Manages Ollama executable discovery, lifecycle, and model querying."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        auto_start: bool = False,
        timeout: float = 3.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.auto_start = auto_start
        self.timeout = timeout

    @staticmethod
    def find_executable() -> Optional[str]:
        """Locates the ollama binary on PATH or standard platform installation paths."""
        found = shutil.which("ollama")
        if found:
            return found

        # Standard installation directories
        candidates = []
        if sys.platform == "win32":
            local_appdata = os.environ.get("LOCALAPPDATA", "")
            program_files = os.environ.get("ProgramFiles", "")
            if local_appdata:
                candidates.append(Path(local_appdata) / "Programs" / "Ollama" / "ollama.exe")
            if program_files:
                candidates.append(Path(program_files) / "Ollama" / "ollama.exe")
        else:
            candidates.extend([
                Path("/usr/local/bin/ollama"),
                Path("/usr/bin/ollama"),
                Path.home() / ".local" / "bin" / "ollama",
            ])

        for c in candidates:
            if c.is_file():
                return str(c)

        return None

    async def is_service_ready(self) -> bool:
        """Checks if the Ollama HTTP API is responding."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.get(f"{self.base_url}/api/tags")
                return res.status_code == 200
        except Exception:
            return False

    async def ensure_service_running(self) -> bool:
        """
        Ensures Ollama service is running. If not running and auto_start is True,
        attempts to start 'ollama serve' without spawning duplicate instances.
        """
        if await self.is_service_ready():
            return True

        if not self.auto_start:
            return False

        exe = self.find_executable()
        if not exe:
            logger.debug("[Ollama] Cannot auto-start: ollama executable not found.")
            return False

        logger.info(f"[Ollama] Starting Ollama daemon ({exe} serve)...")
        try:
            # Spawn background process
            subprocess.Popen(
                [exe, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True if sys.platform != "win32" else False,
            )
        except Exception as e:
            logger.warning(f"[Ollama] Failed to spawn Ollama daemon: {e}")
            return False

        # Poll readiness with bounded retries
        for attempt in range(8):
            await asyncio.sleep(1.0)
            if await self.is_service_ready():
                logger.info("[Ollama] Service successfully started and ready.")
                return True

        logger.warning("[Ollama] Timed out waiting for Ollama service to become ready.")
        return False

    async def preload(self, model: str, num_ctx: Optional[int] = None, timeout: float = 180.0,
                      keep_alive: Optional[Union[int, str]] = None) -> bool:
        """Has Ollama load the model into memory now: an empty prompt only loads it. Uses the same context
        window as later calls ask for, since a different num_ctx would make Ollama load the model again.
        keep_alive sets how long it stays loaded (-1 = until unloaded); None keeps Ollama's default."""
        payload: dict = {"model": model, "prompt": ""}
        if num_ctx:
            payload["options"] = {"num_ctx": num_ctx}
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                res = await client.post(f"{self.base_url}/api/generate", json=payload)
                return res.status_code == 200
        except Exception as e:
            logger.debug(f"[Ollama] Preloading {model} failed: {e}")
            return False

    async def unload(self, model: str) -> bool:
        """Frees the memory (VRAM and RAM) a loaded model holds; it loads again on next use."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.post(f"{self.base_url}/api/generate", json={"model": model, "keep_alive": 0})
                return res.status_code == 200
        except Exception as e:
            logger.debug(f"[Ollama] Unloading {model} failed: {e}")
            return False

    async def list_loaded(self) -> Dict[str, Dict]:
        """Models in memory now (/api/ps): name -> {sizeBytes, vramBytes, expiresAt}."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.get(f"{self.base_url}/api/ps")
                if res.status_code == 200:
                    return {m["name"]: {"sizeBytes": m.get("size", 0), "vramBytes": m.get("size_vram", 0),
                                        "expiresAt": m.get("expires_at")}
                            for m in res.json().get("models", []) if m.get("name")}
        except Exception as e:
            logger.debug(f"[Ollama] Error querying /api/ps: {e}")
        return {}

    async def list_model_details(self) -> List[Dict]:
        """Installed models with size and tool support: [{name, sizeBytes, tools}]. tools is None when this
        Ollama does not report capabilities (older than 0.6)."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.get(f"{self.base_url}/api/tags")
                if res.status_code == 200:
                    out = []
                    for m in res.json().get("models", []):
                        if not m.get("name"):
                            continue
                        caps = m.get("capabilities")
                        out.append({"name": m["name"], "sizeBytes": m.get("size", 0),
                                    "tools": ("tools" in caps) if isinstance(caps, list) else None})
                    return out
        except Exception as e:
            logger.debug(f"[Ollama] Error querying /api/tags: {e}")
        return []

    async def list_installed_models(self) -> List[str]:
        """Queries /api/tags and returns installed model names."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.get(f"{self.base_url}/api/tags")
                if res.status_code == 200:
                    data = res.json()
                    models = [m.get("name") for m in data.get("models", []) if m.get("name")]
                    return models
        except Exception as e:
            logger.debug(f"[Ollama] Error querying /api/tags: {e}")
        return []

    @staticmethod
    def match_installed(installed_models: List[str], requested_model: str) -> Optional[str]:
        """
        Returns the installed model matching requested_model exactly, or by partial name
        (e.g. "qwen3.5" matches "qwen3.5:2b"). Returns None when nothing matches, so callers
        can tell a genuine local model apart from a remote model name.
        """
        req_clean = requested_model.lower().removeprefix("ollama/")
        for m in installed_models:
            if m.lower() == req_clean:
                return m
        for m in installed_models:
            if req_clean in m.lower():
                return m
        return None

    def select_best_model(self, installed_models: List[str], requested_model: Optional[str] = None) -> Optional[str]:
        """
        Selects an installed model:
        1. If requested_model matches or is a prefix/suffix of an installed model, returns it.
        2. Otherwise ranks installed models, preferring coding/instruction models.
        3. Returns the first installed model as fallback, or None if list is empty.
        """
        if not installed_models:
            return None

        if requested_model:
            matched = self.match_installed(installed_models, requested_model)
            if matched:
                return matched

        # Priority keywords for automatic selection (coding tasks first)
        keywords = ["coder", "code", "deepseek", "qwen", "llama", "mistral", "instruct"]
        for kw in keywords:
            for m in installed_models:
                if kw in m.lower():
                    return m

        return installed_models[0]
