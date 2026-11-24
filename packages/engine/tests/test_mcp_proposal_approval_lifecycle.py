"""
Unit test suite verifying the Trust Gate Proposal & Staged Actions Lifecycle.
Verifies staging mutation proposals, approval/rejection state transitions,
and guardrail isolation.
"""

import time
import tempfile
from pathlib import Path
from emiliano.routines.models import StagedAction, StagedActionStatus
from emiliano.routines.store import RoutineStore


class TestMcpProposalApprovalLifecycle:
    """Verifies that mutation proposals are guarded, stageable, and resolvable."""

    @classmethod
    def setup_class(cls):
        cls.tmp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.db_path = Path(cls.tmp_dir.name) / "test_routines.db"
        cls.store = RoutineStore(db_path=cls.db_path)

    @classmethod
    def teardown_class(cls):
        try:
            cls.tmp_dir.cleanup()
        except Exception:
            pass

    def test_01_create_staged_menu_proposal(self):
        action = StagedAction(
            id="staged_prop_01",
            routine_id="routine_test",
            run_id="run_01",
            action_type="propose_menu_item",
            target="plaatoos__menu",
            payload={
                "name": "Summer Paloma",
                "price": 32.0,
                "category": "Cocktails",
                "venue": "La Estación del Verano",
            },
            status=StagedActionStatus.PENDING,
            created_at=time.time(),
        )
        saved = self.store.create_staged_action(action)
        assert saved.id == "staged_prop_01"
        assert saved.status == StagedActionStatus.PENDING
        assert saved.payload["name"] == "Summer Paloma"

    def test_02_list_pending_returns_staged_proposal(self):
        pending = self.store.list_staged_actions(status=StagedActionStatus.PENDING)
        assert len(pending) >= 1
        ids = [a.id for a in pending]
        assert "staged_prop_01" in ids

    def test_03_approve_staged_proposal(self):
        resolved = self.store.resolve_staged_action(
            action_id="staged_prop_01",
            status=StagedActionStatus.APPROVED,
            notes="Approved by venue manager for Summer campaign",
        )
        assert resolved is not None
        assert resolved.status == StagedActionStatus.APPROVED
        assert resolved.resolved_at is not None
        assert "Approved by venue manager" in resolved.notes

        # Verify it no longer appears in pending list
        pending = self.store.list_staged_actions(status=StagedActionStatus.PENDING)
        assert "staged_prop_01" not in [a.id for a in pending]

        # Verify it appears in approved list
        approved = self.store.list_staged_actions(status=StagedActionStatus.APPROVED)
        assert "staged_prop_01" in [a.id for a in approved]

    def test_04_create_and_reject_proposal(self):
        action2 = StagedAction(
            id="staged_prop_02",
            routine_id="routine_test",
            run_id="run_02",
            action_type="propose_pricing_change",
            target="plaatoos__pricing",
            payload={"item": "Vodka Shot", "old_price": 14.0, "new_price": 25.0},
            status=StagedActionStatus.PENDING,
            created_at=time.time(),
        )
        self.store.create_staged_action(action2)

        # Reject it
        rejected = self.store.resolve_staged_action(
            action_id="staged_prop_02",
            status=StagedActionStatus.REJECTED,
            notes="Price increase excessive for happy hour",
        )
        assert rejected is not None
        assert rejected.status == StagedActionStatus.REJECTED

        # Verify query filters isolate rejected actions
        rejected_list = self.store.list_staged_actions(status=StagedActionStatus.REJECTED)
        assert "staged_prop_02" in [a.id for a in rejected_list]
        pending_list = self.store.list_staged_actions(status=StagedActionStatus.PENDING)
        assert "staged_prop_02" not in [a.id for a in pending_list]
