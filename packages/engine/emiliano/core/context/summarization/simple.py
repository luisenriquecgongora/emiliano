"""
Simple truncation strategy (fallback when summarization unavailable).
"""

from typing import List, Dict, Optional

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("emiliano")


class SimpleTruncator:
    """
    Simple truncation without LLM summarization.
    Fallback strategy when summarization is disabled or fails.

    Single Responsibility: Truncate messages to fit budget.
    """

    async def summarize(
        self,
        messages: List[Dict[str, str]],
        max_output_tokens: int = 500,
        context: Optional[str] = None,
    ) -> Dict[str, str]:
        """
        Create a simple truncation notice.

        Args:
            messages: Messages that were truncated
            max_output_tokens: Ignored (not used)
            context: Optional context

        Returns:
            System message indicating truncation
        """
        count = len(messages)
        return {
            "role": "system",
            "content": f"[Context truncated: {count} older messages removed to fit context window]"
        }

    async def should_summarize(
        self,
        messages: List[Dict[str, str]],
        threshold_tokens: int,
    ) -> bool:
        """Always returns False since this is pure truncation."""
        return False
