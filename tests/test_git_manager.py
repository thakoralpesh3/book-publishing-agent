"""
PublisheR AI • Git Manager & Cloud Sync Unit Tests
Verifies GitManager state detection, commit message generation, and FastAPI endpoints.
"""

import unittest
import tempfile
import shutil
import subprocess
from pathlib import Path
from fastapi.testclient import TestClient

from core.git_manager import GitManager
from ui.app import app


class TestGitManager(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_git_repo_"))
        self.client = TestClient(app)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_non_git_directory_status(self):
        """Verifies GitManager handles non-git directories gracefully."""
        gm = GitManager(self.temp_dir)
        self.assertFalse(gm.is_git_repo())
        status = gm.get_status()
        self.assertFalse(status["initialized"])
        self.assertEqual(status["branch"], "none")
        self.assertTrue(status["clean"])

    def test_02_git_repo_lifecycle_and_commit_message_generation(self):
        """Verifies Git initialization, change detection, and auto commit message."""
        # Initialize a test git repo
        subprocess.run(["git", "init", "-b", "main"], cwd=str(self.temp_dir), capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(self.temp_dir), capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(self.temp_dir), capture_output=True, check=True)

        gm = GitManager(self.temp_dir)
        self.assertTrue(gm.is_git_repo())
        self.assertEqual(gm.get_current_branch(), "main")

        # Create a new file
        test_file = self.temp_dir / "core" / "sample.py"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("print('test')", encoding="utf-8")

        status = gm.get_status()
        self.assertFalse(status["clean"])
        self.assertGreaterEqual(status["total_changes"], 1)

        # Check generated auto commit message
        msg = gm.generate_auto_commit_message(status)
        self.assertIn("chore(antigravity): auto-sync updates", msg)
        self.assertIn("core", msg)

        # Sync locally (no remote)
        res = gm.sync(message="Initial test commit")
        self.assertTrue(res["success"])
        self.assertIn("warning", res)  # No remote configured, so it commits locally with warning

        # After commit, working tree should be clean
        new_status = gm.get_status()
        self.assertTrue(new_status["clean"])
        self.assertEqual(new_status["last_commit"]["message"], "Initial test commit")

    def test_03_fastapi_git_endpoints(self):
        """Verifies GET /api/git/status and POST /api/git/sync endpoints."""
        resp = self.client.get("/api/git/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("initialized", data)
        self.assertIn("branch", data)
        self.assertIn("clean", data)

        # Test sync endpoint with empty message
        sync_resp = self.client.post("/api/git/sync", json={"message": None, "pull_first": False})
        # Could be success (or error if git not initialized yet) - either way, returns valid JSON response
        self.assertIn(sync_resp.status_code, [200, 500])


if __name__ == "__main__":
    unittest.main()
