#!/bin/bash
# Pre-market cleanup — kills zombie data_capture/aggregator processes
# and releases DuckDB file locks from previous sessions.
# 
# Runs at 06:58 (before token_refresh) ahead of 09:14 data capture start.
# Idempotent — safe to run multiple times.

set -euo pipefail

LOG="/home/trading_ceo/antariksh/logs/cleanup_zombies.log"
exec >>"$LOG" 2>&1

# ── Refuse to run during market hours ──
# Both pkill -9 and fuser -k are SIGKILL with no graceful stop; running this
# mid-session would hard-kill the live capture writer and force DuckDB recovery.
NOW=$(date +%H%M)
if [ "$NOW" -ge 900 ] && [ "$NOW" -le 1540 ]; then
    echo "[$(date)] Market hours ($NOW) — refusing to run destructive cleanup."
    exit 0
fi

echo "[$(date)] Pre-market zombie cleanup starting..."

# ── Kill all data capture + aggregator processes ──
KILLED=0
for pattern in "data_capture_v3.1_duckdb" "data_capture_v4_queue_aggregator" "varaha_main"; do
    PIDS=$(pgrep -f "$pattern" 2>/dev/null || true)
    if [ -n "$PIDS" ]; then
        echo "[$(date)] Killing $pattern: $PIDS"
        pkill -9 -f "$pattern" 2>/dev/null || true
        KILLED=$((KILLED + $(echo "$PIDS" | wc -w)))
    fi
done

# ── Release DuckDB file locks (fuser -k kills lock holders) ──
for DB in \
    /home/trading_ceo/python-trader/varaha/data/varaha_data.duckdb \
    /home/trading_ceo/python-trader/varaha/data/varaha_data_sensex.duckdb \
    /home/trading_ceo/python-trader/varaha/data/market_data_multitf.duckdb \
; do
    if [ -f "$DB" ]; then
        fuser -k "$DB" 2>/dev/null && echo "[$(date)] Released lock on $DB" || true
    fi
done

# ── Clean stale lock/pid files from project lock dirs ──
find /home/trading_ceo/antariksh/locks -maxdepth 1 \( -name "*.lock" -o -name "*.pid" \) \
    -mmin +60 -delete 2>/dev/null || true
find /home/trading_ceo/brahmand/locks -maxdepth 1 \( -name "*.lock" -o -name "*.pid" \) \
    -mmin +60 -delete 2>/dev/null || true

# ── Verify DuckDBs are writable ──
for DB in \
    /home/trading_ceo/python-trader/varaha/data/varaha_data.duckdb \
    /home/trading_ceo/python-trader/varaha/data/varaha_data_sensex.duckdb \
    /home/trading_ceo/python-trader/varaha/data/market_data_multitf.duckdb \
; do
    if python3 -c "import duckdb; duckdb.connect('$DB').close()" 2>/dev/null; then
        echo "[$(date)] $DB: writable"
    else
        echo "[$(date)] ⚠️  $DB: NOT WRITABLE — lock conflict!"
    fi
done

# ── Verify Redis is alive (per-index keys: v3_ohlcv_queue_NIFTY, _SENSEX) ──
if redis-cli ping 2>/dev/null | grep -q PONG; then
    echo "[$(date)] Redis: running"
else
    echo "[$(date)] ⚠️  Redis: NOT running!"
fi

echo "[$(date)] Cleanup complete — $KILLED processes killed"
