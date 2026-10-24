"""Unit Tests for Upload Assistants and Post-Generation Upload Integration
Verifies Amazon KDP Assistant, Flipkart Assistant, UploadManager, Quick-Copy Wizard, and FastAPI routes.
"""

import unittest
import json
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

import config
from uploader.flipkart_assistant import FlipkartAssistant
from uploader.kdp_assistant import KDPAssistant
from uploader.upload_manager import start_upload_job, get_upload_job, UPLOAD_JOBS
from ui.app import app

class TestUploadAssistants(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.book_slug = "test_upload_book"
        self.book_dir = self.test_dir / self.book_slug
        self.book_dir.mkdir(parents=True, exist_ok=True)

        self.mock_dossier = {
            "amazon_kdp": {
                "title": "Autonomous AI Wealth Blueprint",
                "subtitle": "Step-by-Step Systems for Financial Independence",
                "author": "Alpesh Patel",
                "html_description": "<p>Discover the secrets of <b>modern automated wealth</b>.</p>",
                "backend_keywords": ["wealth creation", "passive income", "financial freedom", "investing"],
                "pricing": {"inr": {"paperback_list_price": 499}, "usd": {"paperback_list_price": 9.99}}
            },
            "flipkart": {
                "title": "Autonomous AI Wealth Blueprint",
                "subtitle": "Step-by-Step Systems for Financial Independence",
                "author": "Alpesh Patel",
                "publisher": "Independent Publishing Press",
                "isbn_13": "9789309324604",
                "hsn_code": "4901.10.00",
                "gst_rate_percent": 0,
                "mrp_inr": 499,
                "selling_price_inr": 399,
                "dimensions_cm": {"length": 22.86, "breadth": 15.24, "height": 1.4},
                "weight_grams": 185,
                "binding": "Paperback",
                "number_of_pages": 48,
                "highlights": ["Zero GST 0%", "1st Edition", "Paperback format", "22.86 x 15.24 cm"],
                "synopsis": "A masterclass in modern digital wealth creation and automated cash flow."
            }
        }

        # Write mock files
        (self.book_dir / "listing_metadata.json").write_text(json.dumps(self.mock_dossier, indent=2))
        (self.book_dir / "manuscript_interior.pdf").write_bytes(b"%PDF-1.4 mock pdf content")
        (self.book_dir / "cover_full_wrap.pdf").write_bytes(b"%PDF-1.4 mock cover wrap content")
        (self.book_dir / "flipkart_bulk_catalog.xlsx").write_bytes(b"PK\x03\x04 mock excel content")
        (self.book_dir / "cover_front.jpg").write_bytes(b"\xff\xd8\xff mock jpg content")

        # Patch config.OUTPUT_DIR
        self._orig_output = config.OUTPUT_DIR
        config.OUTPUT_DIR = self.test_dir

    def tearDown(self):
        config.OUTPUT_DIR = self._orig_output
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_flipkart_assistant_validation(self):
        """Verifies Flipkart pre-upload compliance validation."""
        assistant = FlipkartAssistant()
        res = assistant.validate_flipkart_listing(self.book_dir)
        self.assertTrue(res["valid"])
        self.assertEqual(len(res["issues"]), 0)
        self.assertTrue(any("4901" in c for c in res["checks_passed"]))
        self.assertTrue(any("9789309324604" in c for c in res["checks_passed"]))

    def test_02_flipkart_quick_copy_payload(self):
        """Verifies Flipkart 1-click quick-copy attributes are properly formatted."""
        assistant = FlipkartAssistant()
        payload = assistant.get_quick_copy_payload(self.book_dir)
        self.assertEqual(payload["isbn_13"], "9789309324604")
        self.assertEqual(payload["hsn_code"], "4901.10.00")
        self.assertEqual(payload["gst_rate"], "0%")
        self.assertEqual(payload["mrp"], "499")
        self.assertEqual(payload["selling_price"], "399")
        self.assertIn("22.86", payload["dimensions_cm"])
        self.assertIn("•", payload["highlights_formatted"])

    def test_03_upload_manager_start_and_status(self):
        """Verifies asynchronous job creation and tracking via UploadManager."""
        with patch.object(KDPAssistant, "launch_assisted_session") as mock_kdp:
            mock_kdp.return_value = {"status": "completed", "platform": "amazon_kdp"}
            job_id = start_upload_job(
                slug=self.book_slug,
                platform="kdp",
                headless=True,
                auto_advance=True,
                keep_open_seconds=0
            )
            self.assertTrue(job_id.startswith("job_kdp_"))
            job = get_upload_job(job_id)
            self.assertIsNotNone(job)
            self.assertEqual(job["slug"], self.book_slug)
            self.assertEqual(job["platform"], "kdp")

    def test_04_fastapi_upload_endpoints(self):
        """Verifies /api/upload/start, /api/upload/status, and /api/upload/quick_copy."""
        # 1. Quick Copy endpoint
        qc_resp = self.client.get(f"/api/upload/quick_copy/{self.book_slug}")
        self.assertEqual(qc_resp.status_code, 200)
        qc_data = qc_resp.json()
        self.assertEqual(qc_data["isbn_13"], "9789309324604")
        self.assertEqual(qc_data["hsn_code"], "4901.10.00")

        # 2. Upload Start endpoint
        with patch.object(FlipkartAssistant, "launch_assisted_session") as mock_fk:
            mock_fk.return_value = {"status": "completed", "platform": "flipkart"}
            start_resp = self.client.post("/api/upload/start", json={
                "slug": self.book_slug,
                "platform": "flipkart",
                "headless": True
            })
            self.assertEqual(start_resp.status_code, 200)
            data = start_resp.json()
            self.assertEqual(data["status"], "started")
            job_id = data["job_id"]

            # 3. Upload Status endpoint
            status_resp = self.client.get(f"/api/upload/status/{job_id}")
            self.assertEqual(status_resp.status_code, 200)
            status_data = status_resp.json()
            self.assertEqual(status_data["job_id"], job_id)
            self.assertEqual(status_data["platform"], "flipkart")

if __name__ == "__main__":
    unittest.main()
