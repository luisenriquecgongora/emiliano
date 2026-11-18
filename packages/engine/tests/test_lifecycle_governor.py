"""
Unit tests for the ModelLifecycleGovernor and VRAM high-watermark LRU eviction.
"""

import asyncio
import time
import unittest
from unittest.mock import AsyncMock, patch

from emiliano.core.config import EmilianoConfig
from emiliano.direct.hardware import Hardware
from emiliano.direct.lifecycle import ModelLifecycleGovernor
from emiliano.direct.ollama import OllamaManager


class TestModelLifecycleGovernor(unittest.TestCase):
    def setUp(self):
        self.config = EmilianoConfig()
        self.config.models.vram_high_watermark = 0.80  # 80% threshold
        self.config.models.auto_evict_lru = True

        self.mock_mgr = OllamaManager()
        self.mock_mgr.list_loaded = AsyncMock(return_value={})
        self.mock_mgr.list_model_details = AsyncMock(return_value=[])
        self.mock_mgr.unload = AsyncMock(return_value=True)

        self.governor = ModelLifecycleGovernor(config=self.config, ollama_mgr=self.mock_mgr)

    def test_touch_updates_timestamps(self):
        self.governor.touch("qwen3.5:2b")
        ts = self.governor.get_last_accessed("qwen3.5:2b")
        self.assertIsNotNone(ts)
        self.assertLess(time.monotonic() - ts, 1.0)
        # Base name also touches
        self.assertIsNotNone(self.governor.get_last_accessed("qwen3.5"))

    @patch("emiliano.direct.lifecycle.get_gpu_memory_usage")
    @patch("emiliano.direct.lifecycle.detect_hardware")
    def test_no_eviction_when_vram_headroom_is_ample(self, mock_hw, mock_vram):
        # 16 GB GPU, only 4 GB used, loading 3 GB -> 7 GB / 16 GB = 43% < 80%
        gb = 1024 ** 3
        mock_hw.return_value = Hardware(gpu_name="RTX 4080", vram_bytes=16 * gb, ram_bytes=32 * gb)
        mock_vram.return_value = (4 * gb, 12 * gb)
        self.mock_mgr.list_loaded.return_value = {
            "qwen3.5:2b": {"sizeBytes": int(2.5 * gb), "vramBytes": int(2.5 * gb)}
        }

        evicted = asyncio.run(self.governor.ensure_vram_headroom("new-model:7b", required_bytes=3 * gb))
        self.assertEqual(evicted, [])
        self.mock_mgr.unload.assert_not_called()

    @patch("emiliano.direct.lifecycle.get_gpu_memory_usage")
    @patch("emiliano.direct.lifecycle.detect_hardware")
    def test_evicts_lru_model_when_exceeding_high_watermark(self, mock_hw, mock_vram):
        # 4 GB GPU (GTX 1650), 3.0 GB currently used, loading 2.0 GB -> 5.0 GB > 3.2 GB (80%)
        gb = 1024 ** 3
        mock_hw.return_value = Hardware(gpu_name="GTX 1650", vram_bytes=4 * gb, ram_bytes=16 * gb)
        mock_vram.return_value = (int(3.0 * gb), int(1.0 * gb))

        # Model A was accessed long ago, Model B was accessed just now
        self.governor._access_timestamps["model-old"] = 100.0
        self.governor._access_timestamps["model-recent"] = 999999.0

        self.mock_mgr.list_loaded.return_value = {
            "model-recent": {"sizeBytes": int(1.5 * gb), "vramBytes": int(1.5 * gb)},
            "model-old": {"sizeBytes": int(1.5 * gb), "vramBytes": int(1.5 * gb)},
        }

        evicted = asyncio.run(self.governor.ensure_vram_headroom("model-new", required_bytes=int(1.5 * gb)))

        # Oldest model should be evicted first
        self.assertIn("model-old", evicted)
        self.mock_mgr.unload.assert_called_with("model-old")

    @patch("emiliano.direct.lifecycle.get_gpu_memory_usage")
    @patch("emiliano.direct.lifecycle.detect_hardware")
    def test_get_memory_telemetry(self, mock_hw, mock_vram):
        gb = 1024 ** 3
        mock_hw.return_value = Hardware(gpu_name="RTX 4070", vram_bytes=12 * gb, ram_bytes=32 * gb)
        mock_vram.return_value = (6 * gb, 6 * gb)
        self.mock_mgr.list_loaded.return_value = {
            "qwen2.5-coder:7b": {"sizeBytes": 5 * gb, "vramBytes": 5 * gb}
        }

        telemetry = asyncio.run(self.governor.get_memory_telemetry())
        self.assertEqual(telemetry["gpuName"], "RTX 4070")
        self.assertEqual(telemetry["vramUtilizationPercent"], 50.0)
        self.assertEqual(telemetry["vramTotalBytes"], 12 * gb)
        self.assertEqual(telemetry["vramUsedBytes"], 6 * gb)
        self.assertEqual(len(telemetry["loadedModels"]), 1)


if __name__ == "__main__":
    unittest.main()
