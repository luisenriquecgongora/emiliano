# 0004. OpenAI Frontier Stack: Tiered Reasoning Router and Realtime API

- **Status:** Accepted (2026-11-17)
- **Date:** 2026-11-17
- **Target Role Alignment:** OpenAI Applied AI Engineer (Digital Natives) — Frontier AI Architecture & Low-Latency Streaming

---

## 1. Context

Digital native technology startups scale their AI systems across two frontier paradigms:

1. **Reasoning Models (`o3-mini`, `o1`) vs. Low-Latency Fast Models (`gpt-4o-mini`, `gpt-4o`):**
   - Routing all tasks to heavy reasoning models introduces prohibitive latency and excessive token cost for simple file edits and queries.
   - Conversely, routing complex algorithmic debugging, concurrency, or security tasks to fast models leads to silent logic errors and hallucinated edge-case fixes.
   - Furthermore, OpenAI reasoning models require distinct prompt engineering: manual chain-of-thought nudges (`"Think step by step"`) clutter the prompt and degrade internal reasoning token formation.

2. **Ultra Low-Latency Multimodal Interaction (Realtime API):**
   - Traditional voice systems stitch together Speech-to-Text (STT) $\rightarrow$ LLM generation $\rightarrow$ Text-to-Speech (TTS). This pipeline introduces 1,500ms–2,500ms of latency, making natural conversation impossible.
   - The OpenAI Realtime API operates over persistent WebSockets with bidirectional 24kHz PCM16 streaming, reducing latency below 400ms and supporting server-side Voice Activity Detection (VAD) and immediate barge-in interruption.

---

## 2. Decision

We implement:
1. **Tiered Frontier Router & Speculative Execution (`emiliano/core/frontier_router.py`)**:
   - **Fast Path (`gpt-4o-mini`)**: Low-latency (<300ms) triage, single-file edits, formatting, syntax explanations.
   - **Standard Path (`gpt-4o`)**: Multi-file engineering and general multimodal workflows.
   - **Reasoning Path (`o3-mini`)**: Algorithmic refactoring, concurrency bugs, security audits, and mathematical invariants.
   - **Reasoning Effort Control**: Configures `reasoning_effort` (`low`, `medium`, `high`) based on algorithmic complexity.
   - **CoT Normalization**: Strips counterproductive manual step-by-step prompt artifacts when targeting `o3-mini`.
   - **Speculative Escalation**: If a fast-path model attempts a code fix that fails the automated test verification gate, the router speculatively escalates the diagnostic to `o3-mini` with `high` reasoning effort.

2. **OpenAI Realtime API Client (`emiliano/direct/realtime.py`)**:
   - Persistent WebSocket client connecting to `wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview`.
   - Direct 24kHz mono PCM16 streaming without external transcoding.
   - Server-side Voice Activity Detection (`turn_detection: {"type": "server_vad"}`).
   - Instant barge-in / interruption handling: sends `response.cancel` on `input_audio_buffer.speech_started`.
   - Live function calling: executes workspace tools and returns results over the active socket session.

```
+-----------------------------------------------------------------------------------------+
|                                  OpenAI Realtime Client                                 |
|                 (wss://api.openai.com/v1/realtime?model=gpt-4o-realtime)                |
+-----------------------------------------------------------------------------------------+
       |                                                                           |
       | 24kHz PCM16 Audio Stream                                                  | Function Calls
       v                                                                           v
+-----------------------------+                                             +-----------------------------+
|    Server VAD & Barge-In    |                                             |    Tool Execution Loop      |
| • speech_started -> cancel  |                                             | • execute_tool(path, cmd)   |
| • audio_delta streaming     |                                             | • return function_output    |
+-----------------------------+                                             +-----------------------------+
```

---

## 3. Verification

Both modules were validated with dedicated unit test suites:
- [`tests/test_frontier_router.py`](file:///C:/Users/artlu/OracliomNew/Oracliom/emiliano/packages/engine/tests/test_frontier_router.py): **5/5 passed** (Complexity tiering, reasoning effort parameterization, prompt scrubbing, speculative escalation).
- [`tests/test_realtime.py`](file:///C:/Users/artlu/OracliomNew/Oracliom/emiliano/packages/engine/tests/test_realtime.py): **4/4 passed** (WebSocket session handshake, PCM16 chunk delivery, server event decoding, barge-in cancellation, tool result round-trip).
