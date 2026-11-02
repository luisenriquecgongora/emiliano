"""
Base interfaces and protocols for context management system.
Implements SOLID principles through interface segregation.
"""

from typing import Protocol, List, Dict, Optional, Tuple
from abc import abstractmethod
from dataclasses import dataclass


@dataclass
class ContextMetrics:
    """Metrics about current context usage."""
    total_tokens: int
    history_tokens: int
    system_tokens: int
    file_tokens: int
    repo_map_tokens: int
    persistent_tokens: int
    available_tokens: int
    max_tokens: int
    usage_percentage: float
    message_count: int
    truncated_count: int = 0
    summarized_count: int = 0


@dataclass
class TruncationMetadata:
    """Metadata about truncation operation."""
    original_count: int
    truncated_count: int
    tokens_saved: int
    was_truncated: bool
    was_summarized: bool = False
    summary: Optional[str] = None


class ITokenCounter(Protocol):
    """
    Interface for token counting operations.

    Single Responsibility: Count tokens in text/messages.
    """

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """
        Count tokens in text.

        Args:
            text: Text to count tokens for

        Returns:
            Token count
        """
        ...

    @abstractmethod
    def count_message_tokens(self, message: Dict[str, str]) -> int:
        """
        Count tokens in a single message.

        Args:
            message: Message dict with 'role' and 'content'

        Returns:
            Token count including message overhead
        """
        ...

    @abstractmethod
    def count_messages_tokens(self, messages: List[Dict[str, str]]) -> int:
        """
        Count total tokens in message list.

        Args:
            messages: List of message dicts

        Returns:
            Total token count
        """
        ...


class ISummarizer(Protocol):
    """
    Interface for conversation summarization.

    Single Responsibility: Summarize conversation history.
    Open/Closed: Extend with new summarization strategies.
    """

    @abstractmethod
    async def summarize(
        self,
        messages: List[Dict[str, str]],
        max_output_tokens: int = 500,
        context: Optional[str] = None,
    ) -> Dict[str, str]:
        """
        Summarize a list of messages into a compact summary.

        Args:
            messages: Messages to summarize
            max_output_tokens: Maximum tokens in summary
            context: Optional context about what to preserve

        Returns:
            Summary message with role='system'
        """
        ...

    @abstractmethod
    async def should_summarize(
        self,
        messages: List[Dict[str, str]],
        threshold_tokens: int,
    ) -> bool:
        """
        Determine if messages should be summarized.

        Args:
            messages: Message list to check
            threshold_tokens: Token threshold for summarization

        Returns:
            True if summarization recommended
        """
        ...


class IContextMetrics(Protocol):
    """
    Interface for context metrics collection and reporting.

    Single Responsibility: Track and report context usage.
    """

    @abstractmethod
    def collect_metrics(
        self,
        messages: List[Dict[str, str]],
        model_id: str,
        additional_context: Optional[Dict[str, int]] = None,
    ) -> ContextMetrics:
        """
        Collect metrics about current context state.

        Args:
            messages: Current message history
            model_id: Model identifier for context limits
            additional_context: Additional token counts (files, repo map, etc.)

        Returns:
            ContextMetrics object
        """
        ...

    @abstractmethod
    def format_metrics(self, metrics: ContextMetrics) -> str:
        """
        Format metrics for display.

        Args:
            metrics: Metrics to format

        Returns:
            Formatted string for CLI display
        """
        ...


class IPersistentContext(Protocol):
    """
    Interface for persistent context management.

    Single Responsibility: Load and manage persistent context files.
    """

    @abstractmethod
    def load_persistent_context(
        self,
        working_dir: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """
        Load persistent context from files (EMILIANO.md, etc.).

        Args:
            working_dir: Directory to search for context files

        Returns:
            List of system messages from persistent files
        """
        ...

    @abstractmethod
    def get_persistent_filenames(self) -> List[str]:
        """
        Get list of filenames to check for persistent context.

        Returns:
            List of filenames (e.g., ['EMILIANO.md', 'CLAUDE.md'])
        """
        ...


class IContextProvider(Protocol):
    """
    Unified interface for context providers.

    Liskov Substitution: Any context provider can be used interchangeably.
    Dependency Inversion: High-level code depends on this abstraction.
    """

    @abstractmethod
    async def get_context(
        self,
        query: str,
        history: List[Dict[str, str]],
        budget_tokens: int,
    ) -> Tuple[List[Dict[str, str]], ContextMetrics]:
        """
        Get optimized context for a query.

        Args:
            query: Current user query
            history: Conversation history
            budget_tokens: Token budget available

        Returns:
            Tuple of (optimized_messages, metrics)
        """
        ...
