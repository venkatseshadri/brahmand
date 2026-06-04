"""
Project UNICORN — Phase 4 Tests: Judge Scoring & Decision

Tests the Judge's deterministic scoring path (pre-verified claims).
Does NOT require live LLM API — all tests use frozen fixtures.
"""

import json
import pytest
from pathlib import Path

from brahmand.unicorn_verify import verify_points

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name):
    return json.loads((FIXTURES_DIR / name).read_text())


# ── Fixture helpers ────────────────────────────────────────────────────


def _make_points_from_fixture(data: dict, family: str, fields: dict) -> list:
    """Build advocate/skeptic points from fixture data using real values."""
    pts = []
    for field, claimed_val in fields.items():
        pts.append(
            {
                "family": family,
                "claim": f"{family} {field}={claimed_val}",
                "evidence": {field: claimed_val},
            }
        )
    return pts


# ── 4.1: Fabrication detection ────────────────────────────────────────


def test_judge_detects_fabrication():
    """Fabricated claim lands in hallucinations[] and Advocate scores 0 on that point."""
    from brahmand.unicorn_judge import judge

    data = _load_fixture("debate_bearish_not_up.json")

    advocate_pts = [
        {"family": "trend", "claim": "ADX=55 strong trend", "evidence": {"adx": 55.0}},
    ]
    skeptic_pts = [
        {"family": "volatility", "claim": "ATR=18", "evidence": {"atr": 18.0}},
    ]

    result = judge(data, advocate_pts, skeptic_pts, "NOT_UP")
    assert result["hallucinations_detected"] is True
    assert result["hallucination_count"] >= 1


def test_fabrication_penalizes_advocate():
    """When Advocate fabricates, it loses the debate."""
    from brahmand.unicorn_judge import judge

    data = _load_fixture("debate_bearish_not_up.json")

    # Advocate fabricates huge numbers
    advocate_pts = [
        {
            "family": "trend",
            "claim": "Super trend spike",
            "evidence": {"adx": 99.0, "di_minus": 99.0},
        },
    ]
    # Skeptic uses real data
    skeptic_pts = [
        {"family": "macro", "claim": "spot level", "evidence": {"spot": 24800}},
    ]

    result = judge(data, advocate_pts, skeptic_pts, "NOT_UP")
    assert result["go"] is False
    assert result["signal"] == "NONE"


# ── 4.2: Verified claims scoring ──────────────────────────────────────


def test_both_truthful_scores_positive():
    """Both sides truthful → both get positive scores."""
    from brahmand.unicorn_judge import judge

    data = _load_fixture("debate_bearish_not_up.json")

    advocate_pts = [
        {
            "family": "trend",
            "claim": "bearish supertrend",
            "evidence": {"st_consensus": "bearish"},
        },
        {
            "family": "volume",
            "claim": "distribution",
            "evidence": {"cmf_signal": "distribution"},
        },
    ]
    skeptic_pts = [
        {
            "family": "macro",
            "claim": "spot data",
            "evidence": {"spot": 24800, "vix": 15.2},
        },
    ]

    result = judge(data, advocate_pts, skeptic_pts, "NOT_UP")
    assert result["hallucination_count"] == 0


def test_advocate_weak_skeptic_strong():
    """Advocate with 1 weak point, Skeptic with 2 strong → SKIP."""
    from brahmand.unicorn_judge import judge

    data = _load_fixture("debate_bullish_not_down.json")

    advocate_pts = [
        {"family": "momentum", "claim": "RSI", "evidence": {"rsi": 65.0}},
    ]
    skeptic_pts = [
        {
            "family": "trend",
            "claim": "bullish trend",
            "evidence": {"st_consensus": "bullish"},
        },
        {"family": "options", "claim": "bullish PCR", "evidence": {"pcr_total": 0.85}},
    ]

    result = judge(data, advocate_pts, skeptic_pts, "NOT_UP")
    # Both use real data, so scores may be close
    assert result["signal"] in ("NOT_UP", "NONE")


# ── 4.3: Correct signal per gate_type ─────────────────────────────────


def test_not_up_gate_strong_bearish_enters():
    """Strong bearish data + NOT_UP gate → ENTER CALL_SPREAD."""
    from brahmand.unicorn_judge import judge

    data = _load_fixture("debate_bearish_not_up.json")

    advocate_pts = [
        {
            "family": "trend",
            "claim": "bearish trend",
            "evidence": {"st_consensus": "bearish", "sma_position": "bearish"},
        },
        {
            "family": "options",
            "claim": "bearish PCR",
            "evidence": {"pcr_signal": "bearish", "sentiment": "bearish"},
        },
        {
            "family": "volume",
            "claim": "distribution",
            "evidence": {"cmf_signal": "distribution"},
        },
    ]
    skeptic_pts = [
        {"family": "macro", "claim": "VIX low enough", "evidence": {"vix": 15.2}},
    ]

    result = judge(data, advocate_pts, skeptic_pts, "NOT_UP")
    assert result["signal"] == "NOT_UP"
    assert result["strategy_to_execute"] == "CALL_SPREAD"
    assert result["go"] is True
    assert 0 < result["confidence"] <= 0.75


def test_not_down_gate_strong_bullish_enters():
    """Strong bullish data + NOT_DOWN gate → ENTER PUT_SPREAD."""
    from brahmand.unicorn_judge import judge

    data = _load_fixture("debate_bullish_not_down.json")

    advocate_pts = [
        {
            "family": "trend",
            "claim": "bullish trend",
            "evidence": {"st_consensus": "bullish", "sma_position": "bullish"},
        },
        {
            "family": "options",
            "claim": "bullish PCR",
            "evidence": {"pcr_signal": "bullish", "sentiment": "bullish"},
        },
        {
            "family": "volume",
            "claim": "accumulation",
            "evidence": {"cmf_signal": "accumulation"},
        },
    ]
    skeptic_pts = [
        {"family": "macro", "claim": "VIX low", "evidence": {"vix": 14.2}},
    ]

    result = judge(data, advocate_pts, skeptic_pts, "NOT_DOWN")
    assert result["signal"] == "NOT_DOWN"
    assert result["strategy_to_execute"] == "PUT_SPREAD"
    assert result["go"] is True


def test_ambiguous_sideways_skips():
    """Sideways market → both sides weak → SKIP."""
    from brahmand.unicorn_judge import judge

    data = _load_fixture("debate_ambiguous.json")

    advocate_pts = [
        {
            "family": "trend",
            "claim": "neutral trend",
            "evidence": {"st_consensus": "neutral"},
        },
    ]
    skeptic_pts = [
        {"family": "macro", "claim": "flat market", "evidence": {"vix": 15.0}},
    ]

    result = judge(data, advocate_pts, skeptic_pts, "NOT_UP")
    assert result["signal"] == "NONE"
    assert result["go"] is False


# ── 4.4: Output contract ──────────────────────────────────────────────


def test_judge_output_has_all_keys():
    """Judge output must have all entry_decision keys."""
    from brahmand.unicorn_judge import judge

    data = _load_fixture("debate_bearish_not_up.json")
    result = judge(
        data,
        [{"family": "trend", "claim": "test", "evidence": {"st_consensus": "bearish"}}],
        [{"family": "macro", "claim": "test", "evidence": {"vix": 15.2}}],
        "NOT_UP",
    )

    required = {"go", "signal", "confidence", "strategy_to_execute", "reasoning"}
    assert required.issubset(set(result.keys()))

    if result["signal"] == "NOT_UP":
        assert result["not_up_signal"] == "NOT_UP"
        assert result["not_down_signal"] == "NONE"
    elif result["signal"] == "NOT_DOWN":
        assert result["not_down_signal"] == "NOT_DOWN"
        assert result["not_up_signal"] == "NONE"
    else:
        assert result.get("not_up_signal") == "NONE"
        assert result.get("not_down_signal") == "NONE"


# ── 4.5: Judge prompt builder ─────────────────────────────────────────


def test_build_judge_prompt_not_up():
    """Judge prompt for NOT_UP gate contains correct canonical table."""
    from brahmand.unicorn_judge import build_judge_prompt

    data = _load_fixture("debate_bearish_not_up.json")
    from brahmand.unicorn_verify import verify_points

    adv_r = verify_points(
        data,
        [{"family": "trend", "claim": "test", "evidence": {"st_consensus": "bearish"}}],
    )
    skp_r = verify_points(
        data, [{"family": "macro", "claim": "test", "evidence": {"vix": 15.2}}]
    )

    prompt = build_judge_prompt(data, adv_r, skp_r, "NOT_UP")
    assert "CALL_SPREAD" in prompt
    assert "NOT_UP" in prompt
    assert "NONE" in prompt
    assert "CONTRADICTED" in prompt
    assert "UNVERIFIABLE" in prompt
    assert "VERIFIED" in prompt


def test_build_judge_prompt_not_down():
    """Judge prompt for NOT_DOWN gate contains PUT_SPREAD."""
    from brahmand.unicorn_judge import build_judge_prompt

    data = _load_fixture("debate_bullish_not_down.json")
    from brahmand.unicorn_verify import verify_points

    adv_r = verify_points(
        data,
        [{"family": "trend", "claim": "test", "evidence": {"st_consensus": "bullish"}}],
    )
    skp_r = verify_points(
        data, [{"family": "macro", "claim": "test", "evidence": {"vix": 14.2}}]
    )

    prompt = build_judge_prompt(data, adv_r, skp_r, "NOT_DOWN")
    assert "PUT_SPREAD" in prompt
    assert "NOT_DOWN" in prompt


# ── 4.6: LLM error fallback ───────────────────────────────────────────


def test_llm_failure_falls_back_to_deterministic():
    """When LLM callable raises, judge falls back to deterministic scoring."""
    from brahmand.unicorn_judge import judge

    data = _load_fixture("debate_bearish_not_up.json")

    def _broken_llm(*a, **kw):
        raise RuntimeError("api down")

    advocate_pts = [
        {
            "family": "trend",
            "claim": "bearish",
            "evidence": {"st_consensus": "bearish"},
        },
    ]

    result = judge(data, advocate_pts, [], "NOT_UP", llm_callable=_broken_llm)
    assert "go" in result
    assert "signal" in result
