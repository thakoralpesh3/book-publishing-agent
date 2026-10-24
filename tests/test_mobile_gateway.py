"""Unit tests for PublisheR AI Mobile Gateway & Chhaya Integration
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from mobile_gateway import CLOUDFLARED_BIN, QR_CODE_FILE, get_mobile_status, MobileGatewayWatchdog
from fastapi.testclient import TestClient
from ui.app import app

class TestMobileGateway(unittest.TestCase):
    def test_01_cloudflared_binary_ready(self):
        """Verify cloudflared binary is in place and executable."""
        self.assertTrue(CLOUDFLARED_BIN.exists(), f"cloudflared missing at {CLOUDFLARED_BIN}")
        import os
        self.assertTrue(os.access(CLOUDFLARED_BIN, os.X_OK), "cloudflared must be executable")

    def test_02_qr_code_generation(self):
        """Verify QR code generation creates a valid image file."""
        watchdog = MobileGatewayWatchdog(port=8550)
        test_url = "https://publisher-mobile-test.trycloudflare.com"
        watchdog.generate_qr_code(test_url)
        self.assertTrue(QR_CODE_FILE.exists())
        self.assertGreater(QR_CODE_FILE.stat().st_size, 100)

    def test_03_health_endpoint(self):
        """Verify /api/health endpoint returns 200 OK for watchdog check."""
        client = TestClient(app)
        resp = client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("status"), "healthy")

    def test_04_mobile_status_endpoint(self):
        """Verify /api/mobile/status endpoint schema and dual-agent reporting."""
        client = TestClient(app)
        resp = client.get("/api/mobile/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("agents", data)
        self.assertIn("amazon_kdp_agent", data["agents"])
        self.assertIn("flipkart_agent", data["agents"])
        self.assertEqual(data["agents"]["amazon_kdp_agent"]["status"], "READY")
        self.assertEqual(data["agents"]["flipkart_agent"]["status"], "READY")

if __name__ == "__main__":
    unittest.main()
