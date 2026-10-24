#!/usr/bin/env python3
"""
PublisheR AI • Git Sync Script
Run anytime to auto-stage, commit, and push updates to GitHub.
"""

import sys
import argparse
from pathlib import Path

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.git_manager import GitManager


def main():
    parser = argparse.ArgumentParser(description="Synchronize PublisheR AI with GitHub")
    parser.add_argument("-m", "--message", type=str, default=None, help="Commit message (auto-generated if omitted)")
    parser.add_argument("--status-only", action="store_true", help="Print git status without pushing")
    parser.add_argument("--pull", action="store_true", help="Pull upstream before pushing")
    args = parser.parse_args()

    gm = GitManager(BASE_DIR)
    status = gm.get_status()

    if not status["initialized"]:
        print("❌ Error: Directory is not a git repository.")
        sys.exit(1)

    print(f"📦 Repository Branch: {status['branch']}")
    print(f"🌐 Remote: {status['remote_url'] or 'None'}")
    print(f"📊 Working Tree: {'Clean' if status['clean'] else f'{status[\"total_changes\"]} uncommitted changes'}")

    if args.status_only:
        if not status["clean"]:
            print("\nUncommitted Files:")
            for cf in status["changed_files"]:
                print(f"  [{cf['status']}] {cf['path']}")
        sys.exit(0)

    print("\n🚀 Synchronizing with GitHub...")
    res = gm.sync(message=args.message, pull_first=args.pull)

    if res.get("success"):
        print(f"✅ {res.get('message')}")
        if res.get("last_commit"):
            lc = res["last_commit"]
            print(f"📌 Latest Commit: {lc.get('hash')} - \"{lc.get('message')}\" by {lc.get('author')}")
    else:
        print(f"❌ Sync failed: {res.get('error')}")
        sys.exit(1)


if __name__ == "__main__":
    main()
