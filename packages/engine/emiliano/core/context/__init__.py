"""
Context engineering package for Emiliano.
Provides advanced context window management, summarization, and retrieval.
"""

from .base import (
    ITokenCounter,
    ISummarizer,
    IContextMetrics,
    IPersistentContext,
)

__all__ = [
    "ITokenCounter",
    "ISummarizer",
    "IContextMetrics",
    "IPersistentContext",
]
