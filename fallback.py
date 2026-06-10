"""Deterministic chain fallback — thin shim over canonical_strategy (SHERPA).

The strategy logic lives ONLY in canonical_strategy.py. This file keeps the
historical call signature used by e2e_chain; do not add decision logic here.
"""

from logger import get_logger

import canonical_strategy

_log = get_logger("fallback").info


def deterministic_fallback(entry_time, spot, atm, vix, adx, snap):
    """Deterministic entry + regime + strategy when LLM is unavailable."""
    decision = canonical_strategy.decide_entry(
        vix=vix,
        adx=adx,
        session=(snap or {}).get("session_phase"),
    )

    _log(
        f"  Entry (deterministic): {'GO' if decision['go'] else 'NO-GO'} | "
        f"{decision['signal']} {decision['confidence']}% | "
        f"→ {decision['strategy_to_execute']}"
    )

    if not decision["go"]:
        return {"recommendation": "no_go", "entry_decision": decision}

    return {
        "entry_decision": decision,
        "regime": {
            "regime": "sideways" if (adx is not None and adx < 25) else "trending",
            "recommendation": "caution" if (vix is None or vix > 18) else "enter",
            "confidence": 0.6,
        },
        "strategy": decision["strategy"],
        "atm": atm,
        "spot": spot,
        "vix": vix,
        "adx": adx,
        "regime_entry_signal": decision["signal"],
    }
