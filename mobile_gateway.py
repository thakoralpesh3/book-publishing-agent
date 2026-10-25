"""PublisheR AI • Mobile Gateway & 24/7 Watchdog (Project Chhaya Architecture)
Supervises the Web Studio backend on port 8550, establishes a secure Cloudflare HTTPS quick tunnel,
generates mobile QR codes for camera scanning, and manages self-healing & memory trimming.
"""

import os
import sys
import time
import json
import re
import socket
import logging
import urllib.request
import subprocess
import ctypes
from pathlib import Path
from typing import Optional, Dict, Any

import qrcode

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("PublisheR_Gateway")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
BIN_DIR = BASE_DIR / "bin"
STATIC_DIR = BASE_DIR / "ui" / "static"

DATA_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)

CLOUDFLARED_BIN = BIN_DIR / "cloudflared"
PUBLIC_URL_FILE = DATA_DIR / "public_url.txt"
QR_CODE_FILE = STATIC_DIR / "mobile_qr.png"
DESKTOP_QR_FILE = Path("/home/alpesh/Desktop/PublisheR_Mobile_Access_QR.png")
DESKTOP_HUB_FILE = Path("/home/alpesh/Desktop/Mobile_Access_Both_Agents.html")
WATCHDOG_LOG = DATA_DIR / "gateway_watchdog.log"
SERVER_PID_FILE = DATA_DIR / "server.pid"


def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def trim_process_memory():
    """Trigger Python garbage collection and Linux malloc_trim to maintain lean footprint."""
    try:
        import gc
        gc.collect()
        libc = ctypes.CDLL("libc.so.6")
        libc.malloc_trim(0)
    except Exception:
        pass


class MobileGatewayWatchdog:
    """Supervises the PublisheR AI server and provides 24/7 Cloudflare mobile HTTPS access."""
    def __init__(self, port: int = 8550):
        self.port = port
        self.server_proc: Optional[subprocess.Popen] = None
        self.tunnel_proc: Optional[subprocess.Popen] = None
        self.public_url: Optional[str] = None
        self.git_watcher: Optional[Any] = None
        self.running = True

    def check_health(self) -> bool:
        """Pings the /api/health endpoint to ensure the backend is responsive."""
        try:
            url = f"http://127.0.0.1:{self.port}/api/health"
            req = urllib.request.Request(url, headers={"User-Agent": "PublisheRWatchdog/1.0"})
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                data = json.loads(resp.read().decode())
                return data.get("status") in ["healthy", "ok", "HEALTHY"]
        except Exception:
            return False

    def start_server(self) -> bool:
        """Launches main.py server if not already active and healthy."""
        if is_port_in_use(self.port):
            logger.info(f"Port {self.port} is already in use. Verifying health...")
            if self.check_health():
                logger.info(f"✅ Existing server on port {self.port} is healthy.")
                return True
            else:
                logger.warning(f"Port {self.port} is occupied by an unresponsive process. Freeing port...")
                os.system(f"fuser -k {self.port}/tcp >/dev/null 2>&1 || true")
                time.sleep(1)

        logger.info(f"Starting PublisheR AI backend on port {self.port}...")
        log_out = open(DATA_DIR / "server.log", "a", encoding="utf-8")
        
        self.server_proc = subprocess.Popen(
            [sys.executable, str(BASE_DIR / "main.py"), "serve", "--port", str(self.port), "--no-browser"],
            cwd=str(BASE_DIR),
            stdout=log_out,
            stderr=log_out,
            start_new_session=True
        )

        with open(SERVER_PID_FILE, "w") as f:
            f.write(str(self.server_proc.pid))

        # Wait up to 8 seconds for health verification
        for _ in range(16):
            time.sleep(0.5)
            if self.check_health():
                logger.info(f"✅ Server successfully started & verified on port {self.port} (PID: {self.server_proc.pid})")
                return True

        logger.error(f"Failed to confirm server health on port {self.port}")
        return False

    def start_tunnel(self) -> Optional[str]:
        """Starts the Cloudflare Quick Tunnel and extracts the public HTTPS URL."""
        if not CLOUDFLARED_BIN.exists() or not os.access(CLOUDFLARED_BIN, os.X_OK):
            logger.warning(f"cloudflared binary missing or not executable at {CLOUDFLARED_BIN}")
            return None

        if self.tunnel_proc and self.tunnel_proc.poll() is None:
            return self.public_url

        # Check if an existing tunnel process is already running for our port
        try:
            cf_procs = subprocess.run(
                ["pgrep", "-f", f"cloudflared.*{self.port}"],
                capture_output=True, text=True
            ).stdout.strip().split()
            if cf_procs and PUBLIC_URL_FILE.exists():
                url = PUBLIC_URL_FILE.read_text(encoding="utf-8").strip()
                if url and "trycloudflare.com" in url and "api.trycloudflare.com" not in url:
                    self.public_url = url
                    logger.info(f"Existing Cloudflare tunnel found (PID: {cf_procs[0]}): {self.public_url}")
                    self.generate_qr_code(self.public_url)
                    return self.public_url
        except Exception:
            pass

        logger.info(f"Establishing Cloudflare Quick Tunnel to http://127.0.0.1:{self.port}...")
        tunnel_log_path = DATA_DIR / "tunnel.log"
        tunnel_log = open(tunnel_log_path, "w", encoding="utf-8")

        self.tunnel_proc = subprocess.Popen(
            [str(CLOUDFLARED_BIN), "tunnel", "--url", f"http://127.0.0.1:{self.port}"],
            cwd=str(BASE_DIR),
            stdout=tunnel_log,
            stderr=tunnel_log,
            start_new_session=True
        )

        # Poll tunnel_log for up to 45 seconds to extract the trycloudflare.com URL
        for _ in range(90):
            time.sleep(0.5)
            if tunnel_log_path.exists():
                with open(tunnel_log_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    import re
                    matches = re.findall(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", content)
                    valid_matches = [m for m in matches if "api.trycloudflare.com" not in m]
                    if valid_matches:
                        self.public_url = valid_matches[-1]
                        with open(PUBLIC_URL_FILE, "w", encoding="utf-8") as uf:
                            uf.write(self.public_url)
                        logger.info(f"🌐 Public Mobile Access URL: {self.public_url}")
                        self.generate_qr_code(self.public_url)
                        self.print_mobile_banner(self.public_url)
                        return self.public_url

        logger.info("Tunnel initiated in background. Public URL will be captured as soon as precheck completes.")
        return None

    def generate_qr_code(self, url: str):
        """Generates mobile QR code image and saves to static directory and desktop."""
        try:
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=2
            )
            qr.add_data(url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="#0F172A", back_color="#FFFFFF")
            img.save(str(QR_CODE_FILE))
            logger.info(f"📱 Mobile QR code saved to {QR_CODE_FILE}")
            try:
                img.save(str(DESKTOP_QR_FILE))
                logger.info(f"📱 Desktop Mobile QR code saved to {DESKTOP_QR_FILE}")
            except Exception:
                pass
            self.update_desktop_hub(url)
        except Exception as e:
            logger.error(f"Failed to generate QR code image: {e}")

    def update_desktop_hub(self, url: str):
        """Syncs the latest public URL into the desktop Multi-Agent Mobile Hub."""
        if not DESKTOP_HUB_FILE.exists():
            return
        try:
            content = DESKTOP_HUB_FILE.read_text(encoding="utf-8")
            if "PublisheR AI" in content:
                # Update existing URL
                updated = re.sub(
                    r'(id="publisher_mobile_link"[^>]*href=")[^"]*(")',
                    rf'\g<1>{url}\g<2>',
                    content
                )
                updated = re.sub(
                    r'(id="publisher_url_text"[^>]*>)[^<]*(</p>)',
                    rf'\g<1>{url}\g<2>',
                    updated
                )
                DESKTOP_HUB_FILE.write_text(updated, encoding="utf-8")
            else:
                # Append PublisheR AI card before </div><!-- end agents-grid --> or footer
                publisher_card = f"""
        <!-- Agent 3: PublisheR AI (Amazon KDP & Flipkart Seller Hub) -->
        <div class="agent-card publisher" style="border-color: rgba(56, 189, 248, 0.4);">
            <div class="agent-icon">📚</div>
            <div class="agent-title" style="color: #38bdf8;">Agent 3: PublisheR AI (Publishing Studio)</div>
            <p class="agent-desc">Amazon KDP & Flipkart Seller Hub Agent, Gemini 4 Argon Content Generator, Zero-Mistake Pre-Flight Auditor & Automated Catalog Exporter</p>
            <a id="publisher_mobile_link" href="{url}" target="_blank" class="btn-launch" style="background: linear-gradient(135deg, #0284c7, #38bdf8); color: #ffffff; box-shadow: 0 4px 15px rgba(2, 132, 199, 0.4);">
                🚀 Open PublisheR Studio on Mobile
            </a>
            <p id="publisher_url_text" class="small text-muted" style="margin-top:8px;font-size:11px;color:#8f95c0;word-break:break-all;">{url}</p>
            <div class="qr-section">
                <img src="/static/mobile_qr.png" alt="Scan to open PublisheR Studio" onerror="this.src='PublisheR_Mobile_Access_QR.png'">
            </div>
            <span style="font-size:11px;color:#a0a5cc;margin-top:6px;">Scan with Phone Camera to Open Instantly!</span>
        </div>
"""
                marker = "</div>\n\n    <div class=\"footer\">"
                if marker in content:
                    updated = content.replace(marker, f"{publisher_card}\n    </div>\n\n    <div class=\"footer\">")
                    DESKTOP_HUB_FILE.write_text(updated, encoding="utf-8")
                    logger.info("Synced PublisheR AI card into Desktop Mobile Hub HTML.")
        except Exception as e:
            logger.warning(f"Could not update desktop hub HTML: {e}")

    def print_mobile_banner(self, url: str):
        """Prints stylish terminal banner with ASCII QR code and public URL."""
        print("\n" + "="*70)
        print("📱  PUBLISHER AI • MOBILE ACCESS GATEWAY (CHHAYA SYSTEM)")
        print("="*70)
        print(f"🌐  PUBLIC HTTPS URL:  {url}")
        print(f"🏠  LOCAL ACCESS URL:  http://127.0.0.1:{self.port}")
        print(f"🖼️   QR CODE IMAGE:    {QR_CODE_FILE}")
        print("="*70)
        print("Scan the QR code below or open the URL on your smartphone:")
        try:
            qr = qrcode.QRCode(border=1)
            qr.add_data(url)
            qr.make(fit=True)
            qr.print_ascii(invert=True)
        except Exception:
            pass
        print("="*70 + "\n")

    def run_supervision_loop(self):
        """Supervision loop that ensures continuous uptime, tunnel health, and lean memory."""
        logger.info(f"🛡️ Starting Mobile Gateway Supervision Loop (Port {self.port})...")
        self.start_server()
        self.start_tunnel()

        # Start Autonomous Git Auto-Sync Watcher
        try:
            from core.git_watcher import GitAutoSyncWatcher
            self.git_watcher = GitAutoSyncWatcher()
            self.git_watcher.start()
            logger.info("⚡ Autonomous Antigravity Git Auto-Sync Watcher active in 24/7 background.")
        except Exception as gw_e:
            logger.warning(f"Could not initialize GitAutoSyncWatcher: {gw_e}")

        iteration = 0
        while self.running:
            try:
                time.sleep(10)
                iteration += 1

                # 1. Health check backend
                if not self.check_health():
                    logger.warning("⚠️ Backend server unresponsive! Auto-restarting...")
                    self.start_server()

                # 2. Extract public URL if not yet captured
                if not self.public_url:
                    tunnel_log_path = DATA_DIR / "tunnel.log"
                    if tunnel_log_path.exists():
                        with open(tunnel_log_path, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read()
                            import re
                            match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", content)
                            if match:
                                self.public_url = match.group(0)
                                with open(PUBLIC_URL_FILE, "w", encoding="utf-8") as uf:
                                    uf.write(self.public_url)
                                logger.info(f"🌐 Public Mobile Access URL confirmed: {self.public_url}")
                                self.generate_qr_code(self.public_url)
                                self.print_mobile_banner(self.public_url)

                # 3. Check tunnel health periodically
                if iteration % 6 == 0:
                    if not self.tunnel_proc or self.tunnel_proc.poll() is not None:
                        logger.warning("⚠️ Tunnel disconnected! Re-establishing...")
                        self.start_tunnel()

                # 3. Trim memory every 2 minutes
                if iteration % 12 == 0:
                    trim_process_memory()

                # 4. Periodically auto-retry pending uploads when platforms/network are healthy (~5 minutes)
                if iteration % 30 == 0:
                    try:
                        from uploader.pending_queue import pending_queue
                        pending_queue.process_pending_queue()
                    except Exception as pq_e:
                        logger.debug(f"Pending queue auto-retry check: {pq_e}")

            except KeyboardInterrupt:
                logger.info("Mobile Gateway received shutdown signal.")
                break
            except Exception as e:
                logger.error(f"Error in supervision loop: {e}")

        self.shutdown()

    def shutdown(self):
        """Clean shutdown of child processes."""
        self.running = False
        if self.git_watcher:
            try:
                self.git_watcher.stop()
            except Exception:
                pass
        if self.tunnel_proc and self.tunnel_proc.poll() is None:
            self.tunnel_proc.terminate()
        if self.server_proc and self.server_proc.poll() is None:
            self.server_proc.terminate()
        logger.info("Mobile Gateway stopped cleanly.")


def get_mobile_status(port: int = 8550) -> Dict[str, Any]:
    """Retrieves current mobile gateway status and active tunnel URL."""
    url = None
    if PUBLIC_URL_FILE.exists():
        try:
            with open(PUBLIC_URL_FILE, "r", encoding="utf-8") as f:
                url = f.read().strip()
        except Exception:
            pass

    return {
        "status": "ONLINE" if url else "OFFLINE",
        "port": port,
        "public_url": url or f"http://127.0.0.1:{port}",
        "has_public_tunnel": bool(url),
        "qr_code_url": "/static/mobile_qr.png" if QR_CODE_FILE.exists() else None,
        "agents": {
            "amazon_kdp_agent": {
                "name": "Amazon KDP Agent",
                "status": "READY",
                "capabilities": ["HTML Book Description", "7 Search Keywords", "Browse Categories", "Interior & Cover PDFs", "Auto-Fill Wizard"]
            },
            "flipkart_agent": {
                "name": "Flipkart Book Agent",
                "status": "READY",
                "capabilities": ["HSN 4901.10.00 Check", "0% GST Exemption", "Dimensions & Courier Weight", "Bulk Excel Catalog (.xlsx)", "Highlights & Synopsis"]
            }
        }
    }


if __name__ == "__main__":
    gw = MobileGatewayWatchdog(port=8550)
    gw.run_supervision_loop()
