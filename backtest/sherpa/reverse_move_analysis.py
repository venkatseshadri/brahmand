#!/usr/bin/env python3
"""Reverse-analysis: find every NIFTY 50+pt move, check what each timeframe's
EMA-trend state and ADX looked like BEFORE it — a real precision/base-rate
table instead of hand-tuned entry_weights.json thresholds.

Answers: does any (timeframe, lookback horizon) combo actually have
directional predictive power on real 2024 data, and does moving to a
higher TF genuinely reduce whipsaw noise vs just producing a slower,
equally-wrong signal?

Usage (from brahmand/):
    python3 -m backtest.sherpa.reverse_move_analysis --start 2024-01-01 --end 2024-12-31
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from backtest.sherpa import data_loader

BRAHMAND = Path(__file__).resolve().parent.parent.parent
TFS_MIN = {"5m": 5, "15m": 15, "30m": 30, "60m": 60, "240m": 240, "1440m": 1440}
HORIZONS_MIN = [5, 15, 30, 60]
MOVE_THRESHOLD = 50.0


def resample_ohlc(df: pd.DataFrame, minutes: int) -> pd.DataFrame:
    g = df.resample(f"{minutes}min", origin="start_day", offset="15min")
    out = pd.DataFrame({
        "open": g["open"].first(), "high": g["high"].max(),
        "low": g["low"].min(), "close": g["close"].last(),
    }).dropna()
    return out


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr = pd.concat([
        high - low, (high - close.shift()).abs(), (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False).mean()


def tf_trend_state(tf_df: pd.DataFrame) -> pd.Series:
    """BULLISH/BEARISH/NEUTRAL from EMA20 vs close (EMA20 = dominant weight
    in the live entry_weights.json trend score — weight 1.0 vs 0.25/0.75/0/0)."""
    e20 = ema(tf_df["close"], 20)
    diff_pct = (tf_df["close"] - e20) / tf_df["close"] * 100
    state = pd.Series("NEUTRAL", index=tf_df.index)
    state[diff_pct > 0.05] = "BULLISH"
    state[diff_pct < -0.05] = "BEARISH"
    return state


def analyze(start: str, end: str) -> dict:
    warmup_start = (pd.Timestamp(start) - pd.Timedelta(days=90)).date().isoformat()
    nifty = data_loader.load_nifty(warmup_start, end)

    results = []
    for tf_name, tf_min in TFS_MIN.items():
        tf_df = resample_ohlc(nifty, tf_min)
        state = tf_trend_state(tf_df)
        tf_adx = adx(tf_df)
        adx_trending = tf_adx > 25

        # forward-fill TF state onto the 1-min index (as-of last completed TF bar,
        # shifted by 1 bar to avoid using the bar's own still-forming close)
        state_1m = state.shift(1).reindex(nifty.index, method="ffill")
        adx_1m = adx_trending.shift(1).reindex(nifty.index, method="ffill")

        day_mask = (nifty.index.time >= pd.Timestamp("09:20").time()) & (
            nifty.index.time <= pd.Timestamp("15:20").time()
        )
        eval_idx = nifty.loc[str(start):str(end)].index
        eval_idx = eval_idx[
            (eval_idx.time >= pd.Timestamp("09:20").time())
            & (eval_idx.time <= pd.Timestamp("15:20").time())
        ]

        for h in HORIZONS_MIN:
            fwd_close = nifty["close"].shift(-h)
            fwd_move = (fwd_close - nifty["close"]).reindex(eval_idx)
            st = state_1m.reindex(eval_idx)
            adxt = adx_1m.reindex(eval_idx)
            valid = fwd_move.notna() & st.notna()
            fwd_move, st, adxt = fwd_move[valid], st[valid], adxt[valid]

            n = len(fwd_move)
            base_up = (fwd_move >= MOVE_THRESHOLD).mean()
            base_down = (fwd_move <= -MOVE_THRESHOLD).mean()

            bull_mask = st == "BULLISH"
            bear_mask = st == "BEARISH"
            n_bull, n_bear = int(bull_mask.sum()), int(bear_mask.sum())
            prec_up_given_bull = (
                (fwd_move[bull_mask] >= MOVE_THRESHOLD).mean() if n_bull else None
            )
            prec_down_given_bear = (
                (fwd_move[bear_mask] <= -MOVE_THRESHOLD).mean() if n_bear else None
            )
            wrong_down_given_bull = (
                (fwd_move[bull_mask] <= -MOVE_THRESHOLD).mean() if n_bull else None
            )
            wrong_up_given_bear = (
                (fwd_move[bear_mask] >= MOVE_THRESHOLD).mean() if n_bear else None
            )

            # same, but only when ADX confirms "trending" regime
            bull_trend_mask = bull_mask & adxt
            bear_trend_mask = bear_mask & adxt
            n_bull_t, n_bear_t = int(bull_trend_mask.sum()), int(bear_trend_mask.sum())
            prec_up_bull_adx = (
                (fwd_move[bull_trend_mask] >= MOVE_THRESHOLD).mean() if n_bull_t else None
            )
            prec_down_bear_adx = (
                (fwd_move[bear_trend_mask] <= -MOVE_THRESHOLD).mean() if n_bear_t else None
            )

            results.append({
                "tf": tf_name, "horizon_min": h, "n": n,
                "base_rate_up_ge50": round(base_up, 4), "base_rate_down_ge50": round(base_down, 4),
                "n_bullish_states": n_bull, "n_bearish_states": n_bear,
                "precision_up_given_bullish": round(prec_up_given_bull, 4) if prec_up_given_bull is not None else None,
                "precision_down_given_bearish": round(prec_down_given_bear, 4) if prec_down_given_bear is not None else None,
                "wrong_direction_given_bullish": round(wrong_down_given_bull, 4) if wrong_down_given_bull is not None else None,
                "wrong_direction_given_bearish": round(wrong_up_given_bear, 4) if wrong_up_given_bear is not None else None,
                "lift_up": round(prec_up_given_bull / base_up, 2) if prec_up_given_bull and base_up else None,
                "lift_down": round(prec_down_given_bear / base_down, 2) if prec_down_given_bear and base_down else None,
                "n_bullish_adx_trending": n_bull_t, "n_bearish_adx_trending": n_bear_t,
                "precision_up_given_bullish_adx_trending": round(prec_up_bull_adx, 4) if prec_up_bull_adx is not None else None,
                "precision_down_given_bearish_adx_trending": round(prec_down_bear_adx, 4) if prec_down_bear_adx is not None else None,
                "lift_up_adx": round(prec_up_bull_adx / base_up, 2) if prec_up_bull_adx and base_up else None,
                "lift_down_adx": round(prec_down_bear_adx / base_down, 2) if prec_down_bear_adx and base_down else None,
            })

    return {"period": f"{start}..{end}", "move_threshold_pts": MOVE_THRESHOLD, "results": results}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--out", default=None)
    a = p.parse_args()
    report = analyze(a.start, a.end)
    out = Path(a.out) if a.out else BRAHMAND / "backtest" / "sherpa" / f"reverse_move_report_{a.start}_{a.end}.json"
    out.write_text(json.dumps(report, indent=2))

    print(f"{'TF':>6} {'Hzn':>4} {'n':>7} | {'base_up':>7} {'base_dn':>7} | "
          f"{'P(up|BULL)':>10} {'lift':>5} | {'P(dn|BEAR)':>10} {'lift':>5} | "
          f"{'wrong|BULL':>10} {'wrong|BEAR':>10}")
    for r in report["results"]:
        print(f"{r['tf']:>6} {r['horizon_min']:>4} {r['n']:>7} | "
              f"{r['base_rate_up_ge50']:>7.4f} {r['base_rate_down_ge50']:>7.4f} | "
              f"{str(r['precision_up_given_bullish']):>10} {str(r['lift_up']):>5} | "
              f"{str(r['precision_down_given_bearish']):>10} {str(r['lift_down']):>5} | "
              f"{str(r['wrong_direction_given_bullish']):>10} {str(r['wrong_direction_given_bearish']):>10}")
    print(f"\nfull report -> {out}")


if __name__ == "__main__":
    main()
