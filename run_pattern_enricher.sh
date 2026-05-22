#!/bin/bash
# Guard script for pattern_enricher.py --live
# Cron triggers this every 5 min. It starts the enricher only if not already running.
# Prevents the 282-process leak that happened May 20.
#
# Usage (cron):
#   */5 9-15 * * 1-5 /home/trading_ceo/brahmand/run_pattern_enricher.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="$SCRIPT_DIR/logs/pattern_enricher.log"
PID_FILE="/tmp/pattern_enricher.pid"
PYTHON_BIN="/usr/bin/python3"

mkdir -p "$SCRIPT_DIR/logs"

# ── Check if already running ──
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        # Process still alive — skip
        exit 0
    else
        # Stale PID file — clean up
        rm -f "$PID_FILE"
    fi
fi

# Also check by process name (belt + suspenders)
if pgrep -f "pattern_enricher.py --live" > /dev/null; then
    exit 0
fi

# ── Start the enricher ──
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting pattern enricher..." >> "$LOG_FILE"
nohup "$PYTHON_BIN" "$SCRIPT_DIR/pattern_enricher.py" --live >> "$LOG_FILE" 2>&1 &
PID=$!
echo $PID > "$PID_FILE"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Started with PID=$PID" >> "$LOG_FILE"
