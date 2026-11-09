"""
Tests for talking to Ollama directly (UnifiedLLMClient._stream_ollama), without litellm.
A fake Ollama /api/chat is served through httpx.MockTransport.
"""

import asyncio
import json
import unittest
from unittest.mock import patch

import httpx

from emiliano.core.config import EmilianoConfig
from emiliano.direct.client import UnifiedLLMClient


def fake_ollama(client, lines, status=200, body=None):
    sent = []

    def handler(request):
        sent.append({"url": str(request.url), **json.loads(request.content)})
        content = body if body is not None else "\n".join(json.dumps(line) for line in lines)
        return httpx.Response(status, content=content.encode())

    client._ollama_transport = httpx.MockTransport(handler)
    return sent


def collect(client, model="ollama/qwen3.5:2b", **kwargs):
    async def run():
        return [c async for c in client.stream_completion([{"role": "user", "content": "hi"}], model_name=model, **kwargs)]
    return asyncio.run(run())


class TestDirectOllama(unittest.TestCase):
    def test_streams_reply_and_records_usage_without_litellm(self):
        client = UnifiedLLMClient(config=EmilianoConfig())
        sent = fake_ollama(client, [
            {"message": {"content": "Hel"}, "done": False},
            {"message": {"content": "lo"}, "done": False},
            {"message": {"content": ""}, "done": True, "prompt_eval_count": 12, "eval_count": 3},
        ])
        with patch("emiliano.direct.client.load_litellm") as load_litellm:
            self.assertEqual(collect(client), ["Hel", "lo"])
        load_litellm.assert_not_called()
        request = sent[0]
        self.assertTrue(request["url"].endswith("/api/chat"))
        self.assertEqual(request["model"], "qwen3.5:2b")  # without the "ollama/" prefix
        self.assertEqual(request["messages"], [{"role": "user", "content": "hi"}])
        self.assertTrue(request["stream"])
        self.assertEqual(request["options"]["num_ctx"], 8192)
        self.assertNotIn("think", request)  # think=None leaves the model's default
        self.assertEqual(client.last_usage, {"prompt_tokens": 12, "completion_tokens": 3})
        self.assertEqual(client.last_model, "ollama/qwen3.5:2b")

    def test_reasoning_is_streamed_separately(self):
        client = UnifiedLLMClient()
        fake_ollama(client, [{"message": {"content": "", "thinking": "2+2 is 4"}, "done": False},
                             {"message": {"content": "4"}, "done": True}])
        reasoning = []
        self.assertEqual(collect(client, think=True, on_reasoning=reasoning.append), ["4"])
        self.assertEqual(reasoning, ["2+2 is 4"])

    def test_http_error_names_the_problem(self):
        client = UnifiedLLMClient()
        fake_ollama(client, [], status=404, body='{"error": "model \'nope:1b\' not found"}')
        with self.assertRaises(RuntimeError) as ctx:
            collect(client, model="ollama/nope:1b")
        self.assertIn("HTTP 404", str(ctx.exception))
        self.assertIn("not found", str(ctx.exception))

    def test_error_in_stream_fails_the_attempt(self):
        client = UnifiedLLMClient()
        fake_ollama(client, [{"message": {"content": "par"}, "done": False}, {"error": "out of memory"}])
        with self.assertRaises(RuntimeError) as ctx:
            collect(client)
        self.assertIn("out of memory", str(ctx.exception))

    def test_unreachable_ollama_fails_cleanly(self):
        client = UnifiedLLMClient()

        def refuse(request):
            raise httpx.ConnectError("connection refused", request=request)

        client._ollama_transport = httpx.MockTransport(refuse)
        with self.assertRaises(RuntimeError) as ctx:
            collect(client)
        self.assertIn("connection refused", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
