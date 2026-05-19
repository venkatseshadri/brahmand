#!/usr/bin/env python3
"""
Pattern Enricher — adds multi-TF traffic light pattern + forward outcomes to v4 DuckDB.

For every bar in market_data_multitf, computes:
  - candle: GREEN (close > open) or RED per TF
  - gap: current_open vs prev_close (gap_pct) — new info
  - 6-TF pattern: e.g. "GRGRGG" (1440m→5m, daily first)
  - forward outcomes: spot_change at 5m, 15m, 1h, 4h, daily horizons

Stores in: market_data_patterns table (new)

Usage:
  python3 pattern_enricher.py              # enrich last 500 bars
  python3 pattern_enricher.py --live       # run continuously, enrich new bars every 5 min
  python3 pattern_enricher.py --all        # enrich ALL historical bars
"""

import sys, os, json, time, logging
from pathlib import Path
from datetime import datetime
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent / "python-trader"))

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s"
)
logger = logging.getLogger("PatternEnricher")

V4_DB = Path("/home/trading_ceo/python-trader/varaha/data/market_data_multitf.duckdb")

# TF order: highest TF first (daily → 5m)
TF_ORDER = [
    (1440, "1440m"),
    (240, "240m"),
    (60, "60m"),
    (30, "30m"),
    (15, "15m"),
    (5, "5m"),
]

# Outcome horizons: how far forward to check spot change
OUTCOME_HORIZONS = {
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "EOD": None,  # special: same-day close
    "1D": None,  # special: next-day close
}


def init_pattern_table(db):
    """Create market_data_patterns table if not exists."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS market_data_patterns (
            timestamp      VARCHAR,
            index_name     VARCHAR,
            pattern        VARCHAR,       -- e.g. "GRGRGG" (1440m→5m)
            gap_pct        FLOAT,         -- open vs prev_close %
            spot           FLOAT,         -- latest close = spot proxy
            candle_1440m   VARCHAR,
            candle_240m    VARCHAR,
            candle_60m     VARCHAR,
            candle_30m     VARCHAR,
            candle_15m     VARCHAR,
            candle_5m      VARCHAR,
            fwd_5m         FLOAT,         -- spot change % after 5 min
            fwd_15m        FLOAT,         -- spot change % after 15 min
            fwd_30m        FLOAT,
            fwd_1h         FLOAT,
            fwd_4h         FLOAT,
            fwd_EOD        FLOAT,         -- spot change % to same-day close
            fwd_1D         FLOAT,         -- spot change % to next-day close
            enriched_at    VARCHAR,
            UNIQUE(timestamp, index_name)
        )
    """)
    db.commit()


def get_latest_bar_per_tf(db, index: str = "NIFTY", max_age_min: int = 30) -> dict:
    """Get latest bar for each TF within the last N minutes."""
    bars = {}
    for tf_min, tf_label in TF_ORDER:
        row = db.execute(
            """SELECT timestamp, open, high, low, close
               FROM market_data_multitf
               WHERE index_name = ? AND timeframe_min = ?
               ORDER BY timestamp DESC LIMIT 1""",
            (index, tf_min),
        ).fetchone()
        if row:
            bars[tf_label] = {
                "timestamp": row[0],
                "open": row[1],
                "high": row[2],
                "low": row[3],
                "close": row[4],
            }
    return bars


def compute_pattern(bars: dict) -> str:
    """Build 6-char pattern string: daily first. G=GREEN, R=RED."""
    pattern = ""
    for _, tf_label in TF_ORDER:
        b = bars.get(tf_label, {})
        o, c = b.get("open"), b.get("close")
        if o and c:
            pattern += "G" if c > o else "R"
        else:
            pattern += "-"
    return pattern


def compute_gap(bars: dict) -> Optional[float]:
    """Compute gap_pct from 5m open vs previous bar's close."""
    b = bars.get("5m", {})
    o, c = b.get("open"), b.get("close")
    # Gap = (current_open - prev_close) / prev_close * 100
    # prev_close from previous bar — need to query it
    return None  # Requires previous bar lookup, implement in live mode


def compute_forward_outcomes(db, timestamp: str, index: str, spot: float) -> dict:
    """Compute forward spot changes at each horizon using timestamp lookahead."""
    from datetime import datetime as dt, timedelta

    try:
        base_time = dt.fromisoformat(timestamp)
    except (ValueError, TypeError):
        return {}

    outcomes = {}
    # ── Intraday horizons: 5m, 15m, 30m, 1h, 4h ──
    for label, mins in [("5m", 5), ("15m", 15), ("30m", 30), ("1h", 60), ("4h", 240)]:
        target = base_time + timedelta(minutes=mins)
        wstart = (target - timedelta(minutes=3)).isoformat()
        wend = (target + timedelta(minutes=3)).isoformat()
        row = db.execute(
            """SELECT close FROM market_data_multitf
               WHERE index_name = ? AND timeframe_min = 5
               AND timestamp >= ? AND timestamp <= ?
               ORDER BY timestamp ASC LIMIT 1""",
            (index, wstart, wend),
        ).fetchone()
        if row and row[0] and spot > 0:
            outcomes[f"fwd_{label}"] = round((float(row[0]) - spot) / spot * 100, 4)
        else:
            outcomes[f"fwd_{label}"] = None

    # ── EOD: same-day close (daily bar close for this date) ──
    date_str = base_time.strftime("%Y-%m-%d")
    row = db.execute(
        """SELECT close FROM market_data_multitf
           WHERE index_name = ? AND timeframe_min = 1440
           AND timestamp LIKE ?
           ORDER BY timestamp DESC LIMIT 1""",
        (index, f"{date_str}%"),
    ).fetchone()
    if row and row[0] and spot > 0:
        outcomes["fwd_EOD"] = round((float(row[0]) - spot) / spot * 100, 4)
    else:
        outcomes["fwd_EOD"] = None

    # ── 1D: NEXT trading day's daily bar close ──
    # Find the next distinct date with a daily bar
    row = db.execute(
        """SELECT close FROM market_data_multitf
           WHERE index_name = ? AND timeframe_min = 1440
           AND SUBSTR(timestamp, 1, 10) > ?
           ORDER BY timestamp ASC LIMIT 1""",
        (index, date_str),
    ).fetchone()
    if row and row[0] and spot > 0:
        outcomes["fwd_1D"] = round((float(row[0]) - spot) / spot * 100, 4)
    else:
        outcomes["fwd_1D"] = None

    return outcomes


def enrich_bars(db, index: str = "NIFTY", limit: int = 500):
    """Enrich the last N bars with pattern + outcomes."""
    init_pattern_table(db)

    # Get timestamps for the latest 5m bars
    timestamps = db.execute(
        """SELECT DISTINCT timestamp FROM market_data_multitf
           WHERE index_name = ? AND timeframe_min = 5
           ORDER BY timestamp DESC LIMIT ?""",
        (index, limit),
    ).fetchall()

    enriched = 0
    for (ts,) in timestamps:
        # Check if already enriched
        exists = db.execute(
            "SELECT 1 FROM market_data_patterns WHERE timestamp = ? AND index_name = ?",
            (ts, index),
        ).fetchone()
        if exists:
            continue

        # Get bars at this timestamp for all TFs
        spot = None
        bars = {}
        for tf_min, tf_label in TF_ORDER:
            row = db.execute(
                """SELECT open, high, low, close FROM market_data_multitf
                   WHERE index_name = ? AND timeframe_min = ? AND timestamp = ? LIMIT 1""",
                (index, tf_min, ts),
            ).fetchone()
            if row:
                bars[tf_label] = {
                    "open": row[0],
                    "high": row[1],
                    "low": row[2],
                    "close": row[3],
                }
                spot = row[3] if spot is None else spot  # use 5m close as spot

        if not spot or len(bars) < 3:
            continue

        pattern = compute_pattern(bars)
        outcomes = compute_forward_outcomes(db, ts, index, spot)

        db.execute(
            """INSERT OR IGNORE INTO market_data_patterns
               (timestamp, index_name, pattern, spot,
                candle_1440m, candle_240m, candle_60m, candle_30m, candle_15m, candle_5m,
                fwd_5m, fwd_15m, fwd_30m, fwd_1h, fwd_4h, fwd_EOD, fwd_1D, enriched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                ts,
                index,
                pattern,
                spot,
                pattern[0] if len(pattern) > 0 else "-",
                pattern[1] if len(pattern) > 1 else "-",
                pattern[2] if len(pattern) > 2 else "-",
                pattern[3] if len(pattern) > 3 else "-",
                pattern[4] if len(pattern) > 4 else "-",
                pattern[5] if len(pattern) > 5 else "-",
                outcomes.get("fwd_5m"),
                outcomes.get("fwd_15m"),
                outcomes.get("fwd_30m"),
                outcomes.get("fwd_1h"),
                outcomes.get("fwd_4h"),
                outcomes.get("fwd_EOD"),
                outcomes.get("fwd_1D"),
                datetime.now().isoformat(),
            ),
        )
        enriched += 1

    db.commit()
    logger.info(f"Enriched {enriched}/{len(timestamps)} patterns")


def init_trade_outcomes_table(db):
    """Create trade_outcomes table for pattern→P&L correlation."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS trade_outcomes (
            entry_time     VARCHAR,
            exit_time      VARCHAR,
            index_name     VARCHAR,
            pattern        VARCHAR,
            strategy       VARCHAR,
            wing_width     INTEGER,
            net_credit     FLOAT,
            pnl            FLOAT,
            exit_reason    VARCHAR,
            trend_signal   VARCHAR,
            tl_signal      VARCHAR,
            entry_confidence INTEGER,
            enriched_at    VARCHAR
        )
    """)
    db.commit()


def log_trade_pattern(trade: dict) -> bool:
    """
    Link a closed trade to its entry-time pattern.
    Called from kickoff.py exit_trade() after a trade closes.

    Writes to trade_outcomes table for probability-based pattern analysis.
    """
    import duckdb

    try:
        db = duckdb.connect(str(V4_DB))
        init_trade_outcomes_table(db)

        entry_time = trade.get("entry_time", trade.get("monitored_since", ""))
        exit_time = trade.get("exit_time", "")
        pnl = trade.get("pnl", 0)
        strategy = trade.get("strategy_type", "UNKNOWN")
        wing = trade.get("wing_width", trade.get("legs", [{}])[0].get("wing_width", 0))
        net_credit = trade.get("net_credit", 0)
        exit_reason = trade.get("exit_reason", "UNKNOWN")

        es = trade.get("entry_scores", {})
        trend_sig = es.get("trend_signal") or es.get("entry_trend_signal") or "?"
        tl_sig = es.get("traffic_light_signal") or es.get("entry_traffic_light_signal") or "?"
        conf = es.get("confidence", 0) or es.get("entry_combined_confidence", 0)

        # ── Look up pattern by querying raw bars at nearest timestamp ──
        from datetime import datetime as dt, timedelta

        try:
            date_row = db.execute(
                "SELECT SUBSTR(MAX(timestamp), 1, 10) FROM market_data_patterns"
            ).fetchone()
            trade_date = date_row[0] if date_row else dt.now().strftime("%Y-%m-%d")
            entry_dt = dt.fromisoformat(f"{trade_date}T{entry_time}:00")

            # Build pattern from raw bars closest to entry time (within ±7 min)
            tf_order = [
                (1440, "1440m"),
                (240, "240m"),
                (60, "60m"),
                (30, "30m"),
                (15, "15m"),
                (5, "5m"),
            ]
            pattern = ""
            for tf_min, _ in tf_order:
                row = db.execute(
                    """SELECT open, close FROM market_data_multitf
                       WHERE index_name = 'NIFTY' AND timeframe_min = ?
                       AND timestamp >= ? AND timestamp <= ?
                       ORDER BY timestamp DESC LIMIT 1""",
                    (
                        tf_min,
                        (entry_dt - timedelta(minutes=7)).isoformat(),
                        (entry_dt + timedelta(minutes=7)).isoformat(),
                    ),
                ).fetchone()
                if row and row[0] and row[1]:
                    pattern += "G" if row[1] > row[0] else "R"
                else:
                    pattern += "-"

            pattern = pattern if pattern and "-" not in pattern else "partial"
        except Exception:
            pattern = "unknown"

        db.execute(
            """INSERT INTO trade_outcomes
               (entry_time, exit_time, index_name, pattern, strategy, wing_width,
                net_credit, pnl, exit_reason, trend_signal, tl_signal,
                entry_confidence, enriched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry_time,
                exit_time,
                "NIFTY",
                pattern,
                strategy,
                wing,
                net_credit,
                pnl,
                exit_reason,
                trend_sig,
                tl_sig,
                conf,
                datetime.now().isoformat(),
            ),
        )
        db.commit()
        db.close()
        logger.info(f"Trade→Pattern logged: {pattern} | P&L ₹{pnl}")
        return True
    except Exception as e:
        logger.warning(f"Trade→Pattern logging failed: {e}")
        return False


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()

    import duckdb

    if args.all:
        args.limit = 100000

    if args.live:
        logger.info("Live mode — enriching every 5 min (new connection per cycle)")
        while True:
            try:
                # Create fresh connection for each cycle to avoid lock conflicts
                db = duckdb.connect(str(V4_DB))
                enrich_bars(db, limit=50)
                db.close()
            except Exception as e:
                logger.warning(f"Enrichment cycle failed: {str(e)[:100]}")
            time.sleep(300)
    else:
        db = duckdb.connect(str(V4_DB))
        enrich_bars(db, limit=args.limit)
        db.close()


if __name__ == "__main__":
    main()
