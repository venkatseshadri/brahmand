#!/usr/bin/env python3
"""
Data Pipeline Health Monitor — checks v3.1, v4, Redis for NULLs/empties.

Runs every 5 min via cron. Silent when healthy. Logs warnings when:
  - Redis indicators have NULL values
  - v3.1 DuckDB NULL% spikes above baseline
  - v4 bars stop updating (stale data)
  - Redis queue stops growing (capture died)

During market hours (9:15–15:30 IST), uses Redis queue as primary data
source to avoid DuckDB lock contention with the capture process. Falls
back to DuckDB only after hours when capture is not running.

Usage:
  python3 data_health.py              # Quick health check
  python3 data_health.py --alert      # Returns non-zero exit code if unhealthy
"""

import sys, json, os, time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Tuple

V31_DB = Path("/home/trading_ceo/python-trader/varaha/data/varaha_data.duckdb")
V31_SENSEX_DB = Path(
    "/home/trading_ceo/python-trader/varaha/data/varaha_data_sensex.duckdb"
)
V4_NIFTY_DB = Path(
    "/home/trading_ceo/python-trader/varaha/data/market_data_multitf_nifty.duckdb"
)
V4_SENSEX_DB = Path(
    "/home/trading_ceo/python-trader/varaha/data/market_data_multitf_sensex.duckdb"
)
STATE_FILE = Path(__file__).parent / "data" / "data_health_state.json"

IST = timezone(timedelta(hours=5, minutes=30))

BASELINE_NULL_MAX = {
    "ema_5": 25.0,
    "ema_20": 35.0,
    "ema_50": 40.0,
    "rsi": 30.0,
    "adx": 30.0,
    "atr": 30.0,
    "supertrend_direction": 30.0,
}

STALE_V31_MIN = 5
STALE_V4_MIN = 5
STALE_REDIS_MIN = 5

REQUIRED_REDIS_KEYS = [
    "ema5",
    "ema20",
    "ema50",
    "rsi",
    "adx",
    "atr",
    "st_direction",
    "bb_pct_b",
]

REDIS_TO_DB_KEY = {
    "ema5": "ema_5",
    "ema20": "ema_20",
    "ema50": "ema_50",
    "rsi": "rsi",
    "adx": "adx",
    "atr": "atr",
    "st_direction": "supertrend_direction",
    "bb_pct_b": "bb_pct_b",
}


def _is_market_hours() -> bool:
    now = datetime.now(IST)
    t = now.hour * 60 + now.minute
    weekday = now.weekday()
    return weekday < 5 and 555 <= t <= 930


def _check_v31_via_redis() -> Tuple[bool, list]:
    """Check v3.1 health via Redis queue (lock-free, market hours only)."""
    warnings = []
    try:
        import redis as rds

        r = rds.Redis(host="localhost", port=6379, db=0, decode_responses=True)
        r.ping()

        for queue_key, index in [
            ("v3_ohlcv_queue_NIFTY", "NIFTY"),
            ("v3_ohlcv_queue_SENSEX", "SENSEX"),
        ]:
            n = r.llen(queue_key)
            if n == 0:
                warnings.append(
                    f"v3.1 [{index}]: Redis queue empty — capture may not be running"
                )
                continue

            latest_raw = r.lindex(queue_key, 0)
            if not latest_raw:
                continue
            latest = json.loads(latest_raw)

            ts = latest.get("timestamp")
            if ts:
                try:
                    t = datetime.fromisoformat(ts)
                    age = (datetime.now() - t).total_seconds() / 60
                    if age > STALE_V31_MIN:
                        warnings.append(
                            f"v3.1 [{index}]: stale — last bar {age:.0f} min ago"
                        )
                except ValueError:
                    warnings.append(f"v3.1 [{index}]: invalid timestamp: {ts}")

            sample_size = min(n, 100)
            bars_raw = r.lrange(queue_key, 0, sample_size - 1)
            all_bars = [json.loads(b) for b in bars_raw]
            bars = [
                b
                for b in all_bars
                if any(b.get(k) is not None for k in REQUIRED_REDIS_KEYS)
            ]

            if not bars:
                warnings.append(
                    f"v3.1 [{index}]: all {len(all_bars)} sampled bars have NULL indicators"
                )
                continue

            for redis_key, db_key in REDIS_TO_DB_KEY.items():
                null_count = sum(1 for b in bars if b.get(redis_key) is None)
                max_pct = BASELINE_NULL_MAX.get(db_key, 30.0)
                pct = round(null_count / len(bars) * 100, 1)
                if pct > max_pct:
                    warnings.append(
                        f"v3.1 [{index}] {db_key}: {pct}% NULL in last {len(bars)} bars (limit: {max_pct}%)"
                    )

    except Exception as e:
        warnings.append(f"v3.1 [Redis]: connection failed: {e}")
        return False, warnings

    return len(warnings) == 0, warnings


def _check_v31_via_duckdb() -> Tuple[bool, list]:
    """Check v3.1 health via DuckDB (after hours only, no lock contention)."""
    warnings = []
    try:
        import duckdb

        db = duckdb.connect(str(V31_DB), read_only=True)
        n = db.execute("SELECT COUNT(*) FROM market_data").fetchone()[0]
        if n == 0:
            warnings.append("v3.1: EMPTY — 0 rows")
            return False, warnings

        for col, max_pct in BASELINE_NULL_MAX.items():
            null_count = db.execute(
                f"SELECT COUNT(*) FROM market_data WHERE {col} IS NULL"
            ).fetchone()[0]
            pct = round(null_count / n * 100, 1)
            if pct > max_pct:
                warnings.append(f"v3.1 {col}: {pct}% NULL (limit: {max_pct}%)")

        ts = db.execute("SELECT MAX(timestamp) FROM market_data").fetchone()[0]
        if ts:
            try:
                t = datetime.fromisoformat(ts)
                age = (datetime.now() - t).total_seconds() / 60
                if age > STALE_V31_MIN:
                    warnings.append(f"v3.1: stale — last update {age:.0f} min ago")
            except ValueError:
                warnings.append(f"v3.1: invalid timestamp: {ts}")

        db.close()
    except Exception as e:
        warnings.append(f"v3.1: connection failed: {e}")
        return False, warnings

    return len(warnings) == 0, warnings


def check_v31() -> Tuple[bool, list]:
    """Check v3.1 data health. Uses Redis during market hours to avoid
    DuckDB lock contention with the capture process."""
    if _is_market_hours():
        return _check_v31_via_redis()
    return _check_v31_via_duckdb()


def check_v4(index: str = "NIFTY") -> Tuple[bool, list]:
    """Check v4 multi-TF DuckDB. Uses short timeout to avoid blocking capture."""
    warnings = []
    db_path = V4_NIFTY_DB if index.upper() == "NIFTY" else V4_SENSEX_DB
    try:
        import duckdb
        import signal

        def _timeout_handler(signum, frame):
            raise TimeoutError("DuckDB connection timed out")

        old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(3)
        try:
            db = duckdb.connect(str(db_path), read_only=True)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)

        for tf in [5, 15, 30, 60, 240, 1440]:
            n = db.execute(
                f"SELECT COUNT(*) FROM market_data_multitf WHERE timeframe_min = {tf}"
            ).fetchone()[0]
            nulls = db.execute(
                f"SELECT COUNT(*) FROM market_data_multitf WHERE timeframe_min = {tf} AND (close IS NULL OR open IS NULL)"
            ).fetchone()[0]
            ts = db.execute(
                f"SELECT MAX(timestamp) FROM market_data_multitf WHERE timeframe_min = {tf}"
            ).fetchone()[0]

            if n == 0:
                warnings.append(f"v4 {tf}m: EMPTY")
                continue
            if nulls > 0:
                warnings.append(f"v4 {tf}m: {nulls}/{n} NULL O/C")

            if ts:
                try:
                    t = datetime.fromisoformat(ts)
                    age = (datetime.now() - t).total_seconds() / 60
                    if age > STALE_V4_MIN:
                        warnings.append(f"v4 {tf}m: stale — last bar {age:.0f} min ago")
                except ValueError:
                    pass
        db.close()
    except (TimeoutError, Exception) as e:
        if "lock" in str(e).lower() or isinstance(e, TimeoutError):
            pass
        else:
            warnings.append(f"v4: {e}")
            return False, warnings

    return len(warnings) == 0, warnings


def check_redis() -> Tuple[bool, list]:
    """Check Redis queue for NULL indicators and staleness."""
    warnings = []
    try:
        import redis as rds

        r = rds.Redis(host="localhost", port=6379, db=0, decode_responses=True)
        r.ping()

        n = r.llen("v3_ohlcv_queue_NIFTY")
        n_sensex = r.llen("v3_ohlcv_queue_SENSEX")
        if n == 0 and n_sensex == 0:
            warnings.append("Redis: EMPTY queue")
            return False, warnings

        # Check latest bar from NIFTY queue
        latest = json.loads(r.lindex("v3_ohlcv_queue_NIFTY", 0))
        ts = latest.get("timestamp")

        # Check staleness
        if ts:
            try:
                t = datetime.fromisoformat(ts)
                age = (datetime.now() - t).total_seconds() / 60
                if age > STALE_REDIS_MIN:
                    warnings.append(
                        f"Redis: stale — last bar {age:.0f} min ago ({ts[:19]})"
                    )
            except ValueError:
                warnings.append(f"Redis: invalid timestamp: {ts}")

        # Check required indicator keys
        missing = [k for k in REQUIRED_REDIS_KEYS if k not in latest]
        if missing:
            warnings.append(f"Redis: MISSING indicator keys: {missing}")

        # Check NULL values
        nulls = [k for k, v in latest.items() if v is None and k in REQUIRED_REDIS_KEYS]
        if nulls:
            warnings.append(f"Redis: NULL indicators: {nulls}")

        # Check queue growth (compare with last check)
        prev_state = {}
        if STATE_FILE.exists():
            prev_state = json.loads(STATE_FILE.read_text())
        prev_n = prev_state.get("redis_len", 0)
        prev_ts = prev_state.get("redis_ts", "")
        if n == prev_n and ts == prev_ts and datetime.now().hour >= 9:
            warnings.append(f"Redis: NOT GROWING — stuck at {n} bars, ts={ts[:19]}")

        # Save state for next check
        STATE_FILE.write_text(
            json.dumps(
                {
                    "redis_len": n,
                    "redis_ts": ts,
                    "checked_at": datetime.now().isoformat(),
                }
            )
        )

    except Exception as e:
        warnings.append(f"Redis: connection failed: {e}")
        return False, warnings

    return len(warnings) == 0, warnings


def run_all() -> Tuple[bool, list]:
    """Run all health checks. Returns (healthy, all_warnings)."""
    results = []
    all_warnings = []

    for name, fn in [
        ("v3.1", check_v31),
        ("v4_NIFTY", lambda: check_v4("NIFTY")),
        ("v4_SENSEX", lambda: check_v4("SENSEX")),
        ("Redis", check_redis),
    ]:
        ok, warnings = fn()
        results.append(ok)
        for w in warnings:
            all_warnings.append(f"[{name}] {w}")

    healthy = all(results)
    return healthy, all_warnings


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--alert", action="store_true", help="Return non-zero if unhealthy"
    )
    args = parser.parse_args()

    healthy, warnings = run_all()

    if warnings:
        print(f"[{datetime.now().strftime('%H:%M')}] DATA HEALTH:")
        for w in warnings:
            print(f"  ⚠️  {w}")
        if args.alert:
            sys.exit(1)
    elif args.alert:
        # Silent healthy check (for cron)
        pass
    else:
        print(f"[{datetime.now().strftime('%H:%M')}] ✅ All data pipelines healthy")
