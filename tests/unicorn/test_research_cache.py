"""
Project UNICORN — Research Cache Tests

Tests the disk-based LLM debate point cache with TTL and signature validation.
Ensures the 5-min cron execution path never blocks on LLM API calls.
"""

import json
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

CACHE_DIR = Path(__file__).parent.parent.parent / "data" / "unicorn_cache"


@pytest.fixture(autouse=True)
def clean_cache():
    """Clean cache directory before each test."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for f in CACHE_DIR.glob("debate_points_*.json"):
        f.unlink()
    yield
    for f in CACHE_DIR.glob("debate_points_*.json"):
        f.unlink()


# ── Save + Load ────────────────────────────────────────────────────────


def test_save_and_load_valid():
    """Save points → load within TTL → returns them."""
    from unicorn_research_cache import save_debate_points, load_debate_points

    advocate = [{"family": "trend", "claim": "test", "evidence": {"adx": 38}}]
    skeptic = [{"family": "macro", "claim": "test", "evidence": {"vix": 15}}]

    assert save_debate_points("NOT_UP", advocate, skeptic)
    a, s = load_debate_points("NOT_UP")
    assert a == advocate
    assert s == skeptic


def test_load_expired_returns_none():
    """Points saved with short TTL expire → (None, None)."""
    from unicorn_research_cache import save_debate_points, load_debate_points

    save_debate_points("NOT_UP", [{"x": 1}], [{"y": 2}])
    a, s = load_debate_points("NOT_UP", max_age_sec=-1)  # force expired
    assert a is None
    assert s is None


def test_load_no_cache_returns_none():
    """No cache file → (None, None)."""
    from unicorn_research_cache import load_debate_points

    a, s = load_debate_points("NOT_DOWN")
    assert a is None
    assert s is None


def test_signature_mismatch_invalidates():
    """Cached with signature 'A' → load with sig 'B' → stale."""
    from unicorn_research_cache import save_debate_points, load_debate_points

    advocate = [{"family": "trend", "claim": "test", "evidence": {"adx": 38}}]
    skeptic = [{"family": "macro", "claim": "test", "evidence": {"vix": 15}}]

    save_debate_points("NOT_UP", advocate, skeptic, raw_snapshot_signature="sig_v1")
    a, s = load_debate_points("NOT_UP", raw_signature="sig_v2")
    assert a is None
    assert s is None


def test_signature_match_returns_valid():
    """Same signature → cache valid."""
    from unicorn_research_cache import save_debate_points, load_debate_points

    advocate = [{"family": "trend", "claim": "test", "evidence": {"adx": 38}}]
    skeptic = [{"family": "macro", "claim": "test", "evidence": {"vix": 15}}]
    save_debate_points("NOT_UP", advocate, skeptic, raw_snapshot_signature="sig_abc")
    a, s = load_debate_points("NOT_UP", raw_signature="sig_abc")
    assert a is not None
    assert s is not None


def test_empty_signature_skips_check():
    """Empty signature on load → skip signature validation."""
    from unicorn_research_cache import save_debate_points, load_debate_points

    advocate = [{"family": "macro", "claim": "test", "evidence": {"spot": 100}}]
    skeptic = [{"family": "macro", "claim": "test", "evidence": {"vix": 15}}]
    save_debate_points("NOT_DOWN", advocate, skeptic, raw_snapshot_signature="any")
    a, s = load_debate_points("NOT_DOWN", raw_signature="")  # empty = skip
    assert a is not None


# ── Signature computation ──────────────────────────────────────────────


def test_compute_signature_from_raw():
    """Signature captures market state material to debate points."""
    from unicorn_research_cache import compute_signature

    raw = {
        "macro": {"indicators": {"spot": 24850, "vix": 15.2}},
        "trend": {"timeframes": {"5m": {"st_consensus": "bearish"}}},
        "momentum": {"timeframes": {"5m": {"rsi": 35.5}}},
    }
    sig = compute_signature(raw)
    assert "spot" in sig
    assert "vix" in sig
    assert "bearish" in sig
    assert "rsi" in sig


def test_signature_changes_on_spot_shift():
    """A 50-point spot move changes the signature."""
    from unicorn_research_cache import compute_signature

    raw1 = {
        "macro": {"indicators": {"spot": 24800, "vix": 15.0}},
        "trend": {"timeframes": {"5m": {"st_consensus": "bearish"}}},
        "momentum": {"timeframes": {"5m": {"rsi": 35}}},
    }
    raw2 = {
        "macro": {"indicators": {"spot": 24820, "vix": 15.0}},
        "trend": {"timeframes": {"5m": {"st_consensus": "bearish"}}},
        "momentum": {"timeframes": {"5m": {"rsi": 35}}},
    }
    assert compute_signature(raw1) == compute_signature(
        raw2
    )  # same 50-pt bucket (24800-24824)

    raw3 = {
        "macro": {"indicators": {"spot": 24900, "vix": 15.0}},
        "trend": {"timeframes": {"5m": {"st_consensus": "bearish"}}},
        "momentum": {"timeframes": {"5m": {"rsi": 35}}},
    }
    assert compute_signature(raw1) != compute_signature(
        raw3
    )  # different bucket (24900-24949)


def test_signature_still_stable_on_minor_noise():
    """Small fluctuations don't change the signature."""
    from unicorn_research_cache import compute_signature

    raw1 = {
        "macro": {"indicators": {"spot": 24800, "vix": 15.0}},
        "trend": {"timeframes": {"5m": {"st_consensus": "bearish"}}},
        "momentum": {"timeframes": {"5m": {"rsi": 35.2}}},
    }
    raw2 = {
        "macro": {"indicators": {"spot": 24849, "vix": 15.0}},
        "trend": {"timeframes": {"5m": {"st_consensus": "bearish"}}},
        "momentum": {"timeframes": {"5m": {"rsi": 35.9}}},
    }
    assert compute_signature(raw1) == compute_signature(raw2)


# ── Invalidation ───────────────────────────────────────────────────────


def test_invalidate_specific_gate():
    """Invalidate single gate leaves other intact."""
    from unicorn_research_cache import (
        save_debate_points,
        load_debate_points,
        invalidate_cache,
    )

    save_debate_points("NOT_UP", [{"x": 1}], [{"y": 2}])
    save_debate_points("NOT_DOWN", [{"a": 3}], [{"b": 4}])

    invalidate_cache("NOT_UP")
    assert load_debate_points("NOT_UP") == (None, None)
    assert load_debate_points("NOT_DOWN") != (None, None)


def test_invalidate_all():
    """Invalidate all gates."""
    from unicorn_research_cache import (
        save_debate_points,
        load_debate_points,
        invalidate_cache,
    )

    save_debate_points("NOT_UP", [{"x": 1}], [{"y": 2}])
    save_debate_points("NOT_DOWN", [{"a": 3}], [{"b": 4}])

    invalidate_cache()
    assert load_debate_points("NOT_UP") == (None, None)
    assert load_debate_points("NOT_DOWN") == (None, None)


# ── Cache age ──────────────────────────────────────────────────────────


def test_cache_age_returns_seconds():
    """cache_age_sec returns time since cache was written."""
    from unicorn_research_cache import save_debate_points, cache_age_sec

    save_debate_points("NOT_UP", [{"x": 1}], [{"y": 2}])
    age = cache_age_sec("NOT_UP")
    assert isinstance(age, float)
    assert 0 <= age < 5  # just saved, should be <5s


def test_cache_age_none_for_missing():
    """No cache → None."""
    from unicorn_research_cache import cache_age_sec

    assert cache_age_sec("NONEXISTENT") is None
