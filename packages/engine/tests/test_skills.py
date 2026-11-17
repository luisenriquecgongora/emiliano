import pytest
from pathlib import Path
from emiliano.core.skills import SkillManager

@pytest.fixture
def temp_skills_manager(tmp_path):
    mgr = SkillManager(workspace_root=tmp_path)
    return mgr

def test_builtin_discovery(temp_skills_manager):
    skills = temp_skills_manager.get_all_skills()
    assert any(s["id"] == "desktop-cowork" for s in skills)
    assert any(s["status"] == "active" for s in skills)

def test_synthesize_and_approve_skill(temp_skills_manager):
    # 1. Synthesize staged skill
    draft = temp_skills_manager.synthesize_skill(
        id="test-instagram-flow",
        title="Test Instagram Flow",
        description="Autonomous direct messaging",
        instructions_md="# Procedure\n1. Step A\n2. Step B",
        triggers=["test ig", "outreach"],
        selectors={"btn": "button.msg"}
    )
    assert draft.status == "staged"
    assert Path(draft.path).exists()
    assert "test-instagram-flow" in temp_skills_manager._skills

    # 2. Check compact prompt registry (staged skills should NOT appear in base prompt)
    compact = temp_skills_manager.get_compact_registry()
    assert not any(c["id"] == "test-instagram-flow" for c in compact)

    # 3. Approve skill
    approved = temp_skills_manager.approve_skill("test-instagram-flow")
    assert approved is True
    assert temp_skills_manager.get_skill("test-instagram-flow").status == "active"

    # 4. Now it should appear in compact prompt registry
    compact_after = temp_skills_manager.get_compact_registry()
    assert any(c["id"] == "test-instagram-flow" for c in compact_after)

def test_self_healing_patch(temp_skills_manager):
    draft = temp_skills_manager.synthesize_skill(
        id="test-repair",
        title="Repairable Skill",
        description="Testing self-healing",
        instructions_md="# Procedure",
        selectors={"input": "old-selector"}
    )
    assert draft.selectors["input"] == "old-selector"

    # Patch selector and append recovery notes
    patched = temp_skills_manager.patch_skill(
        "test-repair",
        selectors={"input": "new-healed-selector"},
        append_notes="Selector updated after UI mutation."
    )
    assert patched is True
    updated = temp_skills_manager.get_skill("test-repair")
    assert updated.selectors["input"] == "new-healed-selector"
    assert "Selector updated after UI mutation." in updated.instructions_md
