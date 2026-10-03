"""Penguin live-data compatibility layer.

Single source of truth for reading the LIVE Penguin capture (`capture_{index}.sqlite`)
through the OLD `varaha_data.duckdb` table/column names, so legacy readers migrate by
swapping their connection — not rewriting their SQL.

Builds two DuckDB views over the SQLite capture via `sqlite_scanner`:
  - `market_data`      : old 90+ col schema, sourced from market_data ⋈ market_data_enriched
  - `option_snapshots` : old per-strike schema, sourced from option_prices

See brahmand/READER_MIGRATION_MAP.md for the full mapping and the OI/IV gap.
"""

from pathlib import Path

import duckdb

_DATA_DIR = Path("/home/trading_ceo/projects/varaha/data")

# Maps capture_{index}.sqlite onto the old varaha_data.duckdb `market_data` column names.
# Based solely on market_data_enriched (e) — the analytical twin of the old market_data,
# fully populated and free of the empty/forming candles in raw market_data. (The old v3.1
# market_data table carried no volume/ltp, so no migrated reader needs the raw OHLCV table;
# OHLCV+volume lives in the multitf source.) Same shape for live capture and EOD warehouse.
_MARKET_DATA_VIEW_SQL = """
    CREATE VIEW market_data AS
    SELECT
        e.timestamp,
        substr(e.timestamp, 1, 10) AS date,
        substr(e.timestamp, 12, 8) AS time,
        e.instrument AS index_name,
        e.spot, e.futures, e.open_price, e.prev_close, e.atm_strike,
        e.expiry_weekly, e.days_to_weekly, e.expiry_next_weekly, e.days_to_next_weekly,
        e.expiry_monthly, e.days_to_monthly,
        e.india_vix, e.vwap,
        e.ema_5, e.ema_20, e.ema_50,
        e.supertrend_value, e.supertrend_direction,
        e.adx, e.atr, e.rsi,
        e.bb_pct_b, e.bb_width, e.ema20_slope,
        e.gap_pct, e.prev_day_high, e.prev_day_low, e.prev_day_range,
        e.intraday_high, e.intraday_low,
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
        e.distance_to_pivot_pct, e.distance_to_r1_pct, e.distance_to_s1_pct,
        e.data_source, e.buffer_bars
    FROM {enr} e
"""

# Maps option_prices onto the old `option_snapshots` schema. oi/volume are passed
# through when the capture has them (added 2026-06-03); iv is always NULL — Shoonya
# does not transmit per-strike IV, it must be computed. See READER_MIGRATION_MAP.md §4.
_OPTION_SNAPSHOTS_VIEW_SQL = """
    CREATE VIEW option_snapshots AS
    SELECT
        tsym,
        strike,
        option_type,
        ltp,
        timestamp,
        {volume} AS volume,
        {oi} AS oi,
        CAST(NULL AS DOUBLE) AS iv
    FROM {opt}
"""


def _build_views(con, enr: str, opt: str = None, opt_cols: set = None) -> None:
    """Create the compat views from already-resolvable table references.
    `enr` = market_data_enriched ref; `opt` = option_prices ref (None for sources
    without an option table, e.g. the EOD warehouse). `opt_cols` = columns present
    in the option table, so oi/volume pass through only when captured."""
    con.execute(_MARKET_DATA_VIEW_SQL.format(enr=enr))
    if opt:
        cols = opt_cols or set()
        con.execute(
            _OPTION_SNAPSHOTS_VIEW_SQL.format(
                opt=opt,
                volume="volume" if "volume" in cols else "CAST(NULL AS DOUBLE)",
                oi="oi" if "oi" in cols else "CAST(NULL AS DOUBLE)",
            )
        )


def attach_views(con: duckdb.DuckDBPyConnection, sqlite_path: Path) -> None:
    """Create `market_data` + `option_snapshots` compat views over a Penguin SQLite capture."""
    con.execute("INSTALL sqlite_scanner; LOAD sqlite_scanner;")
    src = str(Path(sqlite_path).resolve())

    def scan(tbl):
        return f"sqlite_scan('{src}', '{tbl}')"

    opt_cols = {
        d[0] for d in con.execute(f"SELECT * FROM {scan('option_prices')} LIMIT 0").description
    }
    _build_views(con, scan("market_data_enriched"), scan("option_prices"), opt_cols)


def capture_path(index: str) -> Path:
    return _DATA_DIR / f"capture_{index.lower()}.sqlite"


def warehouse_path(index: str, date: str) -> Path:
    return Path(f"/home/trading_ceo/projects/research/{date}/{index.lower()}.duckdb")


def connect_live(index: str) -> duckdb.DuckDBPyConnection:
    """In-memory DuckDB connection exposing the live Penguin capture for `index`
    through the legacy `market_data` / `option_snapshots` view names.

    Raises FileNotFoundError if the capture file is missing.
    """
    sqlite_path = capture_path(index)
    if not sqlite_path.exists():
        raise FileNotFoundError(f"Penguin capture not found: {sqlite_path}")
    con = duckdb.connect(":memory:")
    attach_views(con, sqlite_path)
    return con


def connect_research(index: str, date: str) -> duckdb.DuckDBPyConnection:
    """Connection exposing the legacy `market_data` view for a given `date`.
    Prefers the Penguin EOD warehouse (research/{date}/{index}.duckdb); falls back
    to today's live capture. The warehouse has no option table, so `option_snapshots`
    is only available when this resolves to the live capture.

    Raises FileNotFoundError if neither source exists for `date`.
    """
    from datetime import date as _date

    wh = warehouse_path(index, date)
    if wh.exists():
        con = duckdb.connect(":memory:")
        con.execute(f"ATTACH '{wh.resolve()}' AS wh (READ_ONLY)")
        _build_views(con, "wh.market_data_enriched")
        return con
    if date == _date.today().isoformat():
        return connect_live(index)
    raise FileNotFoundError(f"No Penguin warehouse for {index} on {date}: {wh}")
