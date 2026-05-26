#!/bin/bash
# Guard script for pattern_enricher.py --live
# Uses flock for atomic locking. Cron-safe — no duplicates.
#
# Usage (cron):
#   */5 9-15 * * 1-5 /home/trading_ceo/brahmand/cron/run_pattern_enricher.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_FILE="$PROJECT_DIR/logs/pattern_enricher.log"
LOCK_FILE="$PROJECT_DIR/locks/pattern_enricher.lock"
mkdir -p "$(dirname "$LOCK_FILE")"
PYTHON_BIN="/usr/bin/python3"

exec {LOCK_FD}>"$LOCK_FILE"

if ! flock -n "$LOCK_FD"; then
    exit 0
fi

mkdir -p "$PROJECT_DIR/logs"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting pattern enricher..." >> "$LOG_FILE"
nohup "$PYTHON_BIN" "$PROJECT_DIR/pattern_enricher.py" --live >> "$LOG_FILE" 2>&1 &
