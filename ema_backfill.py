#!/usr/bin/env python3
"""
EMA Backfill — Initialize EMA state files from DuckDB + yfinance.

Priority chain:
  1. DuckDB (exact live data, most recent)
  2. yfinance (historical, 15min delayed — fills what DuckDB can't)
  3. Live feed (builds remaining gap over time, returns None until ready)

For long-term EMA (100/200), 15-min yfinance delay is irrelevant.
These are multi-day support/resistance levels, not tick data.

Usage:
    python3 ema_backfill.py                # backfill NIFTY all TFs
    from ema_backfill import backfill_all
    backfill_all("NIFTY")
"""

import sys
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from ema_aggregator import update_ema, reset_ema, get_ema_status, seed_ema, PERIODS, TIMEFRAMES

DUCKDB_PATH = "/home/trading_ceo/python-trader/varaha/data/varaha_data.duckdb"

TF_MINUTES = {
    "1min": 1, "5min": 5, "15min": 15,
    "60min": 60, "1D": 1440,
}

# yfinance config per TF
# interval: what yfinance interval to download
# period: how far back to go
# agg_factor: how many yfinance bars = 1 of our TF candles
YF_CONFIG = {
    "5min":  {"interval": "5m",  "period": "60d",  "agg_factor": 1},
    "15min": {"interval": "15m", "period": "60d",  "agg_factor": 1},
    "60min": {"interval": "1h",  "period": "2y",   "agg_factor": 1},
    "1D":    {"interval": "1d",  "period": "5y",   "agg_factor": 1},
    "1min":  None,  # yfinance 1min only 7 days, not useful for backfill
}

YF_TICKER = {
    "NIFTY":  "^NSEI",
    "SENSEX": "^BSESN",
}


# ── DuckDB helpers ──────────────────────────────────────────

def _load_1min_closes_duckdb(index: str, db_path: str, limit: int = 10000) -> List[float]:
    """Load last N 1-min closes from DuckDB. Returns oldest→newest."""
    try:
        import duckdb
        db = duckdb.connect(db_path, read_only=True)
        rows = db.execute(
            f"SELECT spot FROM market_data "
            f"WHERE index_name = '{index}' "
            f"ORDER BY timestamp DESC LIMIT {limit}"
        ).fetchall()
        db.close()
        return [float(r[0]) for r in reversed(rows)]
    except Exception as e:
        print(f"[EMA BACKFILL] DuckDB error: {e}")
        return []


def _aggregate_closes(closes: List[float], factor: int) -> List[float]:
    """
    Aggregate closes to higher TF.
    Takes last close of each bucket as candle close.
    e.g. factor=5: groups 5 bars → 1 5min candle
    """
    if factor == 1:
        return closes
    result = []
    n = len(closes)
    for i in range(0, n - (n % factor), factor):
        bucket = closes[i : i + factor]
        if len(bucket) == factor:
            result.append(bucket[-1])
    return result


# ── yfinance helpers ────────────────────────────────────────

def _get_ema_seeds_yfinance(index: str, tf: str) -> Dict[int, float]:
    """
    Get EMA seed values from yfinance using pandas.ewm().
    Returns {period: seed_value} for periods with enough history.
    """
    cfg = YF_CONFIG.get(tf)
    if cfg is None:
        return {}

    ticker_sym = YF_TICKER.get(index)
    if not ticker_sym:
        print(f"[EMA BACKFILL] yfinance: no ticker for index={index}")
        return {}

    try:
        import yfinance as yf

        df = yf.Ticker(ticker_sym).history(
            interval=cfg["interval"],
            period=cfg["period"]
        )

        if df.empty:
            return {}

        raw_closes = df["Close"].tolist()

        # Aggregate if needed (e.g., 4×1h → 1×4h for 1D TF)
        factor = cfg.get("agg_factor", 1)
        if factor > 1:
            closes = _aggregate_closes(raw_closes, factor)
            series = pd.Series(closes)
        else:
            series = df["Close"]

        # Compute EMA seeds via pandas.ewm()
        seeds = {}
        for period in PERIODS:
            if len(series) >= period:
                ema_val = float(series.ewm(span=period, adjust=False).mean().iloc[-1])
                seeds[period] = ema_val

        print(
            f"[EMA BACKFILL] yfinance {index}/{tf}: "
            f"{len(raw_closes)} raw bars → {len(series)} candles | "
            f"Seeds: {', '.join(f'EMA{p}={v:.2f}' for p, v in sorted(seeds.items()))}"
        )
        return seeds

    except Exception as e:
        print(f"[EMA BACKFILL] yfinance error for {tf}: {e}")
        return {}


# ── Core backfill ───────────────────────────────────────────

def _backfill_tf(tf: str, closes: List[float]) -> dict:
    """
    Feed historical closes into EMA aggregator for one TF.
    Returns status per period.
    """
    if not closes:
        return {p: {"status": "no_data", "value": None} for p in PERIODS}

    for close in closes:
        update_ema(close, tf=tf)

    result = {}
    for period in PERIODS:
        st = get_ema_status(tf, period)
        if st["available"]:
            result[period] = {"status": "ready", "value": st["ema_value"]}
            print(f"  EMA{period:3d}: READY   value={st['ema_value']:.4f}")
        else:
            result[period] = {
                "status": "not_enough_data",
                "value": None,
                "bars_have": st["buffer_count"],
                "bars_need": period,
                "bars_remaining": st["bars_remaining"],
            }
            print(
                f"  EMA{period:3d}: PARTIAL {st['buffer_count']}/{period} bars "
                f"({st['bars_remaining']} more from live feed)"
            )
    return result


def backfill_all(index: str = "NIFTY", db_path: str = DUCKDB_PATH) -> dict:
    """
    Backfill EMA state files for all TFs using DuckDB + yfinance fallback.

    For each TF:
      1. Try DuckDB (derive from 1min bars)
      2. If any period still not ready → try yfinance
      3. Whatever's left builds from live feed (returns None until ready)
    """
    print(f"\n[EMA BACKFILL] Starting for {index}...\n")
    reset_ema()

    # Load 1-min closes from DuckDB (single query, derive all TFs from this)
    closes_1min = _load_1min_closes_duckdb(index, db_path)
    print(f"[EMA BACKFILL] DuckDB: {len(closes_1min)} 1-min bars\n")

    summary = {}

    for tf in TIMEFRAMES:
        tf_mins = TF_MINUTES[tf]
        print(f"--- {tf} ---")

        # Step 1: Derive TF closes from DuckDB 1-min bars
        db_closes = _aggregate_closes(closes_1min, tf_mins)
        print(f"  DuckDB: {len(db_closes)} candles")
        _backfill_tf(tf, db_closes)

        # Step 2: Check if any periods still need data
        missing = [p for p in PERIODS if not get_ema_status(tf, p)["available"]]

        if missing and YF_CONFIG.get(tf):
            print(f"  Missing periods {missing} — trying yfinance...")
            yf_seeds = _get_ema_seeds_yfinance(index, tf)

            if yf_seeds:
                # Seed each missing period directly from yfinance
                for period, seed_val in yf_seeds.items():
                    if period in missing:
                        seed_ema(tf, period, seed_val)

                # Layer DuckDB on top (more recent, exact data)
                if db_closes:
                    print(f"  Layering DuckDB on top ({len(db_closes)} exact bars)...")
                    for close in db_closes:
                        update_ema(close, tf=tf)
            else:
                print(f"  yfinance unavailable — live feed will fill the gap")

        # Final status
        tf_summary = {}
        for period in PERIODS:
            st = get_ema_status(tf, period)
            tf_summary[period] = {
                "available": st["available"],
                "value": st["ema_value"],
                "bars_have": st["buffer_count"],
            }
        summary[tf] = tf_summary
        print()

    return {
        "status": "success",
        "index": index,
        "summary": summary,
        "timestamp": datetime.now().isoformat(),
    }


# ── Test ────────────────────────────────────────────────────

if __name__ == "__main__":
    result = backfill_all("NIFTY")

    print("\n" + "=" * 65)
    print("FINAL SUMMARY")
    print("=" * 65)
    print(f"{'TF':8s}  {'EMA20':>10} {'EMA50':>10} {'EMA100':>10} {'EMA200':>10}")
    print("-" * 65)

    for tf, ema_data in result["summary"].items():
        def fmt(p):
            d = ema_data[p]
            if d["available"]:
                return f"{d['value']:>10.2f}"
            else:
                return f"{'None':>10s}"

        print(
            f"{tf:8s}  {fmt(20)} {fmt(50)} {fmt(100)} {fmt(200)}"
        )
