#!/bin/bash
# Guard script for risk_monitor.py (1-min cadence)
# Cron triggers this every 1 min. Uses flock for atomic locking — no duplicates.
#
# Usage (cron):
#   */1 9-15 * * 1-5 /home/trading_ceo/brahmand/run_risk_monitor.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="$SCRIPT_DIR/logs/risk_monitor_$(date +%Y%m%d).log"
LOCK_FILE="/tmp/risk_monitor.lock"
PYTHON_BIN="/usr/bin/python3"

exec {LOCK_FD}>"$LOCK_FILE"

if ! flock -n "$LOCK_FD"; then
    exit 0  # Another instance running
fi

mkdir -p "$SCRIPT_DIR/logs"
"$PYTHON_BIN" "$SCRIPT_DIR/risk_monitor.py" >> "$LOG_FILE" 2>&1
