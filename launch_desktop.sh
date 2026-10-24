#!/usr/bin/env bash
# PublisheR AI Desktop Launcher Script
set -e

DIR="/home/alpesh/book-publishing-agent"
cd "$DIR"

PORT=8550

is_port_in_use() {
    python3 -c "import socket; s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.settimeout(0.5); exit(0 if s.connect_ex(('127.0.0.1', $PORT)) == 0 else 1)"
}

if is_port_in_use; then
    # Already running, notify and open browser
    if command -v notify-send &>/dev/null; then
        notify-send -i "$DIR/assets/publisher_icon.svg" "PublisheR AI" "Studio is running! Opening browser..."
    fi
    xdg-open "http://127.0.0.1:$PORT" &>/dev/null &
else
    # Start the server in background
    if command -v notify-send &>/dev/null; then
        notify-send -i "$DIR/assets/publisher_icon.svg" "PublisheR AI" "Starting Amazon & Flipkart Publishing Studio..."
    fi
    
    # Launch in background
    nohup python3 "$DIR/main.py" serve --port $PORT --no-browser >> "$DIR/data/desktop_launch.log" 2>&1 &
    
    # Wait up to 6 seconds for port to open
    for i in {1..12}; do
        if is_port_in_use; then
            break
        fi
        sleep 0.5
    done
    
    xdg-open "http://127.0.0.1:$PORT" &>/dev/null &
fi
