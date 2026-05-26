#!/bin/bash
# Guard script for margin_capture.py --loop
# Uses flock for atomic locking. Cron-safe — no duplicates.
#
# Usage (cron):
#   */5 9-15 * * 1-5 /home/trading_ceo/brahmand/cron/run_margin_capture.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_FILE="$PROJECT_DIR/logs/margin_capture.log"
LOCK_FILE="/tmp/margin_capture.lock"
PYTHON_BIN="/usr/bin/python3"

exec {LOCK_FD}>"$LOCK_FILE"

if ! flock -n "$LOCK_FD"; then
    exit 0
fi

mkdir -p "$PROJECT_DIR/logs"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting margin capture..." >> "$LOG_FILE"
nohup "$PYTHON_BIN" "$PROJECT_DIR/margin_capture.py" --loop >> "$LOG_FILE" 2>&1 &
