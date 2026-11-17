"""
Unit tests for OpenAI Realtime WebSocket Client (emiliano/direct/realtime.py).
Tests connection initialization, audio streaming, server VAD, barge-in,
and function calling events without connecting to live network.
"""

import asyncio
import base64
import json
import unittest

from emiliano.direct.realtime import (
    OpenAIRealtimeClient,
    RealtimeEvent,
    RealtimeEventType,
)


class MockWebSocket:
    """Simulates bidirectional WebSocket transport for the OpenAI Realtime protocol."""

    def __init__(self, incoming_messages=None):
        self.incoming = list(incoming_messages or [])
        self.sent: list[dict] = []
        self.closed = False

    async def send(self, data: str) -> None:
        self.sent.append(json.loads(data))

    async def recv(self) -> str:
        if self.incoming:
            msg = self.incoming.pop(0)
            return json.dumps(msg)
        # Block until closed or exit
        await asyncio.sleep(0.01)
        self.closed = True
        raise ConnectionResetError("Connection closed")

    async def close(self) -> None:
        self.closed = True


class TestOpenAIRealtimeClient(unittest.IsolatedAsyncioTestCase):
    async def test_session_initialization_on_connect(self):
        ws = MockWebSocket()
        client = OpenAIRealtimeClient(api_key="mock-key", voice="alloy", turn_detection="server_vad")
        await client.connect(ws_client=ws)

        self.assertTrue(client.is_connected)
        self.assertEqual(len(ws.sent), 1)
        init_event = ws.sent[0]
        self.assertEqual(init_event["type"], "session.update")
        sess = init_event["session"]
        self.assertEqual(sess["voice"], "alloy")
        self.assertEqual(sess["input_audio_format"], "pcm16")
        self.assertEqual(sess["turn_detection"]["type"], "server_vad")

    async def test_send_audio_chunk(self):
        ws = MockWebSocket()
        client = OpenAIRealtimeClient(api_key="mock-key")
        await client.connect(ws_client=ws)

        pcm16_data = b"\x00\x01\x02\x03" * 20  # 80 bytes
        await client.send_audio_chunk(pcm16_data)

        self.assertEqual(len(ws.sent), 2)
        append_evt = ws.sent[1]
        self.assertEqual(append_evt["type"], "input_audio_buffer.append")
        decoded = base64.b64decode(append_evt["audio"])
        self.assertEqual(decoded, pcm16_data)

    async def test_event_streaming_audio_and_function_calling(self):
        mock_server_events = [
            # 1. User starts speaking (barge-in)
            {"type": "input_audio_buffer.speech_started", "event_id": "evt_1"},
            # 2. Model begins streaming audio
            {
                "type": "response.audio.delta",
                "event_id": "evt_2",
                "delta": base64.b64encode(b"\x10\x20\x30\x40").decode("ascii"),
            },
            # 3. Model outputs function call
            {
                "type": "response.function_call_arguments.done",
                "event_id": "evt_3",
                "call_id": "call_abc123",
                "name": "read_file",
                "arguments": json.dumps({"path": "src/main.py"}),
            },
            # 4. Turn complete
            {"type": "response.done", "event_id": "evt_4"},
        ]

        ws = MockWebSocket(incoming_messages=mock_server_events)
        client = OpenAIRealtimeClient(api_key="mock-key")
        await client.connect(ws_client=ws)

        received_events: list[RealtimeEvent] = []
        async for evt in client.events():
            received_events.append(evt)

        self.assertEqual(len(received_events), 4)

        # Event 1: Speech started
        self.assertEqual(received_events[0].event_type, RealtimeEventType.SPEECH_STARTED)

        # Event 2: Audio Delta
        self.assertEqual(received_events[1].event_type, RealtimeEventType.AUDIO_DELTA)
        self.assertEqual(received_events[1].audio_bytes, b"\x10\x20\x30\x40")

        # Event 3: Function call
        self.assertEqual(received_events[2].event_type, RealtimeEventType.FUNCTION_CALL)
        self.assertEqual(received_events[2].tool_name, "read_file")
        self.assertEqual(received_events[2].call_id, "call_abc123")
        self.assertIn("src/main.py", received_events[2].tool_arguments)

        # Event 4: Response Done
        self.assertEqual(received_events[3].event_type, RealtimeEventType.RESPONSE_DONE)

    async def test_function_output_and_cancellation(self):
        ws = MockWebSocket()
        client = OpenAIRealtimeClient(api_key="mock-key")
        await client.connect(ws_client=ws)

        # Return tool output
        await client.send_function_output(call_id="call_abc123", output="file contents here")
        self.assertEqual(len(ws.sent), 3)  # init + item.create + response.create
        self.assertEqual(ws.sent[1]["type"], "conversation.item.create")
        self.assertEqual(ws.sent[1]["item"]["type"], "function_call_output")
        self.assertEqual(ws.sent[1]["item"]["output"], "file contents here")
        self.assertEqual(ws.sent[2]["type"], "response.create")

        # Barge-in cancellation
        client._is_generating = True
        await client.cancel_response()
        self.assertEqual(len(ws.sent), 4)
        self.assertEqual(ws.sent[3]["type"], "response.cancel")
        self.assertFalse(client._is_generating)


if __name__ == "__main__":
    unittest.main()
