#!/usr/bin/env python3
"""
Load NIFTY 50 minute-level spot data from Kaggle (+ OHLCV, per minute).
Much higher fidelity than put-call parity reconstruction from options data.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

DATASET_PATH = Path(
    "/root/.cache/kagglehub/datasets/debashis74017/"
    "nifty-50-minute-data/versions/18/NIFTY 50_minute.csv"
)


def load_spot_bars(start: str = "2024-10-01", end: str = "2024-11-01") -> pd.DataFrame:
    """Load NIFTY 50 minute bars for a date range. Returns DataFrame with
    columns: date, open, high, low, close, volume, index."""
    df = pd.read_csv(DATASET_PATH)
    df["date"] = pd.to_datetime(df["date"])
    mask = (df["date"] >= start) & (df["date"] < end)
    df = df[mask].copy()
    df["timestamp"] = df["date"].dt.strftime("%H:%M:%S")
    df["index"] = "NIFTY"
    return df


def bars_to_dicts(df: pd.DataFrame) -> list[dict]:
    """Convert DataFrame to list of dicts matching production bar format."""
    return [
        {
            "timestamp": row.timestamp,
            "date": str(row.date.date()),
            "open": float(row.open),
            "high": float(row.high),
            "low": float(row.low),
            "close": float(row.close),
            "index": "NIFTY",
        }
        for row in df.itertuples()
    ]


def get_bars_by_date(df: pd.DataFrame) -> dict[str, list[dict]]:
    """Group bars by date string. Returns {date_str: [bar_dicts]}."""
    result = {}
    for date_val in df["date"].dt.date.unique():
        day_df = df[df["date"].dt.date == date_val]
        date_str = str(date_val)
        result[date_str] = bars_to_dicts(day_df)
    return result


if __name__ == "__main__":
    df = load_spot_bars()
    by_date = get_bars_by_date(df)
    print(f"Loaded {len(by_date)} trading days, {len(df)} bars")
    for date, bars in sorted(by_date.items()):
        print(
            f"  {date}: {len(bars)} bars, "
            f"open={bars[0]['open']:.0f} close={bars[-1]['close']:.0f} "
            f"high={max(b['high'] for b in bars):.0f} low={min(b['low'] for b in bars):.0f}"
        )
