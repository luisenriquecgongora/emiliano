"""
Unit tests for Emiliano Hybrid Speculative Execution Pipeline.
"""

import pytest
from emiliano.core.hybrid_pipeline import (
    HybridSpeculativePipeline,
    ExecutionTier,
    VerificationResult,
)
from emiliano.core.privacy_vault import PrivacyVault


class FakeLLMClient:
    def __init__(self):
        self.invocations = []

    async def stream_completion(self, messages, model_name=None, **kwargs):
        self.invocations.append((model_name, messages))
        prompt_text = messages[-1]["content"]

        if model_name.startswith("ollama/"):
            if "syntax_error" in prompt_text:
                yield "def invalid_syntax(:\n    return True\n"
            elif "logic_error" in prompt_text:
                yield "def solve():\n    return 0  # wrong answer\n"
            else:
                token = "__VAULT_PII_EMAIL_1__" if "__VAULT_PII_EMAIL_1__" in prompt_text else "user@example.com"
                yield f"def handle_user():\n    return '{token}'\n"
        else:
            # Frontier model (o3-mini / gpt-4o)
            token = "__VAULT_PII_EMAIL_1__" if "__VAULT_PII_EMAIL_1__" in prompt_text else "user@example.com"
            yield f"def solve_frontier():\n    # Fixed and verified by o3-mini\n    return '{token}'\n"


@pytest.mark.asyncio
async def test_speculative_local_success():
    client = FakeLLMClient()
    vault = PrivacyVault()
    pipeline = HybridSpeculativePipeline(
        llm_client=client,
        local_model="ollama/qwen2.5-coder:7b",
        frontier_model="o3-mini",
        privacy_vault=vault,
    )

    result = await pipeline.execute(
        prompt="Write a helper for user alice@monzo.com",
    )

    assert result.tier_used == ExecutionTier.LOCAL_SPECULATIVE
    assert result.verification_passed is True
    assert result.cost_usd == 0.0
    assert result.cost_saved_usd > 0.0
    assert result.speculative_local_attempted is True
    assert "alice@monzo.com" in result.final_output  # Rehydrated!
    assert len(client.invocations) == 1
    assert client.invocations[0][0] == "ollama/qwen2.5-coder:7b"


@pytest.mark.asyncio
async def test_speculative_local_syntax_failure_escalates():
    client = FakeLLMClient()
    vault = PrivacyVault()
    pipeline = HybridSpeculativePipeline(
        llm_client=client,
        local_model="ollama/qwen2.5-coder:7b",
        frontier_model="o3-mini",
        privacy_vault=vault,
    )

    result = await pipeline.execute(
        prompt="Please trigger syntax_error for customer security@revolut.com",
    )

    assert result.tier_used == ExecutionTier.FRONTIER_ESCALATED
    assert result.verification_passed is True
    assert result.speculative_local_attempted is True
    assert "SyntaxError" in result.escalation_reason
    assert "security@revolut.com" in result.final_output

    assert len(client.invocations) == 2
    # Verify frontier call received diagnostic trace
    frontier_model, frontier_msgs = client.invocations[1]
    assert frontier_model == "o3-mini"
    last_content = frontier_msgs[-1]["content"]
    assert "[SPECULATIVE EXECUTION DIAGNOSTIC]" in last_content
    assert "SyntaxError" in last_content
    # Zero PII leakage verification on external call
    assert "security@revolut.com" not in last_content
    assert "__VAULT_PII_EMAIL_1__" in last_content


@pytest.mark.asyncio
async def test_speculative_custom_verifier_escalates():
    client = FakeLLMClient()
    vault = PrivacyVault()
    pipeline = HybridSpeculativePipeline(
        llm_client=client,
        local_model="ollama/qwen2.5-coder:7b",
        frontier_model="o3-mini",
        privacy_vault=vault,
    )

    def custom_checker(code: str) -> VerificationResult:
        if "return 0" in code:
            return VerificationResult(
                passed=False,
                gate_name="unit_test_checker",
                error_message="AssertionError: Expected 42, got 0",
            )
        return VerificationResult(passed=True, gate_name="unit_test_checker")

    result = await pipeline.execute(
        prompt="Trigger logic_error in calculations",
        verifier=custom_checker,
    )

    assert result.tier_used == ExecutionTier.FRONTIER_ESCALATED
    assert "AssertionError: Expected 42, got 0" in result.escalation_reason
    assert len(client.invocations) == 2


@pytest.mark.asyncio
async def test_direct_frontier_override():
    client = FakeLLMClient()
    vault = PrivacyVault()
    pipeline = HybridSpeculativePipeline(
        llm_client=client,
        local_model="ollama/qwen2.5-coder:7b",
        frontier_model="o3-mini",
        privacy_vault=vault,
    )

    result = await pipeline.execute(
        prompt="Execute directly without local attempt",
        force_tier=ExecutionTier.DIRECT_FRONTIER,
    )

    assert result.tier_used == ExecutionTier.DIRECT_FRONTIER
    assert result.speculative_local_attempted is False
    assert len(client.invocations) == 1
    assert client.invocations[0][0] == "o3-mini"
