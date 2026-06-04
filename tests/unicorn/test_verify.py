"""
Project UNICORN — Phase 2 Tests: unicorn_verify.py

Tests for the deterministic (no-LLM) claim verifier.
This module IS allowed exact-equality assertions since it's deterministic.
"""

import json
import pytest
from pathlib import Path

from brahmand.unicorn_verify import verify_points, _find_raw_value, _MISSING

FIXTURES = Path(__file__).parent / "fixtures"


def _load_raw():
    return json.loads((FIXTURES / "raw_data_sample.json").read_text())


@pytest.fixture
def frozen_raw():
    """Frozen raw data from unicorn_raw_query output."""
    raw = _load_raw()
    from brahmand.unicorn_raw_query import _build_raw_payload

    return _build_raw_payload(raw["families"])


# ── VERIFIED claim ─────────────────────────────────────────────────────


def test_verified_numeric_claim(frozen_raw):
    """A correctly-cited numeric value matches within tolerance."""
    # Grab an actual value from the frozen data
    spot = frozen_raw["macro"]["indicators"]["spot"]
    points = [
        {
            "family": "macro",
            "claim": "spot is at current level",
            "evidence": {"spot": spot},
        }
    ]
    result = verify_points(frozen_raw, points)
    assert result["hallucinations"] == []
    assert result["score"] > 0.9
    assert result["tags"][0]["tag"] == "VERIFIED"


def test_verified_string_claim(frozen_raw):
    """Direction/classification fields match by string equality."""
    st_dir = frozen_raw["trend"]["timeframes"]["5m"]["st_consensus"]
    points = [
        {
            "family": "trend",
            "claim": "SuperTrend is bearish",
            "evidence": {"st_consensus": st_dir},
        }
    ]
    result = verify_points(frozen_raw, points)
    assert result["hallucinations"] == []
    assert result["tags"][0]["tag"] == "VERIFIED"


# ── CONTRADICTED claim ─────────────────────────────────────────────────


def test_contradicted_point_zero_score(frozen_raw):
    """A contradicted claim scores 0 and lands in hallucinations."""
    points = [
        {
            "family": "macro",
            "claim": "VIX is 55",
            "evidence": {"vix": 55.0},
        }
    ]
    result = verify_points(frozen_raw, points)
    assert result["score"] == 0.0
    assert len(result["hallucinations"]) >= 1
    assert any("vix" in h.lower() for h in result["hallucinations"])
    assert result["tags"][0]["tag"] == "CONTRADICTED"


def test_contradicted_adx(frozen_raw):
    """Fabricated ADX value detected. Raw ADX may be None (post-market),
    in which case the verifier scores it as UNVERIFIABLE (0.5), not CONTRADICTED."""
    adx_raw = frozen_raw["trend"]["timeframes"]["5m"]["adx"]
    points = [
        {
            "family": "trend",
            "claim": "ADX is 55 strong trend",
            "evidence": {"adx": 55.0},
        }
    ]

    result = verify_points(frozen_raw, points)

    # If raw ADX is not None, it's CONTRADICTED (score 0.0)
    # If raw ADX is None (post-market frozen data), it's UNVERIFIABLE (score 0.5)
    if adx_raw is not None:
        assert result["score"] == 0.0
        assert any("adx" in h.lower() for h in result["hallucinations"])
    else:
        assert result["tags"][0]["tag"] == "UNVERIFIABLE"


# ── UNVERIFIABLE claim ─────────────────────────────────────────────────


def test_unverifiable_missing_field(frozen_raw):
    """Citing a field not in raw data = UNVERIFIABLE, scores 0.5 weight."""
    points = [
        {
            "family": "trend",
            "claim": "momentum_score is 85",
            "evidence": {"momentum_score": 85.0},
        }
    ]
    result = verify_points(frozen_raw, points)
    assert result["tags"][0]["tag"] == "UNVERIFIABLE"
    assert result["score"] <= 0.6  # 0.5 * weight / 1.0 max


def test_unverifiable_non_numeric(frozen_raw):
    """Non-numeric field that doesn't exist = UNVERIFIABLE."""
    points = [
        {
            "family": "options",
            "claim": "the market maker sentiment is high",
            "evidence": {"mm_sentiment": "high"},
        }
    ]
    result = verify_points(frozen_raw, points)
    assert result["tags"][0]["tag"] == "UNVERIFIABLE"


# ── Cross-family claims ───────────────────────────────────────────────


def test_multiple_families_multiple_points(frozen_raw):
    """Multiple verified points across families produce correct tagging."""
    spot = frozen_raw["macro"]["indicators"]["spot"]
    rsi = frozen_raw["momentum"]["timeframes"]["5m"]["rsi"]
    st = frozen_raw["trend"]["timeframes"]["5m"]["st_consensus"]

    points = [
        {"family": "macro", "claim": "spot level", "evidence": {"spot": spot}},
        {"family": "momentum", "claim": "RSI level", "evidence": {"rsi": rsi}},
        {"family": "trend", "claim": "SuperTrend", "evidence": {"st_consensus": st}},
    ]
    result = verify_points(frozen_raw, points)
    assert result["hallucinations"] == []
    assert result["score"] > 0.9
    assert set(result["families_covered"]) == {"macro", "momentum", "trend"}


def test_mixed_verified_and_contradicted(frozen_raw):
    """One good claim, one fabrication — score reflects it."""
    spot = frozen_raw["macro"]["indicators"]["spot"]
    points = [
        {"family": "macro", "claim": "spot level", "evidence": {"spot": spot}},
        {"family": "macro", "claim": "VIX spike", "evidence": {"vix": 99.0}},
    ]
    result = verify_points(frozen_raw, points)
    assert result["score"] == 0.5  # 1 VERIFIED + 1 CONTRADICTED out of 2
    assert len(result["hallucinations"]) == 1


def test_no_evidence_fields(frozen_raw):
    """Point with empty evidence."""
    points = [
        {
            "family": "trend",
            "claim": "market is trending",
            "evidence": {},
        }
    ]
    result = verify_points(frozen_raw, points)
    assert result["tags"][0]["tag"] == "UNVERIFIABLE"


# ── Determinism ────────────────────────────────────────────────────────


def test_deterministic_same_input_same_output(frozen_raw):
    """Same input MUST produce identical output — byte-exact."""
    points = [
        {"family": "macro", "claim": "spot", "evidence": {"spot": 23850.0}},
        {"family": "trend", "claim": "ADX", "evidence": {"adx": 55.0}},
    ]
    r1 = verify_points(frozen_raw, points)
    r2 = verify_points(frozen_raw, points)
    assert r1 == r2


# ── Helper: _find_raw_value ────────────────────────────────────────────


def test_find_raw_value_direct(frozen_raw):
    val, path = _find_raw_value(frozen_raw, "macro", "spot")
    assert val is not None
    assert path and "macro" in path


def test_find_raw_value_timeframe(frozen_raw):
    """Field in timeframes dict is found even if value is None."""
    _, path = _find_raw_value(frozen_raw, "trend", "adx")
    assert path is not None, "Field adx should be findable in trend timeframes"
    assert "timeframes" in path


def test_find_raw_value_with_tf_qualification(frozen_raw):
    """Field exists in multiple TFs — finds the first one even if None."""
    val, path = _find_raw_value(frozen_raw, "trend", "sma20")
    assert path is not None, "Field sma20 should be findable in trend timeframes"
    assert "timeframes" in path


def test_find_raw_value_indicators(frozen_raw):
    val, path = _find_raw_value(frozen_raw, "options", "pcr_total")
    assert val is not None
    assert "indicators" in path


def test_find_raw_value_missing(frozen_raw):
    val, path = _find_raw_value(frozen_raw, "trend", "nonexistent_field")
    assert val is _MISSING
    assert path is None


def test_find_raw_value_with_tf_qualification(frozen_raw):
    """Field exists in multiple TFs — finds the first one even if value is None."""
    _, path = _find_raw_value(frozen_raw, "trend", "sma20")
    assert path is not None
    assert "timeframes" in path


# ── Tolerance tests ────────────────────────────────────────────────────


def test_tolerance_within_abs(frozen_raw):
    """Claim within abs_default tolerance = VERIFIED."""
    spot = frozen_raw["macro"]["indicators"]["spot"]
    points = [{"family": "macro", "claim": "spot", "evidence": {"spot": spot + 0.3}}]
    result = verify_points(frozen_raw, points)
    assert result["tags"][0]["tag"] == "VERIFIED"


def test_tolerance_beyond_abs(frozen_raw):
    """Claim outside abs_default tolerance = CONTRADICTED."""
    spot = frozen_raw["macro"]["indicators"]["spot"]
    points = [{"family": "macro", "claim": "spot", "evidence": {"spot": spot + 5.0}}]
    result = verify_points(frozen_raw, points)
    assert result["tags"][0]["tag"] == "CONTRADICTED"


def test_candles_field_not_verifiable_as_direct_family(frozen_raw):
    """Candle color data can be looked up via 'candles' family."""
    c = frozen_raw["candles"]["candles"]
    first_tf = list(c.keys())[0]
    color = c[first_tf]["color"]

    points = [
        {"family": "candles", "claim": "candle color", "evidence": {"color": color}}
    ]
    result = verify_points(frozen_raw, points)
    # May be UNVERIFIABLE or VERIFIED depending on lookup — but shouldn't crash
    assert "score" in result
