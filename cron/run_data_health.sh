#!/bin/bash
# Guard script for data_health.py --alert (one-shot, 5-min cadence during market)
# Propagates data_health's own exit code (non-zero = unhealthy).
#
# Usage (cron):
#   */5 9-15 * * 1-5 /home/trading_ceo/brahmand/cron/run_data_health.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_FILE="$PROJECT_DIR/logs/data_health.log"
LOCK_FILE="$PROJECT_DIR/locks/data_health.lock"
mkdir -p "$(dirname "$LOCK_FILE")" "$PROJECT_DIR/logs"
PYTHON_BIN="/usr/bin/python3"

# Primary guard: skip this tick if a prior check is still running (overrun).
if pgrep -f "data_health.py" > /dev/null; then
    exit 0
fi

# Secondary guard: close the race between two near-simultaneous ticks.
exec {LOCK_FD}>"$LOCK_FILE"
if ! flock -n "$LOCK_FD"; then
    exit 0
fi

cd "$PROJECT_DIR"
"$PYTHON_BIN" "$PROJECT_DIR/data_health.py" --alert >> "$LOG_FILE" 2>&1
