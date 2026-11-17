"""
Unit & Integration Tests for Emiliano Routines & Teach-a-Task Subsystem.
"""

import pytest

from emiliano.routines.models import (
    ApprovalBoundary,
    ExecutionStatus,
    Routine,
    StagedActionStatus,
    TriggerConfig,
    TriggerType,
)
from emiliano.routines.cron_evaluator import get_next_cron_run, parse_field
from emiliano.routines.store import RoutineStore
from emiliano.routines.scheduler import RoutineScheduler
from emiliano.routines.synthesizer import SkillSynthesizer
from emiliano.core.skills import SkillManager


@pytest.fixture
def temp_store(tmp_path):
    db_file = tmp_path / "test_routines.db"
    return RoutineStore(db_path=db_file)


@pytest.fixture
def temp_skills_manager(tmp_path):
    return SkillManager(workspace_root=tmp_path)


def test_parse_field():
    assert parse_field("*", 0, 5) == {0, 1, 2, 3, 4, 5}
    assert parse_field("*/2", 0, 5) == {0, 2, 4}
    assert parse_field("1-3", 0, 5) == {1, 2, 3}
    assert parse_field("1,3,5", 0, 5) == {1, 3, 5}


def test_cron_next_run():
    now = 1700000000.0  # Fixed timestamp
    next_ts = get_next_cron_run("0 8 * * *", after_timestamp=now)
    assert next_ts > now

    # @hourly should be at minute 0
    next_hourly = get_next_cron_run("@hourly", after_timestamp=now)
    assert next_hourly > now


def test_routine_crud(temp_store):
    routine = Routine(
        id="daily-outreach",
        name="Daily Instagram Outreach",
        description="Heat up target profiles and stage DMs",
        bot_persona="browser",
        goal_template="Check profile {{profile_url}} and draft message",
        inputs={"profile_url": "https://instagram.com/lead"},
        trigger=TriggerConfig(type=TriggerType.CRON, cron_expression="0 9 * * 1-5"),
        approval_boundaries=[
            ApprovalBoundary(action_type="send_message", requires_human=True, draft_mode=True)
        ],
    )
    temp_store.save_routine(routine)

    retrieved = temp_store.get_routine("daily-outreach")
    assert retrieved is not None
    assert retrieved.name == "Daily Instagram Outreach"
    assert retrieved.bot_persona == "browser"
    assert retrieved.trigger.type == TriggerType.CRON
    assert len(retrieved.approval_boundaries) == 1
    assert retrieved.approval_boundaries[0].action_type == "send_message"

    # Test goal rendering
    rendered = retrieved.render_goal()
    assert "https://instagram.com/lead" in rendered


@pytest.mark.asyncio
async def test_scheduler_trust_gates(temp_store):
    scheduler = RoutineScheduler(store=temp_store)

    routine = Routine(
        id="automated-billing",
        name="Automated Invoice Settlement",
        trigger=TriggerConfig(type=TriggerType.MANUAL),
        goal_template="Process payment for account {{account_id}}",
        inputs={"account_id": "ACC-9981", "target": "Stripe"},
        approval_boundaries=[
            ApprovalBoundary(
                action_type="make_payment",
                requires_human=True,
                draft_mode=True,
                description="Requires approval before charging card",
            )
        ],
    )
    temp_store.save_routine(routine)

    # Execute routine
    record = await scheduler.execute_routine("automated-billing", trigger_type=TriggerType.MANUAL)

    # Assert Trust Gate was activated
    assert record.status == ExecutionStatus.AWAITING_APPROVAL
    assert len(record.staged_action_ids) == 1

    # Inspect staged action
    staged_actions = temp_store.list_staged_actions(status=StagedActionStatus.PENDING)
    assert len(staged_actions) == 1
    action = staged_actions[0]
    assert action.action_type == "make_payment"
    assert action.target == "Stripe"

    # Approve action
    approved = temp_store.resolve_staged_action(action.id, StagedActionStatus.APPROVED)
    assert approved.status == StagedActionStatus.APPROVED
    assert approved.resolved_at is not None


def test_teach_a_task_synthesizer(temp_skills_manager):
    synthesizer = SkillSynthesizer(skill_manager=temp_skills_manager)

    mock_events = [
        {"type": "navigate", "url": "https://crm.example.com/login"},
        {"type": "input", "selector": "#username", "value": "demo_user", "tag": "input"},
        {"type": "input", "selector": "#password", "value": "secret_pass", "tag": "input"},
        {"type": "click", "selector": "button.submit-btn", "text": "Sign In", "tag": "button"},
    ]

    skill = synthesizer.compile_trace(
        skill_id="crm-login-flow",
        title="CRM Auto Login",
        user_goal="Log into corporate CRM dashboard",
        events=mock_events,
        approval_actions=["submit_credentials"],
    )

    assert skill.id == "crm-login-flow"
    assert skill.status == "staged"
    assert "## 1. Trigger Context" in skill.instructions_md
    assert "## 2. Inputs & Access" in skill.instructions_md
    assert "## 3. Sequence of Work" in skill.instructions_md
    assert "## 4. Validation Rules" in skill.instructions_md
    assert "## 5. Expected Outputs" in skill.instructions_md
    assert "## 6. Approval Boundaries" in skill.instructions_md
    assert "[submit_credentials]" in skill.instructions_md
