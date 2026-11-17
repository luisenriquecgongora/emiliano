"""
Autonomous Extension & Cowork Workflow Discovery Engine.
Enables Emiliano to discover, load, and execute workspace companion extensions
(such as client outreach pipelines, custom scraping workflows, or data loaders)
without polluting the open-source core with proprietary business logic.
Licensed under PolyForm Shield 1.0.0.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union
from loguru import logger


@dataclass
class ExtensionManifest:
    name: str
    title: str
    description: str = ""
    intents: List[str] = field(default_factory=list)
    entry_point: str = "campaign.py:run_extension_outreach"
    path: Path = field(default_factory=Path)


class ExtensionManager:
    """Discovers and invokes companion workflow extensions in the workspace."""

    def __init__(self, search_paths: Optional[List[Union[str, Path]]] = None):
        self.search_paths: List[Path] = []
        if search_paths:
            self.search_paths.extend([Path(p) for p in search_paths])
        else:
            # Default discovery paths: current directory, parents up to 3 levels, and extensions/
            cwd = Path.cwd().resolve()
            self.search_paths.extend([
                cwd,
                cwd.parent,
                cwd.parent.parent,
                cwd / "extensions",
                cwd / "plugins",
                cwd.parent / "extensions",
                cwd.parent.parent / "extensions",
            ])
            # Include repository roots relative to this file so extensions are discovered
            # even when tests or evals change working directory to temporary folders
            file_parents = list(Path(__file__).resolve().parents)
            for p in file_parents[1:6]:
                if p not in self.search_paths:
                    self.search_paths.append(p)
                    self.search_paths.append(p / "extensions")
                    self.search_paths.append(p / "plugins")

            # Also check EMILIANO_WORKSPACE or EMILIANO_ROOT environment variables if set
            for env_key in ("EMILIANO_WORKSPACE", "EMILIANO_ROOT", "WORKSPACE_ROOT"):
                env_val = os.environ.get(env_key)
                if env_val and Path(env_val).exists():
                    val_path = Path(env_val).resolve()
                    if val_path not in self.search_paths:
                        self.search_paths.append(val_path)

        self.extensions: Dict[str, ExtensionManifest] = {}
        self.discover()

    def discover(self) -> Dict[str, ExtensionManifest]:
        """Scans search paths for extension.json or manifest.json files."""
        discovered: Dict[str, ExtensionManifest] = {}
        for base_path in self.search_paths:
            if not base_path.exists() or not base_path.is_dir():
                continue

            # Look for subdirectories like emiliano-cowork-* or any folder with extension.json
            candidates: List[Path] = []
            if (base_path / "extension.json").exists():
                candidates.append(base_path)

            try:
                for entry in base_path.iterdir():
                    if entry.is_dir() and (entry / "extension.json").exists():
                        candidates.append(entry)
            except Exception as e:
                logger.debug(f"[Extensions] Could not scan {base_path}: {e}")

            for cand in candidates:
                manifest_file = cand / "extension.json"
                try:
                    data = json.loads(manifest_file.read_text(encoding="utf-8"))
                    name = data.get("name") or cand.name
                    ext = ExtensionManifest(
                        name=name,
                        title=data.get("title") or name,
                        description=data.get("description", ""),
                        intents=[i.lower().strip() for i in data.get("intents", [])],
                        entry_point=data.get("entry_point", "campaign.py:run_extension_outreach"),
                        path=cand.resolve(),
                    )
                    discovered[name] = ext
                    logger.info(f"[Extensions] Discovered extension: {ext.name} ('{ext.title}') at {ext.path}")
                except Exception as e:
                    logger.warning(f"[Extensions] Failed to load manifest at {manifest_file}: {e}")

        self.extensions = discovered
        return self.extensions

    def match_intent(self, goal: str) -> Optional[ExtensionManifest]:
        """Matches a user prompt/goal to a registered extension by intent keyword."""
        clean_goal = goal.lower().strip()
        for ext in self.extensions.values():
            for intent in ext.intents:
                words = intent.split()
                if len(words) == 1:
                    pattern = rf"\b{re.escape(words[0])}\b"
                    if re.search(pattern, clean_goal):
                        logger.info(f"[Extensions] Matched goal '{goal[:50]}' to extension '{ext.name}' via intent '{intent}'")
                        return ext
                else:
                    # Allow up to 3 intervening words (such as numbers or adjectives: "send 5 instagram dms")
                    pattern = r"\b" + r"\b(?:\s+\w+){0,3}\s+\b".join(re.escape(w) for w in words) + r"\b"
                    if re.search(pattern, clean_goal) or intent in clean_goal:
                        logger.info(f"[Extensions] Matched goal '{goal[:50]}' to extension '{ext.name}' via flexible intent '{intent}'")
                        return ext
        return None

    async def execute_extension(
        self,
        extension: ExtensionManifest,
        goal: str,
        on_chunk: Optional[Callable[[str], None]] = None,
        on_progress: Optional[Callable[[str, int, int], None]] = None,
        on_reasoning: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Dynamically loads and invokes the extension entry point."""
        if ":" not in extension.entry_point:
            raise ValueError(f"Invalid entry_point format '{extension.entry_point}'. Expected 'module.py:function'")

        rel_file, func_name = extension.entry_point.split(":", 1)
        target_file = extension.path / rel_file
        if not target_file.exists():
            raise FileNotFoundError(f"Extension entry point file not found: {target_file}")

        # Add extension directory to sys.path so its internal modules resolve
        ext_dir = str(extension.path)
        if ext_dir not in sys.path:
            sys.path.insert(0, ext_dir)

        spec = importlib.util.spec_from_file_location(f"emiliano_ext_{extension.name}", target_file)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load module spec from {target_file}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        target_fn = getattr(module, func_name, None)
        if target_fn is None or not callable(target_fn):
            raise AttributeError(f"Function '{func_name}' not found in {target_file}")

        import inspect
        kwargs: Dict[str, Any] = {"goal": goal}
        sig = inspect.signature(target_fn)
        if "on_chunk" in sig.parameters:
            kwargs["on_chunk"] = on_chunk
        if "on_progress" in sig.parameters:
            kwargs["on_progress"] = on_progress
        if "on_reasoning" in sig.parameters:
            kwargs["on_reasoning"] = on_reasoning

        if inspect.iscoroutinefunction(target_fn):
            result = await target_fn(**kwargs)
        else:
            import asyncio
            result = await asyncio.to_thread(target_fn, **kwargs)

        return str(result)
