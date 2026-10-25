"""
PublisheR AI • Autonomous Git & GitHub Auto-Sync Watcher
Monitors repository filesystem changes in real-time, debounces file write batches,
and automatically commits and pushes all Antigravity and user modifications to GitHub.
"""

import os
import time
import threading
import logging
from pathlib import Path
from typing import Optional, Callable, Dict, Any, List

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileSystemEvent
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    FileSystemEventHandler = object  # type: ignore

from core.git_manager import GitManager

logger = logging.getLogger("GitAutoSyncWatcher")

DEFAULT_DEBOUNCE_SECONDS = 10.0

# Files and directories to strictly ignore during file monitoring
IGNORE_PATTERNS = {
    ".git",
    "output",
    "data",
    "__pycache__",
    ".pytest_cache",
    ".idea",
    ".vscode",
    "bin",
    ".env",
    ".tmp",
    "*.log",
    "*.pyc"
}


def should_ignore_path(rel_path: str) -> bool:
    """Returns True if the file path should be ignored by the git watcher."""
    normalized = rel_path.replace("\\", "/").strip("/")
    parts = normalized.split("/")

    # Check top-level directories or directory components
    for part in parts:
        if part in {".git", "output", "data", "__pycache__", ".pytest_cache", "bin", ".idea", ".vscode"}:
            return True

    filename = parts[-1] if parts else ""
    # Check exact filenames and patterns
    if filename == ".env" or filename.startswith(".env."):
        return True
    if filename.endswith(".log") or filename.endswith(".tmp") or filename.endswith(".pyc") or filename == ".DS_Store":
        return True
    if filename == "mobile_qr.png":
        return True

    return False


if WATCHDOG_AVAILABLE:
    class _RepoChangeHandler(FileSystemEventHandler):
        """Watchdog event handler that debounces file modification events."""

        def __init__(self, watcher: "GitAutoSyncWatcher"):
            super().__init__()
            self.watcher = watcher

        def on_any_event(self, event: FileSystemEvent):
            if event.is_directory:
                return

            try:
                rel = os.path.relpath(event.src_path, str(self.watcher.repo_dir))
                if should_ignore_path(rel):
                    return
                # Register meaningful change
                self.watcher.on_file_changed(rel, event.event_type)
            except Exception as e:
                logger.debug(f"Error handling event for {event.src_path}: {e}")
else:
    class _RepoChangeHandler:  # type: ignore
        pass


class GitAutoSyncWatcher:
    """
    Supervises the repository for filesystem changes made by Antigravity or local processes,
    debounces bursts of edits, and automatically pushes updates to GitHub.
    """

    def __init__(
        self,
        repo_dir: Optional[Path] = None,
        debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS,
        on_sync_callback: Optional[Callable[[Dict[str, Any]], None]] = None
    ):
        from config import BASE_DIR
        self.repo_dir = Path(repo_dir or BASE_DIR).resolve()
        self.debounce_seconds = debounce_seconds
        self.on_sync_callback = on_sync_callback

        self.git_manager = GitManager(self.repo_dir)
        self.lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None
        self._running = False
        self._observer: Optional[Any] = None
        self._poll_thread: Optional[threading.Thread] = None
        self._recent_changes: List[str] = []
        self._last_change_time = 0.0

    @property
    def is_running(self) -> bool:
        return self._running

    def on_file_changed(self, rel_path: str, event_type: str = "modified"):
        """Called whenever a relevant non-ignored file is modified, created, or deleted."""
        with self.lock:
            self._last_change_time = time.time()
            if rel_path not in self._recent_changes:
                self._recent_changes.append(rel_path)

            logger.info(f"📝 Detected edit in '{rel_path}' ({event_type}). Debouncing auto-sync ({self.debounce_seconds}s)...")

            # Cancel existing pending timer and reset
            if self._timer and self._timer.is_alive():
                self._timer.cancel()

            self._timer = threading.Timer(self.debounce_seconds, self._execute_debounced_sync)
            self._timer.daemon = True
            self._timer.start()

    def _execute_debounced_sync(self):
        """Fires after debounce window with no further file writes."""
        with self.lock:
            pending_files = list(self._recent_changes)
            self._recent_changes.clear()

        logger.info(f"⚡ Debounce window elapsed. Evaluating Git working tree ({len(pending_files)} files modified)...")
        self.trigger_sync_now()

    def trigger_sync_now(self, custom_message: Optional[str] = None) -> Dict[str, Any]:
        """Performs immediate evaluation and synchronization to GitHub."""
        try:
            status = self.git_manager.get_status()
            if not status.get("initialized"):
                logger.warning("Git repository is not initialized. Skipping auto-sync.")
                return {"success": False, "error": "Not initialized"}

            # If clean and not ahead of remote, nothing to sync
            if status.get("clean") and status.get("ahead", 0) == 0:
                logger.debug("Working tree clean and synchronized with origin. No sync needed.")
                return {"success": True, "synced": True, "message": "Already up to date."}

            logger.info(f"🚀 Auto-syncing Antigravity changes to GitHub ({status.get('total_changes', 0)} changes)...")
            res = self.git_manager.sync(
                message=custom_message,
                pull_first=True
            )

            if res.get("success"):
                commit_info = res.get("last_commit", {})
                hash_str = commit_info.get("hash", "")
                msg_str = commit_info.get("message", "")
                logger.info(f"✅ Successfully auto-pushed to GitHub: [{hash_str}] {msg_str}")
            else:
                logger.warning(f"⚠️ Auto-sync to GitHub encountered issue: {res.get('error') or res.get('warning')}")

            if self.on_sync_callback:
                try:
                    self.on_sync_callback(res)
                except Exception as cb_err:
                    logger.debug(f"Sync callback error: {cb_err}")

            return res

        except Exception as e:
            logger.error(f"Error executing auto-sync: {e}")
            return {"success": False, "error": str(e)}

    def _polling_worker(self):
        """Secondary background polling thread that acts as a failsafe every 30s."""
        logger.info("🛡️ Failsafe git polling watcher active.")
        while self._running:
            time.sleep(30)
            if not self._running:
                break
            try:
                # If there are changes that were not captured by inotify, sync them
                status = self.git_manager.get_status()
                if not status.get("clean") or status.get("ahead", 0) > 0:
                    now = time.time()
                    # Only trigger if quiet for at least debounce window
                    if now - self._last_change_time >= self.debounce_seconds:
                        logger.info("🔍 Polling detected uncommitted changes. Auto-syncing to GitHub...")
                        self.trigger_sync_now()
            except Exception as pe:
                logger.debug(f"Error in git watcher polling worker: {pe}")

    def start(self):
        """Starts real-time monitoring and background auto-sync."""
        if self._running:
            return

        self._running = True

        # 1. Start Watchdog Observer if available
        if WATCHDOG_AVAILABLE:
            try:
                self._observer = Observer()
                handler = _RepoChangeHandler(self)
                self._observer.schedule(handler, str(self.repo_dir), recursive=True)
                self._observer.daemon = True
                self._observer.start()
                logger.info(f"👀 Real-time filesystem watcher active on {self.repo_dir}")
            except Exception as we:
                logger.warning(f"Could not initialize watchdog observer: {we}. Falling back to polling.")
                self._observer = None

        # 2. Start polling fallback thread
        self._poll_thread = threading.Thread(target=self._polling_worker, daemon=True)
        self._poll_thread.start()
        logger.info(f"🚀 GitAutoSyncWatcher started for {self.repo_dir} (Debounce: {self.debounce_seconds}s)")

    def stop(self):
        """Stops the watcher cleanly."""
        self._running = False
        with self.lock:
            if self._timer and self._timer.is_alive():
                self._timer.cancel()

        if self._observer:
            try:
                self._observer.stop()
                self._observer.join(timeout=2.0)
            except Exception:
                pass
            self._observer = None

        logger.info("GitAutoSyncWatcher stopped.")


# Global singleton watcher instance
git_watcher = GitAutoSyncWatcher()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    print("Starting standalone GitAutoSyncWatcher...")
    w = GitAutoSyncWatcher()
    w.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        w.stop()
        print("Stopped.")
