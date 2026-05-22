#!/bin/bash
# Guard script for pattern_enricher.py --live
# Uses flock for atomic locking. Cron-safe — no duplicates.
#
# Usage (cron):
#   */5 9-15 * * 1-5 /home/trading_ceo/brahmand/run_pattern_enricher.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="$SCRIPT_DIR/logs/pattern_enricher.log"
LOCK_FILE="/tmp/pattern_enricher.lock"
PYTHON_BIN="/usr/bin/python3"

exec {LOCK_FD}>"$LOCK_FILE"

if ! flock -n "$LOCK_FD"; then
    exit 0  # Already running
fi

mkdir -p "$SCRIPT_DIR/logs"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting pattern enricher..." >> "$LOG_FILE"
nohup "$PYTHON_BIN" "$SCRIPT_DIR/pattern_enricher.py" --live >> "$LOG_FILE" 2>&1 &
# flock is released when this shell exits — that's intentional.
# The enricher is long-lived; the lock prevents double-launch,
# not double-execution. Next cron tick will fail flock and skip.
