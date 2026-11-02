"""
Recursive conversation summarizer using LLM.
Implements LLM-Resumé approach from research literature.
"""

from typing import List, Dict, Optional

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("emiliano")

from ..base import ITokenCounter


class RecursiveSummarizer:
    """
    LLM-based recursive summarization for long conversations.

    Implements the LLM-Resumé method:
    1. Generate summary of conversation chunk
    2. Combine previous summary + new messages
    3. Generate updated summary
    4. Repeat recursively

    Single Responsibility: Summarize conversation history.
    Dependency Inversion: Depends on ITokenCounter and LLM client abstractions.

    References:
        "Recursively Summarizing Enables Long-Term Dialogue Memory in LLMs"
        https://arxiv.org/pdf/2308.15022
    """

    def __init__(
        self,
        token_counter: ITokenCounter,
        llm_client: Optional[any] = None,  # UnifiedLLMClient
    ):
        """
        Initialize recursive summarizer.

        Args:
            token_counter: Token counter for measuring message sizes
            llm_client: LLM client for generating summaries (lazy-loaded if None)
        """
        self.token_counter = token_counter
        self._llm_client = llm_client

    def _get_llm_client(self):
        """Lazy-load LLM client to avoid circular imports."""
        if self._llm_client is None:
            from ...config import load_config
            from ....direct.client import UnifiedLLMClient

            config = load_config()
            self._llm_client = UnifiedLLMClient(
                ollama_base_url=config.models.ollama_base_url,
                fallback_chain=config.models.fallback_chain,
                config=config,
            )
        return self._llm_client

    async def summarize(
        self,
        messages: List[Dict[str, str]],
        max_output_tokens: int = 500,
        context: Optional[str] = None,
    ) -> Dict[str, str]:
        """
        Generate a recursive summary of conversation messages.

        Args:
            messages: Messages to summarize
            max_output_tokens: Maximum tokens in output summary
            context: Optional context hint about what to preserve

        Returns:
            Summary message with role='system'
        """
        if not messages:
            return {"role": "system", "content": "[Empty conversation]"}

        # Filter out system messages from summarization
        user_assistant_msgs = [
            m for m in messages
            if m.get("role") in ("user", "assistant")
        ]

        if not user_assistant_msgs:
            return {"role": "system", "content": "[No user/assistant messages to summarize]"}

        # Build summarization prompt
        context_hint = f"\n\nFocus on: {context}" if context else ""
        conversation_text = self._format_messages_for_summary(user_assistant_msgs)

        prompt = f"""You are summarizing a conversation between a user and an AI coding assistant.

Your task: Create a concise summary that preserves:
1. Key decisions and conclusions
2. Important code changes and their rationale
3. Unresolved issues or follow-up tasks
4. Technical context necessary for continuing the conversation

DO NOT include:
- Small talk or greetings
- Redundant explanations
- Overly detailed code snippets (just describe what was done)

Keep the summary under {max_output_tokens} tokens.{context_hint}

CONVERSATION TO SUMMARIZE:
{conversation_text}

CONCISE SUMMARY:"""

        try:
            client = self._get_llm_client()
            summary_parts = []

            # Use streaming for consistency with rest of system
            async for chunk in client.stream_completion(
                messages=[{"role": "user", "content": prompt}],
                model_name=None,  # Use default from fallback chain
                timeout=30.0,
            ):
                summary_parts.append(chunk)

            summary = "".join(summary_parts).strip()

            if not summary:
                logger.warning("[RecursiveSummarizer] LLM returned empty summary, using fallback")
                summary = self._fallback_summary(user_assistant_msgs)

            logger.info(
                f"[RecursiveSummarizer] Summarized {len(messages)} messages "
                f"({self.token_counter.count_messages_tokens(messages)} tokens) → "
                f"~{len(summary)//4} tokens"
            )

            return {
                "role": "system",
                "content": f"[Conversation summary: Previous discussion covered the following]\n\n{summary}"
            }

        except Exception as e:
            logger.error(f"[RecursiveSummarizer] Failed to generate summary: {e}")
            # Fallback to simple summary
            return {
                "role": "system",
                "content": f"[Conversation summary: {self._fallback_summary(user_assistant_msgs)}]"
            }

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
            True if token count exceeds threshold
        """
        non_system_messages = [m for m in messages if m.get("role") != "system"]
        token_count = self.token_counter.count_messages_tokens(non_system_messages)
        should_summarize = token_count > threshold_tokens

        if should_summarize:
            logger.info(
                f"[RecursiveSummarizer] Summarization recommended: "
                f"{token_count} tokens > {threshold_tokens} threshold"
            )

        return should_summarize

    def _format_messages_for_summary(self, messages: List[Dict[str, str]]) -> str:
        """Format messages for summarization prompt."""
        lines = []
        for msg in messages:
            role = msg.get("role", "unknown").upper()
            content = msg.get("content", "")
            # Truncate very long messages
            if len(content) > 2000:
                content = content[:2000] + "... [truncated]"
            lines.append(f"{role}: {content}")
        return "\n\n".join(lines)

    def _fallback_summary(self, messages: List[Dict[str, str]]) -> str:
        """Generate a simple fallback summary if LLM fails."""
        user_count = sum(1 for m in messages if m.get("role") == "user")
        assistant_count = sum(1 for m in messages if m.get("role") == "assistant")

        # Extract some keywords from user messages
        user_messages = [m.get("content", "") for m in messages if m.get("role") == "user"]
        sample_topics = []
        for content in user_messages[:3]:  # First 3 user messages
            words = content.split()[:10]  # First 10 words
            sample_topics.append(" ".join(words))

        topics_text = " | ".join(sample_topics) if sample_topics else "various topics"

        return (
            f"Earlier conversation covered: {topics_text}. "
            f"Exchange included {user_count} user messages and {assistant_count} assistant responses."
        )
