#!/bin/bash
# UNICORN Research Cron — runs LLM debate point generation every 15 min.
# Research is async: generates Advocate/Skeptic arguments via DeepSeek API
# and caches them to disk. The 5-min entry cron reads from cache (sub-second).
#
# Logs to brahmand/logs/unicorn_YYYYMMDD.log (same file as execution path).
#
# Usage (crontab):
#   0,15,30,45 9-15 * * 1-5 /home/trading_ceo/brahmand/cron/run_unicorn_research.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOCK_FILE="$PROJECT_DIR/locks/unicorn_research.lock"
PYTHON_BIN="/usr/bin/python3"

mkdir -p "$(dirname "$LOCK_FILE")"

exec {LOCK_FD}>"$LOCK_FILE"

if ! flock -n "$LOCK_FD"; then
    exit 0  # another instance running — skip
fi

cd "$PROJECT_DIR"

# Load environment (DeepSeek API key from antariksh/.env)
for env in "$PROJECT_DIR/.env" "/home/trading_ceo/antariksh/.env"; do
    if [ -f "$env" ]; then
        set -a; source "$env"; set +a
    fi
done

"$PYTHON_BIN" unicorn_research.py --all
