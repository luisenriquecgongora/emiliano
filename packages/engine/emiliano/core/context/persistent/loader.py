"""
Persistent context file loader.
Implements IPersistentContext interface.
"""

from pathlib import Path
from typing import List, Dict, Optional

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("emiliano")


class PersistentContextLoader:
    """
    Loads persistent context from special files (EMILIANO.md, CLAUDE.md, etc.).

    Single Responsibility: Load and parse persistent context files.
    Open/Closed: Extend by adding new filename patterns.

    Usage:
        Persistent context files are NEVER truncated or summarized.
        They provide stable, long-term instructions and context.

    Example EMILIANO.md:
        ```markdown
        # Project Context

        This is a Python-based AI agent harness.

        ## Coding Standards
        - Follow PEP 8
        - Use type hints
        - Document all public APIs
        ```
    """

    def __init__(
        self,
        filenames: Optional[List[str]] = None,
        search_paths: Optional[List[str]] = None,
    ):
        """
        Initialize persistent context loader.

        Args:
            filenames: List of filenames to search for
            search_paths: Additional search paths (beyond working dir)
        """
        self.filenames = filenames or [
            "EMILIANO.md",
            "CLAUDE.md",
            ".emiliano/context.md",
            ".ai/context.md",
        ]
        self.search_paths = search_paths or []

    def load_persistent_context(
        self,
        working_dir: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """
        Load persistent context from files.

        Args:
            working_dir: Directory to search (defaults to cwd)

        Returns:
            List of system messages from persistent files
        """
        working_dir = working_dir or str(Path.cwd())
        base_path = Path(working_dir)

        messages = []

        for filename in self.filenames:
            file_path = base_path / filename

            if file_path.exists() and file_path.is_file():
                try:
                    content = file_path.read_text(encoding="utf-8")
                    if content.strip():
                        logger.info(f"[PersistentContext] Loaded {filename} ({len(content)} chars)")
                        messages.append({
                            "role": "system",
                            "content": f"[Persistent context from {filename}]\n\n{content}"
                        })
                except Exception as e:
                    logger.warning(f"[PersistentContext] Failed to load {filename}: {e}")

        # Search additional paths
        for search_path in self.search_paths:
            search_base = Path(search_path)
            if search_base.exists():
                for filename in self.filenames:
                    file_path = search_base / filename
                    if file_path.exists() and file_path.is_file():
                        try:
                            content = file_path.read_text(encoding="utf-8")
                            if content.strip():
                                # Avoid duplicates
                                existing = any(
                                    filename in msg.get("content", "")
                                    for msg in messages
                                )
                                if not existing:
                                    logger.info(f"[PersistentContext] Loaded {filename} from {search_path}")
                                    messages.append({
                                        "role": "system",
                                        "content": f"[Persistent context from {search_path}/{filename}]\n\n{content}"
                                    })
                        except Exception as e:
                            logger.warning(f"[PersistentContext] Failed to load {search_path}/{filename}: {e}")

        if messages:
            logger.info(f"[PersistentContext] Loaded {len(messages)} persistent context file(s)")
        else:
            logger.debug("[PersistentContext] No persistent context files found")

        return messages

    def get_persistent_filenames(self) -> List[str]:
        """
        Get list of filenames checked for persistent context.

        Returns:
            List of filenames
        """
        return self.filenames.copy()

    def create_template(self, output_path: Optional[str] = None) -> str:
        """
        Create a template EMILIANO.md file.

        Args:
            output_path: Path to write template (defaults to ./EMILIANO.md)

        Returns:
            Path to created file
        """
        output_path = output_path or str(Path.cwd() / "EMILIANO.md")
        template = """# Emiliano Persistent Context

This file provides persistent context that is **never truncated or summarized**.
Use it for:
- Project-specific instructions
- Coding standards and conventions
- Important architectural decisions
- Domain knowledge

## Project Overview

<!-- Describe your project here -->

## Coding Standards

<!-- Your coding standards -->
- Follow SOLID principles
- Write tests for new features
- Document public APIs

## Architecture Notes

<!-- Key architectural decisions -->

## Domain Knowledge

<!-- Domain-specific context -->

---

**Note:** This file is automatically loaded at the start of every Emiliano session.
Updates to this file take effect in new sessions.
"""

        path = Path(output_path)
        path.write_text(template, encoding="utf-8")
        logger.info(f"[PersistentContext] Created template at {output_path}")

        return str(path)
