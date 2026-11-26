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

    def test_02b_kdp_marketplace_and_category_matching(self):
        """Verifies live KDP marketplace mapping and category dropdown matching helpers."""
        opts = ["us", "uk", "de", "jp", "ca", "au"]
        self.assertEqual(KDPAssistant._resolve_marketplace_code(opts, "amazon.in"), "us")
        self.assertEqual(KDPAssistant._resolve_marketplace_code(opts, "amazon.co.uk"), "uk")

        top_opts = ["Select one", "Business & Money", "Children's Books", "Computers & Technology", "Self-Help"]
        self.assertEqual(KDPAssistant._match_category_option_label("Children's Books", top_opts), "Children's Books")
        self.assertEqual(KDPAssistant._match_category_option_label("Business", top_opts), "Business & Money")
        self.assertEqual(KDPAssistant._match_category_option_label("Productivity", top_opts), "Self-Help")
        self.assertIsNone(KDPAssistant._match_category_option_label("Books", top_opts))

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
            import time
            for _ in range(30):
                job = get_upload_job(job_id)
                if job and job.get("status") in ("completed", "failed"):
                    break
                time.sleep(0.05)
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
            import time
            for _ in range(30):
                job = get_upload_job(job_id)
                if job and job.get("status") in ("completed", "failed"):
                    break
                time.sleep(0.05)

    def test_05_flipkart_api_payload_and_auth_upload(self):
        """Verifies Flipkart Seller API v3 payload construction, OAuth2 token fetch, and listing upload."""
        from uploader.flipkart_api import FlipkartSellerAPI

        api = FlipkartSellerAPI(app_id="test_app", app_secret="test_secret", location_id="LOC123", sandbox=True)
        self.assertEqual(api.base_url, "https://sandbox-api.flipkart.net")
        self.assertTrue(api.is_configured())

        payload = api.build_listing_payload(self.mock_dossier)
        sku_id = next(iter(payload.keys()))
        entry = payload[sku_id]
        self.assertEqual(entry["product_id"], "9789309324604")
        self.assertEqual(entry["tax"]["hsn"], "49011000")
        self.assertEqual(entry["tax"]["tax_code"], "GST_0")
        self.assertEqual(entry["price"]["mrp"], 499)
        self.assertEqual(entry["price"]["selling_price"], 399)
        self.assertEqual(entry["packages"][0]["weight"], 0.185)
        self.assertEqual(entry["locations"][0]["id"], "LOC123")

        mock_oauth_resp = MagicMock(status_code=200)
        mock_oauth_resp.json.return_value = {"access_token": "tok_abc", "expires_in": 3600}
        mock_list_resp = MagicMock(status_code=200)
        mock_list_resp.json.return_value = {sku_id: {"status": "SUCCESS"}}

        with patch("uploader.flipkart_api.requests.get", return_value=mock_oauth_resp) as m_get:
            with patch("uploader.flipkart_api.requests.post", return_value=mock_list_resp) as m_post:
                res = api.upload_listing(self.book_dir)
                self.assertEqual(res["status"], "completed")
                self.assertEqual(res["mode"], "api")
                m_get.assert_called_once()
                self.assertEqual(m_post.call_count, 2)  # create listing + inventory sync

        # Missing credentials returns clear api_credentials_missing code
        unconfigured = FlipkartSellerAPI(app_id="", app_secret="")
        miss_res = unconfigured.upload_listing(self.book_dir)
        self.assertEqual(miss_res["status"], "failed")
        self.assertEqual(miss_res["error_code"], "api_credentials_missing")

    def test_06_flipkart_assistant_falls_back_to_api_when_browser_fails(self):
        """Verifies FlipkartAssistant automatically uses Flipkart Seller API v3 when browser automation is unavailable."""
        assistant = FlipkartAssistant(user_data_dir=self.test_dir / "fk_profile")
        with patch("uploader.flipkart_assistant.sync_playwright", side_effect=RuntimeError("no browser display")):
            with patch("uploader.flipkart_api.FlipkartSellerAPI.upload_listing", return_value={
                "status": "completed", "platform": "flipkart", "mode": "api", "sku_id": "FP-BK-TEST", "product_id": "9789309324604"
            }) as mock_api:
                res = assistant.launch_assisted_session(self.book_dir, headless=True, keep_open_seconds=0)
                mock_api.assert_called_once()
                self.assertEqual(res["status"], "completed")
                self.assertEqual(res["mode"], "api")

    def test_07_kdp_step3_auto_publish_and_draft_modes(self):
        """Verifies KDP Step 3 sets territory/price and clicks Publish when auto_publish=True, or Save as Draft otherwise."""
        assistant = KDPAssistant(user_data_dir=self.test_dir / "kdp_profile")

        def make_mock_page():
            page = MagicMock()
            page.url = "https://kdp.amazon.com/en_US/title-setup/paperback/ABC/pricing"
            loc = MagicMock()
            loc.count.return_value = 1
            loc.first = loc
            loc.is_visible.return_value = True
            loc.is_enabled.return_value = True
            page.locator.return_value = loc
            page.evaluate.return_value = []
            return page, loc

        page_pub, loc_pub = make_mock_page()
        with patch.object(assistant, "_collect_visible_alerts", return_value=[]):
            ok_pub = assistant._fill_step3_pricing(page_pub, self.mock_dossier["amazon_kdp"], lambda *a, **k: None, auto_publish=True)
            self.assertTrue(ok_pub)
            loc_pub.fill.assert_called()
            loc_pub.click.assert_called()

        page_draft, loc_draft = make_mock_page()
        ok_draft = assistant._fill_step3_pricing(page_draft, self.mock_dossier["amazon_kdp"], lambda *a, **k: None, auto_publish=False)
        self.assertTrue(ok_draft)
        loc_draft.click.assert_called()

if __name__ == "__main__":
    unittest.main()
