#!/bin/bash
# Guard script for position_manager.py --bridge (1-min cadence)
# Dispatches to risk_agent_crew (CrewAI LLM path) with P1-P7 fallback.
#
# Usage (cron):
#   */1 9-15 * * 1-5 /home/trading_ceo/brahmand/run_position_manager.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="$SCRIPT_DIR/logs/position_manager_$(date +%Y%m%d).log"
LOCK_FILE="/tmp/position_manager.lock"
PYTHON_BIN="/usr/bin/python3"

exec {LOCK_FD}>"$LOCK_FILE"

if ! flock -n "$LOCK_FD"; then
    exit 0  # Another instance running
fi

mkdir -p "$SCRIPT_DIR/logs"
"$PYTHON_BIN" "$SCRIPT_DIR/position_manager.py" --bridge >> "$LOG_FILE" 2>&1
