"""
PublisheR AI • Git Manager & Cloud Synchronization Engine
Handles bidirectional sync, automatic commit generation, and status monitoring.
"""

import os
import subprocess
import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger("GitManager")

import shutil

BASE_DIR = Path(__file__).resolve().parent.parent

# Ensure ~/.local/bin and common user bin directories are in PATH
_user_local_bin = str(Path.home() / ".local" / "bin")
if _user_local_bin not in os.environ.get("PATH", ""):
    os.environ["PATH"] = f"{_user_local_bin}:{os.environ.get('PATH', '')}"

def _find_git_binary() -> str:
    """Finds the git executable across PATH and known user locations."""
    found = shutil.which("git")
    if found:
        return found
    for candidate in [
        str(Path.home() / ".local" / "bin" / "git"),
        "/usr/local/bin/git",
        "/usr/bin/git",
        "/bin/git"
    ]:
        if Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    return "git"

GIT_BIN = _find_git_binary()


class GitManager:
    """Manages Git operations, auto-commits, and GitHub cloud sync."""

    def __init__(self, repo_dir: Optional[Path] = None):
        self.repo_dir = repo_dir or BASE_DIR
        self.git_bin = GIT_BIN

    def _run_git(self, args: List[str], timeout: int = 30) -> subprocess.CompletedProcess:
        """Runs a git command inside the repository directory."""
        return subprocess.run(
            [self.git_bin] + args,
            cwd=str(self.repo_dir),
            capture_output=True,
            text=True,
            timeout=timeout
        )

    def is_git_repo(self) -> bool:
        """Checks if current directory is inside a valid git working tree."""
        res = self._run_git(["rev-parse", "--is-inside-work-tree"])
        return res.returncode == 0 and res.stdout.strip() == "true"

    def get_current_branch(self) -> str:
        """Returns the active branch name or 'main'."""
        if not self.is_git_repo():
            return "none"
        res = self._run_git(["rev-parse", "--abbrev-ref", "HEAD"])
        return res.stdout.strip() if res.returncode == 0 else "main"

    def get_remote_url(self, remote: str = "origin") -> Optional[str]:
        """Gets URL of the specified remote."""
        if not self.is_git_repo():
            return None
        res = self._run_git(["remote", "get-url", remote])
        return res.stdout.strip() if res.returncode == 0 else None

    def get_last_commit(self) -> Dict[str, str]:
        """Returns metadata about the latest commit."""
        if not self.is_git_repo():
            return {}
        res = self._run_git(["log", "-1", "--format=%H|%s|%an|%cd", "--date=iso"])
        if res.returncode == 0 and res.stdout.strip():
            parts = res.stdout.strip().split("|")
            if len(parts) >= 4:
                return {
                    "hash": parts[0][:7],
                    "full_hash": parts[0],
                    "message": parts[1],
                    "author": parts[2],
                    "date": parts[3]
                }
        return {}

    def get_status(self) -> Dict[str, Any]:
        """Returns comprehensive git working tree and remote synchronization status."""
        if not self.is_git_repo():
            return {
                "initialized": False,
                "branch": "none",
                "clean": True,
                "changed_files": [],
                "untracked_files": [],
                "modified_files": [],
                "deleted_files": [],
                "remote_url": None,
                "last_commit": {}
            }

        branch = self.get_current_branch()
        remote_url = self.get_remote_url("origin")
        last_commit = self.get_last_commit()

        # Check working tree changes
        status_res = self._run_git(["status", "--porcelain"])
        changed = []
        untracked = []
        modified = []
        deleted = []

        if status_res.returncode == 0 and status_res.stdout:
            for raw_line in status_res.stdout.splitlines():
                if len(raw_line) < 4:
                    continue
                code = raw_line[:2].strip()
                path = raw_line[3:].strip()
                changed.append({"status": code, "path": path})
                if "?" in code:
                    untracked.append(path)
                elif "D" in code:
                    deleted.append(path)
                else:
                    modified.append(path)

        # Check ahead/behind count vs origin
        ahead = 0
        behind = 0
        if remote_url:
            count_res = self._run_git(["rev-list", "--left-right", "--count", f"HEAD...origin/{branch}"])
            if count_res.returncode == 0 and count_res.stdout.strip():
                parts = count_res.stdout.strip().split()
                if len(parts) == 2:
                    ahead, behind = int(parts[0]), int(parts[1])

        return {
            "initialized": True,
            "branch": branch,
            "clean": len(changed) == 0,
            "total_changes": len(changed),
            "changed_files": changed,
            "modified_files": modified,
            "untracked_files": untracked,
            "deleted_files": deleted,
            "remote_url": remote_url,
            "ahead": ahead,
            "behind": behind,
            "last_commit": last_commit
        }

    def generate_auto_commit_message(self, status: Dict[str, Any]) -> str:
        """Generates a descriptive commit message based on modified files."""
        mod = status.get("modified_files", [])
        untracked = status.get("untracked_files", [])
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        key_components = []
        for path in mod + untracked:
            top_level = path.split("/")[0] if "/" in path else path
            if top_level not in key_components:
                key_components.append(top_level)

        comp_str = ", ".join(key_components[:4]) if key_components else "codebase"
        return f"chore(antigravity): auto-sync updates ({comp_str}) at {now_str}"

    def sync(
        self,
        message: Optional[str] = None,
        branch: Optional[str] = None,
        remote: str = "origin",
        pull_first: bool = False
    ) -> Dict[str, Any]:
        """
        Executes a full Git sync:
        1. Checks status.
        2. Optionally pulls latest changes.
        3. Stages all changes respecting .gitignore.
        4. Commits with custom or auto-generated message.
        5. Pushes to the remote branch.
        """
        if not self.is_git_repo():
            return {
                "success": False,
                "error": "Not a git repository. Initialize git first."
            }

        cur_branch = branch or self.get_current_branch()
        if cur_branch == "HEAD" or not cur_branch:
            cur_branch = "main"

        # Pull if requested
        if pull_first:
            self._run_git(["pull", remote, cur_branch])

        # Check current status
        status = self.get_status()

        # If nothing has changed and we are not ahead, we are already synced
        if status["clean"] and status.get("ahead", 0) == 0:
            return {
                "success": True,
                "synced": True,
                "status": "clean",
                "message": "Repository is up to date, working tree clean.",
                "branch": cur_branch,
                "last_commit": status.get("last_commit")
            }

        # Stage files if there are working tree changes
        if not status["clean"]:
            add_res = self._run_git(["add", "-A"])
            if add_res.returncode != 0:
                return {
                    "success": False,
                    "error": f"Failed to stage changes: {add_res.stderr.strip()}"
                }

            # Generate commit message if not provided
            commit_msg = message or self.generate_auto_commit_message(status)
            commit_res = self._run_git(["commit", "-m", commit_msg])
            if commit_res.returncode != 0 and "nothing to commit" not in commit_res.stdout:
                return {
                    "success": False,
                    "error": f"Failed to commit: {commit_res.stderr.strip()}"
                }

        # Push to remote
        remote_url = self.get_remote_url(remote)
        if not remote_url:
            return {
                "success": True,
                "synced": False,
                "warning": f"Committed locally, but no remote '{remote}' configured to push to.",
                "branch": cur_branch,
                "last_commit": self.get_last_commit()
            }

        push_res = self._run_git(["push", "-u", remote, cur_branch], timeout=60)
        if push_res.returncode != 0:
            return {
                "success": False,
                "error": f"Push failed: {push_res.stderr.strip()}",
                "branch": cur_branch,
                "last_commit": self.get_last_commit()
            }

        new_status = self.get_status()
        return {
            "success": True,
            "synced": True,
            "branch": cur_branch,
            "remote": remote,
            "remote_url": remote_url,
            "last_commit": new_status.get("last_commit"),
            "message": f"Successfully synchronized and pushed to {remote}/{cur_branch}"
        }


if __name__ == "__main__":
    gm = GitManager()
    import json
    print(json.dumps(gm.get_status(), indent=2))
