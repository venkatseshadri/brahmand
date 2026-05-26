#!/bin/bash
# Guard script for pattern_enricher.py --live
# Dual guard: pgrep liveness check + flock atomic lock. Cron-safe — no duplicates.
#
# Usage (cron):
#   */5 9-15 * * 1-5 /home/trading_ceo/brahmand/cron/run_pattern_enricher.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_FILE="$PROJECT_DIR/logs/pattern_enricher.log"
LOCK_FILE="$PROJECT_DIR/locks/pattern_enricher.lock"
mkdir -p "$(dirname "$LOCK_FILE")" "$PROJECT_DIR/logs"
PYTHON_BIN="/usr/bin/python3"

# Primary guard: the daemon is backgrounded and this wrapper exits, so a
# flock held only via inherited FD is released once the daemon closes FDs —
# which let duplicates accumulate. pgrep is the reliable liveness check.
if pgrep -f "pattern_enricher.py --live" > /dev/null; then
    exit 0
fi

# Secondary guard: close the race between two near-simultaneous cron ticks.
exec {LOCK_FD}>"$LOCK_FILE"
if ! flock -n "$LOCK_FD"; then
    exit 0
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting pattern enricher..." >> "$LOG_FILE"
nohup "$PYTHON_BIN" "$PROJECT_DIR/pattern_enricher.py" --live >> "$LOG_FILE" 2>&1 &
