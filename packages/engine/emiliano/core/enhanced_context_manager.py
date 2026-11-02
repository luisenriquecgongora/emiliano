"""
Enhanced Context Window Manager with Phase 1 integrations.
Combines truncation, summarization, persistent context, and metrics collection.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("emiliano")

from .context_manager import ContextWindowManager, TruncationStrategy
from .context.base import ContextMetrics, TruncationMetadata
from .context.summarization import RecursiveSummarizer, SimpleTruncator
from .context.persistent import PersistentContextLoader
from .context.metrics import ContextMetricsCollector
from .config import EmilianoConfig, load_config


class EnhancedContextManager(ContextWindowManager):
    """
    Enhanced context manager with Phase 1 features:
    - LLM-based conversation summarization
    - Persistent context files (EMILIANO.md)
    - Real-time metrics collection
    - Backward compatible with base ContextWindowManager

    Single Responsibility: Orchestrate all context management operations
    Dependency Inversion: Depends on abstract interfaces (ISummarizer, etc.)
    """

    def __init__(
        self,
        config: Optional[EmilianoConfig] = None,
        max_tokens: Optional[int] = None,
        strategy: TruncationStrategy = TruncationStrategy.SLIDING_WINDOW,
        reserve_tokens: int = 2000,
        safety_margin: float = 0.85,
    ):
        """
        Initialize enhanced context manager.

        Args:
            config: Emiliano configuration
            max_tokens: Override maximum tokens
            strategy: Truncation strategy
            reserve_tokens: Tokens reserved for response
            safety_margin: Fraction of window to use
        """
        # Call parent constructor
        super().__init__(
            max_tokens=max_tokens,
            strategy=strategy,
            reserve_tokens=reserve_tokens,
            safety_margin=safety_margin,
        )

        # Load config
        self.config = config or load_config()

        # Override from config if not explicitly set
        if max_tokens is None and self.config.context.max_tokens:
            self.max_tokens = self.config.context.max_tokens
        if self.config.context.safety_margin:
            self.safety_margin = self.config.context.safety_margin
        if self.config.context.reserve_tokens:
            self.reserve_tokens = self.config.context.reserve_tokens

        # Initialize Phase 1 components
        self._init_components()

        # Persistent context cache (loaded once per session)
        self._persistent_context_cache: Optional[List[Dict[str, str]]] = None

    def _init_components(self):
        """Initialize Phase 1 components based on configuration."""
        # Summarizer
        if self.config.context.summarization.enabled:
            if self.config.context.summarization.strategy == "recursive":
                self.summarizer = RecursiveSummarizer(
                    token_counter=self,
                    llm_client=None,  # Lazy-loaded
                )
            else:
                self.summarizer = SimpleTruncator()
        else:
            self.summarizer = SimpleTruncator()

        # Persistent context loader
        if self.config.context.persistent.enabled:
            self.persistent_loader = PersistentContextLoader(
                filenames=self.config.context.persistent.filenames,
            )
        else:
            self.persistent_loader = None

        # Metrics collector
        if self.config.context.metrics.enabled:
            self.metrics_collector = ContextMetricsCollector(
                token_counter=self,
            )
        else:
            self.metrics_collector = None

    def load_persistent_context(self, working_dir: Optional[str] = None) -> List[Dict[str, str]]:
        """
        Load persistent context files (EMILIANO.md, CLAUDE.md, etc.).
        Cached for session lifetime.

        Args:
            working_dir: Directory to search for files

        Returns:
            List of system messages from persistent files
        """
        if self._persistent_context_cache is not None:
            return self._persistent_context_cache

        if self.persistent_loader:
            self._persistent_context_cache = self.persistent_loader.load_persistent_context(working_dir)
        else:
            self._persistent_context_cache = []

        return self._persistent_context_cache

    def get_metrics(
        self,
        messages: List[Dict[str, str]],
        model_id: str,
        additional_context: Optional[Dict[str, int]] = None,
    ) -> ContextMetrics:
        """
        Collect context usage metrics.

        Args:
            messages: Current message history
            model_id: Model identifier
            additional_context: Additional token counts (files, repo map, etc.)

        Returns:
            ContextMetrics object
        """
        if self.metrics_collector:
            context_limit = self.get_model_context_limit(model_id)
            return self.metrics_collector.collect_metrics(
                messages=messages,
                model_id=model_id,
                model_context_limit=context_limit,
                additional_context=additional_context,
            )
        else:
            # Fallback: simple metrics
            context_limit = self.get_model_context_limit(model_id)
            total_tokens = self.count_messages_tokens(messages)
            return ContextMetrics(
                total_tokens=total_tokens,
                history_tokens=total_tokens,
                system_tokens=0,
                file_tokens=0,
                repo_map_tokens=0,
                persistent_tokens=0,
                available_tokens=max(0, context_limit - total_tokens),
                max_tokens=context_limit,
                usage_percentage=(total_tokens / context_limit * 100) if context_limit > 0 else 0,
                message_count=len(messages),
            )

    async def manage_context(
        self,
        messages: List[Dict[str, str]],
        model_id: str,
        include_persistent: bool = True,
    ) -> Tuple[List[Dict[str, str]], TruncationMetadata]:
        """
        Comprehensive context management: persistent context + summarization + truncation.

        This is the main entry point that orchestrates all Phase 1 features.

        Args:
            messages: Conversation history
            model_id: Model identifier
            include_persistent: Include persistent context files

        Returns:
            Tuple of (managed_messages, metadata)
        """
        # 1. Load persistent context (if enabled)
        if include_persistent and self.persistent_loader:
            persistent_msgs = self.load_persistent_context()
            if persistent_msgs:
                # Prepend persistent context (these are never truncated)
                messages = persistent_msgs + messages

        # 2. Check if summarization is needed
        if self.config.context.summarization.enabled:
            threshold = self.config.context.summarization.threshold_tokens
            should_summarize = await self.summarizer.should_summarize(messages, threshold)

            if should_summarize:
                logger.info("[EnhancedContextManager] Triggering conversation summarization")
                summary_msg = await self.summarizer.summarize(
                    messages,
                    max_output_tokens=self.config.context.summarization.max_summary_tokens,
                )

                # Replace old messages with summary
                # Keep system messages, replace old user/assistant messages with summary
                system_messages = [m for m in messages if m.get("role") == "system"]
                recent_messages = messages[-10:]  # Keep last 10 messages
                messages = system_messages + [summary_msg] + recent_messages

                metadata = TruncationMetadata(
                    original_count=len(messages),
                    truncated_count=len(messages),
                    tokens_saved=0,  # Will be calculated after truncation
                    was_truncated=False,
                    was_summarized=True,
                    summary=summary_msg.get("content", ""),
                )

                if self.config.context.metrics.log_summarization:
                    logger.info(f"[EnhancedContextManager] Summarized conversation: {len(messages)} messages retained")

                # Now proceed to truncation if still needed
                messages, trunc_meta = self.truncate_history(messages, model_id)

                # Merge metadata
                metadata.was_truncated = trunc_meta["was_truncated"]
                metadata.truncated_count = trunc_meta["truncated_count"]
                metadata.tokens_saved = trunc_meta["tokens_saved"]

                return messages, metadata

        # 3. Truncation only (no summarization)
        messages, trunc_meta = self.truncate_history(messages, model_id)

        metadata = TruncationMetadata(
            original_count=trunc_meta["original_count"],
            truncated_count=trunc_meta["truncated_count"],
            tokens_saved=trunc_meta["tokens_saved"],
            was_truncated=trunc_meta["was_truncated"],
            was_summarized=False,
        )

        if self.config.context.metrics.log_truncation and metadata.was_truncated:
            logger.info(
                f"[EnhancedContextManager] Truncated context: "
                f"{metadata.original_count} → {metadata.truncated_count} messages"
            )

        return messages, metadata

    async def compact_conversation(
        self,
        messages: List[Dict[str, str]],
    ) -> Tuple[List[Dict[str, str]], str]:
        """
        Manually trigger conversation compaction (like Claude Code /compact).

        Args:
            messages: Full conversation history

        Returns:
            Tuple of (compacted_messages, summary_text)
        """
        if not self.config.context.summarization.enabled:
            logger.warning("[EnhancedContextManager] Summarization disabled, cannot compact")
            return messages, "[Summarization is disabled in configuration]"

        # Generate summary
        summary_msg = await self.summarizer.summarize(
            messages,
            max_output_tokens=self.config.context.summarization.max_summary_tokens,
            context="Manual compaction requested by user",
        )

        # Replace conversation with summary
        system_messages = [m for m in messages if m.get("role") == "system"]
        compacted = system_messages + [summary_msg]

        summary_text = summary_msg.get("content", "")
        logger.info(f"[EnhancedContextManager] Manually compacted: {len(messages)} → {len(compacted)} messages")

        return compacted, summary_text
