"""Unit tests for Startup Sentry and 8-Hour Recurring Auto-Publishing Scheduler."""

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
from core.daily_scheduler import DailyPublishScheduler
from core.background_orchestrator import BackgroundPublishingOrchestrator
from ui.app import app


class TestStartupAndInterval(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.sched_config_file = self.temp_dir / "test_schedule_config.json"
        self.tracker_file = self.temp_dir / "test_tracker.json"
        self.scheduler = DailyPublishScheduler(
            config_file=self.sched_config_file,
            interval_hours=8.0,
            target_time="23:30",
            auto_upload="both"
        )
        self.orchestrator = BackgroundPublishingOrchestrator(tracker_file=self.tracker_file)
        self.client = TestClient(app)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_schedule_config_initialization(self):
        """Verifies schedule config initializes with 8-hour interval and startup wait."""
        cfg = self.scheduler.get_config()
        self.assertTrue(cfg.get("enabled"))
        self.assertEqual(cfg.get("interval_hours"), 8.0)
        self.assertEqual(cfg.get("scheduled_time"), "23:30")
        self.assertEqual(cfg.get("auto_upload"), "both")
        self.assertTrue(cfg.get("startup_prereq_wait"))

    def test_02_update_config_interval(self):
        """Tests updating interval hours and auto upload platform."""
        st = self.scheduler.update_config(interval_hours=6.0, auto_upload="kdp")
        self.assertEqual(st.get("interval_hours"), 6.0)
        self.assertEqual(st.get("auto_upload"), "kdp")

        # Invalid interval should raise ValueError
        with self.assertRaises(ValueError):
            self.scheduler.update_config(interval_hours=-5)

    def test_03_calculate_next_run_countdown(self):
        """Tests calculation of next run time based on 8-hour elapsed time."""
        # 1. No last run -> Due immediately
        res = self.scheduler.calculate_next_run()
        self.assertTrue(res.get("is_due"))
        self.assertEqual(res.get("countdown_human"), "DUE NOW")

        # 2. Run occurred 4 hours ago -> Next run in ~4 hours
        four_hours_ago = datetime.datetime.now() - datetime.timedelta(hours=4)
        cfg = self.scheduler.get_config()
        cfg["last_run_timestamp"] = four_hours_ago.strftime("%Y-%m-%d %H:%M:%S")
        self.scheduler._save_config(cfg)

        res2 = self.scheduler.calculate_next_run()
        self.assertFalse(res2.get("is_due"))
        self.assertGreater(res2.get("countdown_seconds"), 3 * 3600)
        self.assertLessEqual(res2.get("countdown_seconds"), 4 * 3600)
        self.assertIn("3h ", res2.get("countdown_human"))

        # 3. Run occurred 9 hours ago -> Due now!
        nine_hours_ago = datetime.datetime.now() - datetime.timedelta(hours=9)
        cfg["last_run_timestamp"] = nine_hours_ago.strftime("%Y-%m-%d %H:%M:%S")
        self.scheduler._save_config(cfg)

        res3 = self.scheduler.calculate_next_run()
        self.assertTrue(res3.get("is_due"))
        self.assertEqual(res3.get("countdown_human"), "DUE NOW")

    def test_04_orchestrator_8_hour_interval_due(self):
        """Tests is_run_due in BackgroundPublishingOrchestrator."""
        # Fresh tracker -> run is due
        self.assertTrue(self.orchestrator.is_run_due(min_interval_hours=8.0))

        # Run 2 hours ago -> run NOT due
        two_h_ago = datetime.datetime.now() - datetime.timedelta(hours=2)
        data = self.orchestrator.get_tracker_data()
        data["last_run_timestamp"] = two_h_ago.strftime("%Y-%m-%d %H:%M:%S")
        self.tracker_file.write_text(json.dumps(data), encoding="utf-8")

        self.assertFalse(self.orchestrator.is_run_due(min_interval_hours=8.0))

        # Run 8.5 hours ago -> run IS due
        eight_half_ago = datetime.datetime.now() - datetime.timedelta(hours=8.5)
        data["last_run_timestamp"] = eight_half_ago.strftime("%Y-%m-%d %H:%M:%S")
        self.tracker_file.write_text(json.dumps(data), encoding="utf-8")

        self.assertTrue(self.orchestrator.is_run_due(min_interval_hours=8.0))

    @patch("core.background_orchestrator.BackgroundPublishingOrchestrator.run_daily_publishing_pipeline")
    def test_05_watch_and_run_coordination(self, mock_pipeline):
        """Tests watch_and_run when prerequisites finish."""
        mock_pipeline.return_value = {"status": "completed", "title": "Startup Book"}

        with patch.object(self.orchestrator, "check_prerequisite_agents_status") as mock_status:
            mock_status.return_value = {
                "today": "2026-11-01",
                "youtube": {"running": False, "completed_today": True},
                "social": {"running": False, "completed_today": True},
                "prerequisites_finished": True,
                "publisher_daily_due": True
            }

            res = self.orchestrator.watch_and_run(poll_interval_seconds=1, max_wait_seconds=5, force=True)
            self.assertEqual(res.get("status"), "completed")
            self.assertEqual(res.get("title"), "Startup Book")
            mock_pipeline.assert_called_once()

    def test_06_fastapi_schedule_endpoints(self):
        """Tests /api/schedule GET, POST, and run_now endpoints."""
        # 1. GET /api/schedule
        res = self.client.get("/api/schedule")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("status"), "success")
        self.assertIn("schedule", data)
        self.assertEqual(data["schedule"].get("interval_hours"), 8.0)

        # 2. POST /api/schedule (update)
        up_res = self.client.post("/api/schedule", json={
            "interval_hours": 8.0,
            "scheduled_time": "23:30",
            "auto_upload": "both",
            "enabled": True
        })
        self.assertEqual(up_res.status_code, 200)
        self.assertEqual(up_res.json()["schedule"]["interval_hours"], 8.0)

        # 3. POST /api/schedule/run_now
        run_res = self.client.post("/api/schedule/run_now")
        self.assertEqual(run_res.status_code, 200)
        self.assertEqual(run_res.json().get("status"), "queued")


if __name__ == "__main__":
    unittest.main()
