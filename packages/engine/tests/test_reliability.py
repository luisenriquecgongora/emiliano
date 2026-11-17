"""
Unit tests for Production Reliability, Concurrency Rate Limiting,
Retry Policies, Circuit Breakers, and Prompt Caching Optimization.
"""

import time
import unittest

from emiliano.core.reliability import (
    CircuitBreaker,
    CircuitState,
    PromptCacheOptimizer,
    RetryPolicy,
    SemanticCache,
    TokenBucketRateLimiter,
)


class TestTokenBucketRateLimiter(unittest.IsolatedAsyncioTestCase):
    async def test_acquire_within_capacity(self):
        limiter = TokenBucketRateLimiter(requests_per_minute=600, tokens_per_minute=60_000)
        # First 5 acquisitions should complete with negligible latency (< 50ms)
        for _ in range(5):
            waited = await limiter.acquire(estimated_tokens=500, timeout=2.0)
            self.assertLess(waited, 0.05)

    async def test_acquire_blocks_when_capacity_exhausted(self):
        # Very low capacity: 2 requests per minute = 1 every 30s
        limiter = TokenBucketRateLimiter(requests_per_minute=2, tokens_per_minute=1000)
        # Drain the 2 available burst requests
        await limiter.acquire(estimated_tokens=100)
        await limiter.acquire(estimated_tokens=100)

        # 3rd request must wait or timeout
        with self.assertRaises(TimeoutError):
            await limiter.acquire(estimated_tokens=100, timeout=0.1)


class TestRetryPolicy(unittest.IsolatedAsyncioTestCase):
    def test_jittered_delay_bounds(self):
        policy = RetryPolicy(base_delay_s=0.5, max_delay_s=10.0, jitter_mode="full")
        for attempt in range(5):
            delay = policy.compute_delay(attempt)
            self.assertGreaterEqual(delay, 0.0)
            self.assertLessEqual(delay, min(10.0, 0.5 * (2 ** attempt)))

    def test_decorrelated_jitter_bounds(self):
        policy = RetryPolicy(base_delay_s=0.5, max_delay_s=8.0, jitter_mode="decorrelated")
        prev = 1.0
        for _ in range(10):
            delay = policy.compute_delay(attempt=1, previous_delay=prev)
            self.assertGreaterEqual(delay, 0.5)
            self.assertLessEqual(delay, 8.0)
            prev = delay

    async def test_retry_on_transient_error(self):
        policy = RetryPolicy(max_retries=3, base_delay_s=0.01)
        calls = 0

        async def flaky_operation():
            nonlocal calls
            calls += 1
            if calls < 3:
                raise RuntimeError("HTTP 429 Rate limit exceeded. Please retry.")
            return "success"

        res = await policy.execute(flaky_operation)
        self.assertEqual(res, "success")
        self.assertEqual(calls, 3)

    async def test_immediate_fail_on_non_transient_error(self):
        policy = RetryPolicy(max_retries=3, base_delay_s=0.01)
        calls = 0

        async def fatal_operation():
            nonlocal calls
            calls += 1
            raise ValueError("Invalid parameter schema")

        with self.assertRaises(ValueError):
            await policy.execute(fatal_operation)
        self.assertEqual(calls, 1)


class TestCircuitBreaker(unittest.TestCase):
    def test_circuit_trips_after_failures_and_recovers(self):
        breaker = CircuitBreaker(name="test_llm", failure_threshold=3, recovery_timeout_s=0.05)
        self.assertEqual(breaker.state, CircuitState.CLOSED)
        self.assertTrue(breaker.is_available())

        # Record 2 failures -> remains closed
        breaker.record_failure()
        breaker.record_failure()
        self.assertEqual(breaker.state, CircuitState.CLOSED)

        # 3rd failure -> trips to OPEN
        breaker.record_failure()
        self.assertEqual(breaker.state, CircuitState.OPEN)
        self.assertFalse(breaker.is_available())

        # Wait for recovery timeout
        time.sleep(0.1)
        # Should now allow canary call (HALF_OPEN)
        self.assertTrue(breaker.is_available())
        self.assertEqual(breaker.state, CircuitState.HALF_OPEN)

        # Successful canary resets circuit to CLOSED
        breaker.record_success()
        self.assertEqual(breaker.state, CircuitState.CLOSED)
        self.assertEqual(breaker.failure_count, 0)


class TestPromptCacheOptimizer(unittest.TestCase):
    def test_structure_messages_anchor_prefix(self):
        system = "You are an autonomous engineering agent."
        tools = [{"name": "read_file", "parameters": {"path": "str"}}]
        history = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        goal = "Refactor the database module"

        messages = PromptCacheOptimizer.structure_messages(
            system_instruction=system,
            tool_schemas=tools,
            conversation_history=history,
            user_goal=goal,
        )

        self.assertEqual(len(messages), 4)
        # First message MUST be the static anchor block
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("### Available Tools & Schemas", messages[0]["content"])
        self.assertIn("read_file", messages[0]["content"])
        # Dynamic goal must be at tail
        self.assertEqual(messages[-1]["role"], "user")
        self.assertEqual(messages[-1]["content"], goal)

    def test_extract_cache_metrics(self):
        usage_data = {
            "prompt_tokens": 4000,
            "completion_tokens": 500,
            "prompt_tokens_details": {"cached_tokens": 3000},
        }
        metrics = PromptCacheOptimizer.extract_cache_metrics(usage_data)
        self.assertEqual(metrics.prompt_tokens, 4000)
        self.assertEqual(metrics.cached_tokens, 3000)
        self.assertEqual(metrics.cache_hit_ratio, 0.75)
        self.assertGreater(metrics.estimated_savings_usd, 0.0)


class TestSemanticCache(unittest.TestCase):
    def test_cache_hit_and_ttl_expiration(self):
        cache = SemanticCache(max_size=2, ttl_seconds=0.05)
        msgs = [{"role": "user", "content": "ping"}]

        cache.set("gpt-4o", msgs, "pong")
        self.assertEqual(cache.get("gpt-4o", msgs), "pong")

        # Wait for TTL to expire
        time.sleep(0.06)
        self.assertIsNone(cache.get("gpt-4o", msgs))

    def test_cache_lru_eviction(self):
        cache = SemanticCache(max_size=2, ttl_seconds=10.0)
        m1 = [{"role": "user", "content": "1"}]
        m2 = [{"role": "user", "content": "2"}]
        m3 = [{"role": "user", "content": "3"}]

        cache.set("model", m1, "res1")
        cache.set("model", m2, "res2")
        # Access m1 so m2 becomes the oldest
        _ = cache.get("model", m1)
        # Insert m3 -> should evict m2
        cache.set("model", m3, "res3")

        self.assertIsNotNone(cache.get("model", m1))
        self.assertIsNone(cache.get("model", m2))
        self.assertIsNotNone(cache.get("model", m3))


if __name__ == "__main__":
    unittest.main()
