"""
DuckDB Market Data Tool — CrewAI Tool for Post-Mortem historical queries.

Queries varaha_data.duckdb (live market data) and static_metadata.db (scrip master).
Cross-references state.db trades against actual market conditions at execution time.

Tables:
- market_data: 90+ columns (VIX, spot, ADX, RSI, Greeks, IV, PCR, SuperTrend)
- option_snapshots: LTP, IV, OI for each option strike+expiry

Used exclusively by the Post-Mortem Agent for trade→market cross-referencing.
"""

import json
import time
from pathlib import Path
from typing import Type, Optional

import duckdb
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

# Paths (same as antariksh's contract_tools.py)
VARAH_DATA = Path("/home/trading_ceo/python-trader/varaha/data/varaha_data.duckdb")
STATIC_DB = Path("/home/trading_ceo/antariksh/data/static_metadata.db")


def _connect() -> duckdb.DuckDBPyConnection:
    """Open read-only DuckDB connection with concurrent access."""
    for attempt in range(30):
        try:
            con = duckdb.connect(str(VARAH_DATA), read_only=True)
            con.execute("PRAGMA enable_progress_bar=false")
            return con
        except Exception:
            if attempt < 29:
                time.sleep(0.5)
    raise IOError("DuckDB locked by capture after 30 retries — skip this cycle")


class MarketDataQueryInput(BaseModel):
    query_type: str = Field(
        default="vix",
        description="What to query: vix, spot, greeks, regime, iv, pcr, sentiment, all.",
    )
    date: str = Field(
        default="",
        description="Date filter as YYYY-MM-DD. Empty = latest available.",
    )
    time_range: str = Field(
        default="",
        description="Time range filter: '09:15-09:30' or '10:30' for exact minute.",
    )


class MarketDataQueryTool(BaseTool):
    name: str = "query_market_data"
    description: str = (
        "Query historical market conditions from DuckDB. "
        "Cross-reference a trade's execution time against actual market data. "
        "\n\nQUERY TYPES:\n"
        "- vix: Returns india_vix at the given time\n"
        "- spot: Returns NIFTY spot price\n"
        "- greeks: Returns agg_delta, agg_gamma, agg_vega, agg_theta\n"
        "- regime: Returns ADX, SuperTrend direction, structure_type\n"
        "- iv: Returns iv_current, iv_rank, iv_regime, iv_52w_high\n"
        "- pcr: Returns pcr_total, pcr_atm, oi_skew, sentiment\n"
        "- volume: vwap, open_range_high, open_range_low, call_oi_concentration, put_oi_concentration, oi_skew, pcr_total, spot\n"
        "- all: Returns all available columns (be specific with date/time)\n\n"
        "Use this to find out: What was VIX when SL was hit? Was ADX trending "
        "or sideways? What was IV rank? This makes Post-Mortem data-driven."
    )
    args_schema: Type[BaseModel] = MarketDataQueryInput

    def _run(
        self,
        query_type: str = "vix",
        date: str = "",
        time_range: str = "",
    ) -> str:
        columns = {
            "vix": "date, time, india_vix",
            "spot": "date, time, spot, open_price, prev_close",
            "greeks": "date, time, agg_delta, agg_gamma, agg_vega, agg_theta, "
            "wings_delta, body_delta",
            "regime": "date, time, adx, supertrend_direction, structure_type, "
            "session_phase, atr, rsi",
            "iv": "date, time, iv_current, iv_rank, iv_regime, iv_52w_high, "
            "iv_52w_low, iv_short, iv_long",
            "pcr": "date, time, pcr_total, pcr_atm, sentiment, oi_skew, max_pain_strike",
            "ema": "date, time, spot, ema_5, ema_20, ema_50",
            "full_regime": "date, time, spot, atm_strike, india_vix, adx, "
            "supertrend_direction, st_15min_direction, ema_20, ema_50, "
            "iv_current, iv_rank, rsi, structure_type, session_phase",
            "volume": "date, time, spot, vwap, open_range_high, open_range_low, "
            "call_oi_concentration, put_oi_concentration, oi_skew, pcr_total, "
            "intraday_high, intraday_low",
            "all": "*",
        }

        col = columns.get(query_type, "date, time, india_vix, spot, adx, iv_current")
        where = []
        if date:
            where.append(f"date = '{date}'")
        if time_range:
            if "-" in time_range:
                t_start, t_end = time_range.split("-")
                where.append(f"time >= '{t_start}' AND time <= '{t_end}'")
            else:
                where.append(f"time = '{time_range}'")

        where_clause = " AND ".join(where) if where else "1=1"

        query = f"""
            SELECT {col}
            FROM market_data
            WHERE {where_clause}
            ORDER BY timestamp DESC
            LIMIT 10
        """

        try:
            con = _connect()
            rows = con.execute(query).fetchall()
            cols = [c[0] for c in con.description]
            result = [dict(zip(cols, [str(v) for v in r])) for r in rows]
            con.close()
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e), "query": query})


class OptionSnapshotQueryInput(BaseModel):
    date: str = Field(
        ...,
        description="Date filter as YYYY-MM-DD. Required.",
    )
    strike: int = Field(
        default=0,
        description="Specific strike to query. 0 = all strikes.",
    )
    option_type: str = Field(
        default="",
        description="CE or PE. Empty = both.",
    )
    time_range: str = Field(
        default="",
        description="Time range: '09:15-09:30' or '10:30' for exact minute.",
    )


class OptionSnapshotQueryTool(BaseTool):
    name: str = "query_option_snapshots"
    description: str = (
        "Query historical option chain data from DuckDB. "
        "Get LTP, IV, OI, volume for specific strikes at specific times. "
        "\n\nUse this to answer: What was the actual premium of the 23600 CE "
        "at 10:30? What was the IV at entry? How did OI move during the trade? "
        "Essential for Post-Mortem premium vs actual market cross-check."
    )
    args_schema: Type[BaseModel] = OptionSnapshotQueryInput

    def _run(
        self,
        date: str,
        strike: int = 0,
        option_type: str = "",
        time_range: str = "",
    ) -> str:
        where = [f"date = '{date}'"]
        if strike > 0:
            where.append(f"strike = {strike}")
        if option_type:
            where.append(f"option_type = '{option_type.upper()}'")
        if time_range:
            if "-" in time_range:
                t_start, t_end = time_range.split("-")
                where.append(
                    f"strftime(CAST(timestamp AS TIMESTAMP), '%H:%M:%S') >= '{t_start}' "
                    f"AND strftime(CAST(timestamp AS TIMESTAMP), '%H:%M:%S') <= '{t_end}'"
                )
            else:
                where.append(
                    f"strftime(CAST(timestamp AS TIMESTAMP), '%H:%M:%S') = '{time_range}'"
                )

        where_clause = " AND ".join(where)

        query = f"""
            SELECT date, strftime(CAST(timestamp AS TIMESTAMP), '%H:%M:%S') as time,
                   strike, option_type, ltp, volume, oi, iv,
                   expiry_label, expiry_date, tsym, strike_offset
            FROM option_snapshots
            WHERE {where_clause}
            ORDER BY timestamp DESC
            LIMIT 20
        """

        try:
            con = _connect()
            rows = con.execute(query).fetchall()
            cols = [c[0] for c in con.description]
            result = [dict(zip(cols, [str(v) for v in r])) for r in rows]
            con.close()
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e), "query": query})


def get_latest_market_snapshot() -> dict:
    """Convenience: return the most recent market_data row."""
    con = _connect()
    try:
        row = con.execute(
            "SELECT * FROM market_data ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        if row:
            cols = [c[0] for c in con.description]
            return dict(zip(cols, [str(v) for v in row]))
        return {}
    finally:
        con.close()
