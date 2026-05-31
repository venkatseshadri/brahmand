"""
Brahmand E2E Chain — Contract Builder.

Generates option leg specs from strategy parameters, queries SQLite for
trading symbols and LTPs, and builds complete trade dicts.
"""

import sqlite3
from pathlib import Path

from antariksh.config.sqlite_schema import get_sqlite_capture_path


def resolve_contracts(
    atm: int, wing_width: int, expiry: str, strategy_type: str
) -> tuple:
    """Generate leg specs from strategy + query SQLite option_prices for tsyms/LTPs."""
    db_path = get_sqlite_capture_path("NIFTY")

    if strategy_type == "PUT_SPREAD":
        leg_specs = [
            ("sell_pe", atm, "PE", "SELL"),
            ("buy_pe", atm - wing_width, "PE", "BUY"),
        ]
    elif strategy_type == "CALL_SPREAD":
        leg_specs = [
            ("sell_ce", atm, "CE", "SELL"),
            ("buy_ce", atm + wing_width, "CE", "BUY"),
        ]
    else:
        leg_specs = [
            ("sell_ce", atm, "CE", "SELL"),
            ("buy_ce", atm + wing_width, "CE", "BUY"),
        ]

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        result = {}
        for label, strike, ot, action in leg_specs:
            row = conn.execute(
                "SELECT tsym, ltp FROM option_prices "
                "WHERE strike = ? AND option_type = ? "
                "ORDER BY timestamp DESC LIMIT 1",
                (strike, ot),
            ).fetchone()
            if row and row["tsym"]:
                result[label] = {
                    "tsym": row["tsym"],
                    "ltp": float(row["ltp"] or 0),
                    "strike": strike,
                    "option_type": ot,
                    "action": action,
                }
            else:
                result[label] = {
                    "tsym": f"NIFTY{expiry.replace('-', '')}{ot[0]}{strike}",
                    "ltp": 0.0,
                    "strike": strike,
                    "option_type": ot,
                    "action": action,
                }
        return result, leg_specs
    finally:
        conn.close()


def build_trade(
    entry_time,
    spot,
    atm,
    vix,
    expiry,
    ww,
    sl_p,
    tp_p,
    contracts,
    strategy_type,
) -> dict:
    """Build complete trade dict from resolved contracts and strategy params."""
    legs = []
    sl = {}
    tp = {}
    prem_sell = 0.0
    prem_buy = 0.0
    for label, c in contracts.items():
        leg = {
            "action": c["action"],
            "strike": c["strike"],
            "type": c["option_type"],
            "fill_price": c["ltp"],
            "tsym": c["tsym"],
        }
        legs.append(leg)
        if c["action"] == "SELL":
            prem_sell += c["ltp"]
            key = c["option_type"].lower()
            sl[key] = round(c["ltp"] * (1 + sl_p), 2)
            tp[key] = round(c["ltp"] * (1 - tp_p), 2)
        else:
            prem_buy += c["ltp"]
    return {
        "entry_time": entry_time,
        "spot_at_entry": spot,
        "atm_strike": atm,
        "vix": vix,
        "expiry": expiry,
        "wing_width": ww,
        "strategy_type": strategy_type,
        "leg_count": len(legs),
        "net_credit": round(prem_sell - prem_buy, 2),
        "premium_sell": round(prem_sell, 2),
        "premium_buy": round(prem_buy, 2),
        "legs": legs,
        "sl": sl,
        "tp": tp,
        "status": "OPEN",
    }
