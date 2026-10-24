#!/usr/bin/env bash
# PublisheR AI • 24/7 Mobile Gateway & Cloudflare Tunnel Launcher (Project Chhaya)
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "=================================================================="
echo "    📱 Starting PublisheR AI Mobile Gateway (Project Chhaya)"
echo "    Amazon KDP Agent & Flipkart Book Agent Remote Access"
echo "=================================================================="

# Check python3
if ! command -v python3 &> /dev/null; then
    echo "Python 3 is required but not installed."
    exit 1
fi

# Run the Mobile Gateway Watchdog
python3 mobile_gateway.py
