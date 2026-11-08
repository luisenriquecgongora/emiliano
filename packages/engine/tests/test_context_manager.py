"""
Tests for context window management functionality.
"""

import pytest
from emiliano.core.context_manager import (
    ContextWindowManager,
    TruncationStrategy,
    MODEL_CONTEXT_LIMITS,
)


class TestContextWindowManager:
    """Test suite for ContextWindowManager."""

    def test_token_counting(self):
        """Test basic token counting functionality."""
        manager = ContextWindowManager()

        # Short text
        text = "Hello world"
        tokens = manager.count_tokens(text)
        assert tokens > 0
        assert tokens < 10  # Should be around 2-3 tokens

        # Long text
        long_text = "This is a much longer piece of text that contains many words and should result in more tokens being counted."
        long_tokens = manager.count_tokens(long_text)
        assert long_tokens > tokens
        assert long_tokens > 10

    def test_message_token_counting(self):
        """Test counting tokens in messages."""
        manager = ContextWindowManager()

        message = {"role": "user", "content": "Hello, how are you?"}
        tokens = manager.count_message_tokens(message)
        assert tokens > 0

        # System message should also work
        system_message = {"role": "system", "content": "You are a helpful assistant."}
        system_tokens = manager.count_message_tokens(system_message)
        assert system_tokens > 0

    def test_model_context_limits(self):
        """Test model-specific context limits."""
        manager = ContextWindowManager()

        # Test Claude models
        claude_limit = manager.get_model_context_limit("anthropic/claude-3-7-sonnet")
        assert claude_limit == 180000

        # Test OpenAI models
        gpt4_limit = manager.get_model_context_limit("openai/gpt-4-turbo")
        assert gpt4_limit == 120000

        # Test Gemini models
        gemini_limit = manager.get_model_context_limit("gemini/gemini-2.0-flash")
        assert gemini_limit == 900000

        # Test unknown model (should return default)
        unknown_limit = manager.get_model_context_limit("unknown/unknown-model")
        assert unknown_limit == MODEL_CONTEXT_LIMITS["default"]

    def test_no_truncation_needed(self):
        """Test that short conversations are not truncated."""
        manager = ContextWindowManager(max_tokens=10000)

        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello!"},
            {"role": "assistant", "content": "Hi there!"},
        ]

        truncated, metadata = manager.truncate_history(messages, "anthropic/claude-3-7-sonnet")

        assert len(truncated) == len(messages)
        assert metadata["was_truncated"] is False
        assert metadata["original_count"] == 3
        assert metadata["truncated_count"] == 3
        assert metadata["tokens_saved"] == 0

    def test_sliding_window_truncation(self):
        """Test sliding window truncation strategy."""
        manager = ContextWindowManager(
            max_tokens=100,  # Very small limit to force truncation
            strategy=TruncationStrategy.SLIDING_WINDOW,
        )

        # Create many messages to exceed limit
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
        ]
        for i in range(20):
            messages.append({"role": "user", "content": f"Question {i}: " + "x" * 50})
            messages.append({"role": "assistant", "content": f"Answer {i}: " + "y" * 50})

        truncated, metadata = manager.truncate_history(messages, "anthropic/claude-3-7-sonnet")

        # Should be truncated
        assert metadata["was_truncated"] is True
        assert len(truncated) < len(messages)
        assert metadata["tokens_saved"] > 0

        # System message should be preserved
        assert truncated[0]["role"] == "system"
        assert truncated[0]["content"] == "You are a helpful assistant."

        # Should keep most recent messages
        # The last user message should be in the truncated list
        user_messages_in_truncated = [m for m in truncated if m["role"] == "user"]
        assert any("Question 19" in m["content"] for m in user_messages_in_truncated)

    def test_drop_middle_truncation(self):
        """Test drop middle truncation strategy."""
        manager = ContextWindowManager(
            max_tokens=200,  # Small limit
            strategy=TruncationStrategy.DROP_MIDDLE,
        )

        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
        ]
        for i in range(15):
            messages.append({"role": "user", "content": f"Question {i}: " + "x" * 30})
            messages.append({"role": "assistant", "content": f"Answer {i}: " + "y" * 30})

        truncated, metadata = manager.truncate_history(messages, "anthropic/claude-3-7-sonnet")

        assert metadata["was_truncated"] is True
        assert len(truncated) < len(messages)

        # System message should be preserved
        assert truncated[0]["role"] == "system"

        # Should have early messages
        early_questions = [m for m in truncated if "Question 0" in m.get("content", "") or "Question 1" in m.get("content", "")]
        assert len(early_questions) > 0

        # Should have recent messages
        recent_questions = [m for m in truncated if "Question 14" in m.get("content", "") or "Question 13" in m.get("content", "")]
        assert len(recent_questions) > 0

    def test_preserve_system_messages(self):
        """Test that system messages are always preserved."""
        manager = ContextWindowManager(
            max_tokens=50,  # Very small limit
            strategy=TruncationStrategy.SLIDING_WINDOW,
        )

        messages = [
            {"role": "system", "content": "System instruction 1."},
            {"role": "system", "content": "System instruction 2."},
            {"role": "user", "content": "User message " + "x" * 100},
            {"role": "assistant", "content": "Assistant response " + "y" * 100},
        ]

        truncated, metadata = manager.truncate_history(messages, "anthropic/claude-3-7-sonnet")

        # All system messages should be preserved
        system_messages = [m for m in truncated if m["role"] == "system"]
        assert len(system_messages) == 2
        assert system_messages[0]["content"] == "System instruction 1."
        assert system_messages[1]["content"] == "System instruction 2."

    def test_empty_messages(self):
        """Test handling of empty message list."""
        manager = ContextWindowManager()

        truncated, metadata = manager.truncate_history([], "anthropic/claude-3-7-sonnet")

        assert len(truncated) == 0
        assert metadata["was_truncated"] is False
        assert metadata["original_count"] == 0
        assert metadata["truncated_count"] == 0

    def test_custom_max_tokens(self):
        """Test using custom max_tokens override."""
        manager = ContextWindowManager(max_tokens=5000)

        # Even for a model with large context, use the override
        limit = manager.get_model_context_limit("gemini/gemini-2.0-flash")
        assert limit == 5000

    def test_safety_margin(self):
        """Test that safety margin is applied correctly."""
        manager = ContextWindowManager(
            max_tokens=1000,
            safety_margin=0.5,  # Use only 50% of context
            reserve_tokens=100,
        )

        # Effective limit should be: 1000 * 0.5 - 100 = 400
        messages = [{"role": "user", "content": "x" * 500}]  # About 125 tokens

        # This should fit in raw context but not with safety margin
        truncated, metadata = manager.truncate_history(messages, "anthropic/claude-3-7-sonnet")

        # With strict safety margin, this might be truncated or close to limit
        # The key is that it respects the safety margin
        tokens = manager.count_messages_tokens(truncated)
        assert tokens <= 400  # Should respect effective limit


class TestOfflineTokenizer:
    """Token counting must work without internet access (local-first use)."""

    def test_loads_bundled_encoding_without_network(self, monkeypatch):
        import tiktoken.load
        import tiktoken.registry

        def no_network(url):
            raise OSError(f"offline: tried to download {url}")

        monkeypatch.delenv("TIKTOKEN_CACHE_DIR", raising=False)
        monkeypatch.setattr(tiktoken.registry, "ENCODINGS", {})  # forget encodings loaded by other tests
        monkeypatch.setattr(tiktoken.load, "read_file", no_network)
        manager = ContextWindowManager()
        assert manager._get_encoder() is not None
        assert manager.count_tokens("Hello world") == 2

    def test_falls_back_to_estimate_when_no_tokenizer_loads(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def failing_import(name, *args, **kwargs):
            if name == "tiktoken":
                raise OSError("offline: certificate verify failed")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", failing_import)
        manager = ContextWindowManager()
        assert manager.count_tokens("x" * 40) == 10
        assert manager.count_tokens("x" * 8) == 2  # loading is not retried, and still no error


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
