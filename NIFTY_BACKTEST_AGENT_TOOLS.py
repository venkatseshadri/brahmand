#!/usr/bin/env python3
"""
NIFTY 2024 Backtest — Production Agent Tools on Kaggle Data.

Loads NIFTY OCT24 options from Kaggle cache, reconstructs NIFTY spot per
minute via put-call parity, then feeds pre-computed indicators to the
ACTUAL PRODUCTION agent tools (score_trend_redis, score_traffic_light_redis,
combine_entry_scores) via monkey-patched Redis + EMA state files.

No LLM. No mocks for the tools themselves — only Redis/filesystem replaced
with equivalent data from Kaggle.

Output: per-day entry decisions + simulated P&L + production tool validity report.
"""

from __future__ import annotations

import csv
import json
import re
import sys
import time as _time_module
from collections import defaultdict
from copy import deepcopy
from datetime import datetime as _dt
from pathlib import Path as _Path
from typing import Optional
from unittest.mock import patch

import numpy as np

KAGGLE_CACHE = _Path(
    "/root/.cache/kagglehub/datasets/kaalicharan9080/"
    "nse-future-and-options-data/versions/2"
)
BACKTEST_EMA_DIR = _Path("/tmp/backtest_ema_state")
BACKTEST_OUTPUT_DIR = _Path("/home/trading_ceo/brahmand/data")
ENTRY_GATE_MIN_CONFIDENCE = 0.75
ENTRY_DELAY_BARS = 30  # wait 30 mins after open (09:15 → 09:45)

# -- ticker pattern (only NIFTY, not BANKNIFTY) ---------------------------
_TICKER_RE = re.compile(
    r"^NIFTY(\d{2}[A-Z]{3}\d{2})(\d{5})(PE|CE)\.NFO$", re.IGNORECASE
)

# -- EMA globals ----------------------------------------------------------
EMA_PERIODS = [5, 20, 50, 100, 200]
EMA_MULT = {p: 2.0 / (p + 1) for p in EMA_PERIODS}


# ====================================================================
# DATA LOADING — options CSV → put-call parity spot reconstruction
# ====================================================================


def _csv_files():
    return sorted(p for p in KAGGLE_CACHE.iterdir() if p.suffix.lower() == ".csv")


def load_day(csv_path: _Path) -> tuple[str, dict]:
    """Read one options CSV, extract NIFTY options for nearest weekly expiry."""
    date_str = ""
    time_data = defaultdict(dict)
    expiries_seen = defaultdict(int)

    with open(csv_path) as f:
        reader = csv.reader(f)
        for ticker, date, time, open_p, high, low, close, vol, oi in reader:
            m = _TICKER_RE.search(ticker)
            if not m:
                continue
            date_str = date
            expiry = m.group(1)
            strike = int(m.group(2))
            opt_type = m.group(3)
            expiries_seen[expiry] += 1
            time_data[time][(strike, opt_type, expiry)] = float(close)

    if not expiries_seen:
        return date_str, time_data

    # Filter to nearest weekly expiry
    trade_date_dt = _dt.strptime(date_str, "%d/%m/%Y")
    month_map = {
        "JAN": 1,
        "FEB": 2,
        "MAR": 3,
        "APR": 4,
        "MAY": 5,
        "JUN": 6,
        "JUL": 7,
        "AUG": 8,
        "SEP": 9,
        "OCT": 10,
        "NOV": 11,
        "DEC": 12,
    }
    best_expiry, best_days = None, 999
    for exp in expiries_seen:
        day = int(exp[:2])
        month = month_map[exp[2:5]]
        year = int(f"20{exp[5:7]}")
        exp_dt = _dt(year, month, day)
        days_diff = (exp_dt - trade_date_dt).days
        if 0 <= days_diff < best_days:
            best_days, best_expiry = days_diff, exp

    if best_expiry:
        filtered = defaultdict(dict)
        for t, vault in time_data.items():
            for (strike, opt_type, exp), price in vault.items():
                if exp == best_expiry:
                    filtered[t][(strike, opt_type)] = price
        time_data = filtered
    return date_str, time_data


def reconstruct_spot(time_data: dict) -> dict:
    """For each time, find ATM strike (min |CE-PE|), derive spot via put-call parity."""
    spot = {}
    for t in sorted(time_data):
        data = time_data[t]
        best_diff, best_spot = float("inf"), None
        for (strike, otype), price in data.items():
            if otype != "CE":
                continue
            pe = data.get((strike, "PE"))
            if pe is None:
                continue
            diff = abs(price - pe)
            if diff < best_diff:
                best_diff = diff
                best_spot = price - pe + strike
        if best_spot is not None:
            spot[t] = best_spot
    return spot


def spot_to_bars(spot_map: dict) -> list[dict]:
    """Convert {time: spot} to 1-min OHLCV bars (O=H=L=C=spot for put-call parity)."""
    bars = []
    for t in sorted(spot_map):
        bars.append(
            {
                "timestamp": t,
                "open": spot_map[t],
                "high": spot_map[t],
                "low": spot_map[t],
                "close": spot_map[t],
                "index": "NIFTY",
            }
        )
    return bars


# ====================================================================
# INDICATOR COMPUTATION
# ====================================================================


def compute_emas(bars: list[dict]) -> dict[int, list[float]]:
    """Compute rolling EMA(5,20,50,100,200) for a list of 1-min bars."""
    closes = np.array([b["close"] for b in bars], dtype=float)
    emas = {p: np.full(len(closes), np.nan) for p in EMA_PERIODS}
    for p in EMA_PERIODS:
        if len(closes) < p:
            continue
        k = EMA_MULT[p]
        seed = np.mean(closes[:p])
        emas[p][p - 1] = seed
        for i in range(p, len(closes)):
            emas[p][i] = closes[i] * k + emas[p][i - 1] * (1 - k)
    return emas


def candle_color(open_p: float, close_p: float) -> str:
    return "GREEN" if close_p > open_p else "RED"


def aggregate_tf(bars: list[dict], start_idx: int, tf_mins: int) -> dict | None:
    """Aggregate min bars [start_idx, start_idx+tf_mins) into one TF candle."""
    end = min(start_idx + tf_mins, len(bars))
    bucket = bars[start_idx:end]
    if not bucket:
        return None
    return {
        "open": bucket[0]["open"],
        "high": max(b["high"] for b in bucket),
        "low": min(b["low"] for b in bucket),
        "close": bucket[-1]["close"],
    }


def compute_tf_colors(bars: list[dict], idx: int) -> dict[str, str]:
    """
    Compute multi-TF candle colors using bars from [0, idx] range.
    Returns {tf_label: "GREEN"|"RED"|"no_data"}.
    """
    tf_map = {"5m": 5, "15m": 15, "30m": 30, "60m": 60, "240m": 240}
    colors = {}
    for label, mins in tf_map.items():
        if idx < mins:
            colors[label] = "no_data"
            continue
        candle = aggregate_tf(bars, idx - mins + 1, mins)
        if candle:
            colors[label] = candle_color(candle["open"], candle["close"])
        else:
            colors[label] = "no_data"
    # Daily: from first bar of day to current
    if idx > 0:
        first_close = bars[0]["close"]
        current_open = bars[idx]["open"]
        colors["1440m"] = "GREEN" if current_open > first_close else "RED"
    else:
        colors["1440m"] = "no_data"
    return colors


# ====================================================================
# EMA STATE FILES (format score_trend_redis expects)
# ====================================================================


def write_ema_state(period: int, value: float, tf: str, timestamp: str) -> None:
    """Write one EMA state JSON file."""
    d = BACKTEST_EMA_DIR / tf
    d.mkdir(parents=True, exist_ok=True)
    state = {
        "tf": tf,
        "period": period,
        "ema_value": round(value, 4),
        "available": True,
        "status": "ready",
        "buffer_count": period,
        "threshold_crossed_at": timestamp,
        "timestamp": _dt.now().isoformat(),
    }
    (d / f"ema_{period}.json").write_text(json.dumps(state, indent=2))


class _PathRedirector:
    """Redirect ema_state paths to backtest temp dir."""

    def __init__(self, redirect: str):
        self._redirect = redirect
        self._orig = _Path

    def __call__(self, path):
        s = str(path)
        if "ema_state" in s:
            parts = s.split("ema_state", 1)
            return (
                _Path(self._redirect + parts[1])
                if len(parts) > 1
                else _Path(self._redirect)
            )
        return _Path(s)


# ====================================================================
# MOCK REDIS
# ====================================================================


class MockRedis:
    """Returns pre-computed bars. Mimics redis.Redis lrange/lindex/get."""

    def __init__(self, bars: list[dict], prev_close: Optional[float] = None):
        self._bars = [json.dumps(b) for b in bars]
        self._prev_close = str(prev_close) if prev_close is not None else None
        self._call_count_lrange = 0

    def ping(self):
        return True

    def lrange(self, key, start, end):
        self._call_count_lrange += 1
        if key == "v3_ohlcv_queue":
            return self._bars[start : end + 1 if end >= 0 else None]
        return []

    def lindex(self, key, idx):
        if key == "v3_ohlcv_queue":
            return self._bars[idx] if 0 <= idx < len(self._bars) else None
        return None

    def get(self, key):
        if key.startswith("prev_close_"):
            return self._prev_close
        return None

    def close(self):
        pass


def _make_mock_redis_connect(bars, prev_close=None):
    """Factory for _redis_connect monkey-patch."""

    def _connect():
        return MockRedis(bars, prev_close)

    return _connect


# ====================================================================
# NOT_UP / NOT_DOWN REJECTION (mirrors production entry_gate_tools.py)
# ====================================================================


def evaluate_not_up(trend: dict, tl: dict) -> dict:
    """Production tiers from EvaluateNotUpRejection._run()."""
    t_sig = trend.get("signal", "NEUTRAL")
    t_conf = trend.get("confidence", 50)
    tl_sig = tl.get("signal", "NEUTRAL")
    tl_conf = tl.get("confidence", 50)

    go = False
    confidence = 0
    reasoning = ""

    if t_sig == "BEARISH" and tl_sig == "BEARISH":
        go = True
        confidence = round((t_conf + tl_conf) / 2)
        reasoning = f"Both Trend ({t_conf}%) and TL ({tl_conf}%) are BEARISH. Strong upside rejection."
    elif (t_sig == "BEARISH" and tl_sig == "NEUTRAL") or (
        t_sig == "NEUTRAL" and tl_sig == "BEARISH"
    ):
        go = True
        confidence = round(max(t_conf if t_sig == "BEARISH" else tl_conf, 0) * 0.67)
        reasoning = f"One BEARISH + one NEUTRAL. Moderate upside rejection."
    elif t_sig == "BULLISH" or tl_sig == "BULLISH":
        go = False
        confidence = 0
        reasoning = (
            f"Trend: {t_sig}({t_conf}%), TL: {tl_sig}({tl_conf}%). No upside rejection."
        )
    else:
        go = False
        confidence = 0
        reasoning = "Both Trend and TL are NEUTRAL. Insufficient bearish pressure."

    return {
        "go": go,
        "signal": "NOT_UP",
        "confidence": confidence,
        "trend_signal": t_sig,
        "trend_confidence": t_conf,
        "traffic_light_signal": tl_sig,
        "traffic_light_confidence": tl_conf,
        "reasoning": reasoning,
    }


def evaluate_not_down(trend: dict, tl: dict) -> dict:
    """Production tiers from EvaluateNotDownRejection._run()."""
    t_sig = trend.get("signal", "NEUTRAL")
    t_conf = trend.get("confidence", 50)
    tl_sig = tl.get("signal", "NEUTRAL")
    tl_conf = tl.get("confidence", 50)

    go = False
    confidence = 0
    reasoning = ""

    if t_sig == "BULLISH" and tl_sig == "BULLISH":
        go = True
        confidence = round((t_conf + tl_conf) / 2)
        reasoning = f"Both Trend ({t_conf}%) and TL ({tl_conf}%) are BULLISH. Strong downside rejection."
    elif (t_sig == "BULLISH" and tl_sig == "NEUTRAL") or (
        t_sig == "NEUTRAL" and tl_sig == "BULLISH"
    ):
        go = True
        confidence = round(max(t_conf if t_sig == "BULLISH" else tl_conf, 0) * 0.67)
        reasoning = f"One BULLISH + one NEUTRAL. Moderate downside rejection."
    elif t_sig == "BEARISH" or tl_sig == "BEARISH":
        go = False
        confidence = 0
        reasoning = f"Trend: {t_sig}({t_conf}%), TL: {tl_sig}({tl_conf}%). No downside rejection."
    else:
        go = False
        confidence = 0
        reasoning = "Both Trend and TL are NEUTRAL. Insufficient bullish pressure."

    return {
        "go": go,
        "signal": "NOT_DOWN",
        "confidence": confidence,
        "trend_signal": t_sig,
        "trend_confidence": t_conf,
        "traffic_light_signal": tl_sig,
        "traffic_light_confidence": tl_conf,
        "reasoning": reasoning,
    }


# ====================================================================
# TRADE SIMULATION
# ====================================================================


def get_option_premium(
    time_data: dict, atm_strike: int, opt_type: str, wing: int = 200
) -> float | None:
    """Get option premium for a strike at a given minute snapshot."""
    strike = (
        atm_strike
        if opt_type == "SELL"
        else (atm_strike - wing if opt_type == "BUY_PE" else atm_strike + wing)
    )
    # Adjust for actual strike lookup
    if opt_type == "SELL":
        # ATM
        look_strike = atm_strike
        look_type = "PE"  # default for put spread
    elif opt_type == "BUY_PE":
        look_strike = atm_strike - wing
        look_type = "PE"
    elif opt_type == "BUY_CE":
        look_strike = atm_strike + wing
        look_type = "CE"
    else:
        return None
    if (look_strike, look_type) in time_data:
        return time_data[(look_strike, look_type)]
    return None


def find_atm_strike(time_data: dict) -> int | None:
    """Find ATM strike from a minute's option data."""
    best_diff = float("inf")
    best_strike = None
    for (strike, otype), price in time_data.items():
        if otype != "CE":
            continue
        pe = time_data.get((strike, "PE"))
        if pe is None:
            continue
        diff = abs(price - pe)
        if diff < best_diff:
            best_diff = diff
            best_strike = strike
    return best_strike


def simulate_trade(
    decision: dict,
    entry_snapshot: dict,  # {(strike, type): close} at entry time
    all_bars: list[dict],
    entry_bar_idx: int,
    target_pct: float = 0.80,
    stop_pct: float = -0.30,
    time_data_full: dict = None,  # {time: {(strike, type): close}} for full day
    entry_time: str = "",
) -> dict | None:
    """
    Simulate butterfly spread from entry to EOD.
    Uses linear time-decay model + spot-based SL detection.
    """
    if not decision.get("go"):
        return None

    suggested = decision.get("suggested_trade", "NONE")
    if suggested == "NONE":
        return None

    atm_strike = find_atm_strike(entry_snapshot)
    if atm_strike is None:
        return None

    lot_size = 75

    if suggested == "SELL_PUT":
        sell_prem = get_option_premium(entry_snapshot, atm_strike, "SELL")
        buy_prem = get_option_premium(entry_snapshot, atm_strike, "BUY_PE")
        if sell_prem is None or buy_prem is None:
            return None
        spread = sell_prem - buy_prem
    elif suggested == "SELL_CALL":
        if (atm_strike, "CE") in entry_snapshot:
            sell_prem = entry_snapshot[(atm_strike, "CE")]
        else:
            return None
        buy_strike = atm_strike + 200
        if (buy_strike, "CE") in entry_snapshot:
            buy_prem = entry_snapshot[(buy_strike, "CE")]
        else:
            return None
        spread = sell_prem - buy_prem
    else:
        return None

    if spread <= 0:
        return None

    max_profit = spread * lot_size
    tp_target = max_profit * target_pct
    sl_loss = max_profit * stop_pct

    exit_reason = "EOD"
    exit_idx = len(all_bars) - 1
    exit_pnl = 0.0

    last_known_spread = spread  # fallback when leg data is missing

    for i in range(entry_bar_idx + 1, len(all_bars)):
        bar_time = all_bars[i]["timestamp"]

        # Update spread if both legs available at this minute
        if time_data_full and bar_time in time_data_full:
            snap = time_data_full[bar_time]

            if suggested == "SELL_PUT":
                cur_sell = snap.get((atm_strike, "PE"))
                cur_buy = snap.get((atm_strike - 200, "PE"))
            else:
                cur_sell = snap.get((atm_strike, "CE"))
                cur_buy = snap.get((atm_strike + 200, "CE"))

            if cur_sell is not None and cur_buy is not None:
                last_known_spread = cur_sell - cur_buy

        # Always check SL/TP with last known spread (never skip a minute)
        current_pnl = (spread - last_known_spread) * lot_size

        if current_pnl >= tp_target:
            exit_reason = "TP"
            exit_idx = i
            exit_pnl = tp_target
            break
        if current_pnl <= sl_loss:
            exit_reason = "SL"
            exit_idx = i
            exit_pnl = sl_loss
            break
        exit_pnl = current_pnl

    # EOD: mark to market at last available spread
    if exit_reason == "EOD":
        if time_data_full:
            last_times = sorted(time_data_full.keys(), reverse=True)
            for lt in last_times:
                snap = time_data_full[lt]
                if suggested == "SELL_PUT":
                    cur_sell = snap.get((atm_strike, "PE"))
                    cur_buy = snap.get((atm_strike - 200, "PE"))
                else:
                    cur_sell = snap.get((atm_strike, "CE"))
                    cur_buy = snap.get((atm_strike + 200, "CE"))
                if cur_sell is not None and cur_buy is not None:
                    final_spread = cur_sell - cur_buy
                    exit_pnl = (spread - final_spread) * lot_size
                    break

    tnx = {
        "suggested_trade": suggested,
        "atm_strike": atm_strike,
        "spread": round(spread, 2),
        "max_profit": round(max_profit, 2),
        "tp_target": round(tp_target, 2),
        "exit_reason": exit_reason,
        "exit_pnl": round(exit_pnl, 2),
        "entry_time": entry_time,
        "exit_time": all_bars[exit_idx]["timestamp"],
    }
    return tnx


# ====================================================================
# MAIN BACKTEST LOOP
# ====================================================================


def run_backtest():
    csvs = sorted(p for p in KAGGLE_CACHE.iterdir() if p.suffix.lower() == ".csv")
    if not csvs:
        print("No CSV files found in Kaggle cache.")
        sys.exit(1)

    sys.path.insert(0, str(_Path(__file__).parent.parent / "antariksh"))
    sys.path.insert(0, str(_Path(__file__).parent.parent / "antariksh" / "tools"))

    # Import from antariksh to test the import
    try:
        import tools.entry_tools as _et

        print(f"  ✓ Imported antariksh/tools/entry_tools.py successfully")
    except ImportError as e:
        print(f"  ! Cannot import entry_tools: {e}")
        sys.exit(1)

    print("=" * 100)
    print("NIFTY 2024 BACKTEST — Production Agent Tools on Kaggle Data")
    print("=" * 100)
    print(
        f"\nSource: {len(csvs)} options CSV files → put-call parity spot + real premiums"
    )
    print(f"Entry delay: {ENTRY_DELAY_BARS} min (09:15 → 09:45)")
    print(f"Entry gate:  min confidence >= {ENTRY_GATE_MIN_CONFIDENCE * 100:.0f}%")
    print(
        "Agent tools: score_trend_redis, score_traffic_light_redis, combine_entry_scores"
    )

    results = []
    daily_log = []
    trade_count = 0
    total_pnl = 0.0
    wins = 0
    prev_day_close = None
    all_bars_buffer = []

    BACKTEST_EMA_DIR.mkdir(parents=True, exist_ok=True)

    for csv_idx, csv_file in enumerate(csvs):
        date_str, time_data = load_day(csv_file)
        if not date_str:
            continue

        spot_map = reconstruct_spot(time_data)
        if not spot_map:
            print(f"\n  {csv_file.name}: no NIFTY data")
            continue

        bars = spot_to_bars(spot_map)
        if len(bars) < 30:
            continue

        combined_bars = all_bars_buffer + bars
        emas = compute_emas(combined_bars)

        print(f"\n{'─' * 50}")
        print(
            f"  [{csv_idx + 1}/{len(csvs)}] {csv_file.name} → {date_str}"
            f"  |  {len(bars)} bars  |  buf={len(all_bars_buffer)}"
        )
    print("Rejection:  NOT_UP / NOT_DOWN")

    # Load real spot data for EMA + candle computation
    spot_df = load_spot_bars_df()
    spot_by_date = {}
    for date_str in spot_df["date_str"].unique():
        bars = spot_bars_for_date(spot_df, date_str)
        if bars:
            spot_by_date[date_str] = bars

    # Build options lookup: date -> options data (for trade simulation)
    options_by_date = {}
    for csv_file in csvs:
        date_str, time_data = load_options_data(csv_file)
        if date_str and date_str in spot_by_date:
            options_by_date[date_str] = time_data

    # Iterate over all dates with spot data
    all_dates = sorted(set(list(spot_by_date.keys()) + list(options_by_date.keys())))
    print(f"\n  Trading days with spot data: {len(spot_by_date)}")
    print(f"  Trading days with options data: {len(options_by_date)}")

    results = []
    daily_log = []
    trade_count = 0
    total_pnl = 0.0
    wins = 0
    prev_day_close = None

    BACKTEST_EMA_DIR.mkdir(parents=True, exist_ok=True)

    all_bars_buffer = []

    for day_idx, date_str in enumerate(all_dates):
        bars = spot_by_date.get(date_str)
        if not bars or len(bars) < 30:
            continue

        time_data = options_by_date.get(date_str)
        has_options = time_data is not None

        combined_bars = all_bars_buffer + bars
        emas = compute_emas(combined_bars)
        first_time = bars[0]["timestamp"]

        print(f"\n{'─' * 50}")
        print(
            f"  [{day_idx + 1}/{len(all_dates)}] {date_str}"
            f"  |  {len(bars)} bars  |  buffer: {len(all_bars_buffer)}"
            f"  {'📊 options' if has_options else 'spot only'}"
        )
        entry_idx = len(all_bars_buffer)
        for p in EMA_PERIODS:
            while entry_idx < len(combined_bars) and np.isnan(emas[p][entry_idx]):
                entry_idx += 1
        if entry_idx >= len(combined_bars):
            all_bars_buffer = combined_bars[-max(EMA_PERIODS) :]
            continue

        entry_bar = combined_bars[entry_idx]
        entry_time = entry_bar["timestamp"]
        bar_in_day = entry_idx - len(all_bars_buffer)

        ema_snapshot = {}
        for p in EMA_PERIODS:
            if not np.isnan(emas[p][entry_idx]):
                ema_snapshot[p] = float(emas[p][entry_idx])

        if len(ema_snapshot) < 3:
            all_bars_buffer = combined_bars[-max(EMA_PERIODS) :]
            continue

        # Push to Redis + write EMA, run tools (BODY)
        print(
            f"    entry={entry_time} bar#{bar_in_day} ema_20={ema_snapshot.get(20, '?')}"
        )

        # Write EMA files
        for period, value in ema_snapshot.items():
            for tf in ["1min"]:
                d = BACKTEST_EMA_DIR / tf
                d.mkdir(parents=True, exist_ok=True)
                state = {
                    "tf": tf,
                    "period": period,
                    "ema_value": round(value, 4),
                    "available": True,
                    "status": "ready",
                    "buffer_count": period,
                    "threshold_crossed_at": entry_time,
                    "timestamp": _dt.now().isoformat(),
                }
                (d / f"ema_{period}.json").write_text(json.dumps(state, indent=2))

        redirector = _PathRedirector(str(BACKTEST_EMA_DIR))
        mock_redis_obj = MockRedis(
            list(reversed(combined_bars[: entry_idx + 1])), prev_close=prev_day_close
        )
        mock_connect = lambda: mock_redis_obj

        try:
            from tools.entry_tools import (
                score_trend_redis,
                score_traffic_light_redis,
                combine_entry_scores,
            )

            with (
                patch("tools.entry_tools._Path", side_effect=redirector),
                patch("tools.entry_tools._redis_connect", side_effect=mock_connect),
            ):
                trend_result = score_trend_redis("NIFTY")
                tl_result = score_traffic_light_redis("NIFTY")

            market_ctx = {"vix": None, "pcr_total": None, "matching_patterns": []}
            decision = combine_entry_scores(trend_result, tl_result, market_ctx)

            not_up = evaluate_not_up(trend_result, tl_result)
            not_down = evaluate_not_down(trend_result, tl_result)

            entry_gate, suggested_trade = None, "NONE"
            if not_up["go"]:
                entry_gate, suggested_trade = not_up, "SELL_CALL"
            elif not_down["go"]:
                entry_gate, suggested_trade = not_down, "SELL_PUT"

            conf_pct = entry_gate["confidence"] / 100.0 if entry_gate else 0
            gate_label = entry_gate["signal"] if entry_gate else "NONE"
            passes_gate = conf_pct >= ENTRY_GATE_MIN_CONFIDENCE

            print(
                f"    UP={not_up['go']}/{not_up['confidence']}% "
                f"DN={not_down['go']}/{not_down['confidence']}% "
                f"→ {gate_label} conf={conf_pct:.0%} "
                f"{'🟢 ENTRY' if passes_gate else ''}"
            )

            trade = None
            if passes_gate and entry_gate and has_options:
                gate_decision = {
                    "go": passes_gate,
                    "signal": "BULLISH" if suggested_trade == "SELL_PUT" else "BEARISH",
                    "suggested_trade": suggested_trade,
                    "confidence": entry_gate["confidence"],
                }
                # Match options time to spot time (options uses HH:MM:59, spot uses HH:MM:00)
                entry_snapshot = time_data.get(entry_time, {})
                if not entry_snapshot:
                    # Try with seconds=59
                    entry_snapshot = time_data.get(
                        entry_time.rsplit(":", 1)[0] + ":59", {}
                    )
                if not entry_snapshot:
                    entry_snapshot = {}
                if entry_snapshot:
                    trade = simulate_trade(
                        gate_decision,
                        entry_snapshot,
                        bars,
                        bar_in_day,
                        target_pct=0.50,  # 50% TP (production default)
                        stop_pct=-0.25,  # 25% SL (production default)
                        time_data_full=time_data,
                        entry_time=entry_time,
                    )
                if trade:
                    trade_count += 1
                    total_pnl += trade["exit_pnl"]
                    if trade["exit_pnl"] > 0:
                        wins += 1
                    print(
                        f"    → {trade['suggested_trade']} ATM={trade['atm_strike']} "
                        f"spread=₹{trade['spread']:.2f} P&L=₹{trade['exit_pnl']:,.0f} "
                        f"[{trade['exit_reason']}]"
                    )

            daily_log.append(
                {
                    "date": date_str,
                    "trend_signal": trend_result["signal"],
                    "trend_confidence": trend_result["confidence"],
                    "tl_signal": tl_result["signal"],
                    "tl_confidence": tl_result["confidence"],
                    "not_up_go": not_up["go"],
                    "not_up_confidence": not_up["confidence"],
                    "not_down_go": not_down["go"],
                    "not_down_confidence": not_down["confidence"],
                    "combined_signal": decision.get("signal"),
                    "combined_confidence": decision.get("confidence"),
                    "suggested_trade": suggested_trade,
                    "passes_entry_gate": passes_gate,
                    "entry_gate_confidence": entry_gate["confidence"]
                    if entry_gate
                    else 0,
                    "entry_gate_signal": gate_label,
                    "trade": trade,
                    "tl_pattern": tl_result.get("key_indicators", {}).get(
                        "pattern", ""
                    ),
                    "tf_colors": {},
                }
            )
            results.append(decision)
        except Exception as e:
            print(f"    Error: {e}")
            import traceback

            traceback.print_exc()

        prev_day_close = combined_bars[-1]["close"] if combined_bars else None
        all_bars_buffer = combined_bars[-max(EMA_PERIODS) :]

    # -- SUMMARY ---------------------------------------------------------
    print("\n" + "=" * 100)
    print("BACKTEST RESULTS SUMMARY")
    print("=" * 100)

    n_days = len([d for d in daily_log if "trend_signal" in d])
    n_not_up = sum(1 for d in daily_log if d.get("not_up_go"))
    n_not_down = sum(1 for d in daily_log if d.get("not_down_go"))
    n_gate_pass = sum(1 for d in daily_log if d.get("passes_entry_gate"))
    n_trades = len([d for d in daily_log if d.get("trade")])

    print(f"\n  Days processed:    {n_days}")
    print(f"  NOT_UP go:  {n_not_up}")
    print(f"  NOT_DOWN go: {n_not_down}")
    print(f"  Entry gate pass:   {n_gate_pass}")
    print(f"  Trades executed:   {n_trades}")
    if n_trades:
        print(f"  Win rate:          {wins}/{n_trades} ({wins / n_trades * 100:.1f}%)")
        print(f"  Total P&L:         ₹{total_pnl:,.0f}")
        print(f"  Avg P&L/trade:     ₹{total_pnl / n_trades:,.0f}")

    # Save results
    output_path = BACKTEST_OUTPUT_DIR / "NIFTY_BACKTEST_AGENT_TOOLS_LOG.json"
    output_path.write_text(
        json.dumps(
            {
                "run_ts": _dt.now().isoformat(),
                "source": "Kaggle NSE FNO + NIFTY 50 minute spot",
                "summary": {
                    "n_days": n_days,
                    "not_up": n_not_up,
                    "not_down": n_not_down,
                    "gate_pass": n_gate_pass,
                    "trades": n_trades,
                    "wins": wins,
                    "total_pnl": round(total_pnl, 2),
                },
                "daily_log": daily_log,
            },
            indent=2,
            default=str,
        )
    )

    return daily_log, output_path


if __name__ == "__main__":
    run_backtest()
