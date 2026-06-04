"""
unicorn_anomaly.py — Scorecard anomaly detector + graceful fallback.

Detects contradictions in the debate output that shouldn't happen:
- Both sides score 0.0 but ENTER returned
- Confidence > 0 with no families covered
- Hallucination count exceeding safe threshold (>5)

Provides fallback to current deterministic gate when Unicorn fails.
"""

import json
from typing import Optional

from unicorn_logger import log_anomaly, log_error, PHASE_ANOMALY

MAX_HALLUCINATIONS = 5
MIN_FAMILIES_FOR_ENTER = 2


def check_anomaly(decision: dict) -> dict:
    """Check a debate decision for anomalies.

    Returns: {anomaly: bool, flags: [str], safe: bool}
    """
    flags = []
    anomaly = False

    go = decision.get("go", False)
    signal = decision.get("signal", "NONE")
    confidence = decision.get("confidence", 0.0)

    if go and signal == "NONE":
        flags.append("go=true but signal=NONE (contradiction)")
        anomaly = True

    if not go and signal not in ("NONE", None) and confidence > 0:
        flags.append(f"go=false but signal={signal} with confidence={confidence}")
        anomaly = True

    if go and confidence <= 0:
        flags.append(f"go=true but confidence={confidence}")
        anomaly = True

    h_count = decision.get("hallucination_count", 0)
    if h_count > MAX_HALLUCINATIONS:
        flags.append(f"hallucination_count={h_count} exceeds safe threshold")
        anomaly = True

    f_count = decision.get("families_covered", 0)
    if go and f_count < MIN_FAMILIES_FOR_ENTER:
        flags.append(f"ENTER with only {f_count} families covered")
        anomaly = True

    return {
        "anomaly": anomaly,
        "flags": flags,
        "safe": not anomaly,
    }


def safe_debate(
    raw_data: dict,
    gate_type: str,
    advocate_pts: list = None,
    skeptic_pts: list = None,
    fallback_fn: callable = None,
) -> dict:
    """Run debate with anomaly gating.

    If the debate produces an anomalous result, falls back to the
    current deterministic gate (or the provided fallback_fn).
    """
    from unicorn_debate import run_unicorn_debate

    try:
        decision = run_unicorn_debate(raw_data, gate_type, advocate_pts, skeptic_pts)
    except Exception as e:
        log_error(
            PHASE_ANOMALY,
            "debate crashed",
            gate=gate_type,
            exception=e,
            message="falling back to deterministic",
        )
        return _fallback_result(gate_type, f"debate exception: {e}", fallback_fn)

    check = check_anomaly(decision)
    log_anomaly(
        gate=gate_type, flags=check["flags"], fallback_triggered=check["anomaly"]
    )

    if check["anomaly"]:
        return _fallback_result(
            gate_type,
            f"anomaly: {', '.join(check['flags'])}",
            fallback_fn,
        )

    return decision


def _fallback_result(gate_type: str, reason: str, fallback_fn: callable = None) -> dict:
    """Return a safe NONE result when debate fails."""
    if fallback_fn:
        try:
            return fallback_fn()
        except Exception:
            pass

    return {
        "go": False,
        "signal": "NONE",
        "confidence": 0.0,
        "strategy_to_execute": "NONE",
        "reasoning": f"Unicorn anomaly fallback: {reason}",
        "source": "unicorn_anomaly_fallback",
        "not_up_signal": "NONE",
        "not_up_confidence": 0,
        "not_down_signal": "NONE",
        "not_down_confidence": 0,
        "hallucinations_detected": False,
        "hallucination_count": 0,
        "families_covered": 0,
    }
