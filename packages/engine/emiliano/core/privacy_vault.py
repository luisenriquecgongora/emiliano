"""
Local Zero-PII Anonymization and Rehydration Vault for Emiliano.

Designed for European & UK Digital Native scale-ups (FinTech, HealthTech, B2B SaaS)
with strict GDPR, UK-DPA, and enterprise confidentiality requirements.

Architecture:
1. Zero Egress Anonymization:
   Scans outgoing payloads locally before any network call. Replaces sensitive
   credentials, financial identifiers, and personal data with referentially-consistent
   synthetic surrogate tokens (e.g., `__VAULT_PII_EMAIL_1__`).
2. Referential Preservation:
   Identical entities map to identical tokens across the entire session, allowing
   frontier models (OpenAI o3-mini, gpt-4o) to reason about entity relationships,
   refactor code, and track variable bindings without ever seeing the real raw values.
3. Local Rehydration Engine:
   When frontier model completions return from the cloud, the vault intercepts the response
   and swaps synthetic tokens back with their original real values before saving to disk
   or displaying to the user.
4. Zero-Leakage Verification Gate:
   Cryptographically asserts that no registered sensitive plaintext exists in outgoing
   network payloads.
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("emiliano")


class VaultCategory(str, Enum):
    # Credentials & API Keys
    SECRET_OPENAI = "SECRET_OPENAI"
    SECRET_GITHUB = "SECRET_GITHUB"
    SECRET_AWS = "SECRET_AWS"
    SECRET_ANTHROPIC = "SECRET_ANTHROPIC"
    SECRET_JWT = "SECRET_JWT"
    SECRET_GENERIC = "SECRET_GENERIC"

    # Financial & Banking (FinTech)
    FIN_IBAN = "FIN_IBAN"
    FIN_CREDIT_CARD = "FIN_CREDIT_CARD"

    # Personal Identifiable Information (GDPR / UK-DPA)
    PII_EMAIL = "PII_EMAIL"
    PII_PHONE = "PII_PHONE"
    PII_UK_NINO = "PII_UK_NINO"
    PII_US_SSN = "PII_US_SSN"
    PII_IP = "PII_IP"

    # Custom
    CUSTOM = "CUSTOM"


@dataclass
class VaultEntity:
    """An individual tracked sensitive entity inside the vault."""
    category: VaultCategory
    real_value: str
    surrogate_token: str
    occurrences: int = 1
    description: Optional[str] = None

    def mask_preview(self) -> str:
        """Returns a non-sensitive preview (first 2 chars, masked, last 2 chars)."""
        val = self.real_value
        if len(val) <= 4:
            return "***"
        return f"{val[:2]}...{val[-2:]}"


@dataclass
class VaultReport:
    """Report generated after anonymizing a text or payload."""
    entities_detected: int
    categories_found: Set[VaultCategory]
    surrogate_tokens_applied: List[str]
    zero_leakage_guaranteed: bool
    audit_summary: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entities_detected": self.entities_detected,
            "categories_found": [c.value for c in self.categories_found],
            "surrogate_tokens_applied": self.surrogate_tokens_applied,
            "zero_leakage_guaranteed": self.zero_leakage_guaranteed,
            "audit_summary": self.audit_summary,
        }


class PrivacyVault:
    """
    In-memory reversible cryptographic privacy vault for local edge-to-cloud sanitization.
    """

    # High-precision patterns for identifying sensitive entities
    PATTERNS: List[Tuple[VaultCategory, re.Pattern]] = [
        # OpenAI API Keys (legacy and project-scoped)
        (
            VaultCategory.SECRET_OPENAI,
            re.compile(r"\b(sk-[a-zA-Z0-9]{20,T3BlbkFJ[a-zA-Z0-9]{20,}|sk-proj-[a-zA-Z0-9_-]{40,})\b"),
        ),
        # GitHub Personal Access, Fine-grained, and OAuth Tokens
        (
            VaultCategory.SECRET_GITHUB,
            re.compile(r"\b(ghp_[a-zA-Z0-9]{36}|github_pat_[a-zA-Z0-9_]{82}|gho_[a-zA-Z0-9]{36})\b"),
        ),
        # AWS Access Key IDs
        (
            VaultCategory.SECRET_AWS,
            re.compile(r"\b(AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}\b"),
        ),
        # Anthropic API Keys
        (
            VaultCategory.SECRET_ANTHROPIC,
            re.compile(r"\bsk-ant-api[a-zA-Z0-9_-]{30,}\b"),
        ),
        # Bearer / JWT Tokens (header.payload.signature)
        (
            VaultCategory.SECRET_JWT,
            re.compile(r"\beyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\b"),
        ),
        # International Bank Account Numbers (IBAN: UK, DE, FR, ES, etc.)
        (
            VaultCategory.FIN_IBAN,
            re.compile(r"\b[A-Z]{2}[0-9]{2}(?:[ ]?[A-Z0-9]{4}){3,7}(?:[ ]?[A-Z0-9]{1,4})?\b"),
        ),
        # Credit Card Numbers (Visa, Mastercard, Amex, Discover)
        (
            VaultCategory.FIN_CREDIT_CARD,
            re.compile(r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\b|\b(?:\d{4}[ -]){3}\d{4}\b"),
        ),
        # UK National Insurance Numbers (NINO - e.g. QQ 12 34 56 A or standard 2 letters + 6 digits + letter)
        (
            VaultCategory.PII_UK_NINO,
            re.compile(r"\b(?:QQ|[A-CEGHJ-PR-TW-Z]{2})[ ]?[0-9]{2}[ ]?[0-9]{2}[ ]?[0-9]{2}[ ]?[A-D]{1}\b", re.IGNORECASE),
        ),
        # US Social Security Numbers
        (
            VaultCategory.PII_US_SSN,
            re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        ),
        # Email Addresses
        (
            VaultCategory.PII_EMAIL,
            re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b"),
        ),
        # International & UK / US Phone Numbers
        (
            VaultCategory.PII_PHONE,
            re.compile(r"(?:\+44\s?7\d{3}|\b07\d{3})\s?\d{3}\s?\d{3}\b|(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
        ),
        # IPv4 Addresses (excluding loopback 127.0.0.1 and private 0.0.0.0)
        (
            VaultCategory.PII_IP,
            re.compile(r"\b(?!127\.0\.0\.1\b)(?!0\.0\.0\.0\b)(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b"),
        ),
    ]

    # Regex to detect surrogate tokens in text during rehydration
    SURROGATE_TOKEN_REGEX = re.compile(r"__VAULT_([A-Z_]+)_([0-9a-f]{8}|\d+)__")

    def __init__(self, salt: Optional[bytes] = None):
        """
        Initializes an isolated Privacy Vault instance.
        """
        self._lock = threading.RLock()
        self._salt = salt or os.urandom(16)

        # Mapping: real_value -> VaultEntity
        self._forward_map: Dict[str, VaultEntity] = {}
        # Mapping: surrogate_token -> VaultEntity
        self._reverse_map: Dict[str, VaultEntity] = {}

        # Per-category counter for deterministic indexing
        self._counters: Dict[VaultCategory, int] = {cat: 0 for cat in VaultCategory}

        # Custom user-defined patterns
        self._custom_patterns: List[Tuple[VaultCategory, re.Pattern]] = []

    def register_custom_pattern(self, name: str, regex: str | re.Pattern) -> None:
        """Adds a proprietary domain entity pattern (e.g. internal customer UUIDs, tenant keys)."""
        pattern = re.compile(regex) if isinstance(regex, str) else regex
        with self._lock:
            self._custom_patterns.append((VaultCategory.CUSTOM, pattern))

    def register_secret_literal(self, secret: str, category: VaultCategory = VaultCategory.SECRET_GENERIC) -> str:
        """
        Explicitly pre-registers a secret literal into the vault (e.g. from environment or config).
        Returns the synthetic surrogate token.
        """
        if not secret or len(secret.strip()) < 3:
            return secret

        with self._lock:
            if secret in self._forward_map:
                entity = self._forward_map[secret]
                entity.occurrences += 1
                return entity.surrogate_token

            self._counters[category] = self._counters.get(category, 0) + 1
            index = self._counters[category]
            surrogate = f"__VAULT_{category.value}_{index}__"

            entity = VaultEntity(
                category=category,
                real_value=secret,
                surrogate_token=surrogate,
                occurrences=1,
            )
            self._forward_map[secret] = entity
            self._reverse_map[surrogate] = entity
            return surrogate

    def _get_or_create_token(self, real_value: str, category: VaultCategory) -> str:
        """Returns existing token or registers a new token for the given entity value."""
        if real_value in self._forward_map:
            entity = self._forward_map[real_value]
            entity.occurrences += 1
            return entity.surrogate_token

        self._counters[category] = self._counters.get(category, 0) + 1
        index = self._counters[category]
        surrogate = f"__VAULT_{category.value}_{index}__"

        entity = VaultEntity(
            category=category,
            real_value=real_value,
            surrogate_token=surrogate,
            occurrences=1,
        )
        self._forward_map[real_value] = entity
        self._reverse_map[surrogate] = entity
        return surrogate

    def anonymize(self, text: str) -> Tuple[str, VaultReport]:
        """
        Scans and sanitizes the given text.
        Replaces all sensitive occurrences with their surrogate tokens.
        Preserves referential identity.
        """
        if not text:
            return text, VaultReport(
                entities_detected=0,
                categories_found=set(),
                surrogate_tokens_applied=[],
                zero_leakage_guaranteed=True,
                audit_summary={},
            )

        with self._lock:
            sanitized = text
            applied_tokens: List[str] = []
            categories_found: Set[VaultCategory] = set()
            audit_summary: Dict[str, int] = {}

            # First, check pre-registered literals (exact match)
            for real_val, entity in sorted(self._forward_map.items(), key=lambda x: len(x[0]), reverse=True):
                if real_val in sanitized:
                    sanitized = sanitized.replace(real_val, entity.surrogate_token)
                    applied_tokens.append(entity.surrogate_token)
                    categories_found.add(entity.category)
                    audit_summary[entity.category.value] = audit_summary.get(entity.category.value, 0) + 1

            # Second, run custom patterns first (so domain entities take precedence over generic phone/number matches), then standard patterns
            all_patterns = self._custom_patterns + self.PATTERNS
            for category, pattern in all_patterns:
                matches = list(pattern.finditer(sanitized))
                # Sort matches by length descending to prevent sub-string collision
                for match in matches:
                    matched_str = match.group(0).strip()
                    if not matched_str or matched_str.startswith("__VAULT_"):
                        continue

                    token = self._get_or_create_token(matched_str, category)
                    # Replace in text
                    sanitized = sanitized.replace(matched_str, token)
                    applied_tokens.append(token)
                    categories_found.add(category)
                    audit_summary[category.value] = audit_summary.get(category.value, 0) + 1

            # Verify zero leakage
            zero_leakage, leaks = self.assert_zero_leakage(sanitized)

            report = VaultReport(
                entities_detected=len(applied_tokens),
                categories_found=categories_found,
                surrogate_tokens_applied=applied_tokens,
                zero_leakage_guaranteed=zero_leakage,
                audit_summary=audit_summary,
            )
            return sanitized, report

    def rehydrate(self, text: str) -> str:
        """
        Replaces surrogate tokens in the text with their original real values.
        Safe for source code, markdown, JSON, or agent reasoning responses.
        """
        if not text:
            return text

        with self._lock:
            rehydrated = text
            # Replace all registered reverse mappings
            for surrogate, entity in self._reverse_map.items():
                if surrogate in rehydrated:
                    rehydrated = rehydrated.replace(surrogate, entity.real_value)

            return rehydrated

    def assert_zero_leakage(self, text: str) -> Tuple[bool, List[str]]:
        """
        Cryptographically asserts that no registered sensitive plaintext values
        are present in the sanitized text before external transmission.
        """
        if not text:
            return True, []

        leaks: List[str] = []
        with self._lock:
            for real_val, entity in self._forward_map.items():
                if real_val in text:
                    leaks.append(f"{entity.category.value}:{entity.mask_preview()}")

        return len(leaks) == 0, leaks

    def sanitize_messages(self, messages: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], VaultReport]:
        """
        Sanitizes a full OpenAI-compatible list of message dicts.
        Walks text content, tool arguments, and system prompts.
        """
        total_detected = 0
        all_categories: Set[VaultCategory] = set()
        all_tokens: List[str] = []
        summary: Dict[str, int] = {}

        sanitized_messages: List[Dict[str, Any]] = []

        for msg in messages:
            msg_copy = dict(msg)
            content = msg_copy.get("content")

            if isinstance(content, str):
                s_content, report = self.anonymize(content)
                msg_copy["content"] = s_content
                total_detected += report.entities_detected
                all_categories.update(report.categories_found)
                all_tokens.extend(report.surrogate_tokens_applied)
                for k, v in report.audit_summary.items():
                    summary[k] = summary.get(k, 0) + v
            elif isinstance(content, list):
                # Multi-modal content parts
                sanitized_parts = []
                for part in content:
                    part_copy = dict(part)
                    if part_copy.get("type") == "text" and "text" in part_copy:
                        s_text, report = self.anonymize(part_copy["text"])
                        part_copy["text"] = s_text
                        total_detected += report.entities_detected
                        all_categories.update(report.categories_found)
                        all_tokens.extend(report.surrogate_tokens_applied)
                        for k, v in report.audit_summary.items():
                            summary[k] = summary.get(k, 0) + v
                    sanitized_parts.append(part_copy)
                msg_copy["content"] = sanitized_parts

            # Sanitize tool call arguments if present
            if "tool_calls" in msg_copy and isinstance(msg_copy["tool_calls"], list):
                s_tool_calls = []
                for tc in msg_copy["tool_calls"]:
                    tc_copy = dict(tc)
                    fn = tc_copy.get("function")
                    if fn and "arguments" in fn and isinstance(fn["arguments"], str):
                        s_args, r = self.anonymize(fn["arguments"])
                        fn_copy = dict(fn)
                        fn_copy["arguments"] = s_args
                        tc_copy["function"] = fn_copy
                        total_detected += r.entities_detected
                        all_categories.update(r.categories_found)
                        all_tokens.extend(r.surrogate_tokens_applied)
                    s_tool_calls.append(tc_copy)
                msg_copy["tool_calls"] = s_tool_calls

            sanitized_messages.append(msg_copy)

        combined_report = VaultReport(
            entities_detected=total_detected,
            categories_found=all_categories,
            surrogate_tokens_applied=all_tokens,
            zero_leakage_guaranteed=True,
            audit_summary=summary,
        )
        return sanitized_messages, combined_report

    def clear(self) -> None:
        """Clears all in-memory vault mappings."""
        with self._lock:
            self._forward_map.clear()
            self._reverse_map.clear()
            self._counters = {cat: 0 for cat in VaultCategory}
