"""Rating local models against the machine's GPU and RAM, and the model load/unload endpoints."""

import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from emiliano.direct.hardware import (FIT_GPU, FIT_SLOW, FIT_TOO_BIG, GB, Hardware, rate_fit, rate_installed,
                                      suggest_downloads)
from emiliano.server.app import app, get_dispatcher

# A GTX 1650 laptop: 4 GB VRAM, 16 GB RAM
LAPTOP = Hardware(gpu_name="GTX 1650", vram_bytes=4 * GB, ram_bytes=16 * GB)
NO_GPU = Hardware(gpu_name=None, vram_bytes=0, ram_bytes=16 * GB)


class TestRating(unittest.TestCase):
    def test_fit_by_size(self):
        self.assertEqual(rate_fit(int(2.7 * GB), LAPTOP), FIT_GPU)
        self.assertEqual(rate_fit(int(5.2 * GB), LAPTOP), FIT_SLOW)
        self.assertEqual(rate_fit(20 * GB, LAPTOP), FIT_TOO_BIG)

    def test_without_gpu_nothing_is_fast(self):
        self.assertEqual(rate_fit(1 * GB, NO_GPU), FIT_SLOW)

    def test_recommends_biggest_tool_model_on_gpu(self):
        rated = rate_installed([
            {"name": "small", "sizeBytes": 1 * GB, "tools": True},
            {"name": "mid", "sizeBytes": int(2.5 * GB), "tools": True},
            {"name": "notools", "sizeBytes": 3 * GB, "tools": False},
            {"name": "big", "sizeBytes": 5 * GB, "tools": True},
        ], LAPTOP)
        self.assertEqual([m["name"] for m in rated if m["recommended"]], ["mid"])

    def test_recommends_smallest_slow_model_when_none_fit(self):
        rated = rate_installed([
            {"name": "a", "sizeBytes": 5 * GB, "tools": True},
            {"name": "b", "sizeBytes": 7 * GB, "tools": True},
        ], LAPTOP)
        self.assertEqual([m["name"] for m in rated if m["recommended"]], ["a"])

    def test_suggestions_skip_installed_and_too_big(self):
        names = [s["name"] for s in suggest_downloads(["qwen3:4b"], Hardware(None, 0, 8 * GB))]
        self.assertNotIn("qwen3:4b", names)
        self.assertNotIn("qwen2.5-coder:14b", names)
        fits = [s["fit"] for s in suggest_downloads([], LAPTOP)]
        self.assertEqual(fits, sorted(fits, key=lambda f: f != FIT_GPU))  # fast ones first


class TestModelEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, base_url="http://127.0.0.1")
        self.mgr = get_dispatcher().registry.ollama_mgr

    def test_recommendations(self):
        with patch.object(self.mgr, "list_model_details", AsyncMock(return_value=[
                {"name": "qwen3.5:2b", "sizeBytes": int(2.7 * GB), "tools": True}])), \
             patch.object(self.mgr, "list_loaded", AsyncMock(return_value={
                "qwen3.5:2b": {"sizeBytes": 1, "vramBytes": 123, "expiresAt": None}})), \
             patch("emiliano.direct.hardware.detect_hardware", return_value=LAPTOP):
            body = self.client.get("/api/models/recommendations").json()
        model = body["models"][0]
        self.assertEqual((model["fit"], model["recommended"], model["loaded"], model["vramBytes"]),
                         (FIT_GPU, True, True, 123))
        self.assertEqual(body["hardware"]["vramBytes"], 4 * GB)
        self.assertTrue(body["suggestions"])

    def test_load_keeps_model_in_memory(self):
        preload = AsyncMock(return_value=True)
        with patch.object(self.mgr, "list_installed_models", AsyncMock(return_value=["qwen3.5:2b"])), \
             patch.object(self.mgr, "preload", preload):
            resp = self.client.post("/api/models/load", json={"model": "qwen3.5:2b"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(preload.call_args.kwargs["keep_alive"], -1)

    def test_load_unknown_model_is_404(self):
        with patch.object(self.mgr, "list_installed_models", AsyncMock(return_value=[])):
            resp = self.client.post("/api/models/load", json={"model": "nope"})
        self.assertEqual(resp.status_code, 404)

    def test_unload(self):
        unload = AsyncMock(return_value=True)
        with patch.object(self.mgr, "unload", unload):
            resp = self.client.post("/api/models/unload", json={"model": "qwen3.5:2b"})
        self.assertEqual(resp.status_code, 200)
        unload.assert_awaited_once_with("qwen3.5:2b")


if __name__ == "__main__":
    unittest.main()
