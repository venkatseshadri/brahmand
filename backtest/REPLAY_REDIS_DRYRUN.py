#!/usr/bin/env python3
"""
Redis Replay — push historical DuckDB bars into Redis for after-hours testing.
Simulates market conditions so you can validate entry gates, trade execution,
and monitoring without waiting for the next market day.

Usage:
    python3 REPLAY_REDIS_DRYRUN.py 2026-05-22     # replay May 22 data
    python3 REPLAY_REDIS_DRYRUN.py 2026-05-22 --run-kickoff  # replay + execute kickoff
"""

from __future__ import annotations

import json
import sys
from datetime import datetime as _dt
from pathlib import Path
from typing import Optional

import duckdb
import numpy as np

DUCKDB_PATH = "/home/trading_ceo/projects/varaha/data/varaha_data.duckdb"
EMA_STATE_DIR = Path("/tmp/replay_ema_state")
INDEX = "NIFTY"
REDIS_KEY = f"v3_ohlcv_queue_{INDEX}"

EMA_PERIODS = [5, 9, 20, 50, 100, 200]
EMA_MULT = {p: 2.0 / (p + 1) for p in EMA_PERIODS}


def load_bars(date: str) -> list[dict]:
    """Load market_data bars for a given date from DuckDB."""
    db = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    rows = db.execute(
        "SELECT timestamp, open_price, intraday_high, intraday_low, spot "
        "FROM market_data WHERE date = ? AND index_name = ? ORDER BY timestamp ASC",
        (date, INDEX),
    ).fetchall()
    db.close()

    if not rows:
        print(f"No market_data for {INDEX} on {date}")
        return []

    bars = []
    for ts, open_p, high, low, close in rows:
        bars.append(
            {
                "timestamp": ts,
                "open": float(open_p),
                "high": float(high),
                "low": float(low),
                "close": float(close),
                "index": INDEX,
            }
        )
    print(f"Loaded {len(bars)} bars for {INDEX} on {date}")
    return bars


def push_to_redis(bars: list[dict]):
    """Push bars to Redis v3_ohlcv_queue_{index} (LPUSH, newest at head)."""
    try:
        import redis as _redis

        r = _redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
        r.ping()
    except Exception as e:
        print(f"Redis not available: {e}")
        return

    r.delete(REDIS_KEY)
    for bar in bars:  # LPUSH oldest first → newest ends up at head
        r.lpush(REDIS_KEY, json.dumps(bar))
    r.expire(REDIS_KEY, 604800)
    print(f"Pushed {len(bars)} bars to {REDIS_KEY}")


def compute_emas(bars: list[dict]) -> dict[int, list[float]]:
    closes = np.array([b["close"] for b in bars], dtype=float)
    emas = {p: np.full(len(closes), np.nan) for p in EMA_PERIODS}
    for p in EMA_PERIODS:
        if len(closes) < p:
            continue
        k = EMA_MULT[p]
        emas[p][p - 1] = np.mean(closes[:p])
        for i in range(p, len(closes)):
            emas[p][i] = closes[i] * k + emas[p][i - 1] * (1 - k)
    return emas


def write_ema_files(emas: dict, idx: int):
    """Write 1min EMA state files to replay path."""
    EMA_STATE_DIR.mkdir(parents=True, exist_ok=True)
    d = EMA_STATE_DIR / "1min"
    d.mkdir(exist_ok=True)
    for p in EMA_PERIODS:
        val = emas[p][idx] if idx < len(emas[p]) else np.nan
        if np.isnan(val):
            continue
        state = {
            "tf": "1min",
            "period": p,
            "ema_value": round(float(val), 4),
            "available": True,
            "status": "ready",
            "buffer_count": p,
            "timestamp": _dt.now().isoformat(),
        }
        (d / f"ema_{p}.json").write_text(json.dumps(state, indent=2))
    print(f"Wrote EMA state to {EMA_STATE_DIR}/1min/")


def replay_date(date: str, run_kickoff: bool = False):
    """Full replay: push bars, write EMAs, optionally run kickoff."""
    bars = load_bars(date)
    if not bars:
        return

    push_to_redis(bars)
    emas = compute_emas(bars)

    # Write EMAs at every 60-minute interval for full-day coverage
    for i in range(0, len(bars), 60):
        write_ema_files(emas, i)

    # Set prev_close for gap calculation
    try:
        import redis as _redis

        r = _redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
        r.set(f"prev_close_{INDEX}", str(bars[-1]["close"]))
        print(f"prev_close_{INDEX} = {bars[-1]['close']:.2f}")
    except:
        pass

    if run_kickoff:
        print("\nRunning kickoff.py --once...")
        import subprocess

        result = subprocess.run(
            ["python3", str(Path(__file__).parent / "kickoff.py"), "--once"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(Path(__file__).parent),
        )
        print(result.stdout[-3000:] if len(result.stdout) > 3000 else result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr[-500:])


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 REPLAY_REDIS_DRYRUN.py <YYYY-MM-DD> [--run-kickoff]")
        sys.exit(1)

    date = sys.argv[1]
    kickoff = "--run-kickoff" in sys.argv

    replay_date(date, run_kickoff=kickoff)
