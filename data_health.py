"""Data Health — file-based checks. No Redis dependency.

Runs every 5 min via cron. Reads heartbeat files + log files.
Alerts to Telegram via configured hooks.

Ports from Redis to files (2026-06-11 DAMBUILDER): all feed/enricher
heartbeats are in data/live/*.heartbeat files. Bar queues are in
data/live/*_1min.log files.
"""

import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Tuple

log = logging.getLogger("brahmand.data_health")

HEARTBEAT_DIR = Path("/home/trading_ceo/antariksh/data/live")


def _is_market_hours() -> bool:
    now = datetime.now()
    hour, minute = now.hour, now.minute
    if now.weekday() >= 5:
        return False
    tm = hour * 60 + minute
    return 9 * 60 + 15 <= tm <= 15 * 60 + 30


def _heartbeat_age(prefix: str, instrument: str) -> float | None:
    """Read heartbeat file, return age in minutes or None if missing."""
    path = HEARTBEAT_DIR / f"{prefix}_{instrument}.heartbeat"
    if not path.exists():
        return None
    try:
        ts_str = path.read_text().strip()
        if not ts_str:
            return None
        # Strip timezone offset if present (feed heartbeats may have +05:30)
        ts_str = ts_str.replace("+05:30", "").rstrip("Z")
        dt = datetime.fromisoformat(ts_str)
        return (datetime.now() - dt).total_seconds() / 60
    except (OSError, ValueError):
        return None


def _last_log_line(pattern: str) -> dict | None:
    """Read last line of matching log file."""
    files = sorted(HEARTBEAT_DIR.glob(pattern))
    if not files:
        return None
    path = files[-1]  # latest match
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            if size < 20:
                return None
            f.seek(max(0, size - 300))
            raw = f.read().decode(errors="replace").strip().split("\n")
            if not raw:
                return None
            parts = raw[-1].split("|")
            if len(parts) >= 6:
                return {
                    "timestamp": parts[0],
                    "close": float(parts[5]),
                    "high": float(parts[3]),
                    "low": float(parts[4]),
                }
    except (OSError, ValueError):
        pass
    return None


# ── Checks ────────────────────────────────────────────────────────────────


def check_feed() -> Tuple[bool, list]:
    """Feed heartbeats (file-based). Must be <5 min old during market hours."""
    warnings = []
    if not _is_market_hours():
        return True, warnings
    for inst in ("NIFTY", "SENSEX", "INDIAVIX"):
        age = _heartbeat_age("feed", inst)
        if age is None:
            warnings.append(f"FATAL [{inst}]: feed heartbeat MISSING")
        elif age > 5:
            warnings.append(f"FEED [{inst}]: heartbeat stale {age:.0f}m")
    return len(warnings) == 0, warnings


def check_penguin() -> Tuple[bool, list]:
    """Penguin enricher heartbeat + bar freshness from log files."""
    warnings = []
    if not _is_market_hours():
        return True, warnings
    for inst in ("NIFTY", "SENSEX"):
        age = _heartbeat_age("enricher", inst)
        if age is None:
            warnings.append(f"FATAL [{inst}]: enricher heartbeat MISSING")
        elif age > 5:
            warnings.append(f"ENRICHER [{inst}]: heartbeat stale {age:.0f}m")
        bar = _last_log_line(f"{inst}_1min.log")
        if bar:
            try:
                t = datetime.fromisoformat(bar["timestamp"])
                age_m = (datetime.now() - t).total_seconds() / 60
                if age_m > 5:
                    warnings.append(
                        f"BARS [{inst}]: stale — last bar {age_m:.0f} min ago"
                    )
            except (ValueError, OSError):
                pass
    return len(warnings) == 0, warnings


def check_porcupine() -> Tuple[bool, list]:
    """Porcupine simulation enricher heartbeat."""
    warnings = []
    if not _is_market_hours():
        return True, warnings
    for label in ("NIFTY", "SENSEX"):
        age = _heartbeat_age("enricher", label)
        if age is None:
            continue  # sim not running
        if age > 15:
            warnings.append(
                f"PORCUPINE [{label}]: enricher heartbeat stale {age:.0f}m (crash-loop?)"
            )
    return len(warnings) == 0, warnings


def check_dambuilder() -> Tuple[bool, list]:
    """DAMBUILDER multitf enricher heartbeat."""
    warnings = []
    if not _is_market_hours():
        return True, warnings
    for label in ("NIFTY", "SENSEX"):
        age = _heartbeat_age("multitf_enricher", label)
        if age is None:
            continue  # pre-T1
        if age > 10:
            warnings.append(
                f"DAMBUILDER [{label}]: multitf_enricher heartbeat stale {age:.0f}m"
            )
    return len(warnings) == 0, warnings


def check_data_freshness() -> Tuple[bool, list]:
    """Check MAX(timestamp) of market_data + market_data_enriched per index.
    WARN if > 5 min old during market hours (heartbeat files can lie).
    WARN if table is empty during market hours (capture stopped entirely)."""
    warnings = []
    if not _is_market_hours():
        return True, warnings
    import sqlite3
    from datetime import datetime

    for inst in ("NIFTY", "SENSEX"):
        db = (
            f"/home/trading_ceo/python-trader/varaha/data/capture_{inst.lower()}.sqlite"
        )
        try:
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            for tbl, label in [
                ("market_data", "feed"),
                ("market_data_enriched", "enricher"),
            ]:
                row = conn.execute(
                    f"SELECT MAX(timestamp) FROM {tbl} WHERE instrument=?",
                    (inst,),
                ).fetchone()
                if not row or not row[0]:
                    warnings.append(
                        f"DATA [{inst}]: {label} table EMPTY — capture may have stopped"
                    )
                    continue
                try:
                    ts = datetime.fromisoformat(row[0])
                    age = (datetime.now() - ts).total_seconds() / 60
                    if age > 5:
                        warnings.append(
                            f"DATA [{inst}]: {label} stale — last bar {age:.0f} min ago"
                        )
                except (ValueError, OSError):
                    pass
            conn.close()
        except Exception:
            pass
    return len(warnings) == 0, warnings


def check_llm() -> Tuple[bool, list]:
    """LLM availability — scan today's kickoff/chain logs."""
    warnings = []
    if not _is_market_hours():
        return True, warnings
    day = datetime.now().strftime("%Y%m%d")
    log_dir = Path(__file__).parent / "logs"
    try:
        kickoff = log_dir / f"kickoff_{day}.log"
        if kickoff.exists():
            n402 = kickoff.read_text(errors="replace").count("Error code: 402")
            if n402:
                warnings.append(
                    f"LLM 402 Insufficient Balance — {n402} failed calls today"
                )
        chain = log_dir / f"chain_{day}.log"
        if chain.exists():
            ctext = chain.read_text(errors="replace")
            fb = ctext.count('"source": "deterministic_fallback"')
            agents = ctext.count("| AGENT  |")
            if agents and fb * 2 > agents:
                warnings.append(f"Entry decisions today: {fb}/{agents} from fallback")
    except OSError as e:
        warnings.append(f"LLM check failed: {e}")
        return False, warnings
    return len(warnings) == 0, warnings


def check_redis() -> Tuple[bool, list]:
    """Redis is deprecated — silent pass."""
    return True, []


def run_all() -> Tuple[bool, list]:
    results = []
    all_warnings = []
    for name, fn in [
        ("LLM", check_llm),
        ("FEED", check_feed),
        ("Penguin", check_penguin),
        ("PORCUPINE", check_porcupine),
        ("DAMBUILDER", check_dambuilder),
        ("DATA_FRESH", check_data_freshness),
        ("Redis", check_redis),
    ]:
        ok, warnings = fn()
        results.append(ok)
        for w in warnings:
            all_warnings.append(f"[{name}] {w}")
    return all(results), all_warnings


def main():
    healthy, warnings = run_all()
    if warnings:
        for w in warnings:
            print(w)
    if not healthy:
        sys.exit(1)
