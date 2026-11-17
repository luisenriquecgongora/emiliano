"""
OpenAI Realtime API Client (WebSockets / WebRTC Protocol).

Provides low-latency, bidirectional streaming audio and function calling for voice agents
and real-time desktop coworkers using the official OpenAI Realtime API:
- Endpoint: wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview
- Protocol: JSON-RPC events over WebSockets with 24kHz mono PCM16 audio.
- Server-side Voice Activity Detection (VAD) with automated turn detection.
- Barge-in & Interruption Handling: cancels active audio generation on user speech.
- Tool Calling / Function Execution over the persistent real-time socket.
"""

from __future__ import annotations

import base64
import json
import os
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncGenerator, Dict, List, Optional

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("emiliano")


class RealtimeEventType(str, Enum):
    SESSION_CREATED = "session_created"
    SESSION_UPDATED = "session_updated"
    SPEECH_STARTED = "speech_started"      # User began speaking (signals barge-in / truncate playback)
    SPEECH_STOPPED = "speech_stopped"      # User finished speaking
    AUDIO_DELTA = "audio_delta"            # Streaming model audio chunk (PCM16)
    TRANSCRIPT_DELTA = "transcript_delta"  # Streaming text transcript of model audio
    TEXT_DELTA = "text_delta"              # Streaming text chunk
    FUNCTION_CALL = "function_call"        # Model initiated function call
    RESPONSE_DONE = "response_done"        # Response turn complete
    ERROR = "error"


@dataclass
class RealtimeEvent:
    """Structured event emitted by the OpenAI Realtime stream."""

    event_type: RealtimeEventType
    event_id: str
    data: Dict[str, Any] = field(default_factory=dict)
    audio_bytes: Optional[bytes] = None
    text: Optional[str] = None
    call_id: Optional[str] = None
    tool_name: Optional[str] = None
    tool_arguments: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "type": self.event_type.value,
            "event_id": self.event_id,
            "data": self.data,
            "text": self.text,
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "tool_arguments": self.tool_arguments,
        }
        if self.audio_bytes:
            d["audio_byte_length"] = len(self.audio_bytes)
        return d


class OpenAIRealtimeClient:
    """
    Asynchronous client for the OpenAI Realtime WebSocket protocol.
    """

    DEFAULT_MODEL = "gpt-4o-realtime-preview"
    DEFAULT_URL = "wss://api.openai.com/v1/realtime"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        voice: str = "alloy",  # alloy | echo | shimmer | verse | ballad | coral | sage
        instructions: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        turn_detection: str = "server_vad",  # "server_vad" or "none" (manual)
        temperature: float = 0.8,
        ws_endpoint: Optional[str] = None,
    ):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.model = model
        self.voice = voice
        self.instructions = instructions or "You are an autonomous desktop AI coworker."
        self.tools = tools or []
        self.turn_detection = turn_detection
        self.temperature = temperature
        self.ws_endpoint = ws_endpoint or f"{self.DEFAULT_URL}?model={self.model}"

        self._ws: Any = None
        self._connected = False
        self._is_generating = False
        self._current_response_id: Optional[str] = None

    @property
    def is_connected(self) -> bool:
        return self._connected and self._ws is not None

    def _event_id(self) -> str:
        return f"evt_{uuid.uuid4().hex[:12]}"

    async def connect(self, ws_client: Optional[Any] = None) -> None:
        """
        Connects to the OpenAI Realtime WebSocket endpoint.
        Optionally accepts a mock or pre-configured ws_client for testing.
        """
        if ws_client is not None:
            self._ws = ws_client
            self._connected = True
            await self.update_session()
            return

        import websockets

        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is required to connect to OpenAI Realtime API.")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "OpenAI-Beta": "realtime=v1",
        }

        logger.info(f"[Realtime] Connecting to {self.ws_endpoint}...")
        self._ws = await websockets.connect(self.ws_endpoint, additional_headers=headers)
        self._connected = True
        logger.info("[Realtime] Connected successfully. Initializing session...")
        await self.update_session()

    async def disconnect(self) -> None:
        """Closes the WebSocket connection."""
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
        self._connected = False
        self._ws = None

    async def send_event(self, event: Dict[str, Any]) -> None:
        """Sends a JSON-RPC event over the WebSocket."""
        if not self.is_connected:
            raise RuntimeError("Cannot send event: Realtime client is not connected.")
        event.setdefault("event_id", self._event_id())
        payload = json.dumps(event)
        await self._ws.send(payload)

    async def update_session(self) -> None:
        """Configures session parameters: voice, modalities, server VAD, and tools."""
        turn_cfg: Optional[Dict[str, Any]] = None
        if self.turn_detection == "server_vad":
            turn_cfg = {
                "type": "server_vad",
                "threshold": 0.5,
                "prefix_padding_ms": 300,
                "silence_duration_ms": 500,
            }

        session_cfg = {
            "modalities": ["text", "audio"],
            "instructions": self.instructions,
            "voice": self.voice,
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm16",
            "input_audio_transcription": {"model": "whisper-1"},
            "temperature": self.temperature,
            "turn_detection": turn_cfg,
            "tools": self.tools,
        }

        await self.send_event({
            "type": "session.update",
            "session": session_cfg,
        })

    async def send_audio_chunk(self, pcm16_bytes: bytes) -> None:
        """
        Appends raw 24kHz 16-bit mono PCM audio to the server input buffer.
        """
        b64_audio = base64.b64encode(pcm16_bytes).decode("ascii")
        await self.send_event({
            "type": "input_audio_buffer.append",
            "audio": b64_audio,
        })

    async def commit_audio_buffer(self) -> None:
        """Manually commits the audio buffer (when turn_detection is None)."""
        await self.send_event({"type": "input_audio_buffer.commit"})

    async def send_text_message(self, text: str) -> None:
        """Appends a user text message and requests a model response."""
        await self.send_event({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": text}],
            },
        })
        await self.send_event({"type": "response.create"})

    async def cancel_response(self) -> None:
        """Interrupts and cancels the model's active response generation (barge-in)."""
        if self._is_generating:
            await self.send_event({"type": "response.cancel"})
            self._is_generating = False

    async def send_function_output(self, call_id: str, output: str) -> None:
        """Returns the result of a tool execution back to the model turn."""
        await self.send_event({
            "type": "conversation.item.create",
            "item": {
                "type": "function_call_output",
                "call_id": call_id,
                "output": output,
            },
        })
        # Trigger next response generation incorporating tool result
        await self.send_event({"type": "response.create"})

    async def events(self) -> AsyncGenerator[RealtimeEvent, None]:
        """
        Asynchronously streams incoming server events parsed into structured RealtimeEvent objects.
        """
        if not self.is_connected:
            raise RuntimeError("Realtime client is not connected.")

        active_func_calls: Dict[str, Dict[str, str]] = {}

        while self.is_connected:
            try:
                raw = await self._ws.recv()
                if not raw:
                    continue
                data = json.loads(raw)
                evt_type = data.get("type", "")
                evt_id = data.get("event_id", "")

                # 1. Speech Started (User Barge-In)
                if evt_type == "input_audio_buffer.speech_started":
                    self._is_generating = False
                    yield RealtimeEvent(event_type=RealtimeEventType.SPEECH_STARTED, event_id=evt_id, data=data)

                elif evt_type == "input_audio_buffer.speech_stopped":
                    yield RealtimeEvent(event_type=RealtimeEventType.SPEECH_STOPPED, event_id=evt_id, data=data)

                # 2. Audio Delta
                elif evt_type == "response.audio.delta":
                    self._is_generating = True
                    b64 = data.get("delta", "")
                    audio = base64.b64decode(b64) if b64 else None
                    yield RealtimeEvent(
                        event_type=RealtimeEventType.AUDIO_DELTA,
                        event_id=evt_id,
                        data=data,
                        audio_bytes=audio,
                    )

                # 3. Audio Transcript Delta
                elif evt_type == "response.audio_transcript.delta":
                    yield RealtimeEvent(
                        event_type=RealtimeEventType.TRANSCRIPT_DELTA,
                        event_id=evt_id,
                        data=data,
                        text=data.get("delta"),
                    )

                # 4. Text Delta
                elif evt_type == "response.text.delta":
                    yield RealtimeEvent(
                        event_type=RealtimeEventType.TEXT_DELTA,
                        event_id=evt_id,
                        data=data,
                        text=data.get("delta"),
                    )

                # 5. Function Calling
                elif evt_type == "response.function_call_arguments.delta":
                    call_id = data.get("call_id") or data.get("item_id", "")
                    active_func_calls.setdefault(call_id, {"args": ""})
                    active_func_calls[call_id]["args"] += data.get("delta", "")

                elif evt_type == "response.function_call_arguments.done":
                    call_id = data.get("call_id") or data.get("item_id", "")
                    name = data.get("name", "")
                    full_args = data.get("arguments") or active_func_calls.get(call_id, {}).get("args", "{}")
                    yield RealtimeEvent(
                        event_type=RealtimeEventType.FUNCTION_CALL,
                        event_id=evt_id,
                        data=data,
                        call_id=call_id,
                        tool_name=name,
                        tool_arguments=full_args,
                    )

                # 6. Response Completed
                elif evt_type == "response.done":
                    self._is_generating = False
                    yield RealtimeEvent(event_type=RealtimeEventType.RESPONSE_DONE, event_id=evt_id, data=data)

                # 7. Session Events
                elif evt_type == "session.created":
                    yield RealtimeEvent(event_type=RealtimeEventType.SESSION_CREATED, event_id=evt_id, data=data)

                elif evt_type == "session.updated":
                    yield RealtimeEvent(event_type=RealtimeEventType.SESSION_UPDATED, event_id=evt_id, data=data)

                elif evt_type == "error":
                    logger.error(f"[Realtime] Server Error: {data.get('error')}")
                    yield RealtimeEvent(event_type=RealtimeEventType.ERROR, event_id=evt_id, data=data)

            except Exception as e:
                if not self._connected:
                    break
                logger.warning(f"[Realtime] Stream exception: {e}")
                break
