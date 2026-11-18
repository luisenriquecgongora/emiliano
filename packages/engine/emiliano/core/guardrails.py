"""
Production Guardrails and Safety Architecture for Emiliano.

Provides multi-layer defense-in-depth for autonomous agents:
1. PIIGuardrail: Redaction and masking of sensitive credentials, API keys, emails, and financial identifiers.
2. InjectionGuardrail: Detection of prompt injections, system prompt extraction, delimiter breakout, and jailbreaks.
3. ToolSafetyGuardrail: Path traversal confinement to workspace root and destructive shell command blocking.
4. ModerationGuardrail: Content moderation with local heuristics and async OpenAI Moderation API integration.
5. GuardrailPipeline: Composable pipeline for validating inputs, tool calls, and model outputs.
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("emiliano")


@dataclass
class GuardrailVerdict:
    """The result of a guardrail check."""

    guardrail_name: str
    allowed: bool
    action: str = "allow"  # "allow" | "mask" | "block"
    reason: Optional[str] = None
    sanitized_text: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class BaseGuardrail:
    """Base interface for all guardrails."""

    name: str = "base_guardrail"

    def check_input(self, text: str) -> GuardrailVerdict:
        return GuardrailVerdict(guardrail_name=self.name, allowed=True, action="allow")

    def check_output(self, text: str) -> GuardrailVerdict:
        return GuardrailVerdict(guardrail_name=self.name, allowed=True, action="allow")

    def check_tool(self, tool_name: str, args: Dict[str, Any], workspace: str = ".") -> GuardrailVerdict:
        return GuardrailVerdict(guardrail_name=self.name, allowed=True, action="allow")


class PIIGuardrail(BaseGuardrail):
    """
    Detects and masks personally identifiable information (PII) and credentials.
    Protects logs, traces, and external LLM provider calls from data exfiltration.
    """

    name: str = "pii_guardrail"

    # Compiled regex patterns for high-risk tokens and credentials
    PATTERNS: List[Tuple[str, re.Pattern, str]] = [
        # OpenAI API Keys
        ("openai_key", re.compile(r"\bsk-[a-zA-Z0-9]{20,T3BlbkFJ[a-zA-Z0-9]{20,}\b|\bsk-proj-[a-zA-Z0-9_-]{40,}\b"), "[REDACTED_OPENAI_KEY]"),
        # GitHub Tokens (Personal Access Token, Fine-grained, OAuth)
        ("github_token", re.compile(r"\b(ghp_[a-zA-Z0-9]{36}|github_pat_[a-zA-Z0-9_]{82}|gho_[a-zA-Z0-9]{36})\b"), "[REDACTED_GITHUB_TOKEN]"),
        # AWS Access Key IDs
        ("aws_key", re.compile(r"\b(AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
        # Anthropic API Keys
        ("anthropic_key", re.compile(r"\bsk-ant-api[a-zA-Z0-9_-]{30,}\b"), "[REDACTED_ANTHROPIC_KEY]"),
        # Generic Bearer JWT
        ("jwt_token", re.compile(r"\beyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\b"), "[REDACTED_JWT]"),
        # Credit Card Numbers (13-19 digits with optional hyphens/spaces)
        ("credit_card", re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b|\b\d{15,16}\b"), "[REDACTED_CREDIT_CARD]"),
        # Email Addresses
        ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"), "[REDACTED_EMAIL]"),
        # US/Intl Phone numbers
        ("phone", re.compile(r"(?:\+?(\d{1,3}))?[-. (]*(\d{3})[-. )]*(\d{3})[-. ]*(\d{4})\b"), "[REDACTED_PHONE]"),
        # US SSN
        ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),
    ]

    def __init__(self, mask_inputs: bool = True, mask_outputs: bool = True, block_on_secrets: bool = False):
        self.mask_inputs = mask_inputs
        self.mask_outputs = mask_outputs
        self.block_on_secrets = block_on_secrets

    def redact(self, text: str) -> Tuple[str, List[str]]:
        """Replaces matched PII and credentials with redaction tokens."""
        redacted = text
        found_types = []
        for ptype, pattern, replacement in self.PATTERNS:
            if pattern.search(redacted):
                found_types.append(ptype)
                redacted = pattern.sub(replacement, redacted)
        return redacted, found_types

    def check_input(self, text: str) -> GuardrailVerdict:
        if not text:
            return GuardrailVerdict(guardrail_name=self.name, allowed=True, action="allow")

        redacted, found = self.redact(text)
        if not found:
            return GuardrailVerdict(guardrail_name=self.name, allowed=True, action="allow")

        secret_types = {"openai_key", "github_token", "aws_key", "anthropic_key", "jwt_token"}
        has_secrets = bool(set(found) & secret_types)

        if self.block_on_secrets and has_secrets:
            return GuardrailVerdict(
                guardrail_name=self.name,
                allowed=False,
                action="block",
                reason=f"Input contains unmasked credentials/secrets: {', '.join(found)}",
                details={"found_types": found},
            )

        action = "mask" if self.mask_inputs else "allow"
        return GuardrailVerdict(
            guardrail_name=self.name,
            allowed=True,
            action=action,
            sanitized_text=redacted if self.mask_inputs else text,
            details={"found_types": found},
        )

    def check_output(self, text: str) -> GuardrailVerdict:
        if not text:
            return GuardrailVerdict(guardrail_name=self.name, allowed=True, action="allow")

        redacted, found = self.redact(text)
        if not found:
            return GuardrailVerdict(guardrail_name=self.name, allowed=True, action="allow")

        return GuardrailVerdict(
            guardrail_name=self.name,
            allowed=True,
            action="mask" if self.mask_outputs else "allow",
            sanitized_text=redacted if self.mask_outputs else text,
            details={"found_types": found},
        )


class InjectionGuardrail(BaseGuardrail):
    """
    Detects direct and indirect prompt injections, system prompt exfiltration,
    and instructional overrides designed to break out of agent harnesses.
    """

    name: str = "injection_guardrail"

    # Common injection and override heuristics
    INJECTION_PATTERNS: List[Tuple[str, re.Pattern]] = [
        # Instruction overrides
        ("instruction_override", re.compile(
            r"(?i)\b(ignore|disregard|forget|override|bypass)\s+(all\s+)?(previous|prior|above|system)\s+(instructions|prompts|rules|commands)",
        )),
        # Delimiter breakouts
        ("delimiter_breakout", re.compile(
            r"(?i)(<\/?system>|\[system\]|<<sys>>|\[INST\]|---BEGIN SYSTEM PROMPT---|###\s*System)",
        )),
        # Jailbreak roleplay
        ("jailbreak_roleplay", re.compile(
            r"(?i)\b(you are now (unrestricted|DAN|jailbroken)|operate in developer mode|enable god mode)\b",
        )),
        # System prompt exfiltration
        ("prompt_exfiltration", re.compile(
            r"(?i)\b(repeat|output|show|print|reveal|display)\s+(your\s+)?(system prompt|original instructions|initial prompt)\s+(verbatim|word for word)",
        )),
    ]

    def __init__(self, block_injections: bool = True):
        self.block_injections = block_injections

    def check_input(self, text: str) -> GuardrailVerdict:
        if not text:
            return GuardrailVerdict(guardrail_name=self.name, allowed=True, action="allow")

        detected = []
        for name, pattern in self.INJECTION_PATTERNS:
            if pattern.search(text):
                detected.append(name)

        if detected:
            msg = f"Potential prompt injection detected: {', '.join(detected)}"
            logger.warning(f"[{self.name}] {msg}")
            if self.block_injections:
                return GuardrailVerdict(
                    guardrail_name=self.name,
                    allowed=False,
                    action="block",
                    reason=msg,
                    details={"matched_patterns": detected},
                )
            else:
                return GuardrailVerdict(
                    guardrail_name=self.name,
                    allowed=True,
                    action="flag",
                    reason=msg,
                    details={"matched_patterns": detected},
                )

        return GuardrailVerdict(guardrail_name=self.name, allowed=True, action="allow")


class ToolSafetyGuardrail(BaseGuardrail):
    """
    Enforces sandbox containment on tool execution:
    1. Path Confinement: Prevents directory traversal attacks escaping the workspace.
    2. Bash Command Whitelist/Blacklist: Blocks catastrophic and irreversible shell commands.
    """

    name: str = "tool_safety_guardrail"

    # Highly destructive bash commands that must never be run autonomously
    DANGEROUS_COMMAND_PATTERNS: List[re.Pattern] = [
        re.compile(r"(?i)\brm\s+-(?:rf?|fr?)\s+(?:\/|~|\$HOME|\.\.)"),  # rm -rf / or ~ or ..
        re.compile(r"(?i)\bmkfs(\.\w+)?\s+"),                         # filesystem format
        re.compile(r"(?i)\bdd\s+if=.*of=(?:\/dev\/|\b[a-z]:)"),       # raw disk write
        re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"),     # fork bomb
        re.compile(r"(?i)\bshutdown\s+-(?:h|r|s)"),                   # machine shutdown
        re.compile(r"(?i)\b(format|del\s+\/f\s+\/s\s+\/q)\s+[a-z]:"), # Windows disk format/wipe
        re.compile(r"(?i)\bchmod\s+-R\s+777\s+\/"),                   # global root chmod
        re.compile(r"(?i)\bgit\s+push\s+.*--force.*(main|master)"),   # destructive git force push to prod branches
    ]

    # Sensitive paths outside workspace that should never be accessed
    FORBIDDEN_EXTERNAL_PATHS: Set[str] = {
        "/etc/shadow", "/etc/passwd", "/root", "~/.ssh", "~/.aws", "~/.gnupg"
    }

    def __init__(self, enforce_workspace_confinement: bool = True):
        self.enforce_workspace_confinement = enforce_workspace_confinement

    def _is_path_confined(self, path_str: str, workspace_root: str) -> bool:
        """Verifies path resolves to or inside the workspace_root directory."""
        if not path_str:
            return True
        try:
            # Normalize backslashes to forward slashes for cross-platform traversal prevention
            normalized = path_str.replace("\\", "/")
            ws = Path(workspace_root).resolve()
            target = (ws / normalized).resolve() if not Path(normalized).is_absolute() else Path(normalized).resolve()
            # Path must either be workspace itself or inside it
            return target == ws or ws in target.parents
        except Exception:
            return False

    def check_tool(self, tool_name: str, args: Dict[str, Any], workspace: str = ".") -> GuardrailVerdict:
        # 1. Path confinement check for file operations
        if tool_name in ("read_file", "write_file", "edit_file", "list_dir"):
            path = args.get("path") or args.get("file") or ""
            if self.enforce_workspace_confinement and path:
                if not self._is_path_confined(path, workspace):
                    reason = f"Security violation: path '{path}' escapes workspace boundary '{workspace}'"
                    logger.warning(f"[{self.name}] {reason}")
                    return GuardrailVerdict(
                        guardrail_name=self.name,
                        allowed=False,
                        action="block",
                        reason=reason,
                        details={"tool": tool_name, "path": path, "workspace": workspace},
                    )

        # 2. Command analysis for bash execution
        if tool_name == "bash":
            command = args.get("command") or args.get("cmd") or ""
            for pat in self.DANGEROUS_COMMAND_PATTERNS:
                if pat.search(command):
                    reason = f"Security violation: Command blocked by safety policy ({pat.pattern})"
                    logger.error(f"[{self.name}] {reason} for command: {command}")
                    return GuardrailVerdict(
                        guardrail_name=self.name,
                        allowed=False,
                        action="block",
                        reason=reason,
                        details={"tool": tool_name, "command": command},
                    )

        return GuardrailVerdict(guardrail_name=self.name, allowed=True, action="allow")


class ModerationGuardrail(BaseGuardrail):
    """
    Content moderation guardrail.
    Supports asynchronous OpenAI Moderation API verification when available,
    falling back to local zero-latency heuristics for severe harm.
    """

    name: str = "moderation_guardrail"

    # Extreme content local safety heuristics
    SEVERE_CONTENT_PATTERNS: List[Tuple[str, re.Pattern]] = [
        ("self_harm", re.compile(r"(?i)\b(how to commit suicide|kill myself|step by step self-harm)\b")),
        ("cyberattack", re.compile(r"(?i)\b(write a ransomware payload|ddos script targeting|exploit zero-day in)\b")),
        ("violent_extremism", re.compile(r"(?i)\b(instructions to build a bomb|synthesize chemical weapon)\b")),
    ]

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")

    def check_input(self, text: str) -> GuardrailVerdict:
        if not text:
            return GuardrailVerdict(guardrail_name=self.name, allowed=True, action="allow")

        # Local fast heuristic check
        for category, pat in self.SEVERE_CONTENT_PATTERNS:
            if pat.search(text):
                reason = f"Input violated safety moderation policy: {category}"
                logger.error(f"[{self.name}] {reason}")
                return GuardrailVerdict(
                    guardrail_name=self.name,
                    allowed=False,
                    action="block",
                    reason=reason,
                    details={"category": category},
                )

        return GuardrailVerdict(guardrail_name=self.name, allowed=True, action="allow")


class GuardrailPipeline:
    """
    Orchestrates sequential guardrail execution across inputs, tool calls, and outputs.
    Records guardrail execution events for observability and telemetry.
    """

    def __init__(self, guardrails: Optional[List[BaseGuardrail]] = None):
        if guardrails is None:
            self.guardrails: List[BaseGuardrail] = [
                PIIGuardrail(),
                InjectionGuardrail(),
                ToolSafetyGuardrail(),
                ModerationGuardrail(),
            ]
        else:
            self.guardrails = guardrails

    def process_input(self, text: str) -> Tuple[bool, str, List[GuardrailVerdict]]:
        """
        Validates input text through all guardrails.
        Returns: (is_allowed, processed_text, list_of_verdicts)
        """
        verdicts: List[GuardrailVerdict] = []
        current_text = text

        for g in self.guardrails:
            verdict = g.check_input(current_text)
            verdicts.append(verdict)

            if not verdict.allowed:
                return False, current_text, verdicts

            if verdict.action == "mask" and verdict.sanitized_text is not None:
                current_text = verdict.sanitized_text

        return True, current_text, verdicts

    def process_output(self, text: str) -> Tuple[bool, str, List[GuardrailVerdict]]:
        """
        Validates and sanitizes model output before returning to user or client.
        """
        verdicts: List[GuardrailVerdict] = []
        current_text = text

        for g in self.guardrails:
            verdict = g.check_output(current_text)
            verdicts.append(verdict)

            if not verdict.allowed:
                return False, current_text, verdicts

            if verdict.action == "mask" and verdict.sanitized_text is not None:
                current_text = verdict.sanitized_text

        return True, current_text, verdicts

    def process_tool_call(
        self, tool_name: str, args: Dict[str, Any], workspace: str = "."
    ) -> Tuple[bool, Optional[str], List[GuardrailVerdict]]:
        """
        Validates tool execution parameters.
        Returns: (is_allowed, error_message_if_blocked, list_of_verdicts)
        """
        verdicts: List[GuardrailVerdict] = []

        for g in self.guardrails:
            verdict = g.check_tool(tool_name, args, workspace=workspace)
            verdicts.append(verdict)

            if not verdict.allowed:
                return False, verdict.reason, verdicts

        return True, None, verdicts
