#!/bin/bash
# Guard script for margin_capture.py --loop
# pgrep liveness guard (primary) + flock same-tick race-breaker (secondary).
# Cron-safe — no duplicates. flock ALONE cannot guard a backgrounded daemon:
# this wrapper holds the lock FD then exits after `nohup ... &`, releasing it,
# so the next cron tick would re-acquire and stack a duplicate. The pgrep check
# is what actually prevents that. (2026-06-01: this leaked 2 live --loop daemons.)
#
# Usage (cron):
#   */5 9-15 * * 1-5 /home/trading_ceo/projects/brahmand/cron/run_margin_capture.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_FILE="$PROJECT_DIR/logs/margin_capture.log"
LOCK_FILE="$PROJECT_DIR/locks/margin_capture.lock"
mkdir -p "$(dirname "$LOCK_FILE")"
PYTHON_BIN="/usr/bin/python3"

exec {LOCK_FD}>"$LOCK_FILE"

if ! flock -n "$LOCK_FD"; then
    exit 0
fi

# Primary guard: bail if a margin_capture daemon is already alive.
if pgrep -f "margin_capture.py --loop" > /dev/null; then
    exit 0
fi

mkdir -p "$PROJECT_DIR/logs"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting margin capture..." >> "$LOG_FILE"
nohup "$PYTHON_BIN" "$PROJECT_DIR/margin_capture.py" --loop >> "$LOG_FILE" 2>&1 &
