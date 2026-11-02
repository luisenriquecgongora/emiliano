"""
Context metrics collection and visualization.
Implements IContextMetrics interface.
"""

from typing import List, Dict, Optional

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("emiliano")

from ..base import ContextMetrics, ITokenCounter


class ContextMetricsCollector:
    """
    Collects and formats context usage metrics.

    Single Responsibility: Track context token usage across components.
    Dependency Inversion: Depends on ITokenCounter abstraction.
    """

    def __init__(self, token_counter: ITokenCounter):
        """
        Initialize metrics collector.

        Args:
            token_counter: Token counter implementation
        """
        self.token_counter = token_counter

    def collect_metrics(
        self,
        messages: List[Dict[str, str]],
        model_id: str,
        model_context_limit: int,
        additional_context: Optional[Dict[str, int]] = None,
    ) -> ContextMetrics:
        """
        Collect metrics about current context state.

        Args:
            messages: Current message history
            model_id: Model identifier
            model_context_limit: Context window limit for model
            additional_context: Additional token counts (files, repo_map, etc.)

        Returns:
            ContextMetrics object with usage statistics
        """
        # Separate messages by role
        system_messages = [m for m in messages if m.get("role") == "system"]
        history_messages = [m for m in messages if m.get("role") != "system"]

        # Count tokens
        system_tokens = self.token_counter.count_messages_tokens(system_messages)
        history_tokens = self.token_counter.count_messages_tokens(history_messages)
        total_tokens = system_tokens + history_tokens

        # Additional context (files, repo map, persistent)
        file_tokens = additional_context.get("files", 0) if additional_context else 0
        repo_map_tokens = additional_context.get("repo_map", 0) if additional_context else 0
        persistent_tokens = additional_context.get("persistent", 0) if additional_context else 0

        # Calculate totals
        grand_total = total_tokens + file_tokens + repo_map_tokens + persistent_tokens
        available_tokens = max(0, model_context_limit - grand_total)
        usage_percentage = (grand_total / model_context_limit * 100) if model_context_limit > 0 else 0

        # Count truncations/summaries from system messages
        truncated_count = sum(1 for m in system_messages if "[Context truncated:" in m.get("content", ""))
        summarized_count = sum(1 for m in system_messages if "[Conversation summary:" in m.get("content", ""))

        return ContextMetrics(
            total_tokens=grand_total,
            history_tokens=history_tokens,
            system_tokens=system_tokens,
            file_tokens=file_tokens,
            repo_map_tokens=repo_map_tokens,
            persistent_tokens=persistent_tokens,
            available_tokens=available_tokens,
            max_tokens=model_context_limit,
            usage_percentage=usage_percentage,
            message_count=len(messages),
            truncated_count=truncated_count,
            summarized_count=summarized_count,
        )

    def format_metrics(self, metrics: ContextMetrics, model_name: str = "current model") -> str:
        """
        Format metrics for CLI display.

        Args:
            metrics: Metrics to format
            model_name: Model name for display

        Returns:
            Formatted string with visual indicators
        """
        # Create progress bar for usage
        bar_width = 40
        filled = int(bar_width * metrics.usage_percentage / 100)
        bar = "█" * filled + "░" * (bar_width - filled)

        # Color coding based on usage
        if metrics.usage_percentage > 90:
            status = "⚠️  CRITICAL"
        elif metrics.usage_percentage > 75:
            status = "⚡ HIGH"
        elif metrics.usage_percentage > 50:
            status = "✓ MODERATE"
        else:
            status = "✓ GOOD"

        output = [
            "",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"  CONTEXT WINDOW USAGE - {model_name}",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            f"  Total Usage:    {metrics.total_tokens:,} / {metrics.max_tokens:,} tokens",
            f"  Available:      {metrics.available_tokens:,} tokens",
            f"  Percentage:     {metrics.usage_percentage:.1f}%  {status}",
            "",
            f"  [{bar}]",
            "",
            "  Breakdown:",
            f"    • Conversation History:  {metrics.history_tokens:,} tokens ({len([m for m in range(metrics.message_count)])} messages)",
            f"    • System Prompts:        {metrics.system_tokens:,} tokens",
            f"    • Files in Context:      {metrics.file_tokens:,} tokens",
            f"    • Repository Map:        {metrics.repo_map_tokens:,} tokens",
            f"    • Persistent Context:    {metrics.persistent_tokens:,} tokens",
            "",
        ]

        # Add optimization info
        if metrics.truncated_count > 0 or metrics.summarized_count > 0:
            output.append("  Optimizations Applied:")
            if metrics.truncated_count > 0:
                output.append(f"    • Truncations: {metrics.truncated_count}")
            if metrics.summarized_count > 0:
                output.append(f"    • Summarizations: {metrics.summarized_count}")
            output.append("")

        # Add recommendations
        if metrics.usage_percentage > 90:
            output.extend([
                "  💡 Recommendations:",
                "    • Run /clear to reset conversation",
                "    • Enable summarization to compress history",
                "    • Remove unnecessary files from context",
                "",
            ])
        elif metrics.usage_percentage > 75:
            output.extend([
                "  💡 Tip: Consider using /compact to summarize old history",
                "",
            ])

        output.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        return "\n".join(output)
