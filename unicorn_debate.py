"""
unicorn_debate.py — Unicorn Debate Orchestrator

Wires the full adversarial debate pipeline:
  1. Raw data query (unicorn_raw_query)
  2. Advocate argument (argues to ENTER the spread)
  3. Skeptic argument (argues to SKIP)
  4. Deterministic verification (unicorn_verify)
  5. Judge scoring + decision (unicorn_judge)

Supports LLM-based and deterministic modes.
"""

import json
from pathlib import Path

from unicorn_judge import judge as _judge_decision, GATE_MAP
from unicorn_logger import log_debate, log_error, PHASE_DEBATE


def run_unicorn_debate(
    raw_data: dict,
    gate_type: str = "NOT_UP",
    advocate_pts: list = None,
    skeptic_pts: list = None,
) -> dict:
    """Run a full Unicorn debate cycle.

    Args:
        raw_data: Dict from unicorn_raw_query (7 families + candles).
        gate_type: "NOT_UP" or "NOT_DOWN".
        advocate_pts: Pre-built advocate points.
        skeptic_pts: Pre-built skeptic points.

    Returns:
        entry_decision dict compatible with existing e2e_chain contract:
        {go, signal, confidence, strategy_to_execute, reasoning,
         not_up_signal, not_down_signal,
         not_up_confidence, not_down_confidence}
    """
    gate = GATE_MAP.get(gate_type, GATE_MAP["NOT_UP"])

    if advocate_pts is None or skeptic_pts is None:
        result = _deterministic_fallback(raw_data, gate_type, gate)
        log_debate(
            gate=gate_type,
            status="fallback",
            signal=result["signal"],
            go=result["go"],
            confidence=result["confidence"],
            reason="no_advocate_or_skeptic_points",
        )
        return result

    t0 = __import__("time").time()
    try:
        decision = _judge_decision(raw_data, advocate_pts, skeptic_pts, gate_type)
    except Exception as e:
        log_error(PHASE_DEBATE, "_judge_decision failed", gate=gate_type, exception=e)
        decision = _deterministic_fallback(raw_data, gate_type, gate)

    elapsed = __import__("time").time() - t0
    log_debate(
        gate=gate_type,
        status="done",
        signal=decision.get("signal", "NONE"),
        go=decision.get("go", False),
        confidence=decision.get("confidence", 0),
        elapsed=elapsed,
        hallucinations=decision.get("hallucination_count", 0),
        families=decision.get("families_covered", 0),
    )

    # Outer provenance clamp — §7 guardrail 4: keep verify_provenance.
    # Only applies if decision has legacy trend/traffic_light fields.
    if "trend_signal" in decision or "traffic_light_signal" in decision:
        try:
            from brahmand.verification import verify_provenance

            verify_provenance(decision, gate_type)
        except ImportError:
            pass

    return decision


def _deterministic_fallback(
    raw_data: dict,
    gate_type: str,
    gate: dict,
) -> dict:
    """Fallback when no advocate/skeptic points provided.
    Uses SuperTrend consensus + VIX + session phase for direction check."""
    trend = raw_data.get("trend", {})
    timeframes = trend.get("timeframes", {})
    macro = raw_data.get("macro", {})
    mac_indicators = macro.get("indicators", {})

    st_scores = {"bearish": 1, "neutral": 0, "bullish": -1}
    total = 0
    count = 0
    for tf, tf_data in timeframes.items():
        if isinstance(tf_data, dict):
            st = tf_data.get("st_consensus", "neutral")
            total += st_scores.get(str(st).lower(), 0)
            count += 1

    tf_1m = timeframes.get("1m_v3.1", {})
    if isinstance(tf_1m, dict):
        ema_pos = tf_1m.get("ema_position", "neutral")
        st_pos = tf_1m.get("st_consensus", "neutral")
        total += st_scores.get(str(ema_pos).lower(), 0)
        total += st_scores.get(str(st_pos).lower(), 0)
        count += 2

    avg_score = total / max(count, 1)
    vix = mac_indicators.get("vix", 15)
    session = mac_indicators.get("session_phase", "")

    go = False
    if gate_type == "NOT_UP":
        go = avg_score > 0.2 and (
            isinstance(vix, (int, float)) and vix < 20
        )
    elif gate_type == "NOT_DOWN":
        go = avg_score < -0.2 and (
            isinstance(vix, (int, float)) and vix < 20
        )

    if go and session not in ("preopen", "closing", ""):
        confidence = min(abs(avg_score) * 0.5, 0.5)
        return _make_fallback_decision(
            gate,
            confidence,
            f"Deterministic fallback: avg_super_trend={avg_score:.2f}, vix={vix}",
        )

    return _make_fallback_decision(
        gate=None,
        confidence=0.0,
        reason=f"Deterministic fallback: avg_super_trend={avg_score:.2f}, vix={vix}, session={session}",
    )


def _make_fallback_decision(gate: dict, confidence: float, reason: str) -> dict:
    """Build fallback entry_decision dict."""
    if gate and confidence > 0:
        sig = gate["signal"]
        strat = gate["strategy"]
        go = True
    else:
        sig = "NONE"
        strat = "NONE"
        go = False

    result = {
        "go": go,
        "signal": sig,
        "confidence": confidence,
        "strategy_to_execute": strat,
        "reasoning": reason,
        "source": "deterministic_fallback",
    }

    if sig == "NOT_UP":
        result["not_up_signal"] = "NOT_UP"
        result["not_up_confidence"] = confidence
        result["not_down_signal"] = "NONE"
        result["not_down_confidence"] = 0
    elif sig == "NOT_DOWN":
        result["not_down_signal"] = "NOT_DOWN"
        result["not_down_confidence"] = confidence
        result["not_up_signal"] = "NONE"
        result["not_up_confidence"] = 0
    else:
        result["not_up_signal"] = "NONE"
        result["not_up_confidence"] = 0
        result["not_down_signal"] = "NONE"
        result["not_down_confidence"] = 0

    return result
