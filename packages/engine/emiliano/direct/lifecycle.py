"""
Autonomous Model Lifecycle & Memory Governor for Emiliano.
Arbitrates GPU VRAM allocations, enforces high-watermark thresholds,
and automatically evicts Least-Recently-Used (LRU) models to prevent Out-Of-Memory (OOM) crashes.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional
from loguru import logger

from ..core.config import EmilianoConfig
from .hardware import (
    _OVERHEAD_BYTES,
    _OVERHEAD_FACTOR,
    Hardware,
    detect_hardware,
    find_loaded_info,
    get_gpu_memory_usage,
)
from .ollama import OllamaManager


class ModelLifecycleGovernor:
    """
    Supervises local model memory allocations, tracks access recency,
    and automatically evicts older models before new allocations exceed the VRAM high-watermark.
    """

    _instance: Optional[ModelLifecycleGovernor] = None

    def __init__(self, config: Optional[EmilianoConfig] = None, ollama_mgr: Optional[OllamaManager] = None):
        self.config = config or EmilianoConfig()
        self.ollama_mgr = ollama_mgr or OllamaManager(
            base_url=self.config.models.ollama_base_url,
            auto_start=self.config.models.auto_start_ollama,
        )
        self._access_timestamps: Dict[str, float] = {}

    @classmethod
    def get_instance(
        cls,
        config: Optional[EmilianoConfig] = None,
        ollama_mgr: Optional[OllamaManager] = None,
    ) -> ModelLifecycleGovernor:
        if cls._instance is None:
            cls._instance = cls(config=config, ollama_mgr=ollama_mgr)
        elif config:
            cls._instance.config = config
        return cls._instance

    def touch(self, model_name: str) -> None:
        """Records an access timestamp for model_name to maintain LRU eviction order."""
        clean = model_name.lower().removeprefix("ollama/")
        self._access_timestamps[clean] = time.monotonic()
        # Also touch base name without tag
        base = clean.split(":")[0]
        self._access_timestamps[base] = time.monotonic()

    def get_last_accessed(self, model_name: str) -> Optional[float]:
        """Returns the monotonic timestamp of when this model was last accessed."""
        clean = model_name.lower().removeprefix("ollama/")
        return self._access_timestamps.get(clean) or self._access_timestamps.get(clean.split(":")[0])

    async def estimate_model_vram_needed(self, model_name: str) -> int:
        """Estimates VRAM in bytes required to load model_name."""
        clean = model_name.lower().removeprefix("ollama/")
        try:
            details = await self.ollama_mgr.list_model_details()
            for m in details:
                m_clean = m["name"].lower().removeprefix("ollama/")
                if m_clean == clean or m_clean.split(":")[0] == clean.split(":")[0]:
                    return int(m.get("sizeBytes", 0) * _OVERHEAD_FACTOR + _OVERHEAD_BYTES)
        except Exception as e:
            logger.debug(f"[Governor] Could not query model details for {model_name}: {e}")
        # Sensible fallback: 3.5 GB
        return 3500 * 1024 * 1024

    async def ensure_vram_headroom(
        self,
        target_model: str,
        required_bytes: Optional[int] = None,
    ) -> List[str]:
        """
        Verifies there is sufficient VRAM headroom to load target_model without exceeding
        the configured high-watermark threshold. Automatically evicts the least recently used
        (LRU) models until headroom is restored.

        Returns the list of evicted model names.
        """
        if not getattr(self.config.models, "auto_evict_lru", True):
            return []

        hw: Hardware = await asyncio.to_thread(detect_hardware)
        if hw.vram_bytes <= 0:
            # CPU only / no dedicated NVIDIA GPU detected; let Ollama / OS virtual memory manage
            return []

        clean_target = target_model.lower().removeprefix("ollama/")
        loaded = await self.ollama_mgr.list_loaded()
        if find_loaded_info(clean_target, loaded, self.ollama_mgr):
            # Already resident in memory
            self.touch(clean_target)
            return []

        if required_bytes is None:
            required_bytes = await self.estimate_model_vram_needed(clean_target)

        used_vram, _ = await asyncio.to_thread(get_gpu_memory_usage)
        if used_vram == 0:
            used_vram = sum(m.get("vramBytes", 0) for m in loaded.values())

        watermark_ratio = getattr(self.config.models, "vram_high_watermark", 0.85)
        high_watermark_limit = int(hw.vram_bytes * watermark_ratio)

        evicted: List[str] = []
        projected = used_vram + required_bytes

        if projected > high_watermark_limit and loaded:
            logger.info(
                f"[Governor] Projected VRAM ({projected / 1024**3:.2f} GB) exceeds limit "
                f"({high_watermark_limit / 1024**3:.2f} GB, {watermark_ratio*100:.0f}%). "
                f"Evaluating LRU eviction..."
            )

            # Sort loaded candidates by last accessed ascending (oldest first)
            candidates = list(loaded.keys())
            candidates.sort(key=lambda name: self.get_last_accessed(name) or 0.0)

            for candidate in candidates:
                if projected <= high_watermark_limit:
                    break
                candidate_info = loaded.get(candidate, {})
                cand_vram = candidate_info.get("vramBytes", 0)
                logger.info(
                    f"[Governor] Evicting LRU model '{candidate}' "
                    f"({cand_vram / 1024**3:.2f} GB VRAM) to free space for '{clean_target}'"
                )
                if await self.ollama_mgr.unload(candidate):
                    evicted.append(candidate)
                    projected -= cand_vram
                    used_vram = max(0, used_vram - cand_vram)

        self.touch(clean_target)
        return evicted

    async def get_memory_telemetry(self) -> Dict[str, Any]:
        """Provides real-time GPU and system memory statistics for dashboards and APIs."""
        hw: Hardware = await asyncio.to_thread(detect_hardware)
        used_vram, free_vram = await asyncio.to_thread(get_gpu_memory_usage)
        loaded = await self.ollama_mgr.list_loaded()

        if used_vram == 0 and loaded:
            used_vram = sum(m.get("vramBytes", 0) for m in loaded.values())
            if hw.vram_bytes > 0:
                free_vram = max(0, hw.vram_bytes - used_vram)

        pct = (used_vram / hw.vram_bytes * 100) if hw.vram_bytes > 0 else 0.0

        return {
            "gpuName": hw.gpu_name,
            "vramTotalBytes": hw.vram_bytes,
            "vramUsedBytes": used_vram,
            "vramFreeBytes": free_vram,
            "vramUtilizationPercent": round(pct, 1),
            "ramTotalBytes": hw.ram_bytes,
            "highWatermark": getattr(self.config.models, "vram_high_watermark", 0.85),
            "loadedModels": [
                {
                    "name": name,
                    "sizeBytes": info.get("sizeBytes", 0),
                    "vramBytes": info.get("vramBytes", 0),
                    "lastAccessedSecondsAgo": round(time.monotonic() - ts, 1)
                    if (ts := self.get_last_accessed(name))
                    else None,
                }
                for name, info in loaded.items()
            ],
        }
