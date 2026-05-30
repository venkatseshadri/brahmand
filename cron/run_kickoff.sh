#!/bin/bash
# Guard script for kickoff.py (one-shot, ~5-min cadence during market hours)
# Sources antariksh + brahmand .env (matches prior inline cron), then runs kickoff.
#
# Usage (cron):
#   1,6,11,16,21,26,31,36,41,46,51,56 9-15 * * 1-5 /home/trading_ceo/brahmand/cron/run_kickoff.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_FILE="$PROJECT_DIR/logs/kickoff_$(date +%Y%m%d).log"
LOCK_FILE="$PROJECT_DIR/locks/kickoff.lock"
mkdir -p "$(dirname "$LOCK_FILE")" "$PROJECT_DIR/logs"
PYTHON_BIN="/usr/bin/python3"

# Primary guard: skip this tick if a prior kickoff is still running (overrun).
if pgrep -f "kickoff.py" > /dev/null; then
    exit 0
fi

# Source and EXPORT env (antariksh first, then brahmand — matches prior cron).
set -a
[ -f /home/trading_ceo/antariksh/.env ] && . /home/trading_ceo/antariksh/.env
[ -f "$PROJECT_DIR/.env" ] && . "$PROJECT_DIR/.env"
set +a

# Secondary guard: close the race between two near-simultaneous ticks.
exec {LOCK_FD}>"$LOCK_FILE"
if ! flock -n "$LOCK_FD"; then
    exit 0
fi

cd "$PROJECT_DIR"
"$PYTHON_BIN" "$PROJECT_DIR/kickoff.py" >> "$LOG_FILE" 2>&1
