#!/usr/bin/env python3
"""
Trade Execution DB — Separate DuckDB for order ledger and trade state.

Stores:
  - active_trades: current positions (written by Order Agent)
  - trade_history: closed positions (written by Risk Monitor)
  - monitoring_log: minute-by-minute audit trail (written by Risk Monitor)

Location: /home/trading_ceo/brahmand/data/trade_execution.duckdb
"""

import duckdb
import fcntl
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, List
import json
import os

_SANDBOX = os.environ.get("BRAHMAND_SANDBOX", "")
DB_PATH = (
    Path(_SANDBOX) / "state" / "trade_execution.duckdb"
    if _SANDBOX
    else Path("/home/trading_ceo/brahmand/data/trade_execution.duckdb")
)
_LOCK_PATH = Path(str(DB_PATH) + ".lock")
_LOCK_TIMEOUT_S = 15.0  # max wait for the cross-process lock
_CONNECT_RETRIES = 20
_CONNECT_BACKOFF_S = 0.3


@contextmanager
def _connect():
    """Cross-process-safe DuckDB connection for trade_execution.duckdb.

    DuckDB permits only one read-write process per file, but kickoff (5-min),
    the risk monitor (1-min) and order_agent all write this DB. Each open is
    serialized with an flock mutex (the OS auto-releases it on process exit, so
    there are no stale locks) and retried on the residual IOException race.
    Connections are short-lived: lock -> connect -> work -> close -> unlock.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = open(_LOCK_PATH, "w")
    deadline = time.monotonic() + _LOCK_TIMEOUT_S
    while True:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.monotonic() >= deadline:
                lock_fd.close()
                raise IOError(
                    f"trade_execution.duckdb: lock not acquired in {_LOCK_TIMEOUT_S}s"
                )
            time.sleep(0.2)

    conn = None
    try:
        last_err = None
        for _ in range(_CONNECT_RETRIES):
            try:
                conn = duckdb.connect(str(DB_PATH))
                break
            except Exception as e:  # residual DuckDB-level lock race
                last_err = e
                time.sleep(_CONNECT_BACKOFF_S)
        if conn is None:
            raise IOError(f"trade_execution.duckdb: connect failed: {last_err}")
        yield conn
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            lock_fd.close()


def _ensure_tables():
    """Create tables if they don't exist."""
    with _connect() as conn:
        # Create sequence first
        conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_monitoring START 1")

        # Active trades (positions currently open)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS active_trades (
                trade_id TEXT PRIMARY KEY,
                entry_time TIMESTAMP,
                strategy TEXT,
                entry_gate_signal TEXT,
                legs JSON,
                sl JSON,
                tp JSON,
                status TEXT,  -- ACTIVE | CLOSING | CLOSED
                created_at TIMESTAMP DEFAULT now()
            )
        """)

        # Trade history (closed positions, for research)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trade_history (
                trade_id TEXT PRIMARY KEY,
                entry_time TIMESTAMP,
                close_time TIMESTAMP,
                strategy TEXT,
                close_reason TEXT,  -- SL_HIT | TP_HIT | MORPH | MANUAL
                entry_pnl FLOAT,
                final_pnl FLOAT,
                duration_mins INTEGER,
                legs JSON,
                created_at TIMESTAMP DEFAULT now()
            )
        """)

        # Monitoring audit trail (minute-by-minute checks)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS monitoring_log (
                id INTEGER PRIMARY KEY DEFAULT nextval('seq_monitoring'),
                trade_id TEXT,
                monitored_at TIMESTAMP,
                current_ltp JSON,
                current_pnl FLOAT,
                action_taken TEXT,  -- NULL | SL_EXIT | TP_EXIT | MORPH | SHIFT
                note TEXT,
                FOREIGN KEY (trade_id) REFERENCES active_trades(trade_id)
            )
        """)


def init_db():
    """Initialize database and tables."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _ensure_tables()


def add_active_trade(
    trade_id: str,
    entry_time: str,
    strategy: str,
    entry_gate_signal: str,
    legs: List[Dict],
    sl: Dict,
    tp: Dict,
):
    """Record a new active trade."""
    init_db()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO active_trades
            (trade_id, entry_time, strategy, entry_gate_signal, legs, sl, tp, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'ACTIVE')
        """,
            [
                trade_id,
                entry_time,
                strategy,
                entry_gate_signal,
                json.dumps(legs),
                json.dumps(sl),
                json.dumps(tp),
            ],
        )
        conn.commit()


def get_active_trades() -> List[Dict]:
    """Get all active trades."""
    init_db()
    with _connect() as conn:
        # A position is open until CLOSED. ACTIVE, SL_TP_PLACED and CLOSING are all
        # still-open states — filtering on 'ACTIVE' alone hid trades from the monitor
        # and the re-entry gate the moment SL/TP orders were placed.
        result = conn.execute("""
            SELECT trade_id, entry_time, strategy, legs, sl, tp, status
            FROM active_trades
            WHERE status != 'CLOSED'
            ORDER BY entry_time DESC
        """).fetchall()

        trades = []
        for row in result:
            trades.append(
                {
                    "trade_id": row[0],
                    "entry_time": row[1],
                    "strategy": row[2],
                    "legs": json.loads(row[3]) if row[3] else [],
                    "sl": json.loads(row[4]) if row[4] else {},
                    "tp": json.loads(row[5]) if row[5] else {},
                    "status": row[6],
                }
            )
        return trades


def close_trade(
    trade_id: str,
    close_reason: str,
    entry_pnl: Optional[float] = None,
    final_pnl: Optional[float] = None,
):
    """Mark trade as closed and archive to history."""
    init_db()
    with _connect() as conn:
        # Get active trade details
        row = conn.execute(
            "SELECT entry_time, strategy, legs FROM active_trades WHERE trade_id = ?",
            [trade_id],
        ).fetchone()

        if not row:
            return False

        entry_time, strategy, legs_json = row

        # Calculate duration
        from datetime import datetime

        entry_dt = datetime.fromisoformat(str(entry_time))
        close_dt = datetime.now()
        duration_mins = int((close_dt - entry_dt).total_seconds() / 60)

        # Insert into history
        conn.execute(
            """
            INSERT INTO trade_history
            (trade_id, entry_time, close_time, strategy, close_reason, entry_pnl, final_pnl, duration_mins, legs)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            [
                trade_id,
                entry_time,
                close_dt.isoformat(),
                strategy,
                close_reason,
                entry_pnl,
                final_pnl,
                duration_mins,
                legs_json,
            ],
        )

        # Mark as closed in active
        conn.execute(
            "UPDATE active_trades SET status = 'CLOSED' WHERE trade_id = ?", [trade_id]
        )

        conn.commit()
        return True


def log_monitor_action(
    trade_id: str,
    current_ltp: Dict,
    current_pnl: float,
    action_taken: Optional[str] = None,
    note: str = "",
):
    """Log a monitoring check."""
    init_db()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO monitoring_log
            (trade_id, monitored_at, current_ltp, current_pnl, action_taken, note)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            [
                trade_id,
                datetime.now().isoformat(),
                json.dumps(current_ltp),
                current_pnl,
                action_taken,
                note,
            ],
        )
        conn.commit()


def has_active_trades() -> bool:
    """Check if there are any active trades."""
    init_db()
    with _connect() as conn:
        result = conn.execute(
            "SELECT COUNT(*) FROM active_trades WHERE status != 'CLOSED'"
        ).fetchone()
        return result[0] > 0 if result else False


def update_active_trade(
    trade_id: str, legs: List[Dict] = None, sl: Dict = None, tp: Dict = None
):
    """Update active trade legs/SL/TP after morph or roll."""
    init_db()
    with _connect() as conn:
        if legs is not None:
            conn.execute(
                "UPDATE active_trades SET legs = ? WHERE trade_id = ?",
                [json.dumps(legs), trade_id],
            )
        if sl is not None:
            conn.execute(
                "UPDATE active_trades SET sl = ? WHERE trade_id = ?",
                [json.dumps(sl), trade_id],
            )
        if tp is not None:
            conn.execute(
                "UPDATE active_trades SET tp = ? WHERE trade_id = ?",
                [json.dumps(tp), trade_id],
            )
        conn.commit()
        return True
