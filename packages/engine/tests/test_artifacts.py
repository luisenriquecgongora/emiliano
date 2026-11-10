"""
Tests for artifact extraction and wire protocol contracts (emiliano/core/artifacts.py).
"""

import importlib.util
import unittest
from pathlib import Path

from emiliano.core.artifacts import extract_artifacts

# Load packages/protocol/models.py dynamically
protocol_models_path = Path(__file__).resolve().parent.parent.parent.parent / "packages" / "protocol" / "models.py"
spec = importlib.util.spec_from_file_location("protocol_models", protocol_models_path)
protocol_models = importlib.util.module_from_spec(spec)
spec.loader.exec_module(protocol_models)

ArtifactKind = protocol_models.ArtifactKind
ArtifactPayload = protocol_models.ArtifactPayload


class TestArtifactExtraction(unittest.TestCase):
    def test_extract_empty(self):
        self.assertEqual(extract_artifacts(""), [])
        self.assertEqual(extract_artifacts(None), [])
        self.assertEqual(extract_artifacts("Just a normal conversation message."), [])

    def test_extract_mermaid_diagram(self):
        text = (
            "Here is the architecture:\n\n"
            "```mermaid\n"
            "flowchart TD\n"
            "    A[Start] --> B[Process]\n"
            "    B --> C[Finish]\n"
            "```\n\n"
            "Let me know what you think!"
        )
        artifacts = extract_artifacts(text)
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0]["kind"], "diagram")
        self.assertEqual(artifacts[0]["title"], "Architecture & Workflow Diagram")
        self.assertIn("A[Start] --> B[Process]", artifacts[0]["content"])
        self.assertEqual(artifacts[0]["metadata"]["diagramType"], "mermaid")

    def test_extract_plan_checklist(self):
        text = (
            "Here is the plan:\n"
            "- [x] Step 1: Design architecture\n"
            "- [ ] Step 2: Implement core loop\n"
            "- [ ] Step 3: Run verify suite\n"
        )
        artifacts = extract_artifacts(text)
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0]["kind"], "plan")
        self.assertEqual(artifacts[0]["title"], "Execution Plan")
        self.assertEqual(artifacts[0]["metadata"]["totalSteps"], 3)
        self.assertEqual(artifacts[0]["metadata"]["completedSteps"], 1)
        self.assertEqual(artifacts[0]["metadata"]["percentage"], 33)

    def test_extract_multiple_artifacts(self):
        text = (
            "Here is the system plan and flow:\n\n"
            "```mermaid\n"
            "graph LR\n"
            "    X --> Y\n"
            "```\n\n"
            "Steps:\n"
            "- [ ] Task A\n"
            "- [ ] Task B\n"
        )
        artifacts = extract_artifacts(text)
        self.assertEqual(len(artifacts), 2)
        kinds = {a["kind"] for a in artifacts}
        self.assertEqual(kinds, {"diagram", "plan"})

    def test_protocol_models_validation(self):
        payload = ArtifactPayload(
            id="diag-123",
            title="System Architecture",
            kind=ArtifactKind.DIAGRAM,
            content="flowchart TD\nA --> B",
            metadata={"diagramType": "mermaid"},
        )
        self.assertEqual(payload.kind, ArtifactKind.DIAGRAM)
        self.assertEqual(payload.id, "diag-123")
        dump = payload.model_dump()
        self.assertEqual(dump["title"], "System Architecture")


if __name__ == "__main__":
    unittest.main()
