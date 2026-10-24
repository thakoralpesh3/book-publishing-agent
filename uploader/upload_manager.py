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

            job["status"] = "completed"
            job["progress"] = 100
            job["result"] = res
            job["current_step"] = f"✅ {platform.upper()} assistant completed successfully."
            logger.info(f"Upload job {job_id} completed successfully.")

        except Exception as e:
            logger.exception(f"Error in upload job {job_id}: {e}")
            job["status"] = "failed"
            job["error"] = str(e)
            job["current_step"] = f"❌ Error: {str(e)[:100]}"
            job["logs"].append({"time": time.strftime("%H:%M:%S"), "message": f"Fatal error: {e}"})
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
