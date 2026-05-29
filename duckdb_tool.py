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
import os
import time
from pathlib import Path
from typing import Type, Optional

import duckdb
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

_SANDBOX = os.environ.get("BRAHMAND_SANDBOX", "")
VARAH_DATA = (
    Path(_SANDBOX) / "varaha_data.duckdb"
    if _SANDBOX
    else Path("/home/trading_ceo/python-trader/varaha/data/varaha_data.duckdb")
)
STATIC_DB = Path("/home/trading_ceo/antariksh/data/static_metadata.db")


_CAPTURE_DIR = Path("/home/trading_ceo/python-trader/varaha/data")


def _is_market_hours() -> bool:
    from datetime import datetime, timezone, timedelta

    IST = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(IST)
    h, m = now.hour, now.minute
    t = h * 60 + m
    return 555 <= t <= 1410


def _resolve_db_path() -> str:
    """If today's Penguin EOD warehouse exists, use it. Else legacy DuckDB."""
    from datetime import date

    warehouse = Path(
        f"/home/trading_ceo/research/{date.today().isoformat()}/nifty.duckdb"
    )
    if warehouse.exists():
        return str(warehouse)
    return str(VARAH_DATA)


def _connect_sqlite_intraday() -> duckdb.DuckDBPyConnection | None:
    """During market hours, read from live Penguin SQLite via sqlite_scanner."""
    sqlite_path = _CAPTURE_DIR / "capture_nifty.sqlite"
    if not sqlite_path.exists():
        return None

    try:
        con = duckdb.connect(":memory:")
        con.execute("INSTALL sqlite_scanner; LOAD sqlite_scanner;")
        src = str(sqlite_path.resolve())
        enr_src = src

        con.execute(f"""
            CREATE VIEW market_data AS
            SELECT
                timestamp,
                substr(timestamp, 1, 10) AS date,
                substr(timestamp, 12, 8) AS time,
                instrument AS index_name,
                close AS spot,
                open AS open_price,
                high AS intraday_high,
                low AS intraday_low,
                volume,
                ltp,
                e.india_vix, e.vwap, e.prev_close, e.atm_strike,
                e.ema_5, e.ema_20, e.ema_50,
                e.supertrend_value, e.supertrend_direction,
                e.adx, e.atr, e.rsi,
                e.bb_pct_b, e.bb_width, e.ema20_slope,
                e.gap_pct, e.prev_day_high, e.prev_day_low, e.prev_day_range,
                e.pivot_pp, e.pivot_r1, e.pivot_r2, e.pivot_r3,
                e.pivot_s1, e.pivot_s2, e.pivot_s3,
                e.fib_0, e.fib_236, e.fib_382, e.fib_50, e.fib_618, e.fib_786, e.fib_100,
                e.open_range_high, e.open_range_low,
                e.iv_current, e.iv_52w_high, e.iv_52w_low, e.iv_rank, e.iv_regime,
                e.iv_short, e.iv_long, e.iv_slope, e.hv_20, e.hv_60,
                e.agg_delta, e.agg_gamma, e.agg_vega, e.agg_theta,
                e.wings_delta, e.body_delta,
                e.pcr_total, e.pcr_atm, e.sentiment, e.max_pain_strike,
                e.call_oi_concentration, e.put_oi_concentration, e.oi_skew,
                e.ob_zone_high, e.ob_zone_low, e.ob_strength,
                e.fvg_high, e.fvg_low, e.fvg_mitigated,
                e.swing_high, e.swing_low, e.liquidity_swept,
                e.structure_type, e.structure_confirmed, e.next_target, e.smc_strength,
                e.cluster_support, e.cluster_resistance,
                e.distance_to_support, e.distance_to_resistance,
                e.st_5min_value, e.st_5min_direction,
                e.st_15min_value, e.st_15min_direction, e.st_consensus,
                e.session_phase, e.open_to_current_pct,
                e.distance_to_pivot_pct, e.distance_to_r1_pct, e.distance_to_s1_pct
            FROM sqlite_scan('{src}', 'market_data') m
            LEFT JOIN sqlite_scan('{enr_src}', 'market_data_enriched') e
                ON m.timestamp = e.timestamp AND m.instrument = e.instrument
        """)
        return con
    except Exception:
        return None


def _connect() -> duckdb.DuckDBPyConnection:
    """Open read-only DuckDB connection with concurrent access.
    Priority: Penguin SQLite (intraday) → Penguin warehouse → legacy DuckDB."""
    if _is_market_hours():
        con = _connect_sqlite_intraday()
        if con is not None:
            return con

    db_path = _resolve_db_path()
    for attempt in range(30):
        try:
            con = duckdb.connect(db_path, read_only=True)
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
