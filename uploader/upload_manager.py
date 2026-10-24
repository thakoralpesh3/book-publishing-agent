"""Upload Job Manager
Coordinates asynchronous background execution of Amazon KDP and Flipkart Seller Hub upload sessions.
Prevents blocking the web server event loop and provides real-time progress tracking.
"""

import time
import uuid
import logging
import threading
from pathlib import Path
from typing import Dict, Any, Optional, List

import config
from uploader.kdp_assistant import KDPAssistant
from uploader.flipkart_assistant import FlipkartAssistant

logger = logging.getLogger("UploadManager")

UPLOAD_JOBS: Dict[str, Dict[str, Any]] = {}

def start_upload_job(
    slug: str,
    platform: str, # "kdp" or "flipkart"
    headless: bool = False,
    auto_advance: bool = True,
    keep_open_seconds: int = 120
) -> str:
    """Launches an upload assistant in a background worker thread and returns job_id."""
    book_dir = config.OUTPUT_DIR / slug
    if not book_dir.exists():
        raise FileNotFoundError(f"Book directory not found for slug '{slug}': {book_dir}")

    job_id = f"job_{platform}_{uuid.uuid4().hex[:8]}"

    job = {
        "job_id": job_id,
        "slug": slug,
        "platform": platform,
        "status": "running",
        "progress": 0,
        "current_step": f"Initializing {platform.upper()} Assistant...",
        "logs": [],
        "start_time": time.time(),
        "end_time": None,
        "result": None,
        "error": None
    }
    UPLOAD_JOBS[job_id] = job

    def _worker():
        logger.info(f"Starting background upload worker for job {job_id} ({platform.upper()})...")
        def _cb(msg: str, pct: int):
            job["logs"].append({"time": time.strftime("%H:%M:%S"), "message": msg})
            job["current_step"] = msg
            if pct >= 0:
                job["progress"] = pct

        try:
            if platform.lower() in ["kdp", "amazon"]:
                assistant = KDPAssistant()
                res = assistant.launch_assisted_session(
                    book_dir=book_dir,
                    headless=headless,
                    progress_cb=_cb,
                    auto_advance=auto_advance,
                    keep_open_seconds=keep_open_seconds
                )
            elif platform.lower() == "flipkart":
                assistant = FlipkartAssistant()
                res = assistant.launch_assisted_session(
                    book_dir=book_dir,
                    headless=headless,
                    progress_cb=_cb,
                    keep_open_seconds=keep_open_seconds
                )
            else:
                raise ValueError(f"Unknown upload platform: '{platform}'")

            if res.get("status") in ["error", "failed"]:
                from uploader.pending_queue import pending_queue
                pending_queue.add_or_update(slug=slug, platform=platform, error_reason=res.get("message", "Upload did not complete"))
                job["status"] = "failed"
                job["error"] = res.get("message")
                job["current_step"] = f"💾 Content saved to pending queue: {res.get('message', '')[:70]}"
            else:
                job["status"] = "completed"
                job["progress"] = 100
                job["result"] = res
                job["current_step"] = f"✅ {platform.upper()} assistant completed successfully."
                from uploader.pending_queue import pending_queue
                pending_queue.mark_completed(slug=slug, platform=platform)
                logger.info(f"Upload job {job_id} completed successfully.")

        except Exception as e:
            logger.exception(f"Error in upload job {job_id}: {e}")
            job["status"] = "failed"
            job["error"] = str(e)
            job["current_step"] = f"💾 Content saved! Auto-enqueued for retry: {str(e)[:70]}"
            job["logs"].append({"time": time.strftime("%H:%M:%S"), "message": f"Fatal error: {e}"})
            job["logs"].append({"time": time.strftime("%H:%M:%S"), "message": "💾 All book contents, interior PDF, cover wrap, and catalog saved in pending queue."})
            try:
                from uploader.pending_queue import pending_queue
                pending_queue.add_or_update(slug=slug, platform=platform, error_reason=str(e))
            except Exception as q_err:
                logger.error(f"Failed to record pending upload: {q_err}")
        finally:
            job["end_time"] = time.time()

    thread = threading.Thread(target=_worker, daemon=True, name=f"UploadThread-{job_id}")
    thread.start()

    return job_id

def get_upload_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves current job status, logs, and progress."""
    return UPLOAD_JOBS.get(job_id)

def list_upload_jobs() -> List[Dict[str, Any]]:
    """Lists all recent upload jobs."""
    return list(UPLOAD_JOBS.values())
