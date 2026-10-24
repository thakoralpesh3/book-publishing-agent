"""
PublisheR AI • Persistent Pending Upload Queue & Health Prober
Handles offline/failed content persistence, platform reachability checks, and auto-recovery.
"""

import os
import json
import time
import logging
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Any

import config

logger = logging.getLogger("PendingUploadQueue")

QUEUE_FILE = getattr(config, "DATA_DIR", config.BASE_DIR / "data") / "pending_uploads.json"

PLATFORM_HEALTH_URLS = {
    "kdp": "https://kdp.amazon.com",
    "amazon": "https://kdp.amazon.com",
    "flipkart": "https://seller.flipkart.com",
    "internet": "https://1.1.1.1"
}


class PendingUploadQueue:
    """Manages persistent queuing and auto-retries for failed/pending book uploads."""

    def __init__(self, queue_file: Optional[Path] = None, output_dir: Optional[Path] = None):
        self.queue_file = queue_file or QUEUE_FILE
        self.output_dir = output_dir or config.OUTPUT_DIR
        self._ensure_queue_file()

    def _ensure_queue_file(self):
        """Creates the queue file if it doesn't exist."""
        self.queue_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.queue_file.exists():
            with open(self.queue_file, "w", encoding="utf-8") as f:
                json.dump({"queue": []}, f, indent=2)

    def _load_data(self) -> Dict[str, Any]:
        """Loads data from the JSON file safely."""
        try:
            with open(self.queue_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Error loading pending uploads file: {e}. Reinitializing.")
            return {"queue": []}

    def _save_data(self, data: Dict[str, Any]):
        """Saves data to JSON file atomically."""
        temp_file = self.queue_file.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        temp_file.replace(self.queue_file)

    def add_or_update(
        self,
        slug: str,
        platform: str,
        error_reason: str = "",
        failure_reason: Optional[str] = None,
        failure_stage: Optional[str] = None,
        title: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Adds or updates a book in the pending upload queue.
        Calculates exponential backoff for the next retry attempt.
        """
        data = self._load_data()
        queue = data.get("queue", [])

        # Normalize platform name
        plat = "kdp" if platform.lower() in ["kdp", "amazon"] else platform.lower()

        # Check book directory & metadata
        book_dir = self.output_dir / slug
        meta_file = book_dir / "metadata.json"
        book_title = title or slug
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                book_title = meta.get("title", book_title)
            except Exception:
                pass

        # Verify key artifacts exist on disk
        artifacts = {
            "interior_pdf": (book_dir / "manuscript_interior.pdf").exists(),
            "cover_pdf": (book_dir / "cover_full_wrap.pdf").exists(),
            "cover_front_jpg": (book_dir / "cover_front.jpg").exists(),
            "flipkart_excel": (book_dir / "flipkart_bulk_catalog.xlsx").exists(),
            "amazon_md": (book_dir / "amazon_kdp_listing_sheet.md").exists()
        }

        # Check if an entry for this slug and platform already exists
        existing_item = None
        for item in queue:
            if item["slug"] == slug and item["platform"] == plat:
                existing_item = item
                break

        now = time.time()
        now_iso = time.strftime("%Y-%m-%d %H:%M:%S")

        # Resolve reason
        reason = failure_reason or error_reason or "Unknown upload failure"
        saved_files = [k for k, v in artifacts.items() if v]

        if existing_item:
            retries = existing_item.get("retry_count", existing_item.get("attempts", 0)) + 1
            # Exponential backoff: 2 min, 5 min, 15 min, 30 min, max 60 min
            backoff_intervals = [120, 300, 900, 1800, 3600]
            delay = backoff_intervals[min(retries - 1, len(backoff_intervals) - 1)]

            existing_item.update({
                "status": "pending",
                "title": book_title,
                "error_reason": reason,
                "failure_reason": reason,
                "failure_stage": failure_stage or existing_item.get("failure_stage", "upload"),
                "last_attempt": now_iso,
                "last_attempt_at": now_iso,
                "retry_count": retries,
                "attempts": retries,
                "next_retry_at": now + delay,
                "artifacts": artifacts,
                "saved_files": saved_files
            })
            entry = existing_item
            logger.info(f"Updated pending queue item for {slug} ({plat.upper()}): retry #{retries}")
        else:
            qid = f"pending_{plat}_{slug}_{int(now)}"
            entry = {
                "id": qid,
                "queue_id": qid,
                "slug": slug,
                "platform": plat,
                "title": book_title,
                "status": "pending",
                "error_reason": reason,
                "failure_reason": reason,
                "failure_stage": failure_stage or "upload",
                "created_at": now_iso,
                "last_attempt": now_iso,
                "last_attempt_at": now_iso,
                "retry_count": 1,
                "attempts": 1,
                "max_retries": 5,
                "next_retry_at": now + 60,  # First retry after 1 minute
                "artifacts": artifacts,
                "saved_files": saved_files
            }
            queue.append(entry)
            logger.info(f"Enqueued new pending upload for {slug} ({plat.upper()}): {reason}")

        data["queue"] = queue
        self._save_data(data)
        return entry

    def list_items(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Lists items in the queue, optionally filtered by status."""
        data = self._load_data()
        queue = data.get("queue", [])
        if status:
            return [item for item in queue if item.get("status") == status]
        return queue

    def get_item(self, queue_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a single queue entry by ID."""
        for item in self.list_items():
            if item.get("queue_id") == queue_id or item.get("id") == queue_id:
                return item
        return None

    def mark_in_progress(self, queue_id: str) -> bool:
        """Marks a queue item as currently in progress."""
        data = self._load_data()
        for item in data.get("queue", []):
            if item.get("queue_id") == queue_id or item.get("id") == queue_id:
                item["status"] = "in_progress"
                now_iso = time.strftime("%Y-%m-%d %H:%M:%S")
                item["last_attempt"] = now_iso
                item["last_attempt_at"] = now_iso
                self._save_data(data)
                return True
        return False

    def mark_completed(self, slug: str, platform: str) -> bool:
        """Marks a book's pending upload as completed."""
        data = self._load_data()
        plat = "kdp" if platform.lower() in ["kdp", "amazon"] else platform.lower()
        queue = data.get("queue", [])
        updated = False

        now_iso = time.strftime("%Y-%m-%d %H:%M:%S")
        for item in queue:
            if item["slug"] == slug and (item["platform"] == plat or plat == "both"):
                logger.info(f"Upload completed! Resolved pending item {item.get('queue_id')}")
                item["status"] = "completed"
                item["completed_at"] = now_iso
                updated = True

        if updated:
            data["queue"] = queue
            self._save_data(data)
        return updated

    def delete_item(self, queue_id: str) -> bool:
        """Removes an item from the pending queue."""
        data = self._load_data()
        initial_len = len(data.get("queue", []))
        data["queue"] = [
            it for it in data.get("queue", [])
            if it.get("queue_id") != queue_id and it.get("id") != queue_id
        ]
        if len(data["queue"]) != initial_len:
            self._save_data(data)
            return True
        return False

    def mark_failed(self, queue_id: str, error_reason: str = "") -> bool:
        """Marks a queue item back to pending with updated error."""
        data = self._load_data()
        for item in data.get("queue", []):
            if item.get("queue_id") == queue_id or item.get("id") == queue_id:
                item["status"] = "pending"
                if error_reason:
                    item["error_reason"] = error_reason
                    item["failure_reason"] = error_reason
                now_iso = time.strftime("%Y-%m-%d %H:%M:%S")
                item["last_attempt"] = now_iso
                item["last_attempt_at"] = now_iso
                self._save_data(data)
                return True
        return False

    def check_platform_health(self, platform: str = "all", timeout: float = 3.0) -> Dict[str, bool]:
        """
        Probes HTTP reachability of Amazon KDP and/or Flipkart Seller Hub.
        Returns a dict of platform health statuses.
        """
        results = {}
        targets = {}

        if platform.lower() in ["kdp", "amazon"]:
            targets["kdp"] = PLATFORM_HEALTH_URLS["kdp"]
        elif platform.lower() == "flipkart":
            targets["flipkart"] = PLATFORM_HEALTH_URLS["flipkart"]
        else:
            targets = PLATFORM_HEALTH_URLS

        for name, url in targets.items():
            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (PublisheR Health Prober/1.0)"}
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    status_code = getattr(resp, "status", None) or (resp.getcode() if hasattr(resp, "getcode") else 200)
                    results[name] = status_code in [200, 301, 302, 307, 403]
            except urllib.error.HTTPError as e:
                # HTTP errors (like 403 or 401) mean server is reached and responding!
                results[name] = e.code in [200, 301, 302, 401, 403]
            except Exception:
                results[name] = False

        return results

    def is_platform_healthy(self, platform: str) -> bool:
        """Returns True if the given platform is currently reachable."""
        plat = "kdp" if platform.lower() in ["kdp", "amazon"] else platform.lower()
        health = self.check_platform_health(platform=plat)
        return health.get(plat, False) or health.get("internet", False)

    def process_pending_queue(self, force: bool = False) -> Dict[str, Any]:
        """
        Scans all pending items in the queue, checks platform health,
        and auto-dispatches upload jobs for eligible items.
        """
        from uploader.upload_manager import start_upload_job

        pending_items = self.list_items(status="pending")
        if not pending_items:
            return {"status": "empty", "message": "No pending uploads in queue."}

        now = time.time()
        dispatched = []
        skipped = []

        for item in pending_items:
            slug = item["slug"]
            platform = item["platform"]
            queue_id = item["queue_id"]
            next_retry = item.get("next_retry_at", 0)

            # Check if backoff window has elapsed or if forced
            if not force and now < next_retry:
                remaining_sec = int(next_retry - now)
                skipped.append({
                    "queue_id": queue_id,
                    "slug": slug,
                    "reason": f"Waiting for retry backoff window ({remaining_sec}s remaining)"
                })
                continue

            # Check if platform is healthy
            if not self.is_platform_healthy(platform):
                logger.warning(f"Platform {platform.upper()} is currently unreachable. Skipping retry for {slug}.")
                skipped.append({
                    "queue_id": queue_id,
                    "slug": slug,
                    "reason": f"Platform {platform.upper()} is currently unreachable"
                })
                continue

            # Platform is healthy! Dispatch upload
            try:
                self.mark_in_progress(queue_id)
                job_id = start_upload_job(
                    slug=slug,
                    platform=platform,
                    headless=True if not os.environ.get("DISPLAY") else False,
                    auto_advance=True
                )
                dispatched.append({
                    "queue_id": queue_id,
                    "job_id": job_id,
                    "slug": slug,
                    "platform": platform
                })
                logger.info(f"Dispatched auto-retry job {job_id} for pending upload {slug} ({platform})")
            except Exception as e:
                logger.exception(f"Failed to dispatch retry for {slug}: {e}")
                self.mark_failed(queue_id, error_reason=str(e))

        return {
            "status": "success",
            "attempted": len(dispatched) + len(skipped),
            "dispatched_count": len(dispatched),
            "started_jobs": dispatched,
            "dispatched": dispatched,
            "skipped_offline": [s for s in skipped if "unreachable" in s.get("reason", "")],
            "skipped": skipped
        }


# Singleton instance
pending_queue = PendingUploadQueue()
