"""Deterministic fallback chain — runs when LLM is unavailable."""

import sys
from pathlib import Path

from logger import get_logger

_log = get_logger("fallback").info


def deterministic_fallback(entry_time, spot, atm, vix, adx, snap):
    """Deterministic entry + regime + strategy when LLM is unavailable."""
    _ANTARIKSH = Path(__file__).parent.parent / "antariksh"
    sys.path.insert(0, str(_ANTARIKSH))

    from tools.entry_tools import (
        score_trend_redis,
        score_traffic_light_redis,
        combine_entry_scores,
    )

    trend = score_trend_redis("NIFTY")
    tl = score_traffic_light_redis("NIFTY")
    decision = combine_entry_scores(trend, tl)

    _log(
        f"  Entry (deterministic): {'GO' if decision['go'] else 'NO-GO'} | "
        f"{decision['signal']} {decision['confidence']}% | → {decision.get('suggested_trade')}"
    )

    if not decision["go"]:
        return {"recommendation": "no_go", "entry_decision": decision}

    stype = {
        "NOT_UP": "CALL_SPREAD",
        "NOT_DOWN": "PUT_SPREAD",
    }.get(decision["signal"], "CALL_SPREAD")

    return {
        "entry_decision": decision,
        "regime": {
            "regime": "sideways" if adx < 25 else "trending",
            "recommendation": "caution" if vix > 18 else "enter",
            "confidence": 0.6,
        },
        "strategy": {
            "strategy_type": stype,
            "wing_width": 200,
            "sl_pct": 0.25,
            "tp_pct": 0.50,
            "entry_signal": decision["signal"],
        },
        "atm": atm,
        "spot": spot,
        "vix": vix,
        "adx": adx,
        "regime_entry_signal": decision["signal"],
    }
