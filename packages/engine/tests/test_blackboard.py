"""
Unit tests for the Unified SQLite Blackboard (Inter-harness memory & continuity).
"""

import tempfile
import unittest
from pathlib import Path

from emiliano.core.blackboard import Blackboard


class TestBlackboard(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_blackboard.db"
        self.bb = Blackboard(db_path=self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_entity_crud(self):
        # Set
        self.bb.set_entity("current_lead", {"id": "PL-142", "name": "Studio Beza"}, category="outreach")

        # Get
        val = self.bb.get_entity("current_lead")
        self.assertEqual(val["id"], "PL-142")
        self.assertEqual(val["name"], "Studio Beza")

        # Update
        self.bb.set_entity("current_lead", {"id": "PL-143", "name": "Kawiarnia"}, category="outreach")
        val2 = self.bb.get_entity("current_lead")
        self.assertEqual(val2["id"], "PL-143")

        # List
        entities = self.bb.list_entities(category="outreach")
        self.assertIn("current_lead", entities)

        # Delete
        deleted = self.bb.delete_entity("current_lead")
        self.assertTrue(deleted)
        self.assertIsNone(self.bb.get_entity("current_lead"))

    def test_event_stream(self):
        event_id = self.bb.post_event(
            source="claude_code",
            event_type="backend_ready",
            payload={"port": 8080, "health": "ok"},
            session_id="ses_101",
        )
        self.assertGreater(event_id, 0)

        events = self.bb.get_events(limit=10, event_type="backend_ready")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["source"], "claude_code")
        self.assertEqual(events[0]["payload"]["port"], 8080)

    def test_session_summary_handoff(self):
        self.bb.record_session_summary(
            session_id="session_55",
            title="Hospitality Outreach Batch 8",
            summary="Completed leads PL-200 to PL-204. Next session should resume at PL-205.",
            metadata={"batch_size": 5},
        )

        last = self.bb.get_last_session_summary()
        self.assertIsNotNone(last)
        self.assertEqual(last["session_id"], "session_55")
        self.assertIn("PL-205", last["summary"])

    def test_render_context_for_prompt(self):
        self.bb.set_entity("auth_token", "test_tok_xyz")
        self.bb.record_session_summary(
            session_id="s1",
            title="Initial Test",
            summary="All basic checks passed.",
        )

        context_str = self.bb.render_context_for_prompt()
        self.assertIn("Previous Session Handoff (Initial Test)", context_str)
        self.assertIn("All basic checks passed", context_str)
        self.assertIn("auth_token", context_str)
