"""
unicorn_judge.py — Judge Scoring & Decision Logic

Weighs pre-verified Advocate and Skeptic arguments and produces
the final entry signal. The heavy lifting (numeric verification) is
done by unicorn_verify.py BEFORE this runs — the Judge receives
pre-tagged claims.

The Judge LLM (deepseek-reasoner) is optional for live runs — its only
job is weighing + synthesis + tie-breaking. This module includes both
the deterministic scoring path and the LLM wrapper.
"""

import json

from unicorn_verify import verify_points, DEFAULT_WEIGHTS
from unicorn_logger import log_judge, log_error, log_verify, PHASE_JUDGE

GATE_MAP = {
    "NOT_UP": {"signal": "NOT_UP", "strategy": "CALL_SPREAD"},
    "NOT_DOWN": {"signal": "NOT_DOWN", "strategy": "PUT_SPREAD"},
}


def judge(
    raw_data: dict,
    advocate_pts: list,
    skeptic_pts: list,
    gate_type: str = "NOT_UP",
    llm_callable: callable = None,
) -> dict:
    """Run the full Judge pipeline.

    1. Verify all claims from both sides (deterministic).
    2. Score each side.
    3. Optionally invoke Judge LLM for synthesis.
    4. Produce final entry_decision dict.

    Args:
        raw_data: 7-family dict from unicorn_raw_query.
        advocate_pts: [{family, claim, evidence}] from Advocate.
        skeptic_pts: [{family, claim, evidence}] from Skeptic.
        gate_type: "NOT_UP" or "NOT_DOWN".
        llm_callable: Optional fn(raw, adv_result, skp_result, gate) -> dict
                      for LLM-based synthesis. If None, uses deterministic scoring.
    """
    gate = GATE_MAP.get(gate_type, GATE_MAP["NOT_UP"])
    t0 = 0  # placeholder — verify_points includes its own timing

    try:
        adv_result = verify_points(raw_data, advocate_pts)
        skp_result = verify_points(raw_data, skeptic_pts)
    except Exception as e:
        log_error(PHASE_JUDGE, "verify_points failed", gate=gate_type, exception=e)
        return _deterministic_decision(
            {"raw_score": 0, "score": 0, "hallucinations": [], "families_covered": []},
            {"raw_score": 0, "score": 0, "hallucinations": [], "families_covered": []},
            gate_type,
            gate,
        )

    if llm_callable:
        try:
            llm_decision = llm_callable(
                raw=raw_data,
                advocate_result=adv_result,
                skeptic_result=skp_result,
                gate_type=gate_type,
                gate=gate,
            )
            if isinstance(llm_decision, dict) and "go" in llm_decision:
                return _enrich_decision(llm_decision, gate_type, gate)
        except Exception as e:
            log_error(
                PHASE_JUDGE,
                "LLM judge call failed, falling back to deterministic",
                gate=gate_type,
                exception=e,
            )

    return _deterministic_decision(adv_result, skp_result, gate_type, gate)


def _deterministic_decision(
    adv_result: dict, skp_result: dict, gate_type: str, gate: dict
) -> dict:
    """Pure-Python scoring: uses raw_score (unnormalized) so more
    evidence = higher score. Normalized scores don't reward breadth.

    Rules:
    - Advocate raw_score > Skeptic raw_score + 0.3 gap → ENTER
    - Any hallucination reduces Advocate confidence by 0.05 each
    - Skeptic win or tie → SKIP (signal NONE)
    - Maximum confidence: 0.75 (deterministic path is conservative)
    """
    adv_score = adv_result["raw_score"]
    skp_score = skp_result["raw_score"]
    hallucinations = adv_result["hallucinations"] + skp_result["hallucinations"]

    threshold = 0.3
    max_confidence = 0.75

    if adv_score > skp_score + threshold and len(hallucinations) <= 3:
        confidence = max(adv_score - skp_score, 0.1)
        confidence = min(confidence / max(adv_score + skp_score, 1), max_confidence)
        confidence -= len(hallucinations) * 0.05
        confidence = max(confidence, 0.1)

        families_covered = len(
            set(adv_result["families_covered"]) | set(skp_result["families_covered"])
        )

        log_judge(
            gate=gate_type,
            decision=gate["signal"],
            adv_score=adv_score,
            skp_score=skp_score,
            confidence=confidence,
            hallucinations=len(hallucinations),
            families_covered=families_covered,
            reason="advocate wins",
        )

        return _make_entry_decision(
            go=True,
            signal=gate["signal"],
            confidence=round(confidence, 2),
            strategy=gate["strategy"],
            gate_type=gate_type,
            adv_score=adv_score,
            skp_score=skp_score,
            hallucinations=hallucinations,
            families_covered=families_covered,
        )

    families_covered = len(
        set(adv_result["families_covered"]) | set(skp_result["families_covered"])
    )
    reason = "hallucinations" if len(hallucinations) > 3 else "score_gap_insufficient"
    log_judge(
        gate=gate_type,
        decision="NONE",
        adv_score=adv_score,
        skp_score=skp_score,
        confidence=0.0,
        hallucinations=len(hallucinations),
        families_covered=families_covered,
        reason=reason,
    )

    return _make_entry_decision(
        go=False,
        signal="NONE",
        confidence=0.0,
        strategy="NONE",
        gate_type=gate_type,
        adv_score=adv_score,
        skp_score=skp_score,
        hallucinations=hallucinations,
        families_covered=len(
            set(adv_result["families_covered"]) | set(skp_result["families_covered"])
        ),
    )


def _make_entry_decision(
    go: bool,
    signal: str,
    confidence: float,
    strategy: str,
    gate_type: str,
    adv_score: float,
    skp_score: float,
    hallucinations: list,
    families_covered: int,
) -> dict:
    """Build the entry_decision dict matching existing e2e_chain contract."""
    decision = {
        "go": go,
        "signal": signal,
        "confidence": confidence,
        "strategy_to_execute": strategy,
        "reasoning": (
            f"Gate={gate_type} | "
            f"Advocate={adv_score:.2f} | Skeptic={skp_score:.2f} | "
            f"Hallucinations={len(hallucinations)} | "
            f"Families={families_covered}"
        ),
        "hallucinations_detected": len(hallucinations) > 0,
        "hallucination_count": len(hallucinations),
        "hallucination_details": hallucinations[:10],
        "families_covered": families_covered,
    }

    if gate_type == "NOT_UP":
        decision["not_up_signal"] = decision["signal"]
        decision["not_up_confidence"] = decision["confidence"]
        decision["not_down_signal"] = "NONE"
        decision["not_down_confidence"] = 0
    else:
        decision["not_down_signal"] = decision["signal"]
        decision["not_down_confidence"] = decision["confidence"]
        decision["not_up_signal"] = "NONE"
        decision["not_up_confidence"] = 0

    return decision


def _enrich_decision(llm_dict: dict, gate_type: str, gate: dict) -> dict:
    """Ensure LLM-produced decision has all required keys."""
    required = {"go", "signal", "confidence", "strategy_to_execute", "reasoning"}
    for k in required:
        if k not in llm_dict:
            llm_dict[k] = False if k == "go" else ("NONE" if k != "confidence" else 0.0)

    llm_dict.setdefault("hallucinations_detected", False)
    llm_dict.setdefault("hallucination_count", 0)
    llm_dict.setdefault("families_covered", 0)

    if gate_type == "NOT_UP":
        llm_dict["not_up_signal"] = llm_dict["signal"]
        llm_dict["not_up_confidence"] = llm_dict["confidence"]
        llm_dict["not_down_signal"] = "NONE"
        llm_dict["not_down_confidence"] = 0
    else:
        llm_dict["not_down_signal"] = llm_dict["signal"]
        llm_dict["not_down_confidence"] = llm_dict["confidence"]
        llm_dict["not_up_signal"] = "NONE"
        llm_dict["not_up_confidence"] = 0

    return llm_dict


# ── LLM Judge prompt builder (for live runs with deepseek-reasoner) ──


def build_judge_prompt(
    raw_data: dict,
    adv_result: dict,
    skp_result: dict,
    gate_type: str,
) -> str:
    """Build the prompt for the Judge LLM.

    The Judge receives PRE-VERIFIED claims. No LLM ever decides
    'does 38 == 55' — the verifier already answered that.
    """
    gate = GATE_MAP.get(gate_type, GATE_MAP["NOT_UP"])

    prompt_parts = [
        f"You are the JUDGE for the {gate_type} entry debate.",
        "",
        "CANONICAL DIRECTION TABLE:",
        f"- {gate_type} gate → ENTER = {gate['strategy']} (signal: {gate['signal']})",
        f"- SKIP → signal: NONE",
        "",
        "VERIFICATION RESULTS (pre-computed by deterministic verifier):",
        "",
        f"Advocate score: {adv_result['score']:.2f}",
        f"  Families covered: {', '.join(adv_result.get('families_covered', []))}",
        f"  Hallucinations: {len(adv_result.get('hallucinations', []))}",
    ]

    for h in adv_result.get("hallucinations", [])[:5]:
        prompt_parts.append(f"    ❌ {h}")

    prompt_parts.extend(
        [
            "",
            f"Skeptic score: {skp_result['score']:.2f}",
            f"  Families covered: {', '.join(skp_result.get('families_covered', []))}",
            f"  Hallucinations: {len(skp_result.get('hallucinations', []))}",
        ]
    )

    for h in skp_result.get("hallucinations", [])[:5]:
        prompt_parts.append(f"    ❌ {h}")

    prompt_parts.extend(
        [
            "",
            "INSTRUCTIONS:",
            "1. Claims tagged CONTRADICTED → ZERO weight (do NOT credit them).",
            "2. Claims tagged UNVERIFIABLE → HALF weight.",
            "3. Claims tagged VERIFIED → FULL weight.",
            "4. If both sides are evenly matched → signal=NONE, confidence=0.",
            "5. If one side clearly stronger → use CANONICAL DIRECTION TABLE above.",
            "6. NEVER overturn a CONTRADICTED tag — the verifier is always correct.",
            "7. Default to SKIP on ambiguity. The edge is in not overtrading.",
            "",
            "OUTPUT — Return EXACTLY this JSON (no markdown, no preamble):",
            "{",
            '  "go": true/false,',
            f'  "signal": "{gate["signal"]}"|"NONE",',
            '  "confidence": 0.0-1.0,',
            f'  "strategy_to_execute": "{gate["strategy"]}"|"NONE",',
            '  "reasoning": "explanation"',
            "}",
        ]
    )

    return "\n".join(prompt_parts)
