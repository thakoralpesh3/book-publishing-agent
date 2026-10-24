"""Background Publishing Orchestrator
Coordinates autonomous background book generation when prerequisite agents
(Aradhya AI, YouTube Shorts AI, and Social Media Stories AI) have finished their work.
Enforces a 1-run-per-calendar-day quota, selects daily high-velocity trends,
generates the complete book package headlessly, and dispatches desktop notifications.
"""

import os
import sys
import json
import time
import psutil
import logging
import datetime
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import config
from core.gemini_engine import GeminiBookEngine
from core.book_writer import BookWriter
from core.manuscript_compiler import ManuscriptCompiler
from core.cover_generator import CoverGenerator
from core.metadata_engine import MetadataEngine
from core.catalog_exporter import CatalogExporter
from core.trend_radar import TrendRadar
from core.preflight_validator import PreflightValidator

logger = logging.getLogger("BackgroundOrchestrator")

DAILY_TRACKER_FILE = config.OUTPUT_DIR / "publisher_daily_tracker.json"

# External Agent Paths
YOUTUBE_AGENT_DIR = Path("/home/alpesh/youtube-agent")
JARVIS_AGENT_DIR = Path("/home/alpesh/jarvis-agent")
JARVIS_CONFIG_DIR = Path.home() / ".jarvis"


class BackgroundPublishingOrchestrator:
    """Supreme autonomous supervisor for headless, background book publishing operations."""

    def __init__(self, tracker_file: Path = DAILY_TRACKER_FILE):
        self.tracker_file = tracker_file
        self.tracker_file.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_tracker_file()

    def _ensure_tracker_file(self):
        """Initializes daily tracker file if missing."""
        if not self.tracker_file.exists():
            today_str = datetime.date.today().strftime("%Y-%m-%d")
            initial_data = {
                "current_date": today_str,
                "last_run_date": "",
                "runs_today_count": 0,
                "daily_limit": 1,
                "last_run_timestamp": "",
                "last_book_slug": "",
                "last_book_title": "",
                "history": []
            }
            self.tracker_file.write_text(json.dumps(initial_data, indent=2), encoding="utf-8")

    def get_tracker_data(self) -> Dict[str, Any]:
        """Reads tracker data safely."""
        self._ensure_tracker_file()
        try:
            return json.loads(self.tracker_file.read_text(encoding="utf-8") or "{}")
        except Exception as e:
            logger.warning(f"Error reading tracker file: {e}")
            return {"runs_today_count": 0, "last_run_date": ""}

    def is_daily_run_due(self) -> bool:
        """Checks if today's book has already been generated."""
        data = self.get_tracker_data()
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        if data.get("last_run_date") == today_str and data.get("runs_today_count", 0) >= data.get("daily_limit", 1):
            return False
        return True

    def check_prerequisite_agents_status(self) -> Dict[str, Any]:
        """
        Inspects the status of Aradhya AI, YouTube Agent, and Social Media Agent.
        Returns running flags, today's completion records, and overall readiness.
        """
        today_str = datetime.date.today().strftime("%Y-%m-%d")

        # 1. YouTube Shorts Agent Status
        yt_running = False
        yt_completed_today = False
        yt_tracker = YOUTUBE_AGENT_DIR / "output" / "youtube_daily_tracker.json"
        if yt_tracker.exists():
            try:
                ydata = json.loads(yt_tracker.read_text(encoding="utf-8") or "{}")
                if ydata.get("last_run_date") == today_str and ydata.get("runs_today_count", 0) >= 1:
                    yt_completed_today = True
            except Exception:
                pass

        # 2. Social Media Agent Status
        social_running = False
        social_completed_today = False
        social_tracker = YOUTUBE_AGENT_DIR / "output" / "social_daily_tracker.json"
        if social_tracker.exists():
            try:
                sdata = json.loads(social_tracker.read_text(encoding="utf-8") or "{}")
                if sdata.get("last_post_date") == today_str and sdata.get("posts_today_count", 0) >= 1:
                    social_completed_today = True
            except Exception:
                pass

        # 3. Aradhya (Jarvis) Daemon Status
        aradhya_active = False
        jarvis_pid_file = JARVIS_CONFIG_DIR / "jarvis.pid"
        if jarvis_pid_file.exists():
            try:
                pid = int(jarvis_pid_file.read_text().strip())
                if psutil.pid_exists(pid):
                    p = psutil.Process(pid)
                    if p.is_running() and p.status() != psutil.STATUS_ZOMBIE:
                        aradhya_active = True
            except Exception:
                pass

        # Check process table for active rendering/uploading jobs
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmd = " ".join(proc.info.get('cmdline') or [])
                if "youtube-agent" in cmd and ("agent.py" in cmd or "upload_to_youtube" in cmd or "launch_youtube" in cmd):
                    yt_running = True
                if ("launch_social" in cmd or "festival_agent" in cmd or "social_manager" in cmd) and "book-publishing" not in cmd:
                    social_running = True
            except Exception:
                pass

        # Readiness rule:
        # Prerequisite agents are "finished" if:
        # - Neither YouTube nor Social agent is actively running in the process tree, AND
        # - Either they have completed today's run OR the sequential coordinator has completed.
        prereqs_finished = (not yt_running) and (not social_running) and (yt_completed_today or social_completed_today)

        return {
            "today": today_str,
            "youtube": {
                "running": yt_running,
                "completed_today": yt_completed_today
            },
            "social": {
                "running": social_running,
                "completed_today": social_completed_today
            },
            "aradhya": {
                "daemon_active": aradhya_active
            },
            "prerequisites_finished": prereqs_finished,
            "publisher_daily_due": self.is_daily_run_due()
        }

    def _select_daily_trend(self, preferred_category: Optional[str] = None) -> Dict[str, Any]:
        """Picks the top high-demand trend that hasn't been generated yet today."""
        radar = TrendRadar()
        trends = radar.get_trends(category=preferred_category)
        if not trends:
            trends = radar.get_trends()

        # Check already generated slugs to avoid exact repeats
        existing_slugs = [p.name for p in config.OUTPUT_DIR.iterdir() if p.is_dir()]
        for t in trends:
            t_id = t.get("id", "")
            if not any(t_id in s for s in existing_slugs):
                return t

        return trends[0] if trends else {
            "title": "The Daily Financial Freedom Playbook",
            "topic": "How to Get Rich in the Modern AI Economy: Practical Money Mindset, Cash Flow Systems, and Scalable Wealth",
            "category": "wealth",
            "book_type": "standard",
            "suggested_trim_size": "6x9",
            "suggested_chapters": 5,
            "target_audience": "Ambitious Professionals & Knowledge Workers"
        }

    def run_daily_publishing_pipeline(
        self,
        force: bool = False,
        category: Optional[str] = None,
        custom_topic: Optional[str] = None,
        auto_upload: str = "none"
    ) -> Dict[str, Any]:
        """
        Executes complete headless book generation in the background.
        Drafts manuscript, compiles interior PDF, designs cover, builds Amazon KDP and Flipkart metadata,
        and dispatches a desktop notification upon completion.
        """
        today_str = datetime.date.today().strftime("%Y-%m-%d")

        if not force and not self.is_daily_run_due():
            logger.info(f"✨ [PublisheR AI Background] Daily book already generated for {today_str}. Skipping (use force=True to override).")
            return {
                "status": "skipped",
                "message": f"Daily book limit reached for {today_str}",
                "date": today_str
            }

        logger.info("=" * 70)
        logger.info(f"📚 [PublisheR AI Background] Starting Autonomous Daily Book Pipeline for {today_str}")
        logger.info("=" * 70)

        # 1. Select trend topic
        if custom_topic:
            trend_obj = {
                "title": custom_topic,
                "topic": custom_topic,
                "category": category or "general",
                "book_type": "activity_drawing" if any(k in custom_topic.lower() for k in ["drawing", "kids", "doodle", "trace"]) else "standard",
                "suggested_trim_size": "8.5x11" if any(k in custom_topic.lower() for k in ["drawing", "kids", "doodle"]) else "6x9",
                "suggested_chapters": 5,
                "target_audience": "General Reader"
            }
        else:
            trend_obj = self._select_daily_trend(preferred_category=category)

        topic = trend_obj.get("topic") or trend_obj.get("title")
        book_type = trend_obj.get("book_type", "standard")
        trim_size = trend_obj.get("suggested_trim_size", "8.5x11" if book_type == "activity_drawing" else "6x9")
        chapters = trend_obj.get("suggested_chapters", 5)
        audience = trend_obj.get("target_audience", "General Reader")

        logger.info(f"🎯 Selected Daily Niche: '{trend_obj.get('title')}'")
        logger.info(f"   Category: {trend_obj.get('category')} | Type: {book_type} | Trim Size: {trim_size}")

        # Send starting notification
        self._send_notification(
            "📚 PublisheR AI: Daily Pipeline Active",
            f"Generating publication package for: {trend_obj.get('title')[:60]}...",
            urgency="low"
        )

        try:
            engine = GeminiBookEngine()
            writer = BookWriter(engine)
            compiler = ManuscriptCompiler(trim_size=trim_size)
            cover_gen = CoverGenerator(trim_size=trim_size)
            meta_engine = MetadataEngine(engine)
            exporter = CatalogExporter()

            # Step 1: Draft Blueprint & Chapters
            logger.info("[1/5] Drafting book blueprint & chapters with Gemini...")
            book_data = writer.create_book(
                topic=topic,
                target_audience=audience,
                target_chapters=chapters,
                book_type=book_type
            )
            book_dir = Path(book_data["book_dir"])
            logger.info(f"Manuscript drafted: {book_data['title']} ({book_data.get('total_words', 0)} words)")

            # Step 2: Compile Interior PDF (ReportLab)
            logger.info("[2/5] Compiling print-ready interior PDF...")
            pdf_res = compiler.compile_pdf(
                book_data=book_data,
                output_path=book_dir / "manuscript_interior.pdf"
            )
            final_pages = pdf_res["page_count"]
            book_data["final_page_count"] = final_pages
            logger.info(f"Interior PDF compiled: {final_pages} pages")

            # Step 3: Generate Cover Graphic & Full-Wrap PDF
            logger.info("[3/5] Generating full-wrap print cover and front graphic...")
            front_jpg = book_dir / "cover_front.jpg"
            cover_gen.generate_front_cover_image(
                title=book_data["title"],
                subtitle=book_data.get("subtitle", ""),
                author=book_data["author"],
                output_path=front_jpg
            )
            wrap_res = cover_gen.generate_full_wrap_pdf(
                book_data=book_data,
                page_count=final_pages,
                front_cover_img_path=front_jpg,
                output_pdf_path=book_dir / "cover_full_wrap.pdf"
            )

            # Step 4: Metadata for Amazon KDP & Flipkart
            logger.info("[4/5] Generating Amazon KDP and Flipkart listing metadata...")
            dossier = meta_engine.generate_all_metadata(book_data, page_count=final_pages, trim_size=trim_size)

            # Step 5: Export Spreadsheets & Markdown
            logger.info("[5/5] Exporting Flipkart bulk catalog (.xlsx) and Amazon listing dossier (.md)...")
            export_files = exporter.export_all(book_dir, dossier)

            # Step 6: Automated Pre-Flight Zero-Mistake Audit
            logger.info("🛡️ Running Automated 25-Point Pre-Flight Zero-Mistake Audit...")
            validator = PreflightValidator(book_dir)
            audit_report = validator.run_full_audit()
            logger.info(f"🛡️ Zero-Mistake Audit: {audit_report.get('compliance_score')} ({audit_report.get('passed_checks_count')}/{audit_report.get('total_checks_count')} Passed). Certified: {audit_report.get('zero_mistake_certified')}")
            if audit_report.get("issues"):
                for issue in audit_report["issues"]:
                    logger.warning(f"  [Audit Issue]: {issue}")

            # Record in daily tracker
            self._record_completion(book_data)

            # Trigger auto-upload assistant if requested
            upload_job_id = None
            if auto_upload and auto_upload.lower() != "none":
                try:
                    from uploader.upload_manager import start_upload_job
                    plat = "kdp" if auto_upload.lower() in ["kdp", "amazon", "both"] else "flipkart"
                    upload_job_id = start_upload_job(
                        slug=book_data["slug"],
                        platform=plat,
                        headless=True,
                        auto_advance=True
                    )
                    logger.info(f"Background pipeline initiated auto-upload for {plat.upper()} (Job ID: {upload_job_id})")
                except Exception as e:
                    logger.warning(f"Could not initiate auto-upload in background pipeline: {e}")

            # Send completion notification
            notif_msg = f"Completed: \"{book_data['title']}\" ({final_pages} pages). Zero-Mistake Audit: {audit_report.get('compliance_score')}."
            if upload_job_id:
                notif_msg += f" Upload Assistant active ({auto_upload.upper()})."
            self._send_notification(
                "✅ PublisheR AI: Daily Book Package Ready!",
                notif_msg,
                urgency="normal"
            )

            logger.info("=" * 70)
            logger.info(f"✨ [PublisheR AI] Daily Book Successfully Generated: {book_data['title']}")
            logger.info(f"📁 Directory: {book_dir}")
            logger.info("=" * 70)

            return {
                "status": "completed",
                "date": today_str,
                "slug": book_data["slug"],
                "book_slug": book_data["slug"],
                "title": book_data["title"],
                "pages": final_pages,
                "trim_size": trim_size,
                "book_dir": str(book_dir),
                "output_dir": str(book_dir),
                "pdf_interior": pdf_res["pdf_path"],
                "cover_wrap_pdf": wrap_res["cover_wrap_pdf"],
                "flipkart_excel": export_files["flipkart_excel"],
                "amazon_markdown": export_files["amazon_markdown"],
                "audit": audit_report,
                "upload_job_id": upload_job_id
            }

        except Exception as e:
            logger.error(f"❌ [PublisheR AI Background] Error during book generation: {e}", exc_info=True)
            self._send_notification(
                "⚠️ PublisheR AI Warning",
                f"Background book generation error: {str(e)[:80]}",
                urgency="normal"
            )
            return {
                "status": "failed",
                "error": str(e),
                "date": today_str
            }

    def _record_completion(self, book_data: Dict[str, Any]):
        """Updates tracker history upon successful completion."""
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        now_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data = self.get_tracker_data()
        data["current_date"] = today_str
        data["last_run_date"] = today_str
        data["runs_today_count"] = data.get("runs_today_count", 0) + 1
        data["last_run_timestamp"] = now_ts
        data["last_book_slug"] = book_data.get("slug", "")
        data["last_book_title"] = book_data.get("title", "")

        history_entry = {
            "date": today_str,
            "timestamp": now_ts,
            "slug": book_data.get("slug", ""),
            "title": book_data.get("title", ""),
            "pages": book_data.get("final_page_count", 0),
            "genre": book_data.get("genre", ""),
            "status": "completed"
        }
        history = data.get("history", [])
        history.append(history_entry)
        data["history"] = history[-30:]

        self.tracker_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _send_notification(self, title: str, message: str, urgency: str = "normal"):
        """Dispatches Linux desktop notifications via notify-send."""
        try:
            subprocess.run([
                "notify-send",
                "-a", "PublisheR AI",
                "-u", urgency,
                title,
                message
            ], check=False)
        except Exception:
            pass

    def watch_and_run(self, poll_interval_seconds: int = 20, max_wait_seconds: int = 1800) -> Dict[str, Any]:
        """
        Background Sentry:
        Polls prerequisite agent status until Aradhya, YouTube, and Social agent are done,
        then automatically executes PublisheR AI's daily publishing pipeline.
        """
        logger.info(f"👀 [PublisheR AI Sentry] Watching for Aradhya, YouTube & Social agents completion (polling every {poll_interval_seconds}s)...")
        start_time = time.time()

        while (time.time() - start_time) < max_wait_seconds:
            status = self.check_prerequisite_agents_status()
            logger.debug(f"Sentry poll: YT running={status['youtube']['running']}, Social running={status['social']['running']}, Done={status['prerequisites_finished']}")

            # If prerequisites have finished and our daily run is due:
            if status["prerequisites_finished"]:
                if status["publisher_daily_due"]:
                    logger.info("🎯 All prerequisite agents have finished! Commencing PublisheR AI background pipeline...")
                    return self.run_daily_publishing_pipeline(force=False)
                else:
                    logger.info("✨ Prerequisite agents finished, and PublisheR AI has already completed today's book.")
                    return {"status": "already_completed", "date": status["today"]}

            time.sleep(poll_interval_seconds)

        logger.info(f"⏳ Sentry reached timeout ({max_wait_seconds}s). Executing pipeline if due...")
        return self.run_daily_publishing_pipeline(force=False)
