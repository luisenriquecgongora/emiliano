"""
Production Reliability, Concurrency, and Prompt Caching Engine for Emiliano.

Designed for digital-native scale and enterprise-grade SLA requirements:
1. TokenBucketRateLimiter: High-concurrency dual-constraint rate limiter (RPM + TPM)
   with non-blocking async token replenishment.
2. RetryPolicy: Exponential backoff with Full Jitter and Decorrelated Jitter algorithms
   (AWS & OpenAI standard) for resilient recovery from HTTP 429 and transient 5xx errors.
3. CircuitBreaker: Fast-fail state machine (CLOSED -> OPEN -> HALF_OPEN) preventing
   thundering herd and latency cascade when upstream provider endpoints degrade.
4. PromptCacheOptimizer: Enforces prefix stability architecture for OpenAI & Anthropic
   prompt caching (>= 1,024 tokens), ensuring up to 80% TTFT reduction and 50% cost savings.
5. SemanticCache: High-performance LRU memory cache with canonical request hashing and TTL.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("emiliano")

T = TypeVar("T")


# --- 1. Token Bucket Rate Limiter (RPM & TPM) --------------------------------


class TokenBucketRateLimiter:
    """
    Dual-constraint token bucket rate limiter tracking both:
    - Requests Per Minute (RPM)
    - Tokens Per Minute (TPM)
    Smooths traffic spikes and prevents HTTP 429 Rate Limit Exceeded errors.
    """

    def __init__(
        self,
        requests_per_minute: int = 500,
        tokens_per_minute: int = 60_000,
        max_burst_factor: float = 1.0,
    ):
        self.rpm = max(1, requests_per_minute)
        self.tpm = max(1, tokens_per_minute)

        # Capacity caps
        self.max_requests = float(self.rpm * max_burst_factor)
        self.max_tokens = float(self.tpm * max_burst_factor)

        # Current balances
        self.request_tokens = self.max_requests
        self.token_balance = self.max_tokens

        # Refill rates per second
        self.rpm_fill_rate = self.rpm / 60.0
        self.tpm_fill_rate = self.tpm / 60.0

        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()

    def _replenish(self) -> None:
        """Replenishes request and token balances based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self.last_update
        self.last_update = now

        self.request_tokens = min(self.max_requests, self.request_tokens + (elapsed * self.rpm_fill_rate))
        self.token_balance = min(self.max_tokens, self.token_balance + (elapsed * self.tpm_fill_rate))

    async def acquire(self, estimated_tokens: int = 500, timeout: float = 60.0) -> float:
        """
        Asynchronously waits until sufficient RPM and TPM capacity is available.
        Returns the duration waited in seconds.
        """
        start_time = time.monotonic()
        while True:
            async with self._lock:
                self._replenish()

                has_request = self.request_tokens >= 1.0
                has_tokens = self.token_balance >= estimated_tokens

                if has_request and has_tokens:
                    self.request_tokens -= 1.0
                    self.token_balance -= estimated_tokens
                    return round(time.monotonic() - start_time, 3)

                # Calculate required sleep duration to refill deficit
                req_deficit = max(0.0, 1.0 - self.request_tokens)
                tok_deficit = max(0.0, float(estimated_tokens) - self.token_balance)

                wait_req = req_deficit / self.rpm_fill_rate if self.rpm_fill_rate > 0 else 0.1
                wait_tok = tok_deficit / self.tpm_fill_rate if self.tpm_fill_rate > 0 else 0.1
                wait_needed = max(0.01, min(1.0, max(wait_req, wait_tok)))

            if (time.monotonic() - start_time) + wait_needed > timeout:
                raise TimeoutError(f"Rate limiter timed out waiting for capacity after {timeout}s.")

            await asyncio.sleep(wait_needed)


# --- 2. Jittered Exponential Backoff Retry Policy ---------------------------


class RetryPolicy:
    """
    Exponential backoff with Full Jitter and Decorrelated Jitter algorithms.
    Recommended by AWS & OpenAI Architecture guidelines to break retry synchronization.
    """

    TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}

    def __init__(
        self,
        max_retries: int = 4,
        base_delay_s: float = 0.5,
        max_delay_s: float = 30.0,
        jitter_mode: str = "full",  # "full" | "decorrelated"
    ):
        self.max_retries = max_retries
        self.base_delay_s = base_delay_s
        self.max_delay_s = max_delay_s
        self.jitter_mode = jitter_mode

    def compute_delay(self, attempt: int, previous_delay: float = 0.0) -> float:
        """Computes randomized backoff sleep duration."""
        if self.jitter_mode == "decorrelated":
            # Decorrelated Jitter: sleep = min(max_delay, random(base_delay, prev_delay * 3))
            high = max(self.base_delay_s, previous_delay * 3.0)
            delay = random.uniform(self.base_delay_s, min(self.max_delay_s, high))
        else:
            # Full Jitter: sleep = random(0, min(max_delay, base * 2^attempt))
            cap = min(self.max_delay_s, self.base_delay_s * (2 ** attempt))
            delay = random.uniform(0.0, cap)

        return round(delay, 3)

    def is_transient_error(self, exc: Exception) -> bool:
        """Determines if exception is an operational transient network/rate failure."""
        text = str(exc).lower()
        if any(code in text for code in ["429", "500", "502", "503", "504", "rate limit", "overloaded", "busy"]):
            return True
        if any(err in text for err in ["timeout", "connection reset", "broken pipe", "connecterror"]):
            return True
        return False

    async def execute(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Executes an async callable with automatic retries and jittered backoff."""
        prev_delay = self.base_delay_s
        for attempt in range(self.max_retries + 1):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                if attempt >= self.max_retries or not self.is_transient_error(e):
                    raise
                delay = self.compute_delay(attempt, previous_delay=prev_delay)
                prev_delay = delay
                logger.warning(f"[RetryPolicy] Transient error '{e}'. Retrying in {delay}s (Attempt {attempt + 1}/{self.max_retries})...")
                await asyncio.sleep(delay)


# --- 3. Circuit Breaker -----------------------------------------------------


class CircuitState(str, Enum):
    CLOSED = "CLOSED"      # Normal operation: traffic passes
    OPEN = "OPEN"          # Failing: fast-fails requests without waiting
    HALF_OPEN = "HALF_OPEN"  # Testing canary request to verify recovery


class CircuitBreaker:
    """
    Prevents cascading latency failures by cutting off traffic to a repeatedly failing model.
    """

    def __init__(
        self,
        name: str = "default_circuit",
        failure_threshold: int = 4,
        recovery_timeout_s: float = 20.0,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout_s = recovery_timeout_s

        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0.0
        self._lock = asyncio.Lock()

    def is_available(self) -> bool:
        """Checks if calls are currently permitted."""
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            now = time.monotonic()
            if now - self.last_failure_time >= self.recovery_timeout_s:
                self.state = CircuitState.HALF_OPEN
                logger.info(f"[CircuitBreaker:{self.name}] Transitioning to HALF_OPEN (probing recovery).")
                return True
            return False
        return True  # HALF_OPEN allows canary trial

    def record_success(self) -> None:
        """Records a successful response, resetting circuit to healthy CLOSED state."""
        self.failure_count = 0
        if self.state != CircuitState.CLOSED:
            logger.info(f"[CircuitBreaker:{self.name}] Service recovered. Transitioning to CLOSED.")
            self.state = CircuitState.CLOSED

    def record_failure(self) -> None:
        """Records a failure and trips the circuit to OPEN if threshold is crossed."""
        self.failure_count += 1
        self.last_failure_time = time.monotonic()
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.error(f"[CircuitBreaker:{self.name}] Tripped! State is now OPEN for {self.recovery_timeout_s}s.")


# --- 4. Prompt Caching Prefix Stability Optimizer ---------------------------


@dataclass
class PromptCacheMetrics:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    cache_hit_ratio: float = 0.0
    estimated_savings_usd: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class PromptCacheOptimizer:
    """
    Enforces prefix stability to trigger OpenAI and Anthropic Prompt Caching.

    OpenAI Caching Rule: Prompts with >= 1,024 tokens that share an identical prefix
    automatically receive a 50% prompt discount and up to 80% lower TTFT.
    Dynamic variables (timestamps, volatile seeds) must never be in the prefix.
    """

    MIN_CACHE_TOKENS = 1024
    # Approximate pricing: $2.50 per 1M input tokens for GPT-4o, 50% discount on cached tokens
    OPENAI_CACHED_DISCOUNT_PER_M = 1.25

    @classmethod
    def structure_messages(
        cls,
        system_instruction: str,
        tool_schemas: Optional[List[Dict[str, Any]]] = None,
        few_shot_examples: Optional[List[Dict[str, str]]] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        user_goal: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """
        Structures messages into an optimal cache-friendly order:
        [1. Static Anchor: System Prompt + Fixed Tool Definitions] ->
        [2. Static Examples: Few-Shot Demonstrations] ->
        [3. Dynamic Tail: Conversation History + Current User Goal]
        """
        messages: List[Dict[str, str]] = []

        # 1. Static Prefix Block
        static_block = system_instruction
        if tool_schemas:
            static_block += "\n\n### Available Tools & Schemas:\n" + json.dumps(tool_schemas, sort_keys=True)
        messages.append({"role": "system", "content": static_block})

        # 2. Few-shot demonstrations (cache stable)
        if few_shot_examples:
            messages.extend(few_shot_examples)

        # 3. Dynamic conversation tail
        if conversation_history:
            for m in conversation_history:
                if m.get("role") != "system":
                    messages.append(dict(m))

        if user_goal:
            messages.append({"role": "user", "content": user_goal})

        return messages

    @classmethod
    def extract_cache_metrics(cls, usage_data: Dict[str, Any]) -> PromptCacheMetrics:
        """
        Parses provider token usage dictionary, extracting cached token metrics.
        Supports OpenAI prompt_tokens_details.cached_tokens and Anthropic cache_read_input_tokens.
        """
        prompt_tokens = int(usage_data.get("prompt_tokens") or 0)
        completion_tokens = int(usage_data.get("completion_tokens") or 0)

        # 1. OpenAI cached tokens format
        cached_tokens = 0
        details = usage_data.get("prompt_tokens_details") or {}
        if isinstance(details, dict):
            cached_tokens = int(details.get("cached_tokens") or 0)

        # 2. Anthropic / litellm alternative format
        if not cached_tokens:
            cached_tokens = int(usage_data.get("cache_read_input_tokens") or 0)

        hit_ratio = round(cached_tokens / prompt_tokens, 3) if prompt_tokens > 0 else 0.0
        savings = round((cached_tokens / 1_000_000.0) * cls.OPENAI_CACHED_DISCOUNT_PER_M, 5)

        return PromptCacheMetrics(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
            cache_hit_ratio=hit_ratio,
            estimated_savings_usd=savings,
        )


# --- 5. Semantic Cache (In-Memory LRU) ---------------------------------------


class SemanticCache:
    """
    High-speed in-memory LRU cache for deterministic / idempotent agent inquiries.
    Slashes external API latency to 0ms for frequent queries.
    """

    def __init__(self, max_size: int = 500, ttl_seconds: float = 3600.0):
        self.max_size = max_size
        self.ttl = ttl_seconds
        self._cache: OrderedDict[str, Tuple[float, Any]] = OrderedDict()

    def _hash_key(self, model: str, messages: List[Dict[str, str]]) -> str:
        """Generates a SHA-256 canonical hash of the request."""
        serialized = json.dumps({"model": model, "messages": messages}, sort_keys=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def get(self, model: str, messages: List[Dict[str, str]]) -> Optional[Any]:
        """Retrieves cached result if present and within TTL."""
        key = self._hash_key(model, messages)
        if key not in self._cache:
            return None
        created_at, value = self._cache[key]
        if time.time() - created_at > self.ttl:
            del self._cache[key]
            return None
        self._cache.move_to_end(key)
        return value

    def set(self, model: str, messages: List[Dict[str, str]], value: Any) -> None:
        """Stores result in cache, evicting oldest item if over capacity."""
        key = self._hash_key(model, messages)
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = (time.time(), value)
        if len(self._cache) > self.max_size:
            self._cache.popitem(last=False)
