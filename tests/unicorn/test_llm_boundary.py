"""
Project UNICORN — LLM Boundary Tests

Tests the _parse_llm_json() repair logic and the live DeepSeek API smoke test.
These are the only tests that exercise the LLM boundary directly.
"""

import json
import os
import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from unicorn_research import _parse_llm_json


# ── JSON Parse Tests (deterministic, no API) ──────────────────────────────


def test_parse_valid_json():
    result = _parse_llm_json('{"alive": true, "points": [1, 2, 3]}')
    assert result == {"alive": True, "points": [1, 2, 3]}


def test_parse_markdown_wrapped():
    result = _parse_llm_json(
        '```json\n{"recommendation": "ENTER", "gate_type": "NOT_UP", "points": []}\n```'
    )
    assert result["recommendation"] == "ENTER"
    assert result["gate_type"] == "NOT_UP"


def test_parse_markdown_no_lang():
    result = _parse_llm_json('```\n{"status": "ok"}\n```')
    assert result == {"status": "ok"}


def test_parse_trailing_text():
    result = _parse_llm_json(
        '{"recommendation": "ENTER", "confidence": 0.75} Let me explain further...'
    )
    assert result["recommendation"] == "ENTER"
    assert result["confidence"] == 0.75


def test_parse_truncated_missing_closing_bracket():
    result = _parse_llm_json(
        '{"family": "trend", "claim": "bearish", "evidence": {"st_consensus": "bearish"'
    )
    assert result["family"] == "trend"
    assert result["claim"] == "bearish"
    assert result["evidence"]["st_consensus"] == "bearish"


def test_parse_garbage():
    result = _parse_llm_json(
        "I think the answer is 42. Not sure what JSON format you want."
    )
    assert result is None


def test_parse_empty_string():
    result = _parse_llm_json("")
    assert result is None


# ── Live API Smoke Test (skipped without key) ─────────────────────────────


@pytest.mark.skipif(
    not os.environ.get("DEEPSEEK_API_KEY"),
    reason="DEEPSEEK_API_KEY not set — live API test skipped",
)
def test_llm_api_smoke():
    from unicorn_research import _call_llm, RESEARCH_MODEL, SKEPTIC_MODEL

    assert RESEARCH_MODEL == "deepseek-v4-pro", (
        f"Model name changed: {RESEARCH_MODEL} != deepseek-v4-pro"
    )
    assert SKEPTIC_MODEL == "deepseek-v4-flash", (
        f"Skeptic model changed: {SKEPTIC_MODEL} != deepseek-v4-flash"
    )

    result = _call_llm(
        prompt='Return exactly this JSON: {"alive": true, "points": [{"family": "test", "claim": "smoke", "evidence": {"ok": true}}]}',
        system_msg="You are a JSON API. Return only valid JSON. No markdown, no explanation.",
        gate="smoke_test",
        role="test",
    )
    assert result is not None, (
        "API call returned None — connectivity or model name issue"
    )
    assert result["alive"] is True
    assert len(result["points"]) == 1


def test_model_defaults():
    from unicorn_research import RESEARCH_MODEL, SKEPTIC_MODEL

    assert RESEARCH_MODEL == "deepseek-v4-pro"
    assert SKEPTIC_MODEL == "deepseek-v4-flash"
    assert RESEARCH_MODEL != SKEPTIC_MODEL
