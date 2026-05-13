"""
Brahmand Persistence Layer — Custom SQLite state.db.

Manages operational tables for agent outputs (execution reports, research notes,
daily configs). Separate from CrewAI's @persist Flow state.

Post-Mortem Agent queries these tables to enrich ChromaDB metadata.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from schemas import ExecutionReport, ResearchNote

DB_DIR = Path(__file__).parent / "data"
DB_PATH = DB_DIR / "state.db"


def _connection() -> sqlite3.Connection:
    """Return a new SQLite connection with row factory."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create tables if they do not exist. Safe to call repeatedly."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = _connection()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS execution_reports (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id    TEXT    NOT NULL,
            status      TEXT    NOT NULL,
            fill_price  REAL    DEFAULT 0.0,
            timestamp   TEXT    NOT NULL,
            agent_version TEXT  NOT NULL,
            error       TEXT,
            meta        TEXT    DEFAULT '{}',
            created_at  TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS research_notes (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            observation    TEXT    NOT NULL,
            confidence     REAL    NOT NULL,
            source         TEXT    NOT NULL,
            suggested_action TEXT  NOT NULL,
            context_date   INTEGER NOT NULL,
            metadata       TEXT    DEFAULT '{}',
            created_at     TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS daily_configs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            config      TEXT    NOT NULL,
            created_at  TEXT    DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_exec_ts
            ON execution_reports(timestamp);
        CREATE INDEX IF NOT EXISTS idx_rn_date
            ON research_notes(context_date);
        """,
    )
    conn.commit()
    conn.close()


def save_execution_report(report: ExecutionReport) -> int:
    """Insert an execution report into state.db. Returns row id."""
    conn = _connection()
    try:
        cursor = conn.execute(
            "INSERT INTO execution_reports "
            "(order_id, status, fill_price, timestamp, agent_version, error, meta) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                report.order_id,
                report.status,
                report.fill_price,
                report.timestamp,
                report.agent_version,
                report.error,
                json.dumps(getattr(report, "meta_data", {})),
            ),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def save_research_note(note: ResearchNote) -> int:
    """Insert a research note into state.db. Returns row id."""
    conn = _connection()
    try:
        cursor = conn.execute(
            "INSERT INTO research_notes "
            "(observation, confidence, source, suggested_action, context_date, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                note.observation,
                note.confidence,
                note.source,
                note.suggested_action,
                note.context_date,
                json.dumps(note.metadata),
            ),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def query_execution_reports(
    status: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Query execution reports, optionally filtered by status."""
    conn = _connection()
    try:
        if status:
            rows = conn.execute(
                "SELECT * FROM execution_reports WHERE status = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM execution_reports ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def query_research_notes(
    context_date: int | None = None,
    limit: int = 100,
) -> list[dict]:
    """Query research notes, optionally filtered by date (YYYYMMDD)."""
    conn = _connection()
    try:
        if context_date is not None:
            rows = conn.execute(
                "SELECT * FROM research_notes WHERE context_date = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (context_date, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM research_notes ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def save_daily_config(config_dict: dict) -> int:
    """Store the current daily_config.json snapshot in state.db."""
    conn = _connection()
    try:
        cursor = conn.execute(
            "INSERT INTO daily_configs (config) VALUES (?)",
            (json.dumps(config_dict),),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def load_latest_daily_config() -> dict | None:
    """Load the most recent daily config from state.db."""
    conn = _connection()
    try:
        row = conn.execute(
            "SELECT config FROM daily_configs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row:
            return json.loads(row["config"])
        return None
    finally:
        conn.close()


def get_today_date_int() -> int:
    """Return today's date as YYYYMMDD integer for ChromaDB metadata filtering."""
    return int(datetime.now().strftime("%Y%m%d"))
