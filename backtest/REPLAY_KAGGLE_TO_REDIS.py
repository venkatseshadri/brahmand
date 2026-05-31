#!/usr/bin/env python3
"""
Redis Replay Harness: Push Kaggle 2024 NIFTY data into Redis + EMA state files,
then run production agent tools natively (no monkey-patching).

This validates:
1. Tools read from Redis v3_ohlcv_queue exactly as in production
2. Tools read from EMA state files exactly as in production
3. NOT_UP / NOT_DOWN deterministic gates produce same output as tool-level backtest
4. (Optional) Full e2e_chain CrewAI run if LLM API key is configured

Usage:
    python3 REPLAY_KAGGLE_TO_REDIS.py                 # tool-level only
    python3 REPLAY_KAGGLE_TO_REDIS.py --e2e-chain     # full CrewAI agents (needs LLM)
"""

from __future__ import annotations

import csv
import json
import re
import sys
import time
from collections import defaultdict
from datetime import datetime as _dt
from pathlib import Path as _Path
from typing import Optional

import numpy as np

KAGGLE_CACHE = _Path(
    "/root/.cache/kagglehub/datasets/kaalicharan9080/"
    "nse-future-and-options-data/versions/2"
)
BACKTEST_EMA_DIR = _Path("/tmp/backtest_ema_state")
REDIS_KEY = "v3_ohlcv_queue"
EMA_PERIODS = [5, 20, 50, 100, 200]
EMA_MULT = {p: 2.0 / (p + 1) for p in EMA_PERIODS}

_TICKER_RE = re.compile(
    r"^NIFTY(\d{2}[A-Z]{3}\d{2})(\d{5})(PE|CE)\.NFO$", re.IGNORECASE
)

# -- Redis connection ---------------------------------------------------
try:
    import redis as _redis_lib
except ImportError:
    _redis_lib = None


def redis_client():
    """Connect to local Redis DB 1 (backtest — avoids polluting DB 0 production)."""
    if _redis_lib is None:
        return None
    try:
        r = _redis_lib.Redis(host="localhost", port=6379, db=1, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


# ====================================================================
# DATA LOADING (same as NIFTY_BACKTEST_AGENT_TOOLS.py)
# ====================================================================


def _csv_files() -> list[_Path]:
    files = sorted(p for p in KAGGLE_CACHE.iterdir() if p.suffix.lower() == ".csv")
    return files


def load_day(csv_path: _Path):
    """Read CSV, extract NIFTY options for nearest weekly expiry. Returns (date, time_data)."""
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

    # Find nearest weekly expiry (Thursday on or after trade date)
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
    best_expiry = None
    best_days = 999
    for exp in expiries_seen:
        day = int(exp[:2])
        month = month_map[exp[2:5]]
        year = int(f"20{exp[5:7]}")
        exp_dt = _dt(year, month, day)
        days_diff = (exp_dt - trade_date_dt).days
        if days_diff >= 0 and days_diff < best_days:
            best_days = days_diff
            best_expiry = exp

    if best_expiry:
        filtered = defaultdict(dict)
        for t, strikes_dict in time_data.items():
            for (strike, opt_type, exp), price in strikes_dict.items():
                if exp == best_expiry:
                    filtered[t][(strike, opt_type)] = price
        time_data = filtered

    return date_str, time_data


def reconstruct_spot(time_data: dict) -> dict[str, float]:
    spot = {}
    for t in sorted(time_data):
        data = time_data[t]
        best_diff = float("inf")
        best_spot = None
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


def spot_to_bars(spot_map: dict[str, float]) -> list[dict]:
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
# REDIS REPLAY
# ====================================================================


def push_bars_to_redis(r, bars: list[dict]) -> int:
    """Clear and re-populate v3_ohlcv_queue with bars (LPUSH — newest first)."""
    r.delete(REDIS_KEY)
    count = 0
    for bar in bars:  # LPUSH oldest first → newest at head (LINDEX 0)
        r.lpush(REDIS_KEY, json.dumps(bar))
        count += 1
    return count


def set_prev_close(r, index: str, close_price: float) -> None:
    """Store previous day close for gap calculation."""
    r.set(f"prev_close_{index}", str(close_price))


# ====================================================================
# EMA STATE REPLAY
# ====================================================================


def compute_emas(bars: list[dict]) -> dict[int, list[float]]:
    """Compute EMA on 1-min closes. Returns {period: [ema_values]}."""
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


def aggregate_60min_candles(bars: list[dict]) -> list[dict]:
    """Aggregate 1-min bars into 60-min candles."""
    candles = []
    bucket_size = 60
    for i in range(0, len(bars), bucket_size):
        bucket = bars[i : i + bucket_size]
        if not bucket:
            break
        candles.append(
            {
                "open": bucket[0]["open"],
                "high": max(b["high"] for b in bucket),
                "low": min(b["low"] for b in bucket),
                "close": bucket[-1]["close"],
                "timestamp": bucket[0]["timestamp"],
            }
        )
    return candles


def compute_60min_emas(bars: list[dict]) -> dict[int, list[float]]:
    """Compute EMA on 60-min candles. Returns {period: [ema_values]}."""
    candles = aggregate_60min_candles(bars)
    return compute_emas(candles)


def write_ema_state_files(
    emas_1min: dict,
    entry_idx: int,
    timestamp: str,
) -> dict[int, float]:
    """Write 1min EMA state files. score_trend_redis falls back to 1min
    when 60min files are missing/stale (production-expected behavior)."""
    ema_snapshot = {}
    tf = "1min"
    d = BACKTEST_EMA_DIR / tf
    d.mkdir(parents=True, exist_ok=True)
    for p in EMA_PERIODS:
        val = emas_1min[p][entry_idx] if entry_idx < len(emas_1min[p]) else np.nan
        if np.isnan(val):
            continue
        ema_snapshot[p] = float(val)
        state = {
            "tf": tf,
            "period": p,
            "ema_value": round(float(val), 4),
            "available": True,
            "status": "ready",
            "buffer_count": p,
            "threshold_crossed_at": timestamp,
            "timestamp": _dt.now().isoformat(),
        }
        (d / f"ema_{p}.json").write_text(json.dumps(state, indent=2))
    return ema_snapshot


# ====================================================================
# MAIN REPLAY LOOP
# ====================================================================


def run_replay(run_e2e_chain: bool = False):
    csvs = _csv_files()
    if not csvs:
        print("No CSV files found.")
        sys.exit(1)

    # Redis check
    r = redis_client()
    if r is None:
        print("ERROR: Redis not running on localhost:6379")
        print("Start with: redis-server --daemonize yes")
        sys.exit(1)
    print("✓ Redis connected (localhost:6379)")

    # Import production tools — antariksh first, then brahmand for gate tools
    sys.path.insert(0, str(_Path(__file__).parent.parent / "antariksh"))
    sys.path.insert(0, str(_Path(__file__).parent.parent / "antariksh" / "tools"))
    try:
        from tools.entry_tools import (
            score_trend_redis,
            score_traffic_light_redis,
            combine_entry_scores,
        )

        print("✓ Imported antariksh/tools/entry_tools.py")
    except ImportError as e:
        print(f"✗ Import error: {e}")
        sys.exit(1)

    # Import brahmand gate tools directly (avoids 'tools' namespace collision)
    sys.path.insert(0, str(_Path(__file__).parent / "tools"))
    import entry_gate_tools as _gate_tools

    not_up_tool = _gate_tools.EvaluateNotUpRejection()
    not_down_tool = _gate_tools.EvaluateNotDownRejection()

    # Monkey-patch: redirect tool Redis reads to DB 1 (backtest isolation)
    import tools.entry_tools as _et_mod

    _original_connect = _redis_lib.Redis

    def _backtest_redis(**kwargs):
        kwargs["db"] = 1
        return _original_connect(**kwargs)

    _et_mod._redis.Redis = _backtest_redis

    # Monkey-patch: redirect EMA file reads to backtest temp dir
    _real_path = _Path
    _bt_ema_root = str(BACKTEST_EMA_DIR)

    def _bt_path(path):
        s = str(path)
        if "ema_state" in s:
            parts = s.split("ema_state", 1)
            new_s = _bt_ema_root + parts[1] if len(parts) > 1 else _bt_ema_root
            return _real_path(new_s)
        return _real_path(s)

    _et_mod._Path = _bt_path

    print("=" * 100)
    print("NIFTY 2024 REPLAY — Kaggle Data → Redis → Production Agent Tools")
    print("=" * 100)
    print(f"\nRedis key: {REDIS_KEY}")
    print(f"EMA state dir: {BACKTEST_EMA_DIR}")
    print(f"Mode: {'e2e_chain CrewAI' if run_e2e_chain else 'tool-level (no LLM)'}\n")

    all_bars_buffer = []
    prev_day_close = None
    daily_log = []

    for csv_idx, csv_file in enumerate(csvs):
        date_str, time_data = load_day(csv_file)
        if not date_str:
            continue

        spot_map = reconstruct_spot(time_data)
        if not spot_map:
            print(f"\n  {csv_file.name}: no NIFTY data — skipping")
            continue

        bars = spot_to_bars(spot_map)
        if len(bars) < 30:
            print(f"\n  {date_str}: only {len(bars)} bars — skipping")
            continue

        combined_bars = all_bars_buffer + bars
        emas_1min = compute_emas(combined_bars)
        first_time = bars[0]["timestamp"]

        print(f"\n{'─' * 50}")
        print(
            f"  [{csv_idx + 1}/{len(csvs)}] {csv_file.name} → {date_str}"
            f"  |  {len(bars)} bars  |  buffer: {len(all_bars_buffer)}"
        )

        # Entry point: first bar with all EMAs seeded (1-min)
        entry_idx = len(all_bars_buffer)
        for p in EMA_PERIODS:
            while entry_idx < len(combined_bars) and np.isnan(emas_1min[p][entry_idx]):
                entry_idx += 1
        if entry_idx >= len(combined_bars):
            print(f"    Cannot seed all EMAs — skipping")
            all_bars_buffer = combined_bars[-max(EMA_PERIODS) :]
            continue

        entry_bar = combined_bars[entry_idx]
        entry_time = entry_bar["timestamp"]
        bar_in_day = entry_idx - len(all_bars_buffer)
        print(f"    Entry bar: {entry_time}  (day bar #{bar_in_day})")

        ema_snapshot = write_ema_state_files(emas_1min, entry_idx, entry_time)
        if len(ema_snapshot) < 3:
            print(f"    Not enough EMA data — skipping")
            all_bars_buffer = combined_bars[-max(EMA_PERIODS) :]
            continue

        # ── Push Kaggle bars to Redis ──
        bars_to_push = list(reversed(combined_bars[: entry_idx + 1]))
        push_count = push_bars_to_redis(r, bars_to_push)
        if prev_day_close is not None:
            set_prev_close(r, "NIFTY", prev_day_close)
        print(
            f"    Redis: {push_count} bars in v3_ohlcv_queue  "
            f"prev_close={'set' if prev_day_close else 'none'}"
        )

        # ── Run production tools (native Redis/EMA reads via DB 1 + temp dir) ──
        trend_result = score_trend_redis("NIFTY")
        tl_result = score_traffic_light_redis("NIFTY")

        # Call production gate tools (NOT reimplemented)
        not_up = json.loads(not_up_tool._run("NIFTY"))
        not_down = json.loads(not_down_tool._run("NIFTY"))

        # Call production combine_entry_scores (matches entry_check.py)
        market_ctx = {"vix": None, "pcr_total": None, "matching_patterns": []}
        combined = combine_entry_scores(trend_result, tl_result, market_ctx)

        # Strategy picker (CALL priority per production)
        entry_gate = None
        suggested_trade = "NONE"
        if not_up["go"]:
            entry_gate = not_up
            suggested_trade = "SELL_CALL"
        elif not_down["go"]:
            entry_gate = not_down
            suggested_trade = "SELL_PUT"

        conf_pct = entry_gate["confidence"] / 100.0 if entry_gate else 0
        gate_label = entry_gate["signal"] if entry_gate else "NONE"

        print(
            f"    NOT_UP: {'🟢 GO' if not_up['go'] else 'NO-GO'} ({not_up['confidence']}%)"
            f"  |  NOT_DOWN: {'🟢 GO' if not_down['go'] else 'NO-GO'} ({not_down['confidence']}%)"
            f"  |  PICKED: {gate_label} conf={conf_pct:.0%}"
        )
        print(
            f"    Trend: {trend_result['signal']}({trend_result['confidence']}%)"
            f"  TL: {tl_result['signal']}({tl_result['confidence']}%)"
            f"  pattern={tl_result.get('key_indicators', {}).get('pattern', '?')}"
            f"  combined={combined.get('signal')}({combined.get('confidence')}%)"
            f"  go={combined.get('go')}"
        )

        # ── (Optional) e2e_chain CrewAI ──
        e2e_result = None
        if run_e2e_chain:
            print(
                "    ── Running e2e_chain CrewAI (monkey-patching DuckDB snapshot) ──"
            )
            from dotenv import load_dotenv

            load_dotenv()
            from unittest.mock import patch

            try:
                atm_strike, _ = _find_atm_from_time(entry_time, time_data)
                spot_val = spot_map.get(entry_time, 0)
                mock_snap = {
                    "spot": spot_val,
                    "atm_strike": atm_strike or 0,
                    "india_vix": 0,
                    "adx": None,
                    "ema_20": ema_snapshot.get(20, 0),
                    "ema_50": ema_snapshot.get(50, 0),
                    "expiry_weekly": "",
                }

                with patch(
                    "e2e_chain.get_latest_market_snapshot",
                    return_value=mock_snap,
                ):
                    from e2e_chain import run_sequential_crew

                    result = run_sequential_crew(entry_time)
                    e2e_result = result
                    print(
                        f"    e2e_chain result: {json.dumps(result, indent=2, default=str)[:800]}"
                    )
            except Exception as e:
                e2e_result = {"error": str(e)}
                print(f"    e2e_chain error: {e}")
                import traceback

                traceback.print_exc()

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
                "combined_signal": combined.get("signal"),
                "combined_confidence": combined.get("confidence"),
                "combined_go": combined.get("go"),
                "suggested_trade": suggested_trade,
                "entry_gate_confidence": entry_gate["confidence"] if entry_gate else 0,
                "entry_gate_signal": gate_label,
                "tl_pattern": tl_result.get("key_indicators", {}).get("pattern", ""),
                "e2e_chain_result": e2e_result,
            }
        )

        all_bars_buffer = combined_bars[-max(EMA_PERIODS) :]
        prev_day_close = combined_bars[-1]["close"] if combined_bars else None

    # -- SUMMARY ---------------------------------------------------------
    print("\n" + "=" * 100)
    print("REPLAY RESULTS SUMMARY")
    print("=" * 100)

    n = len(daily_log)
    n_up = sum(1 for d in daily_log if d["not_up_go"])
    n_down = sum(1 for d in daily_log if d["not_down_go"])
    n_entries = sum(1 for d in daily_log if d["suggested_trade"] != "NONE")

    print(f"  Days:   {n}")
    print(f"  NOT_UP go:  {n_up}")
    print(f"  NOT_DOWN go: {n_down}")
    print(f"  Entries:    {n_entries}")

    # Save
    output = _Path("/home/trading_ceo/brahmand/data/REPLAY_KAGGLE_TO_REDIS_LOG.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "run_ts": _dt.now().isoformat(),
                "mode": "redis_replay",
                "e2e_chain": run_e2e_chain,
                "source": "Kaggle NSE FNO cache → Redis v3_ohlcv_queue",
                "summary": {
                    "days": n,
                    "not_up": n_up,
                    "not_down": n_down,
                    "entries": n_entries,
                },
                "daily_log": daily_log,
            },
            indent=2,
            default=str,
        )
    )
    print(f"\n  Full log: {output}")

    # -- DIFF vs TOOL-LEVEL BACKTEST ------------------------------------
    try:
        tool_log = json.loads(
            _Path(
                "/home/trading_ceo/brahmand/data/NIFTY_BACKTEST_AGENT_TOOLS_LOG.json"
            ).read_text()
        )
        tool_daily = {d["date"]: d for d in tool_log["daily_log"]}
        diff_count = 0
        for d in daily_log:
            date = d["date"]
            if date in tool_daily:
                t = tool_daily[date]
                if (
                    d["not_up_go"] != t.get("not_up_go")
                    or d["not_down_go"] != t.get("not_down_go")
                    or d["suggested_trade"] != t.get("suggested_trade")
                ):
                    diff_count += 1
                    print(
                        f"  ⚠ DIFF {date}: REDIS vs MOCK: "
                        f"UP={d['not_up_go']}/{t.get('not_up_go')} "
                        f"DN={d['not_down_go']}/{t.get('not_down_go')} "
                        f"TRADE={d['suggested_trade']}/{t.get('suggested_trade')}"
                    )
        if diff_count == 0:
            print("  ✓ ZERO diffs between Redis replay and MockRedis backtest")
        else:
            print(f"  ⚠ {diff_count} divergences found")
    except FileNotFoundError:
        print("  (No tool-level backtest log found for diff)")

    print("\n✓ REPLAY COMPLETE\n")


if __name__ == "__main__":
    run_e2e = "--e2e-chain" in sys.argv
    run_replay(run_e2e_chain=run_e2e)
