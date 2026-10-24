"""Unit tests for Background Publishing Orchestrator, multi-agent status tracking,
and sequential coordination with Aradhya, YouTube Shorts, and Social Media agents.
"""

import os
import sys
import json
import shutil
import tempfile
import datetime
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

import config
from core.background_orchestrator import BackgroundPublishingOrchestrator
from ui.app import app


class TestBackgroundOrchestrator(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.tracker_file = self.temp_dir / "test_tracker.json"
        self.orchestrator = BackgroundPublishingOrchestrator(tracker_file=self.tracker_file)
        self.client = TestClient(app)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_tracker_initialization(self):
        """Verifies tracker file is initialized with proper default schema."""
        self.assertTrue(self.tracker_file.exists())
        data = self.orchestrator.get_tracker_data()
        self.assertEqual(data.get("runs_today_count"), 0)
        self.assertEqual(data.get("daily_limit"), 1)
        self.assertEqual(data.get("last_run_date"), "")
        self.assertTrue(self.orchestrator.is_daily_run_due())

    def test_02_daily_limit_quota_enforcement(self):
        """Verifies daily limit stops execution unless force is applied."""
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        
        # Simulate completed run today
        data = self.orchestrator.get_tracker_data()
        data["last_run_date"] = today_str
        data["runs_today_count"] = 1
        data["daily_limit"] = 1
        self.tracker_file.write_text(json.dumps(data), encoding="utf-8")

        self.assertFalse(self.orchestrator.is_daily_run_due())

        # Attempt pipeline without force -> should be skipped
        res = self.orchestrator.run_daily_publishing_pipeline(force=False)
        self.assertEqual(res.get("status"), "skipped")
        self.assertIn("Daily book limit reached", res.get("message", ""))

    def test_03_prerequisite_agents_detection(self):
        """Tests detection of external agent status."""
        status = self.orchestrator.check_prerequisite_agents_status()
        self.assertIn("youtube", status)
        self.assertIn("social", status)
        self.assertIn("aradhya", status)
        self.assertIn("prerequisites_finished", status)
        self.assertIn("publisher_daily_due", status)
        self.assertIsInstance(status["youtube"]["running"], bool)
        self.assertIsInstance(status["social"]["running"], bool)

    def test_04_select_daily_trend(self):
        """Tests autonomous selection of top daily trending book niches."""
        trend = self.orchestrator._select_daily_trend()
        self.assertIsNotNone(trend)
        self.assertTrue("title" in trend or "topic" in trend)
        self.assertIn("book_type", trend)

        # Test selecting specific category
        kids_trend = self.orchestrator._select_daily_trend(preferred_category="kids")
        self.assertEqual(kids_trend.get("category"), "kids")

    @patch("core.background_orchestrator.GeminiBookEngine")
    @patch("core.background_orchestrator.BookWriter")
    @patch("core.background_orchestrator.ManuscriptCompiler")
    @patch("core.background_orchestrator.CoverGenerator")
    @patch("core.background_orchestrator.MetadataEngine")
    @patch("core.background_orchestrator.CatalogExporter")
    def test_05_mocked_autonomous_pipeline_execution(
        self, mock_exporter_cls, mock_meta_cls, mock_cover_cls, mock_comp_cls, mock_writer_cls, mock_engine_cls
    ):
        """Tests complete pipeline flow with mock generators and tracker persistence."""
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        slug = "autonomous_rich_test_book"
        book_dir = self.temp_dir / slug
        book_dir.mkdir(parents=True, exist_ok=True)

        # Setup mocks
        mock_writer = mock_writer_cls.return_value
        mock_writer.create_book.return_value = {
            "title": "Autonomous Wealth Mastery",
            "subtitle": "Daily Systems",
            "author": "Antigravity AI",
            "publisher": "Autonomous Press",
            "slug": slug,
            "book_dir": str(book_dir),
            "chapters": [{"title": "Ch 1", "sections": [{"title": "S1", "content": "Text"}]}]
        }

        mock_comp = mock_comp_cls.return_value
        mock_comp.compile_pdf.return_value = {"page_count": 52, "pdf_path": str(book_dir / "manuscript_interior.pdf")}

        mock_cover = mock_cover_cls.return_value
        mock_cover.generate_full_wrap_pdf.return_value = {"cover_wrap_pdf": str(book_dir / "cover_full_wrap.pdf")}

        mock_meta = mock_meta_cls.return_value
        mock_meta.generate_all_metadata.return_value = {"book_details": {"title": "Autonomous Wealth Mastery"}}

        mock_exporter = mock_exporter_cls.return_value
        mock_exporter.export_all.return_value = {
            "flipkart_excel": str(book_dir / "flipkart.xlsx"),
            "amazon_markdown": str(book_dir / "amazon.md")
        }

        # Run pipeline
        res = self.orchestrator.run_daily_publishing_pipeline(force=True, custom_topic="Mastering Autonomous Wealth")
        self.assertEqual(res.get("status"), "completed")
        self.assertEqual(res.get("book_slug"), slug)

        # Check tracker state
        tracker_data = self.orchestrator.get_tracker_data()
        self.assertEqual(tracker_data.get("last_run_date"), today_str)
        self.assertEqual(tracker_data.get("runs_today_count"), 1)
        self.assertEqual(tracker_data.get("last_book_slug"), slug)
        self.assertGreaterEqual(len(tracker_data.get("history", [])), 1)

    @patch.object(BackgroundPublishingOrchestrator, "run_daily_publishing_pipeline")
    def test_06_fastapi_background_endpoints(self, mock_run_pipeline):
        """Tests /api/background/status and /api/background/run endpoints."""
        mock_run_pipeline.return_value = {"status": "completed"}
        status_resp = self.client.get("/api/background/status")
        self.assertEqual(status_resp.status_code, 200)
        sdata = status_resp.json()
        self.assertEqual(sdata.get("status"), "success")
        self.assertIn("tracker", sdata)
        self.assertIn("prerequisites", sdata)

        # Test trigger endpoint
        run_resp = self.client.post("/api/background/run", json={"force": False})
        self.assertEqual(run_resp.status_code, 200)
        rdata = run_resp.json()
        self.assertEqual(rdata.get("status"), "queued")

    def test_07_youtube_publisher_bridge_integration(self):
        """Verifies youtube-agent/core/publisher_bridge module works cleanly."""
        import importlib.util
        bridge_path = Path("/home/alpesh/youtube-agent/core/publisher_bridge.py")
        self.assertTrue(bridge_path.exists())
        spec = importlib.util.spec_from_file_location("yt_bridge", bridge_path)
        bridge = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bridge)
        self.assertTrue(bridge.PUBLISHER_SCRIPT.exists())
        ready = bridge.is_publisher_ready_to_run(force=True)
        self.assertTrue(ready)

    def test_08_jarvis_publisher_commander_integration(self):
        """Verifies jarvis-agent/core/publisher_commander module loads and functions."""
        import importlib.util
        jarvis_path = Path("/home/alpesh/jarvis-agent")
        comm_path = jarvis_path / "core" / "publisher_commander.py"
        self.assertTrue(comm_path.exists())
        
        # Add jarvis path so relative imports within jarvis-agent work
        sys.path.insert(0, str(jarvis_path))
        try:
            spec = importlib.util.spec_from_file_location("jarvis_pub_comm", comm_path)
            pub_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(pub_mod)
            commander = pub_mod.PublisheRCommander()
            status = commander.get_schedule_status()
            self.assertIsInstance(status, dict)
            self.assertIn("last_status", status)
        finally:
            if str(jarvis_path) in sys.path:
                sys.path.remove(str(jarvis_path))


if __name__ == "__main__":
    unittest.main()
