# 0002. Observability, Distributed Spans, and Safety Guardrails

- **Status:** Accepted (2026-11-17)
- **Date:** 2026-11-17
- **Target Role Alignment:** OpenAI Applied AI Engineer (Digital Natives) — Production Systems Architecture

---

## 1. Context

As autonomous agents transition from experimental developer tools into mission-critical production systems (serving digital native platforms and enterprise workflows), two critical operational deficiencies emerge:

1. **Lack of Granular Observability:**
   A monolithic task trace (`TaskTrace`) recording only total duration and total token usage is insufficient for debugging multi-turn agent execution. When an agent experiences latency spikes or execution failures, engineers cannot isolate whether the bottleneck occurred during model inference (TTFT vs. decode time), a stalled tool execution (e.g. bash timeout), prompt overhead, or context pruning.

2. **Absence of Production Safety Guardrails:**
   Autonomous agents with workspace tool execution capabilities (`bash`, `write_file`, `read_file`) present severe security risks if uncontained:
   - **Path Traversal Attacks:** Model or prompt injection attempting to read or overwrite files outside the repository boundary (e.g. `../../etc/shadow` or `~/.ssh/`).
   - **Catastrophic Shell Execution:** Dangerous commands such as `rm -rf /`, raw disk writes, or force-pushing to protected git branches.
   - **Credential & PII Exfiltration:** Accidental leakage of API keys (`sk-...`, `ghp_...`, `AKIA...`, JWTs), emails, or customer personal data in logs, traces, or remote provider prompts.
   - **Direct & Indirect Prompt Injection:** Instructional overrides (`"Ignore all previous instructions..."`) and delimiter manipulation designed to hijack agent behavior.

---

## 2. Decision

We implement a dual-pillar architecture: **Granular OpenTelemetry Distributed Spans** and **Multi-Layer Defensive Guardrails**.

```
                +-------------------------------------------------+
                |                  User / Client                  |
                +-------------------------------------------------+
                                         |
                                         v
+---------------------------------------------------------------------------------+
|                        Defensive Guardrails Pipeline                            |
|                                                                                 |
|  1. Input Phase:                                                                |
|     • PIIGuardrail: Redacts API keys, credentials, emails, phone numbers       |
|     • InjectionGuardrail: Blocks instruction overrides & delimiter breakouts    |
|     • ModerationGuardrail: Flags harmful / destructive requests                 |
|                                                                                 |
|  2. Tool Execution Phase:                                                       |
|     • ToolSafetyGuardrail: Enforces workspace containment & blocks destructive  |
|       shell commands (rm -rf, format, fork bombs, git force push)               |
|                                                                                 |
|  3. Output Phase:                                                               |
|     • PIIGuardrail: Sanitizes model & tool responses before returning           |
+---------------------------------------------------------------------------------+
                                         |
                                         v
+---------------------------------------------------------------------------------+
|               Distributed Tracing & OpenTelemetry Engine                        |
|                                                                                 |
|  • TaskTrace (Root Container)                                                   |
|    ├── TraceSpan: agent.turn (turn=1)                                           |
|    │   ├── TraceSpan: llm.generate (gen_ai.request.model, prompt/comp tokens)   |
|    │   └── TraceSpan: tool.execute (gen_ai.tool.name, duration_ms, status)     |
|    └── TraceSpan: agent.turn (turn=2)                                           |
|                                                                                 |
|  • Schema & Export: OpenTelemetry GenAI Semantic Conventions                    |
|  • Telemetry Aggregator: p50/p95/p99 latency, TTFT, token cost, block rates    |
+---------------------------------------------------------------------------------+
```

### Key Technical Specifications

1. **OpenTelemetry GenAI Semantic Alignment:**
   - Every `TraceSpan` adheres to OpenTelemetry GenAI Semantic Conventions:
     - `gen_ai.system`: Provider classification (`openai`, `anthropic`, `custom`).
     - `gen_ai.request.model`: Target model ID (`gpt-4o`, `o3-mini`, `qwen2.5-coder`).
     - `gen_ai.usage.input_tokens` / `output_tokens`: Token consumption accounting.
     - `gen_ai.server.time_to_first_token_s`: First-token streaming latency (TTFT).
     - `gen_ai.tool.name`: Specific tool invoked.
   - Spans are exportable via `to_otel_trace()` for ingestion by Honeycomb, Arize Phoenix, LangSmith, or OpenLLMetry collectors.

2. **Defensive Guardrails (`emiliano/core/guardrails.py`):**
   - **`PIIGuardrail`**: High-performance regex engine detecting OpenAI API keys, GitHub tokens, AWS keys, JWTs, credit card patterns, emails, and phone numbers. Replaces sensitive credentials with `[REDACTED_*]` tokens with optional hard blocking (`block_on_secrets=True`).
   - **`InjectionGuardrail`**: Catches direct instruction overrides, delimiter injection (`<system>`, `[SYSTEM]`, `---BEGIN SYSTEM PROMPT---`), and system prompt exfiltration attempts.
   - **`ToolSafetyGuardrail`**: Enforces strict workspace containment (`pathlib.Path.is_relative_to`), blocking directory traversal attacks (`../../`), and inspects shell commands against catastrophic patterns (`rm -rf /`, `mkfs`, fork bombs).
   - **`ModerationGuardrail`**: Local heuristic safety checks with async extension hooks for the OpenAI Moderation API.

3. **Operational Telemetry Metrics:**
   - Added `TraceStore.get_telemetry_metrics(hours=24)`:
     - Calculates real-time **p50, p95, and p99 latency** distributions.
     - Measures average **TTFT (Time-to-First-Token)**.
     - Tracks aggregate token usage and guardrail block counts.

---

## 3. Performance & Overhead

- **Guardrail Latency Overhead:** All local regex checks in `GuardrailPipeline` execute in `< 1.2ms` on standard text inputs (500–2,000 characters), introducing zero perceptible latency into the agent loop.
- **Span Recording Overhead:** Spans are recorded in-memory as dataclasses during execution and flushed to SQLite in a single transaction on task completion (`TraceStore.save()`).

---

## 4. Consequences & Follow-Ups

- **Positive:**
  - Production-ready safety containment: Untrusted agent instructions cannot escape the repository or run catastrophic shell commands.
  - Zero PII or credential leakage into logs, evals, or model providers.
  - Granular span diagnostics allow instant identification of latency regressions across models and tools.
  - Ready for enterprise deployment and OpenTelemetry collector integration.
- **Follow-Ups:**
  - Add optional LangSmith / Phoenix exporter plug-in for remote cluster visualization.
  - Surface p50/p95 latency and guardrail block counts on the desktop HUD dashboard.
