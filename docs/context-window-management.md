# Context Window Management

## Overview

Emiliano now includes **automatic context window management** to prevent context overflow in long conversations. This feature ensures that conversations can continue indefinitely without hitting model token limits.

## Problem Solved

Previously, after 3-4 messages in a conversation, the full conversation history would exceed the model's context window, causing:
- Context loss when switching between models
- Errors or degraded responses
- Inability to maintain long coding sessions

## Solution

The context window manager:
- **Counts tokens** in conversation history using tiktoken
- **Tracks model-specific limits** for Claude, GPT, Gemini, DeepSeek, and local models
- **Automatically truncates** history when approaching limits
- **Preserves critical context** (system messages, recent exchanges)
- **Logs truncation events** for transparency

## Configuration

### Default Settings

Context management is **enabled by default** with conservative settings:

```yaml
# In emiliano.yaml or ~/.emiliano/config.yaml
context:
  enabled: true                      # Enable automatic truncation
  max_tokens: null                   # Use model's default limit
  truncation_strategy: "sliding_window"  # Strategy: "sliding_window" or "drop_middle"
  safety_margin: 0.85                # Use 85% of context window
  reserve_tokens: 2000               # Reserve space for response
```

### Configuration Options

| Option | Type | Default | Description |
|:---|:---|:---|:---|
| `enabled` | bool | `true` | Enable/disable context management |
| `max_tokens` | int? | `null` | Override model's context limit |
| `truncation_strategy` | str | `"sliding_window"` | How to truncate: `"sliding_window"` or `"drop_middle"` |
| `safety_margin` | float | `0.85` | Fraction of context to use (0.0-1.0) |
| `reserve_tokens` | int | `2000` | Tokens reserved for model's response |

### Truncation Strategies

#### Sliding Window (Default)
- Keeps: System messages + most recent conversation turns
- Drops: Oldest conversation history first
- Best for: Ongoing work where recent context matters most

#### Drop Middle
- Keeps: System messages + early conversation + recent conversation
- Drops: Middle portion of conversation
- Best for: Long sessions where both initial context and recent work are important

## Model-Specific Limits

The context manager knows the limits for popular models:

| Model Family | Context Window | Notes |
|:---|:---|:---|
| Claude 3.x | 180,000 tokens | Claude 3.7, 3.5, 3.0 Sonnet/Opus/Haiku |
| GPT-4 Turbo | 120,000 tokens | |
| GPT-4 | 7,000 tokens | Original GPT-4 |
| Gemini 2.0 | 900,000 tokens | Gemini 2.0 Flash, 1.5 Pro/Flash |
| DeepSeek | 60,000 tokens | DeepSeek Chat/Coder |
| Qwen 2.5 | 30,000 tokens | Local Qwen models |

Unknown models default to **7,000 tokens** (conservative estimate).

## Usage Examples

### Example 1: Long Coding Session

```bash
# Start a conversation
emiliano chat

> User: Explain the dispatcher architecture
Assistant: [Provides explanation...]

> User: Now refactor the context manager
Assistant: [Refactors code...]

# ... 20 more exchanges ...

> User: Now add tests for everything we've built
Assistant: [Still has context from recent work, even after 20+ exchanges]
```

**Behind the scenes:**
- After message 5, truncation starts
- System prompt is always preserved
- Recent 10-15 exchanges are kept
- Oldest exchanges are dropped first
- User never notices the truncation

### Example 2: Custom Configuration

For working with a local model with limited context:

```yaml
# emiliano.yaml
context:
  enabled: true
  max_tokens: 4000           # Force smaller limit for local model
  truncation_strategy: "sliding_window"
  safety_margin: 0.80        # Use only 80% to be extra safe
  reserve_tokens: 1000       # Smaller reserve
```

### Example 3: Disable Context Management

For debugging or testing:

```yaml
# emiliano.yaml
context:
  enabled: false  # Send full history (may cause errors with long conversations)
```

## Monitoring

### Logs

When truncation occurs, you'll see log messages:

```
[INFO] Context truncated for Claude 3.7 Sonnet: 45 → 25 messages, saved 18234 tokens
```

### Debug Information

To see detailed token counts:

```python
from emiliano.core.context_manager import ContextWindowManager

manager = ContextWindowManager()
messages = [...]  # Your conversation history

# Check token count
total_tokens = manager.count_messages_tokens(messages)
print(f"Current conversation: {total_tokens} tokens")

# Test truncation
truncated, metadata = manager.truncate_history(messages, "anthropic/claude-3-7-sonnet")
print(f"Was truncated: {metadata['was_truncated']}")
print(f"Original: {metadata['original_count']} messages")
print(f"After: {metadata['truncated_count']} messages")
print(f"Saved: {metadata['tokens_saved']} tokens")
```

## Architecture

### Components

1. **ContextWindowManager** (`emiliano/core/context_manager.py`)
   - Token counting using tiktoken
   - Model limit lookup
   - Truncation algorithms

2. **ExecutionDispatcher** (`emiliano/core/dispatcher.py`)
   - Integrates context manager
   - Applies truncation before LLM calls
   - Logs truncation events

3. **Configuration** (`emiliano/core/config.py`)
   - `ContextConfig` class
   - Settings in `emiliano.yaml`

### Integration Points

Context management is applied:
- **Before every direct model call** (Ollama, Claude, GPT, Gemini, DeepSeek)
- **In the dispatcher's execute_task method**
- **Only when `context.enabled: true`**

Agent harnesses (Claude Code, Codex, etc.) manage their own context internally and are **not** affected by this truncation.

## Best Practices

### For Long Coding Sessions
1. Use `sliding_window` strategy (default)
2. Set `safety_margin: 0.85` (85% usage)
3. Check logs occasionally to see if truncation is happening

### For Research/Analysis Tasks
1. Consider `drop_middle` strategy to preserve both early and recent context
2. Increase `reserve_tokens` if model responses are long (e.g., 3000-4000)

### For Local Models
1. Set explicit `max_tokens` based on your model's actual limit
2. Use higher `safety_margin` (0.80-0.85) to avoid OOM errors
3. Monitor RAM usage during long sessions

### For Production Deployments
1. Keep `enabled: true` to prevent unexpected failures
2. Log truncation events to monitoring systems
3. Consider persisting full conversation history to database (future feature)

## Future Enhancements

Planned improvements (see `docs/future-horizons.md`):

1. **Intelligent Summarization** - Instead of dropping old messages, summarize them
2. **Conversation Persistence** - Save full history to SQLite database
3. **Semantic Importance Scoring** - Keep important messages, drop less relevant ones
4. **Cross-Harness Context Sharing** - "Unified Blackboard" for context exchange
5. **Automatic Context Recovery** - Resume conversations with restored context

## Troubleshooting

### "Context truncated" warnings every message

**Cause:** Your conversation is consistently near the limit.

**Solutions:**
- Use `/clear` to start fresh
- Reduce `safety_margin` to 0.90 (use more of the window)
- Switch to a model with larger context (e.g., Gemini 2.0)

### Model still returns errors about context length

**Cause:** Context management may be disabled or misconfigured.

**Solutions:**
- Check `emiliano.yaml` - ensure `context.enabled: true`
- Verify `max_tokens` isn't set too high
- Check that tiktoken is installed: `pip install tiktoken`

### Lost important early conversation context

**Cause:** `sliding_window` strategy drops oldest messages.

**Solutions:**
- Switch to `drop_middle` strategy
- Add key information to system prompt
- Use `/clear` and summarize manually when starting new topics

## Testing

Run the test suite:

```bash
cd packages/engine
pytest tests/test_context_manager.py -v
```

Expected output:
```
test_token_counting PASSED
test_message_token_counting PASSED
test_model_context_limits PASSED
test_no_truncation_needed PASSED
test_sliding_window_truncation PASSED
test_drop_middle_truncation PASSED
test_preserve_system_messages PASSED
test_empty_messages PASSED
test_custom_max_tokens PASSED
test_safety_margin PASSED
```

## References

- [Tiktoken Documentation](https://github.com/openai/tiktoken)
- [Anthropic Claude Context Windows](https://docs.anthropic.com/claude/docs/models-overview)
- [OpenAI Token Limits](https://platform.openai.com/docs/models)
- [Emiliano Future Roadmap](./future-horizons.md)
