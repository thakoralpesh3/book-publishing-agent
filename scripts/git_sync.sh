#!/usr/bin/env bash
# PublisheR AI • Shell wrapper for Git synchronization
set -e
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
python3 "$PROJECT_DIR/scripts/git_sync.py" "$@"
