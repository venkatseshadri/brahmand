"""
Native SQLite market data module — reads Penguin capture_nifty.sqlite directly.

Replaces duckdb_tool for Entry Agent, Regime Agent, and Strategy Agent queries.
Post-mortem and research agents still use duckdb_tool (needs option_snapshots, backtest).
"""

import sqlite3
import json
import os
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from typing import Optional

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

_SANDBOX = os.environ.get("BRAHMAND_SANDBOX", "")
if _SANDBOX:
    _CAPTURE_DIR = Path(_SANDBOX)
else:
    _CAPTURE_DIR = Path("/home/trading_ceo/python-trader/varaha/data")

_IST = timezone(timedelta(hours=5, minutes=30))


def _is_market_hours() -> bool:
    now = datetime.now(_IST)
    t = now.hour * 60 + now.minute
    return 555 <= t <= 1410


def _sqlite_path() -> Path:
    return _CAPTURE_DIR / "capture_nifty.sqlite"


def _connect() -> sqlite3.Connection:
    db = _sqlite_path()
    if not db.exists():
        raise FileNotFoundError(f"Penguin SQLite not found: {db}")
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    return conn


def get_latest_market_snapshot() -> dict:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT m.*, e.* FROM market_data m "
            "LEFT JOIN market_data_enriched e "
            "ON m.timestamp = e.timestamp AND m.instrument = e.instrument "
            "ORDER BY m.timestamp DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return {}
        d = dict(row)
        d["spot"] = d["close"]
        d["date"] = d["timestamp"][:10] if d.get("timestamp") else ""
        d["time"] = d["timestamp"][11:19] if d.get("timestamp") else ""
        return {k: str(v) for k, v in d.items() if v is not None}
    finally:
        conn.close()


class _MarketDataQueryInput(BaseModel):
    query: str = Field(description="Natural language query about market conditions")


class MarketDataQueryTool(BaseTool):
    name: str = "query_market_data"
    description: str = (
        "Query Penguin SQLite market data. Returns OHLCV bars, indicators (ADX, "
        "RSI, VIX, SuperTrend, EMA), pivot levels, fibs, OI data, PCR, IV rank, "
        "sentiment for the most recent bars. Use for regime detection (VIX, ADX) "
        "and strategy selection (trend strength, volatility)."
    )
    args_schema: type[BaseModel] = _MarketDataQueryInput

    def _run(self, query: str = "") -> str:
        if not _sqlite_path().exists():
            return json.dumps({"error": "Penguin SQLite not available"})

        try:
            conn = _connect()
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT m.*, e.* FROM market_data m "
                "LEFT JOIN market_data_enriched e "
                "ON m.timestamp = e.timestamp AND m.instrument = e.instrument "
                "ORDER BY m.timestamp DESC LIMIT 5"
            ).fetchall()
            conn.close()

            if not rows:
                return json.dumps({"error": "No market data in Penguin SQLite"})

            bars = []
            for row in rows:
                d = dict(row)
                bar = {
                    "timestamp": d.get("timestamp", ""),
                    "spot": d.get("close"),
                    "open": d.get("open"),
                    "high": d.get("high"),
                    "low": d.get("low"),
                    "volume": d.get("volume"),
                    "india_vix": d.get("india_vix"),
                    "adx": d.get("adx"),
                    "rsi": d.get("rsi"),
                    "atr": d.get("atr"),
                    "supertrend_value": d.get("supertrend_value"),
                    "supertrend_direction": d.get("supertrend_direction"),
                    "ema_5": d.get("ema_5"),
                    "ema_20": d.get("ema_20"),
                    "ema_50": d.get("ema_50"),
                    "pcr_total": d.get("pcr_total"),
                    "pcr_atm": d.get("pcr_atm"),
                    "iv_current": d.get("iv_current"),
                    "iv_rank": d.get("iv_rank"),
                    "sentiment": d.get("sentiment"),
                    "st_consensus": d.get("st_consensus"),
                    "session_phase": d.get("session_phase"),
                    "gap_pct": d.get("gap_pct"),
                }
                bars.append(bar)

            return json.dumps(
                {"bars": bars, "source": "penguin_sqlite", "count": len(bars)},
                default=str,
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)[:200]})
