"""Base classes for summarization strategies."""

from typing import List, Dict, Optional
from abc import ABC, abstractmethod


class BaseSummarizer(ABC):
    """
    Abstract base class for summarization strategies.

    Single Responsibility: Define summarization interface.
    Open/Closed: Extend with new strategies without modifying base.
    """

    @abstractmethod
    async def summarize(
        self,
        messages: List[Dict[str, str]],
        max_output_tokens: int = 500,
        context: Optional[str] = None,
    ) -> Dict[str, str]:
        """Summarize messages into a compact summary."""
        pass

    @abstractmethod
    async def should_summarize(
        self,
        messages: List[Dict[str, str]],
        threshold_tokens: int,
    ) -> bool:
        """Determine if summarization is needed."""
        pass
