"""
Unit Tests for Autonomous Git & GitHub Auto-Sync Watcher
Verifies file ignore rules, debounce logic, event handling, and synchronization dispatch.
"""

import unittest
import tempfile
import shutil
import time
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.git_watcher import GitAutoSyncWatcher, should_ignore_path


class TestGitWatcher(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_git_watcher_"))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_ignore_path_rules(self):
        """Verifies that temporary, secret, and build output paths are strictly ignored."""
        # Ignored files
        self.assertTrue(should_ignore_path(".env"))
        self.assertTrue(should_ignore_path(".env.local"))
        self.assertTrue(should_ignore_path(".git/refs/heads/main"))
        self.assertTrue(should_ignore_path("data/server.log"))
        self.assertTrue(should_ignore_path("data/gateway_watchdog.log"))
        self.assertTrue(should_ignore_path("output/test_book/manuscript_interior.pdf"))
        self.assertTrue(should_ignore_path("output/sample/cover.jpg"))
        self.assertTrue(should_ignore_path("__pycache__/main.cpython-312.pyc"))
        self.assertTrue(should_ignore_path("core/__pycache__/engine.pyc"))
        self.assertTrue(should_ignore_path(".pytest_cache/v/cache"))
        self.assertTrue(should_ignore_path("temp_file.tmp"))
        self.assertTrue(should_ignore_path("ui/static/mobile_qr.png"))

        # Non-ignored tracked project files
        self.assertFalse(should_ignore_path("core/git_watcher.py"))
        self.assertFalse(should_ignore_path("core/book_writer.py"))
        self.assertFalse(should_ignore_path("ui/templates/index.html"))
        self.assertFalse(should_ignore_path("main.py"))
        self.assertFalse(should_ignore_path("config.py"))
        self.assertFalse(should_ignore_path(".github/workflows/daily_publisher.yml"))
        self.assertFalse(should_ignore_path("tests/test_git_watcher.py"))

    def test_02_watcher_lifecycle_and_debounce(self):
        """Verifies debouncing timer resets on successive file modification events."""
        watcher = GitAutoSyncWatcher(repo_dir=self.temp_dir, debounce_seconds=0.2)
        self.assertFalse(watcher.is_running)

        # Trigger file modification
        watcher.on_file_changed("core/sample.py", "modified")
        self.assertIn("core/sample.py", watcher._recent_changes)
        first_time = watcher._last_change_time
        self.assertGreater(first_time, 0)
        self.assertIsNotNone(watcher._timer)
        self.assertTrue(watcher._timer.is_alive())

        # Trigger another modification before debounce expires
        time.sleep(0.05)
        watcher.on_file_changed("ui/sample.html", "modified")
        self.assertIn("ui/sample.html", watcher._recent_changes)
        self.assertGreaterEqual(watcher._last_change_time, first_time)

        # Cancel timer and cleanup
        watcher.stop()
        self.assertFalse(watcher.is_running)

    @patch("core.git_watcher.GitManager")
    def test_03_trigger_sync_now_calls_git_manager(self, mock_gm_class):
        """Verifies trigger_sync_now queries status and invokes sync when changes are present."""
        mock_gm = MagicMock()
        mock_gm.get_status.return_value = {
            "initialized": True,
            "clean": False,
            "total_changes": 2,
            "ahead": 0
        }
        mock_gm.sync.return_value = {
            "success": True,
            "synced": True,
            "last_commit": {"hash": "abc1234", "message": "chore: test sync"}
        }
        mock_gm_class.return_value = mock_gm

        callback_mock = MagicMock()
        watcher = GitAutoSyncWatcher(
            repo_dir=self.temp_dir,
            debounce_seconds=0.1,
            on_sync_callback=callback_mock
        )

        res = watcher.trigger_sync_now(custom_message="Custom test sync")
        self.assertTrue(res["success"])
        mock_gm.get_status.assert_called_once()
        mock_gm.sync.assert_called_once_with(message="Custom test sync", pull_first=True)
        callback_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
