#!/bin/bash
# Guard script for margin_capture.py --loop
# Cron triggers this every 5 min. Starts capture only if not already running.
#
# Usage (cron):
#   */5 9-15 * * 1-5 /home/trading_ceo/brahmand/run_margin_capture.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="$SCRIPT_DIR/logs/margin_capture.log"
PID_FILE="/tmp/margin_capture.pid"
PYTHON_BIN="/usr/bin/python3"

mkdir -p "$SCRIPT_DIR/logs"

# ── Check if already running ──
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        exit 0
    else
        rm -f "$PID_FILE"
    fi
fi

if pgrep -f "margin_capture.py --loop" > /dev/null 2>&1; then
    exit 0
fi

# ── Start the capture ──
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting margin capture..." >> "$LOG_FILE"
nohup "$PYTHON_BIN" "$SCRIPT_DIR/margin_capture.py" --loop >> "$LOG_FILE" 2>&1 &
PID=$!
echo $PID > "$PID_FILE"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Started with PID=$PID" >> "$LOG_FILE"
