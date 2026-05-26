#!/bin/bash
# Guard script for position_manager.py --bridge (1-min cadence)
# Dispatches to risk_agent_crew (CrewAI LLM path) with P1-P7 fallback.
#
# Usage (cron):
#   */1 9-15 * * 1-5 /home/trading_ceo/brahmand/cron/run_position_manager.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_FILE="$PROJECT_DIR/logs/position_manager_$(date +%Y%m%d).log"
LOCK_FILE="/tmp/position_manager.lock"
PYTHON_BIN="/usr/bin/python3"

# Source and EXPORT environment for DEEPSEEK_API_KEY (needed by risk_agent_crew)
set -a
[ -f "$PROJECT_DIR/.env" ] && . "$PROJECT_DIR/.env"
[ -f /home/trading_ceo/antariksh/.env ] && . /home/trading_ceo/antariksh/.env
set +a

exec {LOCK_FD}>"$LOCK_FILE"

if ! flock -n "$LOCK_FD"; then
    exit 0
fi

mkdir -p "$PROJECT_DIR/logs"
"$PYTHON_BIN" "$PROJECT_DIR/position_manager.py" --bridge >> "$LOG_FILE" 2>&1
