#!/bin/bash
# Position Research Cron — runs discretionary (morph/roll/tighten) assessment for
# every open trade every 15 min and caches it. The 1-min run_bridge reads from
# cache (sub-second) and applies it; protective triggers (SL/TP/floor/EOD) are
# evaluated live by run_bridge every cycle and are never cached here.
#
# Today the assessment is deterministic; position_research._llm_refine is the seam
# where an LLM will later optimise shift/morph timing and SL/TP levels.
#
# Usage (crontab):
#   0,15,30,45 9-15 * * 1-5 /home/trading_ceo/projects/brahmand/cron/run_position_research.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOCK_FILE="$PROJECT_DIR/locks/position_research.lock"
PYTHON_BIN="/usr/bin/python3"

mkdir -p "$(dirname "$LOCK_FILE")"

exec {LOCK_FD}>"$LOCK_FILE"

if ! flock -n "$LOCK_FD"; then
    exit 0  # another instance running — skip
fi

cd "$PROJECT_DIR"

# Load environment (DeepSeek API key from antariksh/.env) — for the future LLM seam.
for env in "$PROJECT_DIR/.env" "/home/trading_ceo/projects/antariksh/.env"; do
    if [ -f "$env" ]; then
        set -a; source "$env"; set +a
    fi
done

"$PYTHON_BIN" position_research.py --all
