"""
Artifact extraction and structured representation for Emiliano.
Extracts Mermaid diagrams, step-by-step checklists, and code diffs from agent outputs.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List


def extract_artifacts(text: str) -> List[Dict[str, Any]]:
    """
    Scans model output text for Mermaid diagrams, plan checklists, and code blocks,
    returning structured artifact dictionaries.
    """
    if not text:
        return []

    artifacts: List[Dict[str, Any]] = []

    # 1. Mermaid diagrams: ```mermaid ... ```
    mermaid_pattern = re.compile(r"```mermaid\s*\n(.*?)\n```", re.DOTALL | re.IGNORECASE)
    for match in mermaid_pattern.finditer(text):
        diagram_code = match.group(1).strip()
        if diagram_code:
            artifacts.append({
                "id": f"diag-{uuid.uuid4().hex[:6]}",
                "title": "Architecture & Workflow Diagram",
                "kind": "diagram",
                "content": diagram_code,
                "metadata": {"diagramType": "mermaid"},
            })

    # 2. Checklists / Plans: lines with - [ ] or - [x]
    lines = text.splitlines()
    plan_lines = [line for line in lines if re.match(r"^\s*-\s*\[[ xX]\]\s+", line)]
    if len(plan_lines) >= 2:
        total = len(plan_lines)
        completed = len([line for line in plan_lines if re.match(r"^\s*-\s*\[[xX]\]\s+", line)])
        artifacts.append({
            "id": f"plan-{uuid.uuid4().hex[:6]}",
            "title": "Execution Plan",
            "kind": "plan",
            "content": "\n".join(plan_lines),
            "metadata": {
                "totalSteps": total,
                "completedSteps": completed,
                "percentage": round((completed / total) * 100) if total > 0 else 0,
            },
        })

    return artifacts
