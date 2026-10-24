#!/usr/bin/env bash
# ==============================================================================
# PublisheR AI • Amazon KDP & Flipkart Book Publishing Agent Launcher
# ==============================================================================

DIR="/home/alpesh/book-publishing-agent"
cd "$DIR"

PORT=8550
URL="http://127.0.0.1:$PORT"

# Clean formatting colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
AMBER='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "${BLUE}${BOLD}======================================================================${NC}"
echo -e "${AMBER}${BOLD}  📚  PUBLISHER AI — AMAZON KDP & FLIPKART BOOK PUBLISHING AGENT  ${NC}"
echo -e "${BLUE}${BOLD}======================================================================${NC}"
echo -e "  🌐 Local Web Studio:     ${CYAN}${URL}${NC}"
echo -e "  📱 Mobile Remote Access:  ${GREEN}Cloudflare 24/7 HTTPS Quick Tunnel${NC}"
echo -e "${BLUE}----------------------------------------------------------------------${NC}"

# Check Python3
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: Python 3 is not installed or not in PATH."
    read -p "Press Enter to exit..."
    exit 1
fi

# Ensure port is clean or active
if python3 -c "import socket; s = socket.socket(); s.settimeout(0.5); exit(0 if s.connect_ex(('127.0.0.1', $PORT)) == 0 else 1)" 2>/dev/null; then
    echo -e "${GREEN}⚡ Server is already active on port $PORT! Opening browser...${NC}"
    if command -v firefox &>/dev/null; then
        firefox --new-window "$URL" &>/dev/null &
    else
        xdg-open "$URL" &>/dev/null &
    fi
    echo ""
    echo -e "${BOLD}Server running at ${URL}.${NC}"
    echo "Press Enter to exit this launcher window (server stays running in background)..."
    read -r
    exit 0
fi

# Notify desktop
if command -v notify-send &>/dev/null; then
    notify-send -i "$DIR/assets/publisher_icon.svg" "PublisheR AI" "Starting Amazon & Flipkart Publishing Studio..." 2>/dev/null || true
fi

echo -e "${GREEN}🚀 Initializing Studio Engine & Cloud Tunnel on port $PORT...${NC}"
echo -e "Web browser will open automatically once the engine is ready."
echo ""

# Run the master server (which manages health-check browser launch & mobile tunnel)
exec python3 "$DIR/main.py" serve --port "$PORT"
