#!/usr/bin/env bash
# ==============================================================================
# PublisheR AI - Autonomous Headless Background Runner
# Executes after Aradhya AI, YouTube Shorts, and Social Media agents finish.
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Activate virtualenv if present
if [ -f "$SCRIPT_DIR/.venv/bin/activate" ]; then
    source "$SCRIPT_DIR/.venv/bin/activate"
fi

export DISPLAY="${DISPLAY:-:0}"
export XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}"

# If --watch flag passed, run proactive sentry
if [ "$1" == "--watch" ]; then
    shift
    exec python3 "$SCRIPT_DIR/main.py" watch-and-run "$@"
else
    exec python3 "$SCRIPT_DIR/main.py" run-background "$@"
fi
