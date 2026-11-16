"""
Unit tests for the Multi-Stage Pipeline Engine.
"""

import tempfile
import unittest
from pathlib import Path

from emiliano.core.pipeline import Pipeline, PipelineContext, Stage, StageStatus
from emiliano.core.blackboard import Blackboard


class TestPipelineEngine(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.checkpoint_dir = Path(self.temp_dir.name)
        self.bb_db = self.checkpoint_dir / "blackboard.db"
        self.blackboard = Blackboard(db_path=self.bb_db)

    def tearDown(self):
        self.temp_dir.cleanup()

    async def test_sequential_pipeline_execution(self):
        pipeline = Pipeline(name="test_pipeline", checkpoint_dir=self.checkpoint_dir, blackboard=self.blackboard)

        # Stage 1: Fetch
        def stage_fetch(ctx: PipelineContext):
            ctx.set("fetched_items", ["item1", "item2"])
            return 2

        # Stage 2: Transform (async)
        async def stage_transform(ctx: PipelineContext):
            items = ctx.get("fetched_items", [])
            transformed = [i.upper() for i in items]
            ctx.set("transformed_items", transformed)
            return len(transformed)

        pipeline.add_stage("fetch", stage_fetch, description="Fetch items")
        pipeline.add_stage("transform", stage_transform, description="Transform items")

        res = await pipeline.run()
        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["data"]["transformed_items"], ["ITEM1", "ITEM2"])
        self.assertEqual(res["results"]["fetch"]["status"], "completed")
        self.assertEqual(res["results"]["transform"]["status"], "completed")

        # Check blackboard received events
        events = self.blackboard.get_events(limit=5)
        self.assertGreaterEqual(len(events), 2)

    async def test_stage_selection_and_skipping(self):
        pipeline = Pipeline(name="selective_pipeline")

        calls = []

        def s1(ctx): calls.append("s1")
        def s2(ctx): calls.append("s2")
        def s3(ctx): calls.append("s3")

        pipeline.add_stage("s1", s1)
        pipeline.add_stage("s2", s2)
        pipeline.add_stage("s3", s3)

        # Run with selected stages (only s1 and s3)
        res = await pipeline.run(selected_stages=["s1", "s3"])
        self.assertEqual(calls, ["s1", "s3"])
        self.assertEqual(res["results"]["s2"]["status"], "skipped")

        # Run with skip stages
        calls.clear()
        res_skip = await pipeline.run(skip_stages=["s1"])
        self.assertEqual(calls, ["s2", "s3"])
        self.assertEqual(res_skip["results"]["s1"]["status"], "skipped")

    async def test_pipeline_halts_on_failure(self):
        pipeline = Pipeline(name="failing_pipeline")

        def s1(ctx): return "ok"
        def s2(ctx): raise ValueError("Crash in stage 2")
        def s3(ctx): return "unreachable"

        pipeline.add_stage("s1", s1)
        pipeline.add_stage("s2", s2)
        pipeline.add_stage("s3", s3)

        res = await pipeline.run()
        self.assertEqual(res["status"], "failed")
        self.assertEqual(res["results"]["s2"]["status"], "failed")
        self.assertNotIn("s3", res["results"])  # s3 was never reached

    async def test_optional_stage_failure_does_not_halt(self):
        pipeline = Pipeline(name="optional_stage_pipeline")

        def s1(ctx): return "ok"
        def s2_optional(ctx): raise RuntimeError("Optional failure")
        def s3(ctx): ctx.set("s3_done", True); return "finished"

        pipeline.add_stage("s1", s1)
        pipeline.add_stage("s2", s2_optional, optional=True)
        pipeline.add_stage("s3", s3)

        res = await pipeline.run()
        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["results"]["s2"]["status"], "failed")
        self.assertEqual(res["results"]["s3"]["status"], "completed")
        self.assertTrue(res["data"]["s3_done"])
