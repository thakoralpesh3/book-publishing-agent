"""PublisheR AI • Autonomous Daily & 8-Hour Interval Publishing Scheduler
Coordinates autonomous startup execution (after YouTube Agent and Social Media Agent complete)
and manages recurring 8-hour auto-publishing cycles with direct posting to Amazon KDP and Flipkart.
Supervises state persistence in data/daily_schedule_config.json, calculates live next-run countdowns,
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
DEFAULT_INTERVAL_HOURS = 0.0  # 0.0 = recurring interval disabled (runs once per system startup)
DEFAULT_SCHEDULE_TIME = "23:30"  # 11:30 PM local time (IST)


class DailyPublishScheduler:
    """Manages autonomous startup coordination and the recurring 8-hour publication schedule."""

    def __init__(
        self,
        config_file: Path = SCHEDULE_CONFIG_FILE,
        interval_hours: float = DEFAULT_INTERVAL_HOURS,
        target_time: str = DEFAULT_SCHEDULE_TIME,
        auto_upload: str = "both",
        category: Optional[str] = None,
        startup_prereq_wait: bool = True
    ):
        self.config_file = config_file
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.default_interval_hours = interval_hours
        self.default_target_time = target_time
        self.default_auto_upload = auto_upload
        self.default_category = category
        self.default_startup_prereq_wait = startup_prereq_wait
        self.running = False
        self._thread: Optional[threading.Thread] = None
        self._startup_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._startup_executed = False
        self._ensure_config()

    def _ensure_config(self):
        """Initializes schedule config file with defaults if not present."""
        if not self.config_file.exists():
            cfg = {
                "enabled": True,
                "interval_hours": self.default_interval_hours,
                "scheduled_time": self.default_target_time,
                "auto_upload": self.default_auto_upload,
                "category": self.default_category,
                "custom_topic": None,
                "startup_prereq_wait": self.default_startup_prereq_wait,
                "last_run_date": "",
                "last_run_timestamp": "",
                "last_run_status": "",
                "last_book_title": "",
                "last_book_slug": "",
                "timezone": "Asia/Kolkata (IST)",
                "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            self._save_config(cfg)
        else:
            # Upgrade existing config schema if interval_hours or startup_prereq_wait missing
            try:
                data = json.loads(self.config_file.read_text(encoding="utf-8") or "{}")
                changed = False
                if "interval_hours" not in data:
                    data["interval_hours"] = self.default_interval_hours
                    changed = True
                if "startup_prereq_wait" not in data:
                    data["startup_prereq_wait"] = self.default_startup_prereq_wait
                    changed = True
                if changed:
                    self._save_config(data)
            except Exception:
                pass

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
                    "interval_hours": self.default_interval_hours,
                    "scheduled_time": self.default_target_time,
                    "auto_upload": self.default_auto_upload,
                    "startup_prereq_wait": True
                }

    def _save_config(self, cfg: Dict[str, Any]):
        """Persists schedule configuration atomically."""
        tmp_file = self.config_file.with_suffix(".tmp")
        tmp_file.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        tmp_file.replace(self.config_file)

    def update_config(
        self,
        enabled: Optional[bool] = None,
        interval_hours: Optional[float] = None,
        scheduled_time: Optional[str] = None,
        auto_upload: Optional[str] = None,
        category: Optional[str] = None,
        custom_topic: Optional[str] = None,
        startup_prereq_wait: Optional[bool] = None
    ) -> Dict[str, Any]:
        """Updates schedule settings dynamically."""
        cfg = self.get_config()
        with self._lock:
            if enabled is not None:
                cfg["enabled"] = bool(enabled)
            if interval_hours is not None:
                if interval_hours < 0 or interval_hours > 72:
                    raise ValueError(f"Invalid interval_hours '{interval_hours}'. Must be between 0 and 72 hours.")
                cfg["interval_hours"] = float(interval_hours)
            if scheduled_time is not None:
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
            if startup_prereq_wait is not None:
                cfg["startup_prereq_wait"] = bool(startup_prereq_wait)

            cfg["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._save_config(cfg)
        return self.get_status()

    def calculate_next_run(self) -> Dict[str, Any]:
        """
        Calculates the next target run timestamp based on the 8-hour interval rule,
        or scheduled anchor time.
        """
        cfg = self.get_config()
        interval_hours = float(cfg.get("interval_hours", self.default_interval_hours))
        if interval_hours <= 0:
            return {
                "target_run_iso": "N/A (Startup-Only)",
                "target_time_display": "On Startup / Once Daily",
                "countdown_seconds": 0,
                "countdown_human": "Active on Startup",
                "is_due": False,
                "interval_hours": 0.0
            }

        last_ts_str = cfg.get("last_run_timestamp", "")
        now = datetime.datetime.now()

        if last_ts_str:
            try:
                last_dt = datetime.datetime.strptime(last_ts_str, "%Y-%m-%d %H:%M:%S")
                target_run = last_dt + datetime.timedelta(hours=interval_hours)
            except Exception:
                target_run = now
        else:
            # If never run, next run is due right now
            target_run = now

        diff_seconds = max(0, int((target_run - now).total_seconds()))
        hours, remainder = divmod(diff_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        is_due = diff_seconds == 0

        return {
            "target_run_iso": target_run.strftime("%Y-%m-%d %H:%M:%S"),
            "target_time_display": target_run.strftime("%I:%M %p (%b %d)"),
            "countdown_seconds": diff_seconds,
            "countdown_human": "DUE NOW" if is_due else f"{hours}h {minutes}m {seconds}s",
            "is_due": is_due,
            "interval_hours": interval_hours
        }

    def get_status(self) -> Dict[str, Any]:
        """Returns comprehensive schedule status, 8-hour interval countdown, and prerequisite state."""
        cfg = self.get_config()
        next_run = self.calculate_next_run()

        # Check prerequisite agent readiness
        prereqs = {}
        try:
            from core.background_orchestrator import BackgroundPublishingOrchestrator
            orch = BackgroundPublishingOrchestrator()
            prereqs = orch.check_prerequisite_agents_status()
        except Exception as e:
            prereqs = {"error": str(e)}

        return {
            "enabled": cfg.get("enabled", True),
            "mode": f"every_{cfg.get('interval_hours', 8)}h",
            "interval_hours": float(cfg.get("interval_hours", self.default_interval_hours)),
            "scheduled_time": cfg.get("scheduled_time", self.default_target_time),
            "auto_upload": cfg.get("auto_upload", "both"),
            "category": cfg.get("category"),
            "custom_topic": cfg.get("custom_topic"),
            "startup_prereq_wait": cfg.get("startup_prereq_wait", True),
            "last_run_date": cfg.get("last_run_date", ""),
            "last_run_timestamp": cfg.get("last_run_timestamp", ""),
            "last_run_status": cfg.get("last_run_status", ""),
            "last_book_title": cfg.get("last_book_title", ""),
            "last_book_slug": cfg.get("last_book_slug", ""),
            "next_run": next_run,
            "prerequisites": prereqs,
            "is_active_thread": self.running and self._thread is not None and self._thread.is_alive(),
            "timezone": "Asia/Kolkata (IST)"
        }

    def start(self):
        """Starts the 24/7 background scheduler and launches the startup sentry coordinator."""
        if self.running and self._thread and self._thread.is_alive():
            logger.info("DailyPublishScheduler is already active.")
            return

        self.running = True
        self._thread = threading.Thread(target=self._run_loop, name="DailyPublishSchedulerThread", daemon=True)
        self._thread.start()

        # Launch startup prerequisite sentry in a non-blocking daemon thread
        cfg = self.get_config()
        if cfg.get("startup_prereq_wait", True) and not self._startup_executed:
            self._startup_thread = threading.Thread(
                target=self._run_startup_sentry,
                name="StartupPrerequisiteSentryThread",
                daemon=True
            )
            self._startup_thread.start()

        status = self.get_status()
        logger.info(f"⏰ DailyPublishScheduler active (Interval: {status['interval_hours']}h | Auto-Post: {status['auto_upload'].upper()}).")

    def stop(self):
        """Stops the scheduler loop cleanly."""
        self.running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info("DailyPublishScheduler stopped.")

    def _run_startup_sentry(self):
        """
        Background Startup Sentry:
        Monitors for YouTube Agent and Social Media Agent to finish on startup,
        then automatically executes PublisheR AI book generation & posting!
        """
        logger.info("🛡️ [Startup Sentry] Monitoring YouTube & Social Media agents on startup before running PublisheR AI...")
        try:
            # Check and auto-upload any stored contents from prior sessions
            try:
                from uploader.pending_queue import pending_queue
                logger.info("🔄 [Startup Sentry] Checking for stored book contents from prior sessions...")
                startup_pq = pending_queue.process_startup_stored_contents(force=True)
                if startup_pq.get("dispatched_count", 0) > 0:
                    logger.info(f"🚀 [Startup Sentry] Dispatched {startup_pq['dispatched_count']} stored book upload(s) on startup!")
            except Exception as startup_err:
                logger.debug(f"Startup sentry pending upload check: {startup_err}")

            from core.background_orchestrator import BackgroundPublishingOrchestrator
            orch = BackgroundPublishingOrchestrator()
            cfg = self.get_config()
            interval_h = float(cfg.get("interval_hours", 8.0))
            auto_up = cfg.get("auto_upload", "both")

            # Watch and execute when YouTube & Social are done
            res = orch.watch_and_run(
                poll_interval_seconds=15,
                max_wait_seconds=3600,
                auto_upload=auto_up,
                min_interval_hours=interval_h,
                force=False
            )

            self._startup_executed = True
            logger.info(f"🏁 [Startup Sentry] Startup coordinator finished with status: {res.get('status')}")
            if res.get("status") == "completed":
                self._record_run_success(res)

        except Exception as e:
            logger.error(f"❌ [Startup Sentry] Error in startup coordination: {e}", exc_info=True)

    def _run_loop(self):
        """Precision polling loop monitoring the 8-hour recurring cycle."""
        while self.running:
            try:
                cfg = self.get_config()
                if not cfg.get("enabled", True):
                    time.sleep(30)
                    continue

                from core.background_orchestrator import BackgroundPublishingOrchestrator
                orch = BackgroundPublishingOrchestrator()
                interval_hours = float(cfg.get("interval_hours", self.default_interval_hours))

                # If interval is 0 or less, recurring periodic loop is disabled
                if interval_hours <= 0:
                    time.sleep(60)
                    continue

                # Check orchestrator tracker as the single source of truth for interval
                if orch.is_run_due(min_interval_hours=interval_hours):
                    logger.info(f"🔔 [DailyPublishScheduler] {interval_hours}-Hour interval reached! Launching autonomous generation & posting...")
                    self.execute_daily_pipeline()

            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}", exc_info=True)

            # Sleep 60 seconds between checks to avoid busy-polling and log noise
            time.sleep(60)

    def execute_daily_pipeline(self, force: bool = False) -> Dict[str, Any]:
        """
        Executes the publishing pipeline:
        Generates book via Gemini 4 Argon, compiles PDFs & catalog,
        and posts directly to Amazon KDP and Flipkart Seller Hub.
        """
        cfg = self.get_config()
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        auto_upload = cfg.get("auto_upload", "both")
        category = cfg.get("category")
        topic = cfg.get("custom_topic")
        interval_h = float(cfg.get("interval_hours", 8.0))

        logger.info("=" * 70)
        logger.info(f"🚀 [DailyPublishScheduler] Launching Autonomous Book Publishing Pipeline ({today_str})")
        logger.info(f"   Cycle: Every {interval_h} Hours | Auto-Post: {auto_upload.upper()} | Category: {category or 'Auto Trend'}")
        logger.info("=" * 70)

        try:
            from core.background_orchestrator import BackgroundPublishingOrchestrator
            orchestrator = BackgroundPublishingOrchestrator()
            res = orchestrator.run_daily_publishing_pipeline(
                force=force,
                category=category,
                custom_topic=topic,
                auto_upload=auto_upload,
                min_interval_hours=interval_h
            )

            status_val = res.get("status", "completed")
            if status_val == "completed":
                self._record_run_success(res)
                title = res.get("title", "Daily Book")
                pages = res.get("pages", 0)
                msg = f"Completed: \"{title}\" ({pages} pages). Generated and posted to {auto_upload.upper()}!"
                logger.info(f"✅ [DailyPublishScheduler] {msg}")
                self._send_desktop_notification(
                    "✅ PublisheR AI: Book Generated & Posted!",
                    msg,
                    urgency="normal"
                )
            elif status_val == "skipped":
                logger.info(f"✨ [DailyPublishScheduler] Run skipped: {res.get('message')}")
                tracker_data = orchestrator.get_tracker_data()
                if tracker_data.get("last_run_timestamp"):
                    with self._lock:
                        c = self.get_config()
                        c["last_run_timestamp"] = tracker_data["last_run_timestamp"]
                        c["last_run_date"] = tracker_data.get("last_run_date", today_str)
                        c["last_run_status"] = "cooldown"
                        self._save_config(c)
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
                f"Publishing pipeline error: {str(e)[:80]}",
                urgency="critical"
            )
            return {"status": "failed", "error": str(e), "date": today_str}

    def _record_run_success(self, res: Dict[str, Any]):
        """Records successful run timestamp in schedule config."""
        with self._lock:
            today_str = datetime.date.today().strftime("%Y-%m-%d")
            now_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cfg = self.get_config()
            cfg["last_run_date"] = today_str
            cfg["last_run_timestamp"] = now_ts
            cfg["last_run_status"] = "completed"
            if res.get("title"):
                cfg["last_book_title"] = res["title"]
            if res.get("slug"):
                cfg["last_book_slug"] = res["slug"]
            self._save_config(cfg)

    def _send_desktop_notification(self, title: str, message: str, urgency: str = "normal"):
        """Dispatches Linux desktop notifications via notify-send."""
        try:
            subprocess.run([
                "notify-send",
                "-a", "PublisheR AI",
                "-u", urgency,
                "-t", "8000",
                title,
                message
            ], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        except Exception:
            pass


# Singleton instance
daily_scheduler = DailyPublishScheduler()
