#!/bin/bash
# Thin wrapper — all preflight logic lives in entry_setup.py.
# Cron:
#   1,6,11,16,21,26,31,36,41,46,51,56 9-15 * * 1-5 /home/trading_ceo/projects/brahmand/cron/run_kickoff.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_FILE="$PROJECT_DIR/logs/kickoff_$(date +%Y%m%d).log"
mkdir -p "$PROJECT_DIR/logs"

# Source env
set -a
[ -f /home/trading_ceo/projects/antariksh/.env ] && . /home/trading_ceo/projects/antariksh/.env
[ -f "$PROJECT_DIR/.env" ] && . "$PROJECT_DIR/.env"
set +a

cd "$PROJECT_DIR"

# Singleton guard — bail if a previous entry_setup.py is still running.
# Prevents the pile-up that pegs CPU when a run hangs (load-leak incident 2026-06-01).
if pgrep -f "$PROJECT_DIR/entry_setup.py" >/dev/null 2>&1; then
  echo "$(date '+%F %T') skip: entry_setup.py already running" >> "$LOG_FILE"
  exit 0
fi

/usr/bin/python3 "$PROJECT_DIR/entry_setup.py" >> "$LOG_FILE" 2>&1
