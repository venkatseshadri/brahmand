#!/usr/bin/env python3
"""SuperTrend(15m) vs current EMA20(15m) entry state — same precision/lift
methodology as reverse_move_analysis.py, so the two are directly comparable.

Reuses the REAL SuperTrend implementation (antariksh/enrichers/lib/supertrend.py,
period=10, multiplier=3.0 — live defaults, "lifted verbatim from
varaha_multiframe_supertrend.py"), not a reimplementation.

Usage (from brahmand/):
    python3 -m backtest.sherpa.reverse_move_analysis_supertrend --start 2024-01-01 --end 2024-12-31
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, "/home/trading_ceo/projects/antariksh")

from backtest.sherpa import data_loader
from enrichers.lib.supertrend import _calculate_supertrend

BRAHMAND = Path(__file__).resolve().parent.parent.parent
HORIZONS_MIN = [5, 15, 30, 60]
MOVE_THRESHOLD = 50.0
ST_PERIOD = 10
ST_MULTIPLIER = 3.0


def resample_ohlc(df: pd.DataFrame, minutes: int) -> pd.DataFrame:
    g = df.resample(f"{minutes}min", origin="start_day", offset="15min")
    return pd.DataFrame({
        "high": g["high"].max(), "low": g["low"].min(), "close": g["close"].last(),
    }).dropna()


def st_state_series(tf_df: pd.DataFrame) -> pd.Series:
    _, direction = _calculate_supertrend(
        tf_df["high"].to_numpy(), tf_df["low"].to_numpy(), tf_df["close"].to_numpy(),
        ST_PERIOD, ST_MULTIPLIER,
    )
    state = pd.Series("NEUTRAL", index=tf_df.index)
    state[direction > 0] = "BULLISH"
    state[direction < 0] = "BEARISH"
    return state


def analyze(start: str, end: str) -> list:
    warmup_start = (pd.Timestamp(start) - pd.Timedelta(days=90)).date().isoformat()
    nifty = data_loader.load_nifty(warmup_start, end)

    tf_df = resample_ohlc(nifty, 15)
    state = st_state_series(tf_df)
    state_1m = state.shift(1).reindex(nifty.index, method="ffill")

    eval_idx = nifty.loc[str(start):str(end)].index
    eval_idx = eval_idx[
        (eval_idx.time >= pd.Timestamp("09:20").time())
        & (eval_idx.time <= pd.Timestamp("15:20").time())
    ]

    results = []
    for h in HORIZONS_MIN:
        fwd_move = (nifty["close"].shift(-h) - nifty["close"]).reindex(eval_idx)
        st = state_1m.reindex(eval_idx)
        valid = fwd_move.notna() & st.notna()
        fwd_move, st = fwd_move[valid], st[valid]

        n = len(fwd_move)
        base_up = (fwd_move >= MOVE_THRESHOLD).mean()
        base_down = (fwd_move <= -MOVE_THRESHOLD).mean()
        bull_mask, bear_mask = st == "BULLISH", st == "BEARISH"
        n_bull, n_bear = int(bull_mask.sum()), int(bear_mask.sum())
        prec_up_bull = (fwd_move[bull_mask] >= MOVE_THRESHOLD).mean() if n_bull else None
        prec_down_bear = (fwd_move[bear_mask] <= -MOVE_THRESHOLD).mean() if n_bear else None
        wrong_down_bull = (fwd_move[bull_mask] <= -MOVE_THRESHOLD).mean() if n_bull else None
        wrong_up_bear = (fwd_move[bear_mask] >= MOVE_THRESHOLD).mean() if n_bear else None

        results.append({
            "indicator": "SuperTrend(15m)", "horizon_min": h, "n": n,
            "base_rate_up_ge50": round(base_up, 4), "base_rate_down_ge50": round(base_down, 4),
            "n_bullish_states": n_bull, "n_bearish_states": n_bear,
            "precision_up_given_bullish": round(prec_up_bull, 4) if prec_up_bull is not None else None,
            "precision_down_given_bearish": round(prec_down_bear, 4) if prec_down_bear is not None else None,
            "wrong_direction_given_bullish": round(wrong_down_bull, 4) if wrong_down_bull is not None else None,
            "wrong_direction_given_bearish": round(wrong_up_bear, 4) if wrong_up_bear is not None else None,
            "lift_up": round(prec_up_bull / base_up, 2) if prec_up_bull and base_up else None,
            "lift_down": round(prec_down_bear / base_down, 2) if prec_down_bear and base_down else None,
        })
    return results


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    a = p.parse_args()
    results = analyze(a.start, a.end)

    print(f"{'Ind':>16} {'Hzn':>4} {'n':>7} | {'base_up':>7} {'base_dn':>7} | "
          f"{'P(up|BULL)':>10} {'lift':>5} | {'P(dn|BEAR)':>10} {'lift':>5} | "
          f"{'wrong|BULL':>10} {'wrong|BEAR':>10}")
    for r in results:
        print(f"{r['indicator']:>16} {r['horizon_min']:>4} {r['n']:>7} | "
              f"{r['base_rate_up_ge50']:>7.4f} {r['base_rate_down_ge50']:>7.4f} | "
              f"{str(r['precision_up_given_bullish']):>10} {str(r['lift_up']):>5} | "
              f"{str(r['precision_down_given_bearish']):>10} {str(r['lift_down']):>5} | "
              f"{str(r['wrong_direction_given_bullish']):>10} {str(r['wrong_direction_given_bearish']):>10}")

    out = BRAHMAND / "backtest" / "sherpa" / f"reverse_move_report_supertrend_{a.start}_{a.end}.json"
    out.write_text(json.dumps(results, indent=2))
    print(f"\nfull report -> {out}")


if __name__ == "__main__":
    main()
