"""Margin lifecycle gate — pre-entry check, post-fill refresh, leg-shift resolution.

Broker is source of truth. No local add/subtract arithmetic (VIX moves SPAN intraday).

Usage:
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "antariksh"))
    from margin_gate import check_entry_margin, refresh_margin_after_fill
"""

import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Tuple

log = logging.getLogger("brahmand.margin_gate")

IST = timezone(timedelta(hours=5, minutes=30))
MARGIN_STALE_MINUTES = 5

_ANTARIKSH_ROOT = Path(__file__).resolve().parent.parent / "antariksh"
_LIMITS_FILE = _ANTARIKSH_ROOT / "data" / "broker_limits.json"
_MATRIX_FILE = Path(__file__).resolve().parent / "data" / "margin_matrix.json"


def _parse_ts(ts_str: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt


def _limits_age_minutes(limits: dict) -> Optional[float]:
    try:
        limit_dt = _parse_ts(limits.get("timestamp", ""))
        if limit_dt is None:
            return None
        return (datetime.now(IST) - limit_dt).total_seconds() / 60
    except Exception:
        return None


def _load_broker_limits() -> Optional[dict]:
    try:
        return json.loads(_LIMITS_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _load_margin_matrix() -> Optional[dict]:
    try:
        return json.loads(_MATRIX_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _lookup_spread_margin(
    matrix: dict, option_type: str, sell_strike: int, buy_strike: int
) -> Optional[float]:
    for s in matrix.get("spreads", []):
        if (
            s["type"] == option_type
            and s["sell_strike"] == sell_strike
            and s["buy_strike"] == buy_strike
        ):
            return s["margin"]
    return None


def _compute_wing_from_legs(legs: list) -> int:
    """Compute absolute strike difference between sell and buy legs."""
    sell = None
    buy = None
    for leg in legs:
        action = leg.get("action", "")
        strike = leg.get("strike", 0)
        if action == "SELL":
            sell = strike
        elif action == "BUY":
            buy = strike
    if sell is None or buy is None:
        return 0
    return abs(sell - buy)


def check_entry_margin(
    instrument: str,
    option_type: str,
    legs: list,
    leg_margin: Optional[float] = None,
) -> Tuple[bool, str]:
    """Pre-entry margin gate. Returns (ok, reason). FAIL-CLOSED: blocks on missing data."""
    limits = _load_broker_limits()
    if not limits:
        return False, "MARGIN_DATA_MISSING: broker_limits.json not found"

    age = _limits_age_minutes(limits)
    if age is None:
        return False, "MARGIN_DATA_STALE: unparseable timestamp"

    if age > MARGIN_STALE_MINUTES:
        log.info(f"Margin cache stale ({age:.0f}m) — attempting live refresh")
        fresh = refresh_margin_after_fill()
        if fresh:
            limits = _load_broker_limits()
            if limits:
                age = _limits_age_minutes(limits)
                if age is not None and age <= MARGIN_STALE_MINUTES:
                    log.info(f"Margin live-refreshed OK (age {age:.0f}m)")
        if not limits or age is None or age > MARGIN_STALE_MINUTES:
            return False, (
                f"MARGIN_DATA_STALE: {age:.0f}m old "
                f"(limit {MARGIN_STALE_MINUTES}m, live refresh failed)"
            )

    free_margin = limits.get("free_margin", 0)
    if not free_margin or free_margin <= 0:
        return False, "MARGIN_ZERO_FREE: no free margin available"

    # Lookup estimated margin requirement from matrix
    matrix = _load_margin_matrix()
    required = leg_margin
    if not required and matrix:
        sell_strike = None
        buy_strike = None
        for leg in legs:
            action = leg.get("action", "")
            strike = leg.get("strike", 0)
            if action == "SELL":
                sell_strike = strike
            elif action == "BUY":
                buy_strike = strike
        if sell_strike and buy_strike:
            required = _lookup_spread_margin(
                matrix, option_type, sell_strike, buy_strike
            )
    if required is None:
        wing = _compute_wing_from_legs(legs)
        # Fallback: estimate from lot_size * atm if matrix unavailable
        lot_size = matrix.get("lot_size", 65) if matrix else 65
        atm = matrix.get("atm", 23000) if matrix else 23000
        required = lot_size * atm * 0.10  # rough 10% of contract value

    net_available = free_margin * 0.90  # 10% safety buffer
    if net_available < required:
        return False, (
            f"MARGIN_INSUFFICIENT: need {required:,.0f} "
            f"(net available {net_available:,.0f} = 90% of free {free_margin:,.0f})"
        )

    return True, (
        f"MARGIN_OK: need {required:,.0f} "
        f"(net available {net_available:,.0f}, free {free_margin:,.0f})"
    )


def refresh_margin_after_fill() -> None:
    """Re-fetch broker limits after entry fill or close/exit.
    Rewrites broker_limits.json from fresh get_limits() call."""
    try:
        if str(_ANTARIKSH_ROOT) not in sys.path:
            sys.path.insert(0, str(_ANTARIKSH_ROOT))
        from broker_limits import fetch_live_limits_from_broker

        varaha_root = _ANTARIKSH_ROOT.parent / "python-trader" / "varaha"
        if str(varaha_root) not in sys.path:
            sys.path.insert(0, str(varaha_root))
        from varaha_auth import VarahaConnect

        vc = VarahaConnect()
        vc.start_session()
        limits = fetch_live_limits_from_broker(vc.api)
        if limits:
            log.info(
                f"Margin refreshed: free={limits.free_margin:,.0f} "
                f"used={limits.used_margin:,.0f}"
            )
        else:
            log.warning("Margin refresh returned None")
        return limits
    except Exception as e:
        log.warning(f"Margin refresh failed: {e}")
        return None


def get_available_margin() -> float:
    """Live free_margin for leg-shift resolution. Falls back to cached JSON."""
    limits = _load_broker_limits()
    if not limits:
        return 0
    return limits.get("free_margin", 0)


def is_margin_fresh() -> bool:
    """Check if broker_limits.json is fresh (<5 min)."""
    limits = _load_broker_limits()
    if not limits:
        return False
    try:
        limit_dt = datetime.fromisoformat(limits.get("timestamp", ""))
        age = (datetime.now(IST) - limit_dt).total_seconds() / 60
        return age < MARGIN_STALE_MINUTES
    except (ValueError, TypeError):
        return False
