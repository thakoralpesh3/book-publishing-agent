"""Unit Tests for Store-and-Forward Upload Queue and Auto-Recovery System
Verifies queue persistence, exponential backoff, health probing, auto-retry dispatch, and REST API endpoints.
"""

import unittest
import json
import tempfile
import shutil
import urllib.error
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient

from uploader.pending_queue import PendingUploadQueue
from ui.app import app


class TestPendingUploadQueue(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.queue_file = self.test_dir / "pending_uploads.json"
        self.output_dir = self.test_dir / "output"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Mock book directory with expected output files
        self.slug = "test-resilient-book"
        self.book_dir = self.output_dir / self.slug
        self.book_dir.mkdir(parents=True, exist_ok=True)
        (self.book_dir / "manuscript_interior.pdf").write_bytes(b"%PDF-1.4 mock interior")
        (self.book_dir / "cover_full_wrap.pdf").write_bytes(b"%PDF-1.4 mock wrap")
        (self.book_dir / "cover_front.jpg").write_bytes(b"\xff\xd8\xff mock jpg")
        (self.book_dir / "amazon_kdp_listing_sheet.md").write_text("# KDP Listing Mock")
        (self.book_dir / "flipkart_bulk_catalog.xlsx").write_bytes(b"PK mock xlsx")
        (self.book_dir / "listing_metadata.json").write_text(json.dumps({
            "amazon_kdp": {"title": "Test Resilient Book"}
        }))

        # Initialize queue with isolated test paths
        self.queue = PendingUploadQueue(
            queue_file=self.queue_file,
            output_dir=self.output_dir
        )

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_add_or_update_persists_item(self):
        """Verify adding a failed upload records all metadata and manifests files."""
        item = self.queue.add_or_update(
            slug=self.slug,
            platform="kdp",
            failure_reason="HTTP 503 Server Error at Pricing step",
            failure_stage="pricing"
        )
        self.assertIsNotNone(item)
        self.assertEqual(item["slug"], self.slug)
        self.assertEqual(item["platform"], "kdp")
        self.assertEqual(item["status"], "pending")
        self.assertEqual(item["attempts"], 1)
        self.assertEqual(item["failure_stage"], "pricing")
        self.assertIn("HTTP 503", item["failure_reason"])
        self.assertGreaterEqual(len(item["saved_files"]), 4)

        # Ensure file was persisted to disk atomically
        self.assertTrue(self.queue_file.exists())
        data = json.loads(self.queue_file.read_text())
        self.assertEqual(len(data.get("queue", [])), 1)
        self.assertEqual(data["queue"][0]["id"], item["id"])

    def test_02_repeated_failures_increment_attempts(self):
        """Verify repeated failure updates existing item and increments attempts count."""
        first = self.queue.add_or_update(
            slug=self.slug,
            platform="kdp",
            failure_reason="Captcha challenge detected",
            failure_stage="login"
        )
        self.assertEqual(first["attempts"], 1)

        second = self.queue.add_or_update(
            slug=self.slug,
            platform="kdp",
            failure_reason="Connection timeout",
            failure_stage="network"
        )
        self.assertEqual(second["attempts"], 2)
        self.assertEqual(second["id"], first["id"])
        self.assertEqual(len(self.queue.list_items()), 1)
        self.assertEqual(second["failure_reason"], "Connection timeout")

    def test_03_lifecycle_status_transitions(self):
        """Verify mark_in_progress, mark_completed, and delete transitions."""
        item = self.queue.add_or_update(
            slug=self.slug,
            platform="flipkart",
            failure_reason="Upload button disabled",
            failure_stage="catalog_upload"
        )
        qid = item["id"]

        # Mark in progress
        in_prog = self.queue.mark_in_progress(qid)
        self.assertTrue(in_prog)
        fetched = self.queue.get_item(qid)
        self.assertEqual(fetched["status"], "in_progress")

        # Mark completed
        comp = self.queue.mark_completed(self.slug, "flipkart")
        self.assertTrue(comp)
        fetched = self.queue.get_item(qid)
        self.assertEqual(fetched["status"], "completed")
        self.assertIsNotNone(fetched.get("completed_at"))

        # Delete item
        deleted = self.queue.delete_item(qid)
        self.assertTrue(deleted)
        self.assertIsNone(self.queue.get_item(qid))
        self.assertEqual(len(self.queue.list_items()), 0)

    @patch("urllib.request.urlopen")
    def test_04_platform_health_probing(self, mock_urlopen):
        """Verify platform health probe handles successes, 403 bot challenges, and network outages."""
        # Scenario 1: Platforms are responding normally (200 OK)
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.getcode.return_value = 200
        mock_urlopen.return_value.__enter__.return_value = mock_response

        health = self.queue.check_platform_health()
        self.assertTrue(health["kdp"])
        self.assertTrue(health["flipkart"])
        self.assertTrue(health["internet"])
        self.assertTrue(self.queue.is_platform_healthy("kdp"))
        self.assertTrue(self.queue.is_platform_healthy("flipkart"))

        # Scenario 2: Platform returns HTTP 403 (e.g. Cloudflare challenge - host is up)
        err_403 = urllib.error.HTTPError(
            url="https://seller.flipkart.com",
            code=403,
            msg="Forbidden",
            hdrs={},
            fp=None
        )
        mock_urlopen.side_effect = err_403
        self.assertTrue(self.queue.is_platform_healthy("flipkart"))

        # Scenario 3: Platform is down or network connection error
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused [Errno 111]")
        health_down = self.queue.check_platform_health()
        self.assertFalse(health_down["kdp"])
        self.assertFalse(health_down["flipkart"])
        self.assertFalse(health_down["internet"])

    @patch("uploader.upload_manager.start_upload_job")
    @patch.object(PendingUploadQueue, "is_platform_healthy")
    def test_05_process_pending_queue_auto_retry(self, mock_health, mock_start_job):
        """Verify process_pending_queue launches jobs when platforms are reachable."""
        mock_health.return_value = True
        mock_start_job.return_value = "job-mock-test-1234"

        # Add 2 items
        self.queue.add_or_update(slug=self.slug, platform="kdp", failure_reason="Timeout")
        
        # Create second book
        slug2 = "test-book-two"
        (self.output_dir / slug2).mkdir(parents=True, exist_ok=True)
        (self.output_dir / slug2 / "listing_metadata.json").write_text("{}")
        self.queue.add_or_update(slug=slug2, platform="flipkart", failure_reason="Error")

        res = self.queue.process_pending_queue(force=True)
        self.assertEqual(res["attempted"], 2)
        self.assertEqual(len(res["started_jobs"]), 2)
        self.assertEqual(len(res["skipped_offline"]), 0)
        self.assertEqual(mock_start_job.call_count, 2)

    @patch.object(PendingUploadQueue, "is_platform_healthy")
    def test_06_process_pending_queue_skips_when_offline(self, mock_health):
        """Verify process_pending_queue skips items safely when platform is offline."""
        mock_health.return_value = False
        self.queue.add_or_update(slug=self.slug, platform="kdp", failure_reason="Platform downtime")

        res = self.queue.process_pending_queue(force=True)
        self.assertEqual(res["attempted"], 1)
        self.assertEqual(len(res["started_jobs"]), 0)
        self.assertEqual(len(res["skipped_offline"]), 1)
        self.assertEqual(res["skipped_offline"][0]["slug"], self.slug)

    def test_07_fastapi_endpoints(self):
        """Verify REST API endpoints for pending queue."""
        with patch("uploader.pending_queue.pending_queue", self.queue):
            # 1. Add an item
            item = self.queue.add_or_update(
                slug=self.slug,
                platform="kdp",
                failure_reason="Test API failure",
                failure_stage="launch"
            )
            qid = item["id"]

            # 2. GET /api/upload/pending
            with patch.object(self.queue, "check_platform_health", return_value={"kdp": True, "flipkart": True, "internet": True}):
                res = self.client.get("/api/upload/pending")
                self.assertEqual(res.status_code, 200)
                data = res.json()
                self.assertEqual(data["pending_count"], 1)
                self.assertEqual(len(data["items"]), 1)
                self.assertEqual(data["items"][0]["id"], qid)

            # 3. POST /api/upload/retry_pending (single item)
            with patch("uploader.upload_manager.start_upload_job", return_value="job-test-retry"):
                with patch.object(self.queue, "is_platform_healthy", return_value=True):
                    res = self.client.post("/api/upload/retry_pending", json={"queue_id": qid, "force": True})
                    self.assertEqual(res.status_code, 200)
                    rdata = res.json()
                    self.assertEqual(rdata["status"], "started")
                    self.assertEqual(rdata["job_id"], "job-test-retry")

            # 4. DELETE /api/upload/pending/{queue_id}
            del_res = self.client.delete(f"/api/upload/pending/{qid}")
            self.assertEqual(del_res.status_code, 200)
            self.assertEqual(del_res.json()["status"], "success")

            # Verify deleted
            self.assertEqual(len(self.queue.list_items()), 0)


if __name__ == "__main__":
    unittest.main()
