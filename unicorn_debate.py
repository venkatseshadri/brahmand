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
    """Shim — the deterministic gate decision lives ONLY in canonical_strategy
    (SHERPA Phase 1). Do not add decision logic here."""
    import canonical_strategy

    return canonical_strategy.decide_gate(gate_type, raw_data, gate)

