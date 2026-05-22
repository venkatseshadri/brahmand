#!/usr/bin/env python3
"""
EMA Aggregator — Persistent rolling EMA per timeframe per period.

State files: /home/trading_ceo/brahmand/data/ema_state/{tf}/ema_{period}.json
Once threshold crossed (N bars), EMA is always available (rolling).
Before threshold: returns None ("not_enough_data").

Timeframes: 1min, 5min, 15min, 60min, 1D
Periods per TF: 5, 9, 20, 50, 100, 200

Usage:
    from ema_aggregator import update_ema, get_ema, get_all_emas

    # Feed a closed candle for a timeframe
    update_ema(close=23745.5, tf="5min")

    # Get EMA value (None if not ready)
    val = get_ema(tf="5min", period=20)   # 23741.25 or None
    val = get_ema(tf="15min", period=200) # None (not enough data yet)
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Optional

EMA_BASE_DIR = Path("/home/trading_ceo/brahmand/data/ema_state")
PERIODS = [5, 9, 20, 50, 100, 200]
TIMEFRAMES = ["1min", "5min", "15min", "60min", "1D"]
MULTIPLIERS = {p: round(2 / (p + 1), 8) for p in PERIODS}


# ── Internal helpers ────────────────────────────────────────


def _state_file(tf: str, period: int) -> Path:
    return EMA_BASE_DIR / tf / f"ema_{period}.json"


def _load(tf: str, period: int) -> dict:
    f = _state_file(tf, period)
    if f.exists():
        try:
            return json.loads(f.read_text())
        except (json.JSONDecodeError, IOError):
            pass
    return {
        "tf": tf,
        "period": period,
        "ema_value": None,
        "available": False,
        "status": "not_enough_data",
        "last_bars": [],
        "buffer_count": 0,
        "multiplier": MULTIPLIERS[period],
        "threshold_crossed_at": None,
        "timestamp": None,
    }


def _save(tf: str, period: int, state: dict):
    f = _state_file(tf, period)
    f.parent.mkdir(parents=True, exist_ok=True)
    state["timestamp"] = datetime.now().isoformat()
    f.write_text(json.dumps(state, indent=2))


# ── Public API ──────────────────────────────────────────────


def update_ema(close: float, tf: str, periods: list = None):
    """
    Feed a closed candle's close price for a given timeframe.
    Updates rolling buffer and calculates EMA once threshold crossed.

    Args:
        close: Closing price of the just-closed candle
        tf: Timeframe — "1min", "5min", "15min", "30min", "60min", "240min"
        periods: [20, 50, 100, 200] or subset
    """
    if periods is None:
        periods = PERIODS

    close = float(close)

    # Sanity check: reject obviously wrong prices (NIFTY range ~15k-50k)
    if close < 15000 or close > 50000:
        return

    for period in periods:
        state = _load(tf, period)

        # Add new close to rolling buffer
        state["last_bars"].append(close)
        state["buffer_count"] += 1

        # Keep only last N bars (no memory bloat)
        if len(state["last_bars"]) > period:
            state["last_bars"].pop(0)

        if state["buffer_count"] == period and not state["available"]:
            # First threshold crossing: initial EMA = SMA of first N bars
            state["ema_value"] = round(sum(state["last_bars"]) / period, 4)
            state["available"] = True
            state["status"] = "ready"
            state["threshold_crossed_at"] = datetime.now().isoformat()
            print(
                f"[EMA] {tf}/EMA{period} READY "
                f"(threshold={period} bars) | Value: {state['ema_value']:.4f}"
            )

        elif state["available"]:
            # Rolling EMA update
            prev = state["ema_value"]
            mult = MULTIPLIERS[period]
            state["ema_value"] = round((close - prev) * mult + prev, 4)

        _save(tf, period, state)


def get_ema(tf: str, period: int) -> Optional[float]:
    """
    Get current EMA value.

    Returns:
        float: EMA value if threshold crossed and rolling
        None:  If not enough data yet
    """
    state = _load(tf, period)
    return state["ema_value"] if state["available"] else None


def get_ema_status(tf: str, period: int) -> dict:
    """Full status for a specific TF/period."""
    state = _load(tf, period)
    return {
        "tf": tf,
        "period": period,
        "ema_value": state["ema_value"],
        "available": state["available"],
        "status": state["status"],
        "buffer_count": state["buffer_count"],
        "bars_needed": period,
        "bars_remaining": max(0, period - state["buffer_count"]),
        "timestamp": state["timestamp"],
    }


def get_all_emas(tf: str = None) -> dict:
    """
    Get all EMA values across all TFs and periods.

    Returns:
        {
            "5min": {20: 23741.25, 50: 23738.00, 100: None, 200: None},
            "15min": {20: 23742.00, 50: None, ...},
            ...
        }
    """
    tfs = [tf] if tf else TIMEFRAMES
    result = {}
    for t in tfs:
        result[t] = {p: get_ema(t, p) for p in PERIODS}
    return result


def reset_ema(tf: str = None, period: int = None):
    """
    Reset state files. Pass tf=None to reset all.

    Args:
        tf: Specific timeframe, or None for all
        period: Specific period, or None for all
    """
    tfs = [tf] if tf else TIMEFRAMES
    periods = [period] if period else PERIODS

    for t in tfs:
        for p in periods:
            f = _state_file(t, p)
            if f.exists():
                f.unlink()

    print(f"[EMA] Reset: tf={tf or 'ALL'}, period={period or 'ALL'}")


def seed_ema(tf: str, period: int, value: float):
    """
    Seed an EMA with a value from external source (yfinance, DuckDB backfill).
    Only seeds if not already available.

    Args:
        tf: Timeframe
        period: EMA period (5, 9, 20, 50, 100, 200)
        value: EMA seed value to write
    """
    state = _load(tf, period)
    if not state["available"]:
        state["ema_value"] = round(float(value), 4)
        state["available"] = True
        state["status"] = "ready"
        state["threshold_crossed_at"] = datetime.now().isoformat()
        state["buffer_count"] = period
        _save(tf, period, state)
        print(f"[EMA] {tf}/EMA{period} SEEDED with {state['ema_value']:.4f}")


# ── Test ────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== EMA Aggregator Test ===\n")

    reset_ema()

    prices = [23740.0 + i * 0.5 for i in range(25)]
    print("Feeding 25 bars into 5min...\n")

    for i, price in enumerate(prices, 1):
        update_ema(price, tf="5min")
        if i in [5, 20, 25]:
            print(f"\nAfter bar {i}:")
            for p in PERIODS:
                val = get_ema("5min", p)
                st = get_ema_status("5min", p)
                print(
                    f"  EMA{p}: {val} | "
                    f"{st['buffer_count']}/{st['bars_needed']} bars | "
                    f"{st['status']}"
                )
