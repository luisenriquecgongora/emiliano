"""
Unit tests for OpenAITieredRouter (emiliano/core/frontier_router.py).
Tests complexity classification, reasoning effort selection, prompt scrubbing,
and speculative escalation.
"""

import unittest

from emiliano.core.frontier_router import ModelTier, OpenAITieredRouter, RouteDecision


class TestOpenAITieredRouter(unittest.TestCase):
    def setUp(self):
        self.router = OpenAITieredRouter()

    def test_classify_reasoning_complexity(self):
        prompts = [
            "Fix the race condition in the asyncio lock worker pool",
            "Perform a security audit on auth token verification",
            "Optimize graph traversal algorithm from O(N^2) to O(N log N)",
            "Resolve intermittent deadlock between cache and sqlite session",
        ]
        for p in prompts:
            decision = self.router.classify_complexity(p)
            self.assertEqual(decision.tier, ModelTier.REASONING, f"Failed to route reasoning: {p}")
            self.assertEqual(decision.model, OpenAITieredRouter.MODEL_REASONING)
            self.assertIn(decision.reasoning_effort, ["medium", "high"])

    def test_classify_fast_path(self):
        prompts = [
            "Fix typo in variable name in README.md",
            "Add docstring explanation to helper function",
            "What is the syntax for Python dataclass field defaults?",
        ]
        for p in prompts:
            decision = self.router.classify_complexity(p)
            self.assertEqual(decision.tier, ModelTier.FAST, f"Failed to route fast: {p}")
            self.assertEqual(decision.model, OpenAITieredRouter.MODEL_FAST)
            self.assertIsNone(decision.reasoning_effort)

    def test_classify_standard_multi_file_path(self):
        prompt = "Implement billing subscription webhook handler and update models"
        files = ["models.py", "views.py", "webhook.py", "config.py", "tests.py"]
        decision = self.router.classify_complexity(prompt, context_files=files)
        self.assertEqual(decision.tier, ModelTier.STANDARD)
        self.assertEqual(decision.model, OpenAITieredRouter.MODEL_STANDARD)

    def test_normalize_prompt_for_reasoning_models(self):
        raw = "Fix the race condition. Think step-by-step and show your internal thought process before writing code."
        normalized = self.router.normalize_prompt_for_model(raw, target_model="openai/o3-mini")
        self.assertNotIn("think step-by-step", normalized.lower())
        self.assertNotIn("internal thought process", normalized.lower())
        self.assertIn("Fix the race condition", normalized)

        # Standard models should keep the prompt untouched
        standard = self.router.normalize_prompt_for_model(raw, target_model="openai/gpt-4o")
        self.assertEqual(standard, raw)

    def test_speculative_escalation(self):
        initial = RouteDecision(
            tier=ModelTier.FAST,
            model=OpenAITieredRouter.MODEL_FAST,
            reason="Trivial edit",
        )
        error = "AssertionError: Expected lock acquisition within 0.05s but deadlocked"
        escalated = self.router.speculative_escalate(initial, error)

        self.assertTrue(escalated.is_escalated)
        self.assertEqual(escalated.tier, ModelTier.REASONING)
        self.assertEqual(escalated.model, OpenAITieredRouter.MODEL_REASONING)
        self.assertEqual(escalated.reasoning_effort, "high")
        self.assertIn("deadlocked", escalated.reason)


if __name__ == "__main__":
    unittest.main()
