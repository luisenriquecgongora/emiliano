"""
Tiered Frontier Model Router and Speculative Execution Engine.

Implements production model tiering for OpenAI frontier models:
- Fast Path: gpt-4o-mini for low-latency (< 300ms) triage, single-file edits, and lookups.
- Standard Path: gpt-4o for multi-modal and general multi-tool coding workflows.
- Reasoning Path: o3-mini / o1 for algorithmic debugging, concurrency, security audits,
  and complex architectural refactoring.

Features:
- Complexity Classification: Analyzes task semantics, code complexity, and architectural risk.
- Reasoning Effort Control: Manages o3-mini `reasoning_effort` ('low', 'medium', 'high').
- Reasoning Prompt Optimization: Strips manual chain-of-thought nudges to prevent reasoning interference.
- Speculative Escalation: Automatically escalates fast-path verification failures to o3-mini.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("emiliano")


class ModelTier(str, Enum):
    FAST = "fast"            # gpt-4o-mini
    STANDARD = "standard"    # gpt-4o
    REASONING = "reasoning"  # o3-mini / o1


@dataclass
class RouteDecision:
    """The model routing decision and execution parameters."""

    tier: ModelTier
    model: str
    reasoning_effort: Optional[str] = None  # 'low' | 'medium' | 'high' (for o3-mini)
    temperature: float = 0.2
    reason: str = ""
    is_escalated: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tier": self.tier.value,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "temperature": self.temperature,
            "reason": self.reason,
            "is_escalated": self.is_escalated,
            "metadata": self.metadata,
        }


class OpenAITieredRouter:
    """
    Tiered routing engine optimizing cost, latency, and reasoning depth across OpenAI models.
    """

    MODEL_FAST = "openai/gpt-4o-mini"
    MODEL_STANDARD = "openai/gpt-4o"
    MODEL_REASONING = "openai/o3-mini"

    # Semantic indicators requiring deep chain-of-thought reasoning
    REASONING_PATTERNS = [
        re.compile(r"(?i)\b(algorithm|concurrency|race condition|deadlock|thread safe|asyncio lock|mutex)\b"),
        re.compile(r"(?i)\b(memory leak|heap dump|buffer overflow|security audit|vulnerability|cryptograph\w*)\b"),
        re.compile(r"(?i)\b(refactor architecture|system design|distributed|subtle bug|hard bug|intermittent)\b"),
        re.compile(r"(?i)\b(optimization|binary search|dynamic programming|complexity o\(|graph traversal)\b"),
        re.compile(r"(?i)\b(state machine|formal proof|invariant violation|cache invalidation)\b"),
    ]

    # Semantic indicators suitable for the fast path
    FAST_PATTERNS = [
        re.compile(r"(?i)\b(rename|typo|spelling|format|docstring|comment|bump version|readme)\b"),
        re.compile(r"(?i)\b(what is|explain|how do i|simple example|syntax for|quick question)\b"),
        re.compile(r"(?i)\b(add log|print statement|todo|fix indentation|lint)\b"),
    ]

    # Manual CoT prompt artifacts that degrade o3-mini / o1 reasoning
    COT_SCRUB_PATTERNS = [
        re.compile(r"(?i)\bthink step[- ]by[- ]step\b[,.]?"),
        re.compile(r"(?i)\bshow your (internal )?thought process\b[,.]?"),
        re.compile(r"(?i)\bexplain your reasoning before (answering|code)\b[,.]?"),
        re.compile(r"(?i)\bbreak this down into logical steps\b[,.]?"),
    ]

    def __init__(
        self,
        default_model: str = MODEL_FAST,
        enable_speculative_escalation: bool = True,
    ):
        self.default_model = default_model
        self.enable_speculative_escalation = enable_speculative_escalation

    def classify_complexity(self, prompt: str, context_files: Optional[List[str]] = None) -> RouteDecision:
        """
        Classifies incoming task complexity and assigns the optimal model tier.
        """
        clean_prompt = prompt.strip()
        context_count = len(context_files) if context_files else 0

        # 1. Check for deep reasoning triggers (o3-mini)
        reasoning_matches = []
        for pat in self.REASONING_PATTERNS:
            m = pat.search(clean_prompt)
            if m:
                reasoning_matches.append(m.group(0))

        if reasoning_matches:
            # If multi-match or complex security/concurrency -> high reasoning effort
            high_effort_terms = {"concurrency", "race condition", "security audit", "vulnerability", "deadlock"}
            has_high = any(term in " ".join(reasoning_matches).lower() for term in high_effort_terms)
            effort = "high" if has_high else "medium"

            reason = f"Requires algorithmic reasoning ({', '.join(reasoning_matches)})"
            logger.info(f"[TieredRouter] Routed to {self.MODEL_REASONING} (effort={effort}): {reason}")
            return RouteDecision(
                tier=ModelTier.REASONING,
                model=self.MODEL_REASONING,
                reasoning_effort=effort,
                temperature=1.0,  # o3-mini standard temperature
                reason=reason,
                metadata={"matched_triggers": reasoning_matches},
            )

        # 2. Check for simple/fast tasks (gpt-4o-mini)
        fast_matches = []
        for pat in self.FAST_PATTERNS:
            m = pat.search(clean_prompt)
            if m:
                fast_matches.append(m.group(0))

        if fast_matches and context_count <= 2:
            reason = f"Trivial edit or explanation task ({', '.join(fast_matches)})"
            return RouteDecision(
                tier=ModelTier.FAST,
                model=self.MODEL_FAST,
                reasoning_effort=None,
                temperature=0.2,
                reason=reason,
                metadata={"matched_triggers": fast_matches},
            )

        # 3. Multi-file or general engineering -> standard gpt-4o
        if context_count > 3 or len(clean_prompt.split()) > 80:
            return RouteDecision(
                tier=ModelTier.STANDARD,
                model=self.MODEL_STANDARD,
                reasoning_effort=None,
                temperature=0.2,
                reason="Multi-file workspace engineering",
                metadata={"context_files": context_count},
            )

        # Default to fast path for cost efficiency
        return RouteDecision(
            tier=ModelTier.FAST,
            model=self.MODEL_FAST,
            reasoning_effort=None,
            temperature=0.2,
            reason="Standard complexity default fast path",
        )

    def normalize_prompt_for_model(self, prompt: str, target_model: str) -> str:
        """
        Optimizes prompt syntax based on target model family.
        OpenAI o1/o3-mini reasoning models degrade when manual 'think step by step'
        instructions are included, as reasoning tokens are generated autonomously.
        """
        is_reasoning_model = any(name in target_model.lower() for name in ["o1", "o3"])
        if not is_reasoning_model:
            return prompt

        scrubbed = prompt
        for pat in self.COT_SCRUB_PATTERNS:
            scrubbed = pat.sub("", scrubbed)

        # Normalize redundant whitespace created by stripping
        scrubbed = re.sub(r"\s{2,}", " ", scrubbed).strip()
        return scrubbed

    def speculative_escalate(
        self,
        initial_decision: RouteDecision,
        verification_error: str,
    ) -> RouteDecision:
        """
        Escalates a failed fast-path execution to o3-mini with high reasoning effort.
        """
        if not self.enable_speculative_escalation:
            return initial_decision

        reason = f"Fast-path failed verification gate. Escalating to deep reasoning. Diagnostic: {verification_error[:120]}"
        logger.warning(f"[TieredRouter] {reason}")

        return RouteDecision(
            tier=ModelTier.REASONING,
            model=self.MODEL_REASONING,
            reasoning_effort="high",
            temperature=1.0,
            reason=reason,
            is_escalated=True,
            metadata={"prior_model": initial_decision.model, "error_preview": verification_error[:200]},
        )
