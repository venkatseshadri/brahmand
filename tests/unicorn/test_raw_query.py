"""
Project UNICORN — Phase 1 Tests: unicorn_raw_query.py

TDD tests for UnicornRawQuery:
  1.1 test_returns_seven_families
  1.2 test_no_verdicts_in_output
  1.3 test_cache_ttl
"""

import json
import time
import pytest
from unittest.mock import patch, MagicMock


# ── FROZEN FIXTURE LOADER ────────────────────────────────────────────


def _load_frozen():
    from pathlib import Path

    p = Path(__file__).parent / "fixtures" / "raw_data_sample.json"
    return json.loads(p.read_text())


# ── 1.1: SEVEN FAMILIES ──────────────────────────────────────────────


def test_returns_seven_families():
    """UnicornRawQuery must return 7 core families + candles (raw candle
    structure from traffic_light). No traffic_light verdict fields leak."""
    from brahmand.unicorn_raw_query import UnicornRawQuery, _build_raw_payload

    frozen = _load_frozen()
    result = _build_raw_payload(frozen["families"])

    families_required = {
        "trend",
        "momentum",
        "volatility",
        "volume",
        "options",
        "flow",
        "macro",
    }
    missing = families_required - set(result.keys())
    assert not missing, f"Missing families: {missing}"
    assert "traffic_light" not in result, (
        "traffic_light family must NOT appear in output"
    )


def test_returns_seven_families_via_tool():
    """End-to-end test: the tool._run() path produces 7 core families + candles.
    Uses frozen fixture via mock on _query to avoid live DuckDB."""
    from brahmand.unicorn_raw_query import UnicornRawQuery

    frozen = _load_frozen()
    tool = UnicornRawQuery()
    tool._query = MagicMock(return_value=frozen)
    tool._cache.clear()

    output = tool._run("NIFTY")
    result = json.loads(output)

    families_required = {
        "trend",
        "momentum",
        "volatility",
        "volume",
        "options",
        "flow",
        "macro",
    }
    missing = families_required - set(result.keys())
    assert not missing, f"Missing families: {missing}"
    assert "traffic_light" not in result


# ── 1.2: NO VERDICTS ─────────────────────────────────────────────────


def test_no_verdicts_in_output():
    """The raw output MUST contain zero trading verdict tokens.
    Positional indicators (sma_position bullish/bearish, st_direction etc.)
    are raw computed values — NOT trading verdicts — and are allowed.

    Forbidden tokens: go, signal, recommendation, verdict, enter, skip,
    pattern, confidence, exhaustion, reversal_signal, green_count, red_count.

    Note: BULLISH/BEARISH/NEUTRAL as positional indicator values are OK.
    The full-string tokens "BULLISH"/"BEARISH" may appear inside indicator
    values — that's fine. We forbid verdict-specific keys."""
    from brahmand.unicorn_raw_query import UnicornRawQuery

    frozen = _load_frozen()
    tool = UnicornRawQuery()
    tool._query = MagicMock(return_value=frozen)
    tool._cache.clear()

    output = tool._run("NIFTY")
    result = json.loads(output)

    # Only verdict-level keys are forbidden — not raw indicator values
    forbidden_keys = {"go", "signal", "recommendation", "verdict", "enter", "skip"}
    forbidden_values = {"DEAD_CAT_BOUNCE"}

    for key in result:
        assert key not in forbidden_keys, f"Verdict key '{key}' found in output"

    flat = json.dumps(result).upper()
    # Check that traffic_light-specific verdict fields are not present
    verdict_scored = {
        "GREEN_COUNT",
        "RED_COUNT",
        "PATTERN",
        "CONFIDENCE",
        "EXHAUSTION",
        "REVERSAL_SIGNAL",
    }
    found = [f for f in verdict_scored if f in flat]
    assert not found, f"Traffic light verdict tokens found in raw output: {found}"


def test_traffic_light_entities_stripped():
    """Verify that traffic_light summary verdicts (scored output) are stripped.
    Candle colors like 'RED'/'GREEN' as raw per-TF candle data are allowed."""
    from brahmand.unicorn_raw_query import UnicornRawQuery

    frozen = _load_frozen()
    # Confirm the frozen data HAS traffic_light verdicts
    assert "traffic_light" in frozen["families"]
    tl = frozen["families"]["traffic_light"]
    assert "summary" in tl

    tool = UnicornRawQuery()
    tool._query = MagicMock(return_value=frozen)
    tool._cache.clear()

    output = tool._run("NIFTY")
    result = json.loads(output)

    # Verdict-level keys from traffic_light must NOT appear at top level
    traffic_keys = {"pattern", "confidence", "summary", "exhaustion", "reversal_signal"}
    found = traffic_keys.intersection(set(result.keys()))
    assert not found, f"Traffic light verdict keys found at top level: {found}"

    # Candles key is allowed (raw per-TF structure)
    assert "candles" in result, "Raw candle data must be preserved"


# ── 1.3: CACHE TTL ───────────────────────────────────────────────────


def test_cache_returns_same_data():
    """Within 60s TTL, repeated calls return identical data."""
    from brahmand.unicorn_raw_query import UnicornRawQuery

    frozen = _load_frozen()
    tool = UnicornRawQuery()
    tool._query = MagicMock(return_value=frozen)
    tool._cache.clear()

    r1 = tool._run("NIFTY")
    r2 = tool._run("NIFTY")

    assert r1 == r2, "Cached calls must return identical output"
    assert tool._query.call_count == 1, "Second call must hit cache, not re-query"


def test_cache_expiry():
    """After TTL expires, a new query should be made."""
    from brahmand.unicorn_raw_query import UnicornRawQuery

    frozen = _load_frozen()
    tool = UnicornRawQuery()
    tool._cache_ttl = 0.5  # Short TTL for testing
    tool._query = MagicMock(return_value=frozen)
    tool._cache.clear()

    r1 = tool._run("NIFTY")
    assert tool._query.call_count == 1

    time.sleep(0.6)  # Wait past TTL
    r2 = tool._run("NIFTY")
    assert tool._query.call_count == 2, "Cache expired, should re-query"


def test_cache_index_isolation():
    """Different index values share the same cache key
    (data is the same regardless — the tool has no per-index distinction yet)."""
    from brahmand.unicorn_raw_query import UnicornRawQuery

    frozen = _load_frozen()
    tool = UnicornRawQuery()
    tool._query = MagicMock(return_value=frozen)
    tool._cache.clear()

    tool._run("NIFTY")
    tool._run("SENSEX")
    assert tool._query.call_count == 1, "Same cache key regardless of index"


def test_candle_data_preserved():
    """Candle structure data from traffic_light should be preserved
    (body_pct, color, wick_pct per TF) since it's raw data."""
    from brahmand.unicorn_raw_query import UnicornRawQuery
    from brahmand.unicorn_raw_query import _build_raw_payload

    frozen = _load_frozen()
    result = _build_raw_payload(frozen["families"])

    # Candles should appear somewhere in the output
    # The design doc says include it — we include it under a 'candles' top-level key
    # or merged into macro
    flat = json.dumps(result)
    assert "candles" in result, "Candle data must be preserved in output"
