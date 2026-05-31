#!/bin/bash
# Thin wrapper — all preflight logic lives in entry_setup.py.
# Cron:
#   1,6,11,16,21,26,31,36,41,46,51,56 9-15 * * 1-5 /home/trading_ceo/brahmand/cron/run_kickoff.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_FILE="$PROJECT_DIR/logs/kickoff_$(date +%Y%m%d).log"
mkdir -p "$PROJECT_DIR/logs"

# Source env
set -a
[ -f /home/trading_ceo/antariksh/.env ] && . /home/trading_ceo/antariksh/.env
[ -f "$PROJECT_DIR/.env" ] && . "$PROJECT_DIR/.env"
set +a

cd "$PROJECT_DIR"
/usr/bin/python3 "$PROJECT_DIR/entry_setup.py" >> "$LOG_FILE" 2>&1
