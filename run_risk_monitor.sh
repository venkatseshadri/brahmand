#!/bin/bash
# Guard script for risk_monitor.py (1-min cadence)
# Cron triggers this every 1 min. Skips if already running.
#
# Usage (cron):
#   */1 9-15 * * 1-5 /home/trading_ceo/brahmand/run_risk_monitor.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="$SCRIPT_DIR/logs/risk_monitor_$(date +%Y%m%d).log"
PID_FILE="/tmp/risk_monitor.pid"
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

if pgrep -f "risk_monitor.py" > /dev/null 2>&1; then
    exit 0
fi

# ── Run once and exit ──
echo $BASHPID > "$PID_FILE"
"$PYTHON_BIN" "$SCRIPT_DIR/risk_monitor.py" >> "$LOG_FILE" 2>&1
rm -f "$PID_FILE"
