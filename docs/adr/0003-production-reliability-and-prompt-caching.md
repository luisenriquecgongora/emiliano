# 0003. Production Reliability, Rate Limiting, and Prompt Caching Optimization

- **Status:** Accepted (2026-11-17)
- **Date:** 2026-11-17
- **Target Role Alignment:** OpenAI Applied AI Engineer (Digital Natives) — Reliability, Latency & Cost Engineering

---

## 1. Context

High-growth digital native technology companies face severe operational bottlenecks when deploying autonomous agents and frontier LLMs into production:

1. **Rate Limiting Cascades (HTTP 429):**
   When autonomous multi-turn agents loop through repositories or execute parallel subtasks, unmetered requests instantly exceed provider tier limits (RPM and TPM), causing burst failures, thundering herds, and task crashes.

2. **Latency & Cost Inefficiencies:**
   Prompt context in agentic workflows grows rapidly with system instructions, tool definitions, and file buffers. Without prefix stability, the provider re-processes the entire prompt from scratch on every turn, inflating Time-To-First-Token (TTFT) and token spend.

3. **Cascading Endpoint Failures:**
   When an upstream model endpoint experiences partial degradation or high latency, downstream applications experience timeout pileups without an automated circuit breaker to fast-fail or switch to fallback models.

---

## 2. Decision

We implement a complete production reliability suite in [`emiliano/core/reliability.py`](file:///C:/Users/artlu/OracliomNew/Oracliom/emiliano/packages/engine/emiliano/core/reliability.py) wired directly into [`UnifiedLLMClient`](file:///C:/Users/artlu/OracliomNew/Oracliom/emiliano/packages/engine/emiliano/direct/client.py):

```
+-----------------------------------------------------------------------------------------+
|                                Request Dispatcher                                       |
+-----------------------------------------------------------------------------------------+
                                             |
                                             v
+-----------------------------------------------------------------------------------------+
|                          1. TokenBucketRateLimiter (RPM & TPM)                          |
|  • Tracks Dual Constraints: Requests Per Minute (RPM) & Tokens Per Minute (TPM)         |
|  • Non-blocking async token replenishment smoothing traffic bursts                      |
+-----------------------------------------------------------------------------------------+
                                             |
                                             v
+-----------------------------------------------------------------------------------------+
|                          2. CircuitBreaker State Machine                                |
|  • CLOSED (Healthy) -> OPEN (Tripped after N failures) -> HALF_OPEN (Canary probe)       |
|  • Fast-fails immediately in < 1ms to activate fallback models without timeout pileup   |
+-----------------------------------------------------------------------------------------+
                                             |
                                             v
+-----------------------------------------------------------------------------------------+
|                          3. PromptCacheOptimizer (Prefix Stability)                     |
|  • Locks Static Prefix: System Prompt + Fixed Tool Schemas (>= 1,024 tokens)           |
|  • Keeps dynamic turn context strictly at the message tail                              |
|  • Automatic 50% discount on cached tokens + up to 80% TTFT reduction                   |
|  • Tracks usage.prompt_tokens_details.cached_tokens in telemetry spans                  |
+-----------------------------------------------------------------------------------------+
                                             |
                                             v
+-----------------------------------------------------------------------------------------+
|                          4. RetryPolicy (Jittered Exponential Backoff)                   |
|  • Full Jitter & Decorrelated Jitter algorithms (AWS / OpenAI architecture standard)    |
|  • Retries transient HTTP 429, 500, 502, 503, 504 and connection resets                |
+-----------------------------------------------------------------------------------------+
```

---

## 3. Technical Specifications

### A. Token Bucket Rate Limiter
- Dual-constraint tracking:
  - `request_tokens` refilled at $\frac{\text{RPM}}{60}$ tokens/sec.
  - `token_balance` refilled at $\frac{\text{TPM}}{60}$ tokens/sec.
- Async `acquire(estimated_tokens)`: Sleeps cleanly without blocking the event loop until capacity is replenished.

### B. Jittered Exponential Backoff
- Implements Full Jitter:
  $$t_{\text{sleep}} = \text{random.uniform}(0, \min(t_{\text{max}}, t_{\text{base}} \times 2^{\text{attempt}}))$$
- Breaks synchronized retry waves across concurrent agent instances, preventing the "thundering herd" problem against OpenAI API gateways.

### C. Prompt Caching Prefix Architecture
- Enforces prefix stability:
  - Static instructions and complete JSON tool schemas are concatenated at message index `0`.
  - Prompts exceeding 1,024 tokens trigger OpenAI and Anthropic automatic prompt caching.
  - Telemetry spans record `cached_tokens` and compute real-time dollar savings ($1.25 per 1M cached tokens for GPT-4o).

---

## 4. Verification

The reliability suite was validated across 11 unit tests in [`tests/test_reliability.py`](file:///C:/Users/artlu/OracliomNew/Oracliom/emiliano/packages/engine/tests/test_reliability.py) with 100% pass rate:
- Verified burst capacity and rate limit backpressure under load.
- Verified exponential backoff recovery from simulated HTTP 429 errors.
- Verified circuit breaker tripping, timeout cooldown, and canary recovery.
- Verified prefix structuring and cached token extraction.
