#!/usr/bin/env python3
"""SHERPA Phase 2 — historical data loader (Kaggle NIFTY-50 + INDIA VIX minute bars)."""

from datetime import date
from pathlib import Path

import pandas as pd

KAGGLE_DIR = Path(
    "/root/.cache/kagglehub/datasets/debashis74017/nifty-50-minute-data/versions/18"
)
NIFTY_CSV = KAGGLE_DIR / "NIFTY 50_minute.csv"
VIX_CSV = KAGGLE_DIR / "INDIA VIX_minute.csv"


def load_minute_csv(path: Path, start: str, end: str) -> pd.DataFrame:
    """Minute bars indexed by timestamp, [start, end] inclusive (YYYY-MM-DD)."""
    df = pd.read_csv(path, parse_dates=["date"])
    df = df.rename(columns={"date": "ts"}).set_index("ts").sort_index()
    return df.loc[start : end + " 23:59"]


def load_nifty(start: str, end: str) -> pd.DataFrame:
    return load_minute_csv(NIFTY_CSV, start, end)


def load_vix(start: str, end: str) -> pd.Series:
    """Minute-level VIX close, forward-fillable lookup."""
    return load_minute_csv(VIX_CSV, start, end)["close"]


def trading_days(df: pd.DataFrame) -> list[date]:
    return sorted({ts.date() for ts in df.index})


def day_bars(df: pd.DataFrame, d: date) -> pd.DataFrame:
    return df.loc[str(d)]


def resample_60m(df: pd.DataFrame) -> pd.DataFrame:
    """Completed 60-min bars (NSE hours start 09:15, so offset to bar grid)."""
    g = df.resample("60min", origin="start_day", offset="15min")
    out = pd.DataFrame(
        {
            "open": g["open"].first(),
            "high": g["high"].max(),
            "low": g["low"].min(),
            "close": g["close"].last(),
        }
    ).dropna()
    return out


def vix_at(vix: pd.Series, ts) -> float | None:
    """Latest VIX at or before ts (None if nothing prior)."""
    s = vix.loc[:ts]
    return float(s.iloc[-1]) if len(s) else None
