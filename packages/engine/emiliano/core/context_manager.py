"""
Context Window Manager for Emiliano.
Manages conversation history truncation to fit within model context limits.
Prevents context overflow and ensures long conversations remain functional.
"""

from __future__ import annotations

import importlib.util
import os
from typing import Dict, List, Optional
from enum import Enum

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("emiliano")


def _litellm_tokenizers_dir() -> Optional[str]:
    """Folder of tiktoken encodings bundled with litellm, found without importing litellm."""
    spec = importlib.util.find_spec("litellm")
    for root in (spec.submodule_search_locations or []) if spec else []:
        path = os.path.join(root, "litellm_core_utils", "tokenizers")
        if os.path.isdir(path):
            return path
    return None


class TruncationStrategy(str, Enum):
    """Strategy for truncating conversation history."""
    SLIDING_WINDOW = "sliding_window"  # Keep most recent N messages
    SUMMARIZE_OLD = "summarize_old"     # Summarize dropped messages (future)
    DROP_MIDDLE = "drop_middle"         # Keep first + last, drop middle


# Model-specific context window limits (in tokens)
# Conservative estimates to account for system prompts and safety margin
MODEL_CONTEXT_LIMITS = {
    # Claude models
    "claude-3-7-sonnet": 180000,
    "claude-3-5-sonnet": 180000,
    "claude-3-opus": 180000,
    "claude-3-sonnet": 180000,
    "claude-3-haiku": 180000,
    "claude-2.1": 180000,
    "claude-2": 90000,
    "claude-instant": 90000,

    # OpenAI models
    "gpt-4-turbo": 120000,
    "gpt-4": 7000,
    "gpt-3.5-turbo": 15000,
    "gpt-3.5-turbo-16k": 15000,
    "o1-preview": 120000,
    "o1-mini": 120000,

    # Gemini models
    "gemini-2.0-flash": 900000,
    "gemini-1.5-pro": 900000,
    "gemini-1.5-flash": 900000,
    "gemini-pro": 30000,

    # DeepSeek models
    "deepseek-chat": 60000,
    "deepseek-coder": 60000,

    # Local models (conservative estimates)
    "qwen2.5-coder": 30000,
    "codestral": 30000,
    "mistral": 7000,
    "llama3": 7000,
    "llama3.1": 120000,
    "llama3.2": 120000,

    # Default fallback
    "default": 7000,
}


class ContextWindowManager:
    """
    Manages conversation history to prevent context window overflow.

    Features:
    - Token-aware truncation
    - Model-specific context limits
    - Multiple truncation strategies
    - Preserves system messages
    - Detailed logging
    """

    def __init__(
        self,
        max_tokens: Optional[int] = None,
        strategy: TruncationStrategy = TruncationStrategy.SLIDING_WINDOW,
        reserve_tokens: int = 2000,  # Reserve for response
        safety_margin: float = 0.85,  # Use 85% of context window
    ):
        """
        Initialize context window manager.

        Args:
            max_tokens: Maximum tokens (if None, inferred from model)
            strategy: Truncation strategy to use
            reserve_tokens: Tokens to reserve for model response
            safety_margin: Fraction of context window to use (0.0-1.0)
        """
        self.max_tokens = max_tokens
        self.strategy = strategy
        self.reserve_tokens = reserve_tokens
        self.safety_margin = safety_margin
        self._tiktoken_encoder = None
        self._encoder_unavailable = False  # set once loading failed, so it is not retried per call

    def _get_encoder(self):
        """Lazy-load the cl100k_base encoder, or None to estimate from characters.
        tiktoken downloads the encoding on first use; litellm ships a copy, so point tiktoken's cache
        at it to work offline. Locating litellm does not import it (that takes ~15 s)."""
        if self._tiktoken_encoder is None and not self._encoder_unavailable:
            try:
                bundled = _litellm_tokenizers_dir()
                if bundled and "TIKTOKEN_CACHE_DIR" not in os.environ:
                    os.environ["TIKTOKEN_CACHE_DIR"] = bundled  # what importing litellm would set too
                import tiktoken
                self._tiktoken_encoder = tiktoken.get_encoding("cl100k_base")
            except Exception as e:  # not installed, or offline with no cached encoding
                logger.warning(f"No tokenizer available ({e}). Using character-based estimation (less accurate).")
                self._encoder_unavailable = True
        return self._tiktoken_encoder

    def count_tokens(self, text: str) -> int:
        """
        Count tokens in text.

        Args:
            text: Text to count tokens for

        Returns:
            Estimated token count
        """
        encoder = self._get_encoder()
        if encoder:
            return len(encoder.encode(text))
        else:
            # Fallback: rough estimate (1 token ≈ 4 characters for English)
            return len(text) // 4

    def count_message_tokens(self, message: Dict[str, str]) -> int:
        """
        Count tokens in a single message.

        Args:
            message: Message dict with 'role' and 'content'

        Returns:
            Token count including message formatting overhead
        """
        # Account for message formatting tokens
        # Format: <role>\n<content>\n
        overhead = 4  # Approximate overhead per message
        content = message.get("content", "")
        role = message.get("role", "")
        return self.count_tokens(content) + self.count_tokens(role) + overhead

    def count_messages_tokens(self, messages: List[Dict[str, str]]) -> int:
        """
        Count total tokens in message list.

        Args:
            messages: List of message dicts

        Returns:
            Total token count
        """
        return sum(self.count_message_tokens(msg) for msg in messages)

    def get_model_context_limit(self, model_id: str) -> int:
        """
        Get context window limit for a specific model.

        Args:
            model_id: Model identifier (e.g., "anthropic/claude-3-7-sonnet")

        Returns:
            Context limit in tokens
        """
        if self.max_tokens:
            return self.max_tokens

        # Extract model name from provider-qualified ID
        model_name = model_id.split("/")[-1].lower()

        # Try exact match first
        if model_name in MODEL_CONTEXT_LIMITS:
            return MODEL_CONTEXT_LIMITS[model_name]

        # Try partial match (e.g., "claude-3-7-sonnet-20250219" → "claude-3-7-sonnet")
        for key in MODEL_CONTEXT_LIMITS:
            if key in model_name or model_name.startswith(key):
                return MODEL_CONTEXT_LIMITS[key]

        # Default fallback
        logger.warning(f"Unknown model '{model_id}', using default context limit of {MODEL_CONTEXT_LIMITS['default']} tokens")
        return MODEL_CONTEXT_LIMITS["default"]

    def truncate_history(
        self,
        messages: List[Dict[str, str]],
        model_id: str,
    ) -> tuple[List[Dict[str, str]], Dict[str, any]]:
        """
        Truncate conversation history to fit within model's context window.

        Args:
            messages: Full conversation history
            model_id: Model identifier

        Returns:
            Tuple of (truncated_messages, metadata)
            metadata includes: original_count, truncated_count, tokens_saved, was_truncated
        """
        if not messages:
            return messages, {
                "original_count": 0,
                "truncated_count": 0,
                "tokens_saved": 0,
                "was_truncated": False,
            }

        # Calculate limits
        context_limit = self.get_model_context_limit(model_id)
        # Never reserve more than a quarter of the window for the reply; a fixed reserve
        # larger than a small window made the budget negative and dropped almost everything
        reserve = min(self.reserve_tokens, context_limit // 4)
        effective_limit = int(context_limit * self.safety_margin) - reserve

        # Count current tokens
        current_tokens = self.count_messages_tokens(messages)

        # No truncation needed
        if current_tokens <= effective_limit:
            logger.debug(
                f"Context OK: {current_tokens}/{effective_limit} tokens "
                f"({len(messages)} messages) for {model_id}"
            )
            return messages, {
                "original_count": len(messages),
                "truncated_count": len(messages),
                "tokens_saved": 0,
                "was_truncated": False,
            }

        # Truncation needed
        logger.info(
            f"Context overflow detected: {current_tokens}/{effective_limit} tokens. "
            f"Truncating {len(messages)} messages..."
        )

        # Apply truncation strategy
        if self.strategy == TruncationStrategy.SLIDING_WINDOW:
            truncated = self._truncate_sliding_window(messages, effective_limit)
        elif self.strategy == TruncationStrategy.DROP_MIDDLE:
            truncated = self._truncate_drop_middle(messages, effective_limit)
        else:
            # Fallback to sliding window
            truncated = self._truncate_sliding_window(messages, effective_limit)

        tokens_after = self.count_messages_tokens(truncated)
        tokens_saved = current_tokens - tokens_after

        logger.info(
            f"Context truncated: {len(messages)} → {len(truncated)} messages, "
            f"{current_tokens} → {tokens_after} tokens (saved {tokens_saved})"
        )

        return truncated, {
            "original_count": len(messages),
            "truncated_count": len(truncated),
            "tokens_saved": tokens_saved,
            "was_truncated": True,
        }

    def _truncate_sliding_window(
        self,
        messages: List[Dict[str, str]],
        token_limit: int,
    ) -> List[Dict[str, str]]:
        """
        Sliding window: Keep system message + most recent messages that fit.

        Args:
            messages: Full message history
            token_limit: Maximum tokens allowed

        Returns:
            Truncated message list
        """
        # Always preserve system messages (role == "system")
        system_messages = [msg for msg in messages if msg.get("role") == "system"]
        other_messages = [msg for msg in messages if msg.get("role") != "system"]

        # Start with system messages
        result = system_messages.copy()
        current_tokens = self.count_messages_tokens(result)

        # Add messages from most recent backwards
        for msg in reversed(other_messages):
            msg_tokens = self.count_message_tokens(msg)
            if current_tokens + msg_tokens <= token_limit:
                result.insert(len(system_messages), msg)  # Insert after system messages
                current_tokens += msg_tokens
            else:
                break

        return result

    def _truncate_drop_middle(
        self,
        messages: List[Dict[str, str]],
        token_limit: int,
    ) -> List[Dict[str, str]]:
        """
        Drop middle: Keep system + first few + last few messages.
        Useful for preserving conversation context and recent discussion.

        Args:
            messages: Full message history
            token_limit: Maximum tokens allowed

        Returns:
            Truncated message list
        """
        # Preserve system messages
        system_messages = [msg for msg in messages if msg.get("role") == "system"]
        other_messages = [msg for msg in messages if msg.get("role") != "system"]

        if len(other_messages) <= 4:
            # Too few messages to drop middle
            return self._truncate_sliding_window(messages, token_limit)

        # Allocate: 50% to first messages, 50% to last messages
        half_limit = (token_limit - self.count_messages_tokens(system_messages)) // 2

        # Collect first messages
        first_messages = []
        first_tokens = 0
        for msg in other_messages[:len(other_messages)//2]:
            msg_tokens = self.count_message_tokens(msg)
            if first_tokens + msg_tokens <= half_limit:
                first_messages.append(msg)
                first_tokens += msg_tokens
            else:
                break

        # Collect last messages
        last_messages = []
        last_tokens = 0
        for msg in reversed(other_messages[len(other_messages)//2:]):
            msg_tokens = self.count_message_tokens(msg)
            if last_tokens + msg_tokens <= half_limit:
                last_messages.insert(0, msg)
                last_tokens += msg_tokens
            else:
                break

        # Add truncation indicator
        if len(first_messages) + len(last_messages) < len(other_messages):
            dropped_count = len(other_messages) - len(first_messages) - len(last_messages)
            truncation_notice = {
                "role": "system",
                "content": f"[Context truncated: {dropped_count} messages omitted from middle of conversation]"
            }
            result = system_messages + first_messages + [truncation_notice] + last_messages
        else:
            result = system_messages + first_messages + last_messages

        return result
