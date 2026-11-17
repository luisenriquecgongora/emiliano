"""
Autonomous Skill Synthesizer & Progressive Registry Engine.
Inspired by Nous Research Hermes Agent & the open agentskills.io standard.
Enables Emiliano to discover, progressively disclose, dynamically hydrate,
and autonomously auto-synthesize and self-heal reusable workflow skills (SKILL.md).
Licensed under PolyForm Shield 1.0.0.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("emiliano.skills")


@dataclass
class SkillDefinition:
    id: str
    title: str
    description: str
    version: str = "1.0.0"
    status: str = "active"  # "active" | "staged" | "archived"
    category: str = "workflow"  # "workflow" | "browser" | "system" | "custom"
    triggers: List[str] = field(default_factory=list)
    requirements: List[str] = field(default_factory=list)
    selectors: Dict[str, str] = field(default_factory=dict)
    instructions_md: str = ""
    path: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["path"] = str(self.path)
        return d

    def to_compact_dict(self) -> Dict[str, Any]:
        """Compact representation for progressive disclosure in agent prompts."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "triggers": self.triggers,
            "status": self.status,
            "category": self.category,
        }


class SkillManager:
    """Discovers, manages, progressively discloses, and autonomously synthesizes skills."""

    _instance: Optional["SkillManager"] = None

    def __init__(self, workspace_root: Optional[Path] = None):
        self.workspace_root = workspace_root or Path.cwd().resolve()
        self.skills_dir = self.workspace_root / ".agents" / "skills"
        self.staged_dir = self.workspace_root / ".agents" / "staged_skills"

        # Ensure base directories exist
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.staged_dir.mkdir(parents=True, exist_ok=True)

        self._skills: Dict[str, SkillDefinition] = {}
        self.discover_all()

    @classmethod
    def get_instance(cls, workspace_root: Optional[Path] = None) -> "SkillManager":
        if cls._instance is None:
            cls._instance = cls(workspace_root)
        return cls._instance

    def get_search_directories(self) -> List[Tuple[Path, str]]:
        """Returns list of (directory_path, default_status) to scan."""
        dirs = [
            (self.skills_dir, "active"),
            (self.staged_dir, "staged"),
            (self.workspace_root / "skills", "active"),
            (self.workspace_root / "emiliano-cowork-plaatoos" / "skills", "active"),
        ]
        home_skills = Path.home() / ".emiliano" / "skills"
        if home_skills.exists():
            dirs.append((home_skills, "active"))
        return [(p, status) for p, status in dirs if p.exists()]

    def discover_all(self) -> Dict[str, SkillDefinition]:
        """Scans all search paths for SKILL.md packages and registers them."""
        self._skills.clear()

        # Built-in baseline skills (registered programmatically)
        self._register_builtins()

        for search_dir, default_status in self.get_search_directories():
            try:
                for skill_md in search_dir.glob("**/SKILL.md"):
                    skill = self._parse_skill_md(skill_md, default_status)
                    if skill:
                        self._skills[skill.id] = skill
            except Exception as e:
                logger.warning(f"[SkillManager] Error scanning {search_dir}: {e}")

        logger.info(f"[SkillManager] Discovered {len(self._skills)} skills ({sum(1 for s in self._skills.values() if s.status == 'active')} active, {sum(1 for s in self._skills.values() if s.status == 'staged')} staged).")
        return self._skills

    def _register_builtins(self):
        """Registers built-in baseline skills for desktop cowork and outreach."""
        self._skills["desktop-cowork"] = SkillDefinition(
            id="desktop-cowork",
            title="Desktop Cowork & UIA Pinning",
            description="Native Windows UI automation, window HWND pinning, and coordinate/ghost interactions.",
            category="system",
            status="active",
            triggers=["click", "type", "pin window", "inspect ui"],
            instructions_md="# Desktop Cowork\nUse UIA perception to inspect actionable elements. Invoke non-intrusively via ghost patterns."
        )

    def _parse_skill_md(self, path: Path, default_status: str = "active") -> Optional[SkillDefinition]:
        """Parses a SKILL.md file with YAML frontmatter into a SkillDefinition."""
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"[SkillManager] Could not read {path}: {e}")
            return None

        frontmatter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)
        metadata: Dict[str, Any] = {}
        body = content

        if frontmatter_match:
            raw_yaml = frontmatter_match.group(1)
            body = frontmatter_match.group(2).strip()
            metadata = self._parse_simple_yaml(raw_yaml)

        skill_id = metadata.get("id") or metadata.get("name") or path.parent.name

        # Verify integrity hash if present
        integrity_file = path.parent / ".integrity.sha256"
        if integrity_file.exists():
            try:
                expected_sha = integrity_file.read_text(encoding="utf-8").strip()
                actual_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
                if expected_sha and actual_sha != expected_sha:
                    logger.warning(
                        f"[SkillManager] Integrity warning: skill '{skill_id}' at {path} failed SHA-256 integrity verification! "
                        f"(Expected {expected_sha[:8]}..., actual {actual_sha[:8]}...)"
                    )
            except Exception as e:
                logger.warning(f"[SkillManager] Could not verify integrity for {skill_id}: {e}")

        title = metadata.get("title") or metadata.get("name") or skill_id.replace("-", " ").title()
        description = metadata.get("description") or (body.split("\n")[0].replace("#", "").strip() if body else "")
        status = metadata.get("status") or default_status
        version = metadata.get("version") or "1.0.0"
        category = metadata.get("category") or ("workflow" if "outreach" in skill_id else "custom")

        triggers = metadata.get("triggers", [])
        if isinstance(triggers, str):
            triggers = [t.strip() for t in triggers.split(",")]

        requirements = metadata.get("requirements", [])
        if isinstance(requirements, str):
            requirements = [r.strip() for r in requirements.split(",")]

        selectors = metadata.get("selectors", {})
        if not isinstance(selectors, dict):
            selectors = {}

        return SkillDefinition(
            id=skill_id,
            title=title,
            description=description,
            version=version,
            status=status,
            category=category,
            triggers=triggers,
            requirements=requirements,
            selectors=selectors,
            instructions_md=body,
            path=str(path),
        )

    def _parse_simple_yaml(self, raw: str) -> Dict[str, Any]:
        """Lightweight YAML parser for frontmatter without external dependencies."""
        data: Dict[str, Any] = {}
        current_list_key = None

        for line in raw.splitlines():
            line_str = line.strip()
            if not line_str or line_str.startswith("#"):
                continue

            # List item
            if line_str.startswith("- ") and current_list_key:
                val = line_str[2:].strip().strip("\"'")
                data[current_list_key].append(val)
                continue

            # Key-value pair
            if ":" in line_str:
                parts = line_str.split(":", 1)
                key = parts[0].strip()
                val = parts[1].strip().strip("\"'")
                current_list_key = None

                if val == "":
                    # Might be starting a list
                    data[key] = []
                    current_list_key = key
                elif val.startswith("[") and val.endswith("]"):
                    items = [x.strip().strip("\"'") for x in val[1:-1].split(",") if x.strip()]
                    data[key] = items
                else:
                    data[key] = val

        return data

    def synthesize_skill(
        self,
        id: str,
        title: str,
        description: str,
        instructions_md: str,
        triggers: Optional[List[str]] = None,
        requirements: Optional[List[str]] = None,
        selectors: Optional[Dict[str, str]] = None,
        category: str = "workflow"
    ) -> SkillDefinition:
        """
        Auto-synthesizes a new reusable skill into the .staged_skills directory
        for user review and approval before permanent activation.
        """
        # Clean slug
        clean_id = re.sub(r"[^a-z0-9_-]", "-", id.lower().strip()).strip("-")
        dest_dir = self.staged_dir / clean_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = dest_dir / "SKILL.md"

        triggers_list = triggers or []
        requirements_list = requirements or ["browser_bridge", "cdp"]
        selectors_dict = selectors or {}

        # Build YAML frontmatter
        yaml_lines = [
            "---",
            f"id: {clean_id}",
            f"name: {clean_id}",
            f"title: \"{title}\"",
            f"description: \"{description}\"",
            f"category: {category}",
            "status: staged",
            "version: 1.0.0",
        ]
        if triggers_list:
            yaml_lines.append("triggers:")
            for t in triggers_list:
                yaml_lines.append(f"  - \"{t}\"")
        if requirements_list:
            yaml_lines.append("requirements:")
            for r in requirements_list:
                yaml_lines.append(f"  - \"{r}\"")
        if selectors_dict:
            yaml_lines.append("selectors:")
            for k, v in selectors_dict.items():
                yaml_lines.append(f"  {k}: \"{v}\"")
        yaml_lines.append("---\n")

        full_content = "\n".join(yaml_lines) + instructions_md.strip() + "\n"
        dest_file.write_text(full_content, encoding="utf-8")

        skill = SkillDefinition(
            id=clean_id,
            title=title,
            description=description,
            status="staged",
            category=category,
            triggers=triggers_list,
            requirements=requirements_list,
            selectors=selectors_dict,
            instructions_md=instructions_md,
            path=str(dest_file)
        )
        self._skills[clean_id] = skill
        logger.info(f"[SkillManager] Successfully synthesized staged skill '{clean_id}' at {dest_file}")
        return skill

    def approve_skill(self, skill_id: str) -> bool:
        """Promotes a staged skill to the active skills directory."""
        skill = self._skills.get(skill_id)
        if not skill:
            logger.warning(f"[SkillManager] Cannot approve unknown skill: {skill_id}")
            return False

        if skill.status == "active":
            return True

        src_path = Path(skill.path)
        dest_dir = self.skills_dir / skill_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = dest_dir / "SKILL.md"

        # Update status in file to active
        content = src_path.read_text(encoding="utf-8")
        updated_content = content.replace("status: staged", "status: active")
        dest_file.write_text(updated_content, encoding="utf-8")

        # Cryptographic integrity signature
        sha256 = hashlib.sha256(updated_content.encode("utf-8")).hexdigest()
        (dest_dir / ".integrity.sha256").write_text(sha256, encoding="utf-8")

        # Clean up staged folder
        if src_path.parent != dest_dir:
            shutil.rmtree(src_path.parent, ignore_errors=True)

        skill.status = "active"
        skill.path = str(dest_file)
        self._skills[skill_id] = skill
        logger.info(f"[SkillManager] Approved and promoted skill '{skill_id}' to active library (SHA-256: {sha256[:8]}...).")
        return True

    def discard_skill(self, skill_id: str) -> bool:
        """Deletes a staged skill draft."""
        skill = self._skills.get(skill_id)
        if not skill:
            return False

        if skill.path and Path(skill.path).exists():
            shutil.rmtree(Path(skill.path).parent, ignore_errors=True)

        self._skills.pop(skill_id, None)
        logger.info(f"[SkillManager] Discarded staged skill '{skill_id}'.")
        return True

    def patch_skill(
        self,
        skill_id: str,
        selectors: Optional[Dict[str, str]] = None,
        append_notes: Optional[str] = None
    ) -> bool:
        """Self-healing patch function: updates selectors or appends recovery notes to a skill."""
        skill = self._skills.get(skill_id)
        if not skill or not skill.path:
            return False

        path = Path(skill.path)
        if not path.exists():
            return False

        content = path.read_text(encoding="utf-8")

        # Update selectors
        if selectors:
            skill.selectors.update(selectors)
            # Simple replacement or append
            for k, v in selectors.items():
                if f"{k}:" in content:
                    content = re.sub(rf"{k}:.*", f"{k}: \"{v}\"", content)
                else:
                    content = content.replace("---\n\n", f"  {k}: \"{v}\"\n---\n\n")

        # Append troubleshooting or recovery notes
        if append_notes:
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            note_block = f"\n\n### Self-Healing Note ({timestamp})\n{append_notes.strip()}\n"
            content += note_block
            skill.instructions_md += note_block

        path.write_text(content, encoding="utf-8")
        logger.info(f"[SkillManager] Self-healed and patched skill '{skill_id}'.")
        return True

    def get_compact_registry(self) -> List[Dict[str, Any]]:
        """Returns compact metadata list for prompt progressive disclosure."""
        return [s.to_compact_dict() for s in self._skills.values() if s.status == "active"]

    def get_all_skills(self) -> List[Dict[str, Any]]:
        """Returns all skills (active and staged) for API and UI rendering."""
        return [s.to_dict() for s in self._skills.values()]

    def get_skill(self, skill_id: str) -> Optional[SkillDefinition]:
        return self._skills.get(skill_id)
