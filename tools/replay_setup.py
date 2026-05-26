#!/usr/bin/env python3
"""
Replay Setup — prepare a sandbox for time-machine replay.

Clones production DuckDBs, initializes fresh state, pre-computes EMAs.

Usage:
  python3 tools/replay_setup.py 2026-05-25 --index NIFTY
  python3 tools/replay_setup.py 2026-05-25 --index SENSEX
"""

import argparse
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

DUCKDB_SOURCES = {
    "NIFTY": {
        "v31": "/home/trading_ceo/python-trader/varaha/data/varaha_data.duckdb",
        "multitf": "/home/trading_ceo/python-trader/varaha/data/market_data_multitf_nifty.duckdb",
    },
    "SENSEX": {
        "v31": "/home/trading_ceo/python-trader/varaha/data/varaha_data_sensex.duckdb",
        "multitf": "/home/trading_ceo/python-trader/varaha/data/market_data_multitf_sensex.duckdb",
    },
}

TRADE_EXECUTION_DB = "/home/trading_ceo/brahmand/data/trade_execution.duckdb"
BRAHMAND_STATE_DIR = Path("/home/trading_ceo/brahmand/data")
ANTARIKSH_STATE = "/home/trading_ceo/antariksh/logs/entry_check_latest.json"
SIGNALS_FILE = "/tmp/entry_signals.jsonl"


def _copy_file(src: str, dst: Path):
    if not Path(src).exists():
        print(f"  SKIP {src} (does not exist)")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    print(f"  COPY {src} → {dst} ({os.path.getsize(src) / 1024 / 1024:.0f}MB)")
    shutil.copy2(src, dst)


def _copy_tree(src: Path, dst: Path):
    if not src.exists():
        return
    shutil.copytree(src, dst, dirs_exist_ok=True)


def _init_fresh_trade_execution(dst: Path):
    import duckdb

    db = duckdb.connect(str(dst), read_only=False)
    db.execute("""
        CREATE TABLE IF NOT EXISTS active_trades (
            trade_id TEXT PRIMARY KEY, chain_run_id TEXT, index_name TEXT,
            leg_type TEXT, direction TEXT, strike INTEGER, expiry TEXT,
            entry_price DOUBLE, entry_timestamp TEXT, current_ltp DOUBLE,
            stop_loss DOUBLE, target DOUBLE, status TEXT,
            strat_entry_signal TEXT, strat_entry_score DOUBLE,
            morph_stage INTEGER DEFAULT 0, morph_target_strike INTEGER,
            morph_completed BOOLEAN DEFAULT FALSE,
            notes TEXT, updated_at TEXT
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS trade_history (
            trade_id TEXT, timestamp TEXT, spot DOUBLE, ltp DOUBLE,
            position_pnl DOUBLE, action TEXT, details TEXT
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS monitoring_log (
            trade_id TEXT, timestamp TEXT, event_type TEXT,
            spot DOUBLE, pnl DOUBLE, morph_stage INTEGER, leg_count INTEGER,
            risk_flags TEXT, details TEXT
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS order_ledger (
            trade_id TEXT, timestamp TEXT, order_type TEXT, leg_type TEXT,
            strike INTEGER, direction TEXT, quantity INTEGER, price DOUBLE,
            status TEXT, broker_order_id TEXT, reason TEXT, pnl_impact DOUBLE
        )
    """)
    db.close()


def _precompute_emas(sandbox: Path, replay_date: str, index: str):
    """Pre-compute EMA states from historical DuckDB data up to day before replay_date."""
    import duckdb

    v31 = (
        sandbox / f"varaha_data{'_sensex' if index.upper() == 'SENSEX' else ''}.duckdb"
    )
    ema_dir = sandbox / "data" / "ema_state"
    ema_dir.mkdir(parents=True, exist_ok=True)

    if not v31.exists():
        print(f"  SKIP EMA precompute — no v31 DB at {v31}")
        return

    db = duckdb.connect(str(v31), read_only=True)

    prev_day = (
        datetime.strptime(replay_date, "%Y-%m-%d") - timedelta(days=1)
    ).strftime("%Y-%m-%d")
    rows = (
        db.execute(f"""
        SELECT timestamp, close FROM (
            SELECT timestamp, spot AS close FROM market_data
            WHERE date <= '{prev_day}' AND index_name = '{index.upper()}' AND spot IS NOT NULL
            ORDER BY timestamp DESC
        )
    """).fetchall()
        if db
        else []
    )

    if not rows:
        rows = (
            db.execute(f"""
            SELECT timestamp, close FROM (
                SELECT timestamp, spot AS close FROM market_data
                WHERE date <= '{prev_day}' AND spot IS NOT NULL
                ORDER BY timestamp DESC LIMIT 5000
            )
        """).fetchall()
            if db
            else []
        )
    db.close()

    if not rows:
        print("  SKIP EMA precompute — no historical data found")
        return

    reverses = list(reversed(rows))
    print(
        f"  EMA pre-compute: {len(reverses)} bars from {reverses[0][0][:10]} to {reverses[-1][0][:10]}"
    )

    os.environ["BRAHMAND_SANDBOX"] = str(sandbox)
    from ema_aggregator import reset_ema, update_ema

    reset_ema()

    for ts, close in reverses:
        close = float(close)
        update_ema(close, tf="1min")
        dt = datetime.fromisoformat(ts)

        if dt.minute % 5 == 0:
            update_ema(close, tf="5min")
        if dt.minute % 15 == 0:
            update_ema(close, tf="15min")
        if dt.minute % 60 == 0:
            update_ema(close, tf="60min")

        if dt.time().hour == 15 and dt.time().minute == 30:
            update_ema(close, tf="1D")

    print(f"  EMA pre-compute complete — {ema_dir}")


def setup(date_str: str, index: str):
    sandbox = (
        Path("/home/trading_ceo/brahmand/data/replays") / f"{date_str}_{index.upper()}"
    )
    if sandbox.exists():
        print(f"Sandbox already exists: {sandbox}")
        print("Delete it or use a different date.")
        return sandbox

    sandbox.mkdir(parents=True)
    (sandbox / "data").mkdir()
    (sandbox / "state").mkdir()
    (sandbox / "logs").mkdir()
    (sandbox / "trace").mkdir()

    print(f"\n{'=' * 60}")
    print(f"Replay Setup: {date_str} {index.upper()}")
    print(f"Sandbox: {sandbox}")
    print(f"{'=' * 60}\n")

    # ── 1. Clone DuckDB files ──
    print("[1/5] Cloning DuckDB files...")
    cfg = DUCKDB_SOURCES[index.upper()]
    v31_dst = sandbox / Path(cfg["v31"]).name
    _copy_file(cfg["v31"], v31_dst)
    _copy_file(cfg["multitf"], sandbox / Path(cfg["multitf"]).name)

    # ── 2. Fresh trade execution DB ──
    print("[2/5] Initializing fresh trade_execution.duckdb...")
    _init_fresh_trade_execution(sandbox / "state" / "trade_execution.duckdb")
    print("  OK — empty trade_execution.duckdb with schema")

    # ── 3. Fresh state files ──
    print("[3/5] Initializing fresh state...")
    state = {
        "pid": os.getpid(),
        "last_run": None,
        "active_trade": None,
        "trades_today": [],
        "replay": True,
        "replay_date": date_str,
        "replay_index": index.upper(),
    }
    (sandbox / "state" / "brahmand_kickoff.json").write_text(
        json.dumps(state, indent=2)
    )
    (sandbox / "state" / "order_ledger.json").write_text(
        json.dumps({"orders": [], "trades": []}, indent=2)
    )
    print("  OK — fresh kickoff state + order ledger")

    # ── 4. Pre-compute EMAs ──
    print("[4/5] Pre-computing EMAs...")
    _precompute_emas(sandbox, date_str, index)

    # ── 5. Write manifest ──
    print("[5/5] Writing manifest...")
    manifest = {
        "date": date_str,
        "index": index.upper(),
        "sandbox": str(sandbox),
        "created": datetime.now().isoformat(),
        "db_sources": {k: str(Path(v).name) for k, v in cfg.items()},
        "bar_count": None,
    }
    # Count bars
    import duckdb

    db = duckdb.connect(str(v31_dst), read_only=True)
    n = db.execute(
        f"SELECT COUNT(*) FROM market_data WHERE date = '{date_str}' AND index_name = '{index.upper()}'"
    ).fetchone()[0]
    db.close()
    manifest["bar_count"] = n
    (sandbox / "manifest.json").write_text(json.dumps(manifest, indent=2))

    print(f"\n{'=' * 60}")
    print(f"Setup complete. {n} bars available for {date_str}")
    print(f"Sandbox: {sandbox}")
    print(f"Ready: python3 tools/replay_session.py {sandbox}")
    print(f"{'=' * 60}\n")

    return sandbox


def main():
    parser = argparse.ArgumentParser(description="Replay Setup — sandbox preparation")
    parser.add_argument("date", help="Date to replay (YYYY-MM-DD)")
    parser.add_argument("--index", default="NIFTY", choices=["NIFTY", "SENSEX"])
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).parent.parent))
    setup(args.date, args.index)


if __name__ == "__main__":
    main()
