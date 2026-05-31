#!/bin/bash
# Run entry_setup.py on 5-min cadence during market hours.
# entry_setup.py handles ALL preflight: lock, state, market check, order check.
# kickoff.py is called internally only when all gates pass.
#
# Cron:
#   1,6,11,16,21,26,31,36,41,46,51,56 9-15 * * 1-5 /home/trading_ceo/brahmand/cron/run_kickoff.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_FILE="$PROJECT_DIR/logs/kickoff_$(date +%Y%m%d).log"
mkdir -p "$PROJECT_DIR/logs"

# Primary guard: skip if a prior kickoff/entry_setup is still running.
if pgrep -f "entry_setup.py\|kickoff.py" > /dev/null; then
    exit 0
fi

# Source env
set -a
[ -f /home/trading_ceo/antariksh/.env ] && . /home/trading_ceo/antariksh/.env
[ -f "$PROJECT_DIR/.env" ] && . "$PROJECT_DIR/.env"
set +a

cd "$PROJECT_DIR"

/usr/bin/python3 "$PROJECT_DIR/entry_setup.py" >> "$LOG_FILE" 2>&1
