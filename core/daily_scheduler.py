"""PublisheR AI • Autonomous Daily Publishing Scheduler
Schedules and triggers automatic book generation and posting to Amazon KDP and Flipkart
at a specific daily time (default: 11:30 PM / 23:30 IST).
Supervises state persistence in data/daily_schedule_config.json, calculates next-run countdowns,
and dispatches desktop notifications upon execution.
"""

import os
import sys
import json
import time
import logging
import datetime
import threading
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional

import config

logger = logging.getLogger("DailyScheduler")

SCHEDULE_CONFIG_FILE = config.DATA_DIR / "daily_schedule_config.json"
DEFAULT_SCHEDULE_TIME = "23:30"  # 11:30 PM local time (IST)


class DailyPublishScheduler:
    """Manages the autonomous daily 11:30 PM book generation & posting schedule."""

    def __init__(
        self,
        config_file: Path = SCHEDULE_CONFIG_FILE,
        target_time: str = DEFAULT_SCHEDULE_TIME,
        auto_upload: str = "both",
        category: Optional[str] = None
    ):
        self.config_file = config_file
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.default_target_time = target_time
        self.default_auto_upload = auto_upload
        self.default_category = category
        self.running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._last_execution_date: Optional[str] = None
        self._ensure_config()

    def _ensure_config(self):
        """Initializes schedule config file with defaults if not present."""
        if not self.config_file.exists():
            cfg = {
                "enabled": True,
                "scheduled_time": self.default_target_time,
                "auto_upload": self.default_auto_upload,
                "category": self.default_category,
                "custom_topic": None,
                "last_run_date": "",
                "last_run_timestamp": "",
                "last_run_status": "",
                "last_book_title": "",
                "last_book_slug": "",
                "timezone": "Asia/Kolkata (IST)",
                "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            self._save_config(cfg)

    def get_config(self) -> Dict[str, Any]:
        """Reads schedule configuration safely."""
        self._ensure_config()
        with self._lock:
            try:
                return json.loads(self.config_file.read_text(encoding="utf-8") or "{}")
            except Exception as e:
                logger.warning(f"Error reading schedule config: {e}")
                return {
                    "enabled": True,
                    "scheduled_time": self.default_target_time,
                    "auto_upload": self.default_auto_upload
                }

    def _save_config(self, cfg: Dict[str, Any]):
        """Persists schedule configuration atomically."""
        tmp_file = self.config_file.with_suffix(".tmp")
        tmp_file.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        tmp_file.replace(self.config_file)

    def update_config(
        self,
        enabled: Optional[bool] = None,
        scheduled_time: Optional[str] = None,
        auto_upload: Optional[str] = None,
        category: Optional[str] = None,
        custom_topic: Optional[str] = None
    ) -> Dict[str, Any]:
        """Updates schedule settings dynamically."""
        cfg = self.get_config()
        with self._lock:
            if enabled is not None:
                cfg["enabled"] = bool(enabled)
            if scheduled_time is not None:
                # Validate HH:MM format
                try:
                    datetime.datetime.strptime(scheduled_time.strip(), "%H:%M")
                    cfg["scheduled_time"] = scheduled_time.strip()
                except ValueError:
                    raise ValueError(f"Invalid scheduled_time format '{scheduled_time}'. Expected 'HH:MM' (24-hour), e.g. '23:30'.")
            if auto_upload is not None:
                if auto_upload.lower() in ["none", "kdp", "flipkart", "both", "all"]:
                    cfg["auto_upload"] = auto_upload.lower()
                else:
                    raise ValueError(f"Invalid auto_upload '{auto_upload}'. Choices: 'none', 'kdp', 'flipkart', 'both'.")
            if category is not None:
                cfg["category"] = category if category != "" else None
            if custom_topic is not None:
                cfg["custom_topic"] = custom_topic if custom_topic != "" else None

            cfg["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._save_config(cfg)
        return self.get_status()

    def calculate_next_run(self, scheduled_time_str: Optional[str] = None) -> Dict[str, Any]:
        """Calculates next target run datetime, countdown seconds, and formatted display."""
        cfg = self.get_config()
        time_str = scheduled_time_str or cfg.get("scheduled_time", self.default_target_time)
        try:
            target_hour, target_minute = [int(x) for x in time_str.split(":", 1)]
        except Exception:
            target_hour, target_minute = 23, 30

        now = datetime.datetime.now()
        target_today = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)

        # If today's target time has already passed or today's book has run:
        today_str = now.strftime("%Y-%m-%d")
        last_run_date = cfg.get("last_run_date", "")

        if now >= target_today or last_run_date == today_str:
            target_run = target_today + datetime.timedelta(days=1)
        else:
            target_run = target_today

        diff_seconds = max(0, int((target_run - now).total_seconds()))
        hours, remainder = divmod(diff_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        return {
            "target_run_iso": target_run.strftime("%Y-%m-%d %H:%M:%S"),
            "target_time_display": target_run.strftime("%I:%M %p"),
            "countdown_seconds": diff_seconds,
            "countdown_human": f"{hours}h {minutes}m {seconds}s",
            "is_scheduled_today": target_run.date() == now.date()
        }

    def get_status(self) -> Dict[str, Any]:
        """Returns comprehensive schedule status, next run time, and today's status."""
        cfg = self.get_config()
        next_run = self.calculate_next_run(cfg.get("scheduled_time"))
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        today_completed = cfg.get("last_run_date") == today_str

        return {
            "enabled": cfg.get("enabled", True),
            "scheduled_time": cfg.get("scheduled_time", self.default_target_time),
            "scheduled_time_display": datetime.datetime.strptime(
                cfg.get("scheduled_time", self.default_target_time), "%H:%M"
            ).strftime("%I:%M %p"),
            "auto_upload": cfg.get("auto_upload", "both"),
            "category": cfg.get("category"),
            "custom_topic": cfg.get("custom_topic"),
            "today_completed": today_completed,
            "last_run_date": cfg.get("last_run_date", ""),
            "last_run_timestamp": cfg.get("last_run_timestamp", ""),
            "last_run_status": cfg.get("last_run_status", ""),
            "last_book_title": cfg.get("last_book_title", ""),
            "last_book_slug": cfg.get("last_book_slug", ""),
            "next_run": next_run,
            "is_active_thread": self.running and self._thread is not None and self._thread.is_alive(),
            "timezone": "Asia/Kolkata (IST)"
        }

    def start(self):
        """Starts the background scheduler thread."""
        if self.running and self._thread and self._thread.is_alive():
            logger.info("DailyPublishScheduler is already running.")
            return

        self.running = True
        self._thread = threading.Thread(target=self._run_loop, name="DailyPublishSchedulerThread", daemon=True)
        self._thread.start()
        status = self.get_status()
        logger.info(f"⏰ DailyPublishScheduler started. Next run at {status['scheduled_time_display']} ({status['next_run']['countdown_human']})")

    def stop(self):
        """Stops the scheduler loop cleanly."""
        self.running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info("DailyPublishScheduler stopped.")

    def _run_loop(self):
        """Internal precision polling loop."""
        while self.running:
            try:
                cfg = self.get_config()
                if not cfg.get("enabled", True):
                    time.sleep(15)
                    continue

                now = datetime.datetime.now()
                today_str = now.strftime("%Y-%m-%d")
                time_str = cfg.get("scheduled_time", self.default_target_time)

                try:
                    target_hour, target_minute = [int(x) for x in time_str.split(":", 1)]
                except Exception:
                    target_hour, target_minute = 23, 30

                # Check if current time has reached the scheduled window
                # and today's run has not yet executed
                is_due_time = (now.hour == target_hour and now.minute >= target_minute) or (now.hour > target_hour)
                already_ran_today = (cfg.get("last_run_date") == today_str) or (self._last_execution_date == today_str)

                if is_due_time and not already_ran_today:
                    logger.info(f"🔔 [DailyPublishScheduler] Scheduled time {time_str} reached! Triggering daily publication pipeline...")
                    self.execute_daily_pipeline()

            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}", exc_info=True)

            # Sleep 15 seconds between checks
            time.sleep(15)

    def execute_daily_pipeline(self, force: bool = False) -> Dict[str, Any]:
        """
        Executes the daily publishing pipeline:
        Generates book via Gemini 4 Argon, compiles PDFs & catalog,
        and posts directly to Amazon KDP and Flipkart Seller Hub.
        """
        cfg = self.get_config()
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        auto_upload = cfg.get("auto_upload", "both")
        category = cfg.get("category")
        topic = cfg.get("custom_topic")

        logger.info("=" * 70)
        logger.info(f"🚀 [DailyPublishScheduler] Launching 11:30 PM Daily Auto-Publish Pipeline ({today_str})")
        logger.info(f"   Target Platforms: {auto_upload.upper()} | Category: {category or 'Auto Trend'}")
        logger.info("=" * 70)

        self._send_desktop_notification(
            "⏰ PublisheR AI: 11:30 PM Scheduled Run Starting",
            f"Autonomous book generation active. Target upload: {auto_upload.upper()}.",
            urgency="normal"
        )

        try:
            from core.background_orchestrator import BackgroundPublishingOrchestrator
            orchestrator = BackgroundPublishingOrchestrator()
            res = orchestrator.run_daily_publishing_pipeline(
                force=force,
                category=category,
                custom_topic=topic,
                auto_upload=auto_upload
            )

            status_val = res.get("status", "completed")
            with self._lock:
                cfg = self.get_config()
                cfg["last_run_date"] = today_str
                cfg["last_run_timestamp"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cfg["last_run_status"] = status_val
                if res.get("title"):
                    cfg["last_book_title"] = res["title"]
                if res.get("slug"):
                    cfg["last_book_slug"] = res["slug"]
                self._save_config(cfg)
                self._last_execution_date = today_str

            if status_val == "completed":
                title = res.get("title", "Daily Book")
                pages = res.get("pages", 0)
                msg = f"Completed: \"{title}\" ({pages} pages). Generated and posted to {auto_upload.upper()}!"
                logger.info(f"✅ [DailyPublishScheduler] {msg}")
                self._send_desktop_notification(
                    "✅ PublisheR AI: Daily Book Generated & Posted!",
                    msg,
                    urgency="normal"
                )
            elif status_val == "skipped":
                logger.info(f"✨ [DailyPublishScheduler] Run skipped: {res.get('message')}")
            else:
                logger.warning(f"⚠️ [DailyPublishScheduler] Run completed with status: {status_val}")

            return res

        except Exception as e:
            logger.error(f"❌ [DailyPublishScheduler] Pipeline execution failed: {e}", exc_info=True)
            with self._lock:
                cfg = self.get_config()
                cfg["last_run_status"] = f"failed: {str(e)[:100]}"
                self._save_config(cfg)

            self._send_desktop_notification(
                "❌ PublisheR AI Schedule Alert",
                f"Daily publishing error: {str(e)[:80]}",
                urgency="critical"
            )
            return {"status": "failed", "error": str(e), "date": today_str}

    def _send_desktop_notification(self, title: str, message: str, urgency: str = "normal"):
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


# Singleton instance
daily_scheduler = DailyPublishScheduler()
