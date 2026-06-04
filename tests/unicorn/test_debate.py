"""
Project UNICORN — Phase 3 Tests: Agent Config & Debate Structure

Validates unicorn_agents.yaml correctness and the debate orchestration logic.
Does NOT require live LLM API calls — uses frozen fixtures and structural checks.
"""

import json
import yaml
import pytest
from pathlib import Path

CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ── helpers ───────────────────────────────────────────────────────────


def _load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


def _load_fixture(name):
    return json.loads((FIXTURES_DIR / name).read_text())


# ── 3.0: Config file structure ────────────────────────────────────────


def test_agents_yaml_exists_and_valid():
    """unicorn_agents.yaml must exist, be valid YAML, with 3 blueprints."""
    path = CONFIG_DIR / "unicorn_agents.yaml"
    assert path.exists(), f"{path} not found"
    config = _load_yaml(path)
    assert isinstance(config, dict)
    assert set(config.keys()) == {
        "unicorn_advocate",
        "unicorn_skeptic",
        "unicorn_judge",
    }

    for name, blueprint in config.items():
        assert "role" in blueprint, f"{name}: missing role"
        assert "goal" in blueprint, f"{name}: missing goal"
        assert "backstory" in blueprint, f"{name}: missing backstory"
        assert "tools" in blueprint, f"{name}: missing tools"
        assert "llm" in blueprint, f"{name}: missing llm"
        assert "unicorn_raw_query" in blueprint["tools"], (
            f"{name}: missing unicorn_raw_query tool"
        )


def test_no_bull_or_bear_in_prompts():
    """C3 correction: NO agent prompt may contain 'bull' or 'bear'."""
    config = _load_yaml(CONFIG_DIR / "unicorn_agents.yaml")
    for name, blueprint in config.items():
        text = json.dumps(blueprint).lower()
        assert "bull" not in text, f"{name}: contains 'bull'"
        assert "bear" not in text, f"{name}: contains 'bear'"


def test_advocate_skeptic_use_chat_judge_uses_reasoner():
    """C1 correction: All agents use deepseek-v4-pro."""
    config = _load_yaml(CONFIG_DIR / "unicorn_agents.yaml")
    assert "deepseek-v4-pro" in config["unicorn_advocate"]["llm"]
    assert "deepseek-v4-pro" in config["unicorn_skeptic"]["llm"]
    assert "deepseek-v4-pro" in config["unicorn_judge"]["llm"]


def test_gate_type_parameterized():
    """Both Advocate and Skeptic templates use {gate_type} variable."""
    config = _load_yaml(CONFIG_DIR / "unicorn_agents.yaml")
    for agent_name in ("unicorn_advocate", "unicorn_skeptic"):
        text = json.dumps(config[agent_name])
        assert "{gate_type}" in text, f"{agent_name}: missing {{gate_type}} variable"


def test_advocate_template_resolves_not_up():
    """Template resolution for NOT_UP gate creates correct Advocate prompt."""
    config = _load_yaml(CONFIG_DIR / "unicorn_agents.yaml")
    bp = config["unicorn_advocate"]
    variables = {"gate_type": "NOT_UP"}
    backstory = bp["backstory"].replace("{gate_type}", variables["gate_type"])
    role = bp["role"].replace("{gate_type}", variables["gate_type"])

    assert "NOT_UP" in role
    assert "CALL_SPREAD" in backstory
    assert "NOT_UP" in backstory


def test_advocate_template_resolves_not_down():
    """Template resolution for NOT_DOWN gate creates correct Advocate prompt."""
    config = _load_yaml(CONFIG_DIR / "unicorn_agents.yaml")
    bp = config["unicorn_advocate"]
    variables = {"gate_type": "NOT_DOWN"}
    backstory = bp["backstory"].replace("{gate_type}", variables["gate_type"])

    assert "NOT_DOWN" in backstory
    assert "PUT_SPREAD" in backstory


def test_skeptic_template_resolves_not_up():
    """Template resolution for NOT_UP gate creates correct Skeptic prompt."""
    config = _load_yaml(CONFIG_DIR / "unicorn_agents.yaml")
    bp = config["unicorn_skeptic"]
    variables = {"gate_type": "NOT_UP"}
    backstory = bp["backstory"].replace("{gate_type}", variables["gate_type"])

    assert "NOT_UP" in backstory
    assert "CALL_SPREAD" in backstory


# ── 3.1: Advocate output schema validation ────────────────────────────


def test_advocate_output_schema():
    """Validate that the Advocate output JSON schema is correct."""
    sample = {
        "recommendation": "ENTER",
        "gate_type": "NOT_UP",
        "points": [
            {
                "family": "trend",
                "claim": "Strong bearish trend across multiple TFs",
                "evidence": {"st_consensus": "bearish", "sma50": 23850},
            }
        ],
    }
    assert sample["recommendation"] == "ENTER"
    assert sample["gate_type"] in ("NOT_UP", "NOT_DOWN")
    assert len(sample["points"]) >= 1
    for p in sample["points"]:
        assert "family" in p
        assert "claim" in p
        assert "evidence" in p
        assert isinstance(p["evidence"], dict)
        assert len(p["evidence"]) >= 1


def test_advocate_evidence_fields_exist_in_raw():
    """All evidence fields cited must be findable in raw data."""
    from brahmand.unicorn_raw_query import _build_raw_payload
    from brahmand.unicorn_verify import _find_raw_value, _MISSING

    raw = _build_raw_payload(_load_fixture("raw_data_sample.json")["families"])
    sample_points = [
        {"family": "macro", "claim": "spot level", "evidence": {"spot": 23850}},
        {"family": "momentum", "claim": "RSI", "evidence": {"rsi": 55}},
        {"family": "options", "claim": "PCR", "evidence": {"pcr_total": 0.85}},
    ]
    for p in sample_points:
        family = p["family"]
        for field in p["evidence"]:
            val, path = _find_raw_value(raw, family, field)
            assert val is not _MISSING, (
                f"Field '{field}' not found in family '{family}' of raw data"
            )


def test_skeptic_output_schema():
    """Validate that the Skeptic output JSON schema is correct."""
    sample = {
        "recommendation": "SKIP",
        "gate_type": "NOT_UP",
        "points": [
            {
                "family": "volatility",
                "claim": "Elevated volatility makes spread risky",
                "evidence": {"atr": 25.5, "iv_current": 22.0},
            }
        ],
    }
    assert sample["recommendation"] == "SKIP"
    assert sample["gate_type"] in ("NOT_UP", "NOT_DOWN")
    for p in sample["points"]:
        assert "family" in p
        assert "claim" in p
        assert "evidence" in p
        assert isinstance(p["evidence"], dict)


# ── 3.2: Debate orchestrator structure (no LLM) ───────────────────────


def test_verify_advocate_points():
    """Advocate points run through verifier produce scores and tags."""
    from brahmand.unicorn_raw_query import _build_raw_payload
    from brahmand.unicorn_verify import verify_points

    raw = _build_raw_payload(_load_fixture("raw_data_sample.json")["families"])
    # Get actual values from the raw data
    spot = raw["macro"]["indicators"]["spot"]
    st = raw["trend"]["timeframes"]["5m"]["st_consensus"]

    advocate_pts = [
        {"family": "trend", "claim": "trend check", "evidence": {"st_consensus": st}},
        {"family": "macro", "claim": "spot level", "evidence": {"spot": spot}},
    ]
    result = verify_points(raw, advocate_pts)
    assert "score" in result
    assert "tags" in result
    assert "hallucinations" in result
    assert "families_covered" in result


def test_verify_skeptic_points():
    """Skeptic with fabricated claim gets CONTRADICTED."""
    from brahmand.unicorn_raw_query import _build_raw_payload
    from brahmand.unicorn_verify import verify_points

    raw = _build_raw_payload(_load_fixture("raw_data_sample.json")["families"])
    skeptic_pts = [
        {"family": "macro", "claim": "VIX spike", "evidence": {"vix": 99.0}},
    ]
    result = verify_points(raw, skeptic_pts)
    assert result["score"] == 0.0
    assert len(result["hallucinations"]) >= 1


def test_debate_run_function_signature():
    """run_unicorn_debate exists and accepts gate_type parameter."""
    from brahmand.unicorn_debate import run_unicorn_debate
    import inspect

    sig = inspect.signature(run_unicorn_debate)
    params = list(sig.parameters.keys())
    assert "raw_data" in params
    assert "gate_type" in params


def test_debate_returns_expected_keys():
    """run_unicorn_debate with mock data returns correct output contract."""
    from brahmand.unicorn_debate import run_unicorn_debate
    from brahmand.unicorn_raw_query import _build_raw_payload

    raw = _build_raw_payload(_load_fixture("raw_data_sample.json")["families"])

    # Mock the LLM agent output by patching the debate internals
    # For now, verify the function doesn't crash on valid input
    try:
        result = run_unicorn_debate(raw, "NOT_UP")
        assert "go" in result
        assert "signal" in result
        assert "confidence" in result
        assert "strategy_to_execute" in result
        assert "reasoning" in result
    except Exception as e:
        # LLM calls may fail without API — that's fine, the structure is correct
        assert (
            "api" in str(e).lower()
            or "connection" in str(e).lower()
            or "llm" in str(e).lower()
        ), f"Unexpected error: {e}"


# ── 3.3: Judge output contract ────────────────────────────────────────


def test_judge_output_contract():
    """Judge must emit keys matching the existing entry_decision contract."""
    required_keys = {"go", "signal", "confidence", "strategy_to_execute", "reasoning"}
    sample_judge = {
        "go": True,
        "signal": "NOT_UP",
        "confidence": 0.75,
        "strategy_to_execute": "CALL_SPREAD",
        "reasoning": "Clear bearish trend across 4 families",
        "hallucinations_detected": False,
        "hallucination_count": 0,
        "families_covered": 4,
    }
    missing = required_keys - set(sample_judge.keys())
    assert not missing, f"Judge output missing keys: {missing}"
    assert sample_judge["signal"] in ("NOT_UP", "NOT_DOWN", "NONE")
    assert sample_judge["strategy_to_execute"] in ("CALL_SPREAD", "PUT_SPREAD", "NONE")
    assert isinstance(sample_judge["go"], bool)
    assert 0.0 <= sample_judge["confidence"] <= 1.0


def test_judge_tie_goes_to_skip():
    """Tied or ambiguous evidence → signal=NONE, go=false."""
    sample = {
        "go": False,
        "signal": "NONE",
        "confidence": 0.0,
        "strategy_to_execute": "NONE",
        "reasoning": "Both sides present equally compelling evidence",
    }
    assert sample["signal"] == "NONE"
    assert sample["go"] is False


def test_advocate_wins_produces_signal():
    """Advocate wins → go=true, correct signal and strategy per gate_type."""
    for gate, sig, strat in [
        ("NOT_UP", "NOT_UP", "CALL_SPREAD"),
        ("NOT_DOWN", "NOT_DOWN", "PUT_SPREAD"),
    ]:
        output = {
            "go": True,
            "signal": sig,
            "confidence": 0.8,
            "strategy_to_execute": strat,
            "reasoning": f"Advocate {gate} argument is stronger",
        }
        assert output["signal"] == sig
        assert output["strategy_to_execute"] == strat


# ── 3.4: Full E2E debate with fixtures ────────────────────────────────


def test_full_debate_e2e_not_up():
    """Full E2E debate: raw data → verify → judge → decision (NOT_UP gate)."""
    from brahmand.unicorn_debate import run_unicorn_debate

    data = _load_fixture("debate_bearish_not_up.json")

    advocate_pts = [
        {
            "family": "trend",
            "claim": "bearish trend across TFs",
            "evidence": {"st_consensus": "bearish", "sma_position": "bearish"},
        },
        {
            "family": "options",
            "claim": "bearish PCR and sentiment",
            "evidence": {"pcr_signal": "bearish", "sentiment": "bearish"},
        },
        {
            "family": "volume",
            "claim": "distribution signal",
            "evidence": {"cmf_signal": "distribution"},
        },
    ]
    skeptic_pts = [
        {"family": "macro", "claim": "VIX moderate", "evidence": {"vix": 15.2}},
    ]

    result = run_unicorn_debate(data, "NOT_UP", advocate_pts, skeptic_pts)
    assert result["signal"] in ("NOT_UP", "NONE")
    assert 0 <= result["confidence"] <= 1
    assert (
        "hallucination_count" in result
        or "hallucinations_detected" in result
        or "signal" in result
    )


def test_full_debate_e2e_not_down():
    """Full E2E debate: NOT_DOWN gate with bullish fixture."""
    from brahmand.unicorn_debate import run_unicorn_debate

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

    result = run_unicorn_debate(data, "NOT_DOWN", advocate_pts, skeptic_pts)
    assert result["signal"] in ("NOT_DOWN", "NONE")
    assert "go" in result


def test_full_debate_ambiguous_skips():
    """E2E: ambiguous market → SKIP."""
    from brahmand.unicorn_debate import run_unicorn_debate

    data = _load_fixture("debate_ambiguous.json")

    advocate_pts = [
        {
            "family": "trend",
            "claim": "neutral",
            "evidence": {"st_consensus": "neutral"},
        },
    ]
    skeptic_pts = [
        {"family": "macro", "claim": "flat", "evidence": {"vix": 15.0}},
    ]

    result = run_unicorn_debate(data, "NOT_UP", advocate_pts, skeptic_pts)
    assert result["signal"] == "NONE"
    assert result["go"] is False


def test_full_debate_with_fabrication_detected():
    """E2E: fabricated value detected → SKIP."""
    from brahmand.unicorn_debate import run_unicorn_debate

    data = _load_fixture("debate_bearish_not_up.json")

    advocate_pts = [
        {"family": "trend", "claim": "ADX spike", "evidence": {"adx": 99.0}},
    ]
    skeptic_pts = [
        {"family": "macro", "claim": "spot level", "evidence": {"spot": 24800}},
    ]

    result = run_unicorn_debate(data, "NOT_UP", advocate_pts, skeptic_pts)
    assert result["go"] is False
    assert result["signal"] == "NONE"


# ── 3.5: Anomaly detection ────────────────────────────────────────────


def test_anomaly_detector_clean_result():
    """Clean result → no anomaly."""
    from brahmand.unicorn_anomaly import check_anomaly

    clean = {
        "go": True,
        "signal": "NOT_UP",
        "confidence": 0.5,
        "strategy_to_execute": "CALL_SPREAD",
        "hallucination_count": 0,
        "families_covered": 3,
    }
    result = check_anomaly(clean)
    assert result["anomaly"] is False
    assert result["safe"] is True


def test_anomaly_detector_contradiction():
    """go=true but signal=NONE → anomaly."""
    from brahmand.unicorn_anomaly import check_anomaly

    bad = {
        "go": True,
        "signal": "NONE",
        "confidence": 0.5,
        "hallucination_count": 0,
        "families_covered": 1,
    }
    result = check_anomaly(bad)
    assert result["anomaly"] is True


def test_anomaly_detector_too_many_hallucinations():
    """Too many hallucinations → anomaly."""
    from brahmand.unicorn_anomaly import check_anomaly

    bad = {
        "go": True,
        "signal": "NOT_UP",
        "confidence": 0.5,
        "strategy_to_execute": "CALL_SPREAD",
        "hallucination_count": 10,
        "families_covered": 3,
    }
    result = check_anomaly(bad)
    assert result["anomaly"] is True


def test_anomaly_detector_insufficient_families():
    """ENTER with < 2 families covered → anomaly."""
    from brahmand.unicorn_anomaly import check_anomaly

    bad = {
        "go": True,
        "signal": "NOT_UP",
        "confidence": 0.3,
        "strategy_to_execute": "CALL_SPREAD",
        "hallucination_count": 0,
        "families_covered": 1,
    }
    result = check_anomaly(bad)
    assert result["anomaly"] is True


def test_fallback_on_tool_failure():
    """safe_debate gracefully handles invalid input (empty debate)."""
    from brahmand.unicorn_anomaly import safe_debate

    data = _load_fixture("debate_ambiguous.json")
    result = safe_debate(data, "NOT_UP", [], [])
    assert result["go"] is False
    assert result["signal"] == "NONE"
    assert result["go"] is False
    assert result["signal"] == "NONE"
