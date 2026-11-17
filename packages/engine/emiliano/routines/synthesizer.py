"""
Teach-a-Task Synthesizer: Compiles recorded user demonstrations
into structured, parameterized SKILL.md packages adhering to the 6 core components:
1. Trigger Context
2. Inputs & Access
3. Sequence of Work
4. Validation Rules
5. Expected Outputs
6. Approval Boundaries
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("emiliano.routines.synthesizer")

from ..core.skills import SkillDefinition, SkillManager


class SkillSynthesizer:
    """Compiles recorded DOM & UIA demonstration traces into reusable skills."""

    def __init__(self, skill_manager: Optional[SkillManager] = None):
        self.skill_manager = skill_manager or SkillManager.get_instance()

    def compile_trace(
        self,
        skill_id: str,
        title: str,
        user_goal: str,
        events: List[Dict[str, Any]],
        approval_actions: Optional[List[str]] = None,
    ) -> SkillDefinition:
        """
        Compiles raw recorded telemetry events into a production SkillDefinition.
        """
        logger.info(f"Synthesizing skill '{skill_id}' from {len(events)} demonstrated events...")

        selectors: Dict[str, str] = {}
        inputs: Dict[str, str] = {}
        steps_md: List[str] = []
        validation_rules: List[str] = []
        step_idx = 1

        for ev in events:
            ev_type = ev.get("type", "action")
            tag_name = ev.get("tag", "element")
            selector = ev.get("selector", "")
            value = ev.get("value", "")
            text = ev.get("text", "")
            url = ev.get("url", "")

            sel_key = f"{tag_name}_{step_idx}"
            if selector:
                selectors[sel_key] = selector

            if ev_type == "navigate":
                steps_md.append(f"{step_idx}. **Navigate** to `{url}` and wait for DOM load.")
                validation_rules.append(f"Verify URL matches `{url}`.")
                step_idx += 1

            elif ev_type in ("click", "tap"):
                label = text or selector or "button"
                steps_md.append(f"{step_idx}. **Click** on `{label}` (`{selector}`).")
                steps_md.append("   - Confirm target element received activation state.")
                step_idx += 1

            elif ev_type in ("input", "type", "change"):
                input_key = f"input_{step_idx}"
                inputs[input_key] = value
                steps_md.append(f"{step_idx}. **Type** into `{selector}`:")
                steps_md.append(f"   - Value: `{{{{inputs.{input_key}}}}}` (Default: `{value}`)")
                step_idx += 1

        # Build standard 6-component markdown structure
        instructions = [
            f"# {title}",
            "> Autonomous skill synthesized via Teach-a-Task demonstration.",
            "",
            "## 1. Trigger Context",
            f"Active when user requests: *\"{user_goal}\"*",
            "",
            "## 2. Inputs & Access",
        ]

        if inputs:
            for k, default_val in inputs.items():
                instructions.append(f"- `{k}`: (default: `{default_val}`)")
        else:
            instructions.append("- No external dynamic inputs required.")

        instructions.extend([
            "",
            "## 3. Sequence of Work",
            *steps_md,
            "",
            "## 4. Validation Rules",
            *([f"- {r}" for r in validation_rules] if validation_rules else ["- Verify all UI actions return successful receipts."]),
            "",
            "## 5. Expected Outputs",
            "- Status: `success` | `failure`",
            "- Visual screenshot receipt of final completion state.",
            "",
            "## 6. Approval Boundaries",
        ])

        boundaries = approval_actions or ["send_message", "make_payment", "delete_file"]
        for b in boundaries:
            instructions.append(f"- `[{b}]`: **Requires explicit human confirmation** before execution.")

        instructions_content = "\n".join(instructions)

        # Stage the synthesized skill via SkillManager
        staged_skill = self.skill_manager.synthesize_skill(
            id=skill_id,
            title=title,
            description=f"Automated skill for: {user_goal}",
            instructions_md=instructions_content,
            triggers=[user_goal.lower(), title.lower()],
            selectors=selectors,
            category="browser" if any(e.get("url") for e in events) else "workflow",
        )

        return staged_skill
