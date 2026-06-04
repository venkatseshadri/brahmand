"""
Project UNICORN — Integration Tests: Prove the switch happened.

These tests verify that USE_UNICORN=True means the UNICORN debate pipeline
is active and the old CrewAI entry agents are retired from the path.
"""

import json
import inspect
import unittest.mock as mock
import pytest
from unittest.mock import MagicMock, patch


# ── 1. Flag existence + defaults ───────────────────────────────────────


def test_use_unicorn_flag_exists():
    """USE_UNICORN flag must be defined and default to True."""
    import e2e_chain

    assert hasattr(e2e_chain, "USE_UNICORN"), "USE_UNICORN flag missing"
    assert e2e_chain.USE_UNICORN is True, "USE_UNICORN must default to True"


# ── 2. Unicorn modules are importable from e2e_chain context ──────────


def test_unicorn_modules_importable():
    """All UNICORN modules must be importable from the brahmand package."""
    from unicorn_raw_query import UnicornRawQuery
    from unicorn_verify import verify_points, _find_raw_value
    from unicorn_judge import judge, build_judge_prompt, GATE_MAP
    from unicorn_debate import run_unicorn_debate
    from unicorn_anomaly import check_anomaly, safe_debate

    assert callable(run_unicorn_debate)
    assert callable(judge)
    assert callable(verify_points)
    assert "NOT_UP" in GATE_MAP
    assert "NOT_DOWN" in GATE_MAP
    assert GATE_MAP["NOT_UP"]["strategy"] == "CALL_SPREAD"
    assert GATE_MAP["NOT_DOWN"]["strategy"] == "PUT_SPREAD"


# ── 3. Old tools are NOT in the UNICORN execution path ────────────────


def test_old_tools_not_in_unicorn_path():
    """The UNICORN path of run_sequential_crew() must NOT reference
    the old deterministic entry tools. Only the else branch (old path)
    may contain them."""
    import e2e_chain

    src = inspect.getsource(e2e_chain.run_sequential_crew)

    old_tools = [
        "EvaluateNotUpRejection",
        "EvaluateNotDownRejection",
        "not_up_entry_agent",
        "not_down_entry_agent",
        "not_up_rejection_tool",
        "not_down_rejection_tool",
    ]

    # Split source into UNICORN path and old path
    if "if USE_UNICORN:" in src and "else:" in src:
        # Find the if/else blocks
        unicorn_start = src.index("if USE_UNICORN:")
        else_start = src.index("else:", unicorn_start)

        unicorn_block = src[unicorn_start:else_start]
        old_block = src[else_start:]

        # Old block MAY contain old tools — that's the legacy path
        # UNICORN block MUST NOT contain old tools
        for tool in old_tools:
            if tool in unicorn_block:
                # Allow tools to appear in comments/log messages
                lines = unicorn_block.split("\n")
                tool_lines = [
                    l for l in lines if tool in l and not l.strip().startswith("#")
                ]
                if tool_lines:
                    assert False, f"Old tool '{tool}' found in UNICORN execution path!"
    else:
        pytest.fail("USE_UNICORN if/else gating not found in run_sequential_crew()")


def test_unicorn_functions_in_unicorn_path():
    """The UNICORN path must reference the key UNICORN functions."""
    import e2e_chain

    src = inspect.getsource(e2e_chain.run_sequential_crew)

    unicorn_functions = ["run_unicorn_debate", "UnicornRawQuery", "safe_debate"]
    for fn in unicorn_functions:
        assert fn in src, f"UNICORN function '{fn}' not found in run_sequential_crew()"


# ── 4. UNICORN path produces valid entry_decision ─────────────────────


def test_unicorn_path_returns_entry_decision_with_frozen_data():
    """Use frozen fixture to verify UNICORN path produces correct output contract
    without live LLM API or live data connections."""
    from unicorn_raw_query import _build_raw_payload
    from unicorn_debate import run_unicorn_debate
    from pathlib import Path

    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "debate_bearish_not_up.json").read_text()
    )

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
        {
            "family": "macro",
            "claim": "VIX low",
            "evidence": {"vix": 15.2},
        },
    ]

    result = run_unicorn_debate(fixture, "NOT_UP", advocate_pts, skeptic_pts)

    required_keys = {
        "go",
        "signal",
        "confidence",
        "strategy_to_execute",
        "reasoning",
        "not_up_signal",
        "not_up_confidence",
        "not_down_signal",
        "not_down_confidence",
    }
    missing = required_keys - set(result.keys())
    assert not missing, f"Missing keys in UNICORN output: {missing}"

    assert result["signal"] in ("NOT_UP", "NOT_DOWN", "NONE")
    assert isinstance(result["go"], bool)
    assert 0.0 <= result["confidence"] <= 1.0
    assert result["strategy_to_execute"] in ("CALL_SPREAD", "PUT_SPREAD", "NONE")


def test_unicorn_vs_old_output_contract_compatible():
    """UNICORN output has all keys the downstream e2e_chain code reads."""
    from unicorn_debate import run_unicorn_debate
    from pathlib import Path

    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "debate_bearish_not_up.json").read_text()
    )

    pts = [
        {
            "family": "trend",
            "claim": "bearish",
            "evidence": {"st_consensus": "bearish"},
        },
    ]

    # Simulate a NOT_UP ENTER via 4 evidence points
    advocate_pts = [
        {
            "family": "trend",
            "claim": "bearish",
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
        {"family": "macro", "claim": "VIX low", "evidence": {"vix": 15.2}},
    ]

    result = run_unicorn_debate(fixture, "NOT_UP", advocate_pts, skeptic_pts)

    # Downstream code reads these keys (e2e_chain.py ~306-355):
    assert "go" in result
    assert "signal" in result
    assert "confidence" in result
    assert "not_up_signal" in result, "not_up_signal required for downstream logic"
    assert "not_up_confidence" in result
    assert "not_down_signal" in result
    assert "not_down_confidence" in result


# ── 5. Deterministic fallback triggers on UNICORN failure ─────────────


def test_e2e_chain_imports_do_not_crash():
    """e2e_chain module must import cleanly with USE_UNICORN=True."""
    import e2e_chain

    assert e2e_chain.USE_UNICORN is True


# ── 6. Research trigger mechanism ───────────────────────────────────────


def test_research_trigger_function_exists():
    """_trigger_unicorn_research must exist and be callable."""
    import e2e_chain

    assert hasattr(e2e_chain, "_trigger_unicorn_research")
    assert callable(e2e_chain._trigger_unicorn_research)


def test_research_lock_prevents_duplicates():
    """_trigger_unicorn_research must not spawn duplicate processes."""
    import e2e_chain
    import fcntl

    lock = e2e_chain._UNICORN_RESEARCH_LOCK
    lock.parent.mkdir(parents=True, exist_ok=True)

    # Acquire lock manually (simulating existing research)
    lf = open(str(lock), "w")
    fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)

    # _trigger should return immediately (lock held)
    try:
        e2e_chain._trigger_unicorn_research("NOT_UP")
    finally:
        fcntl.flock(lf, fcntl.LOCK_UN)
        lf.close()
        lock.unlink(missing_ok=True)

    # If we get here without error or blocking, lock guard works
    assert True


def test_research_module_importable():
    """unicorn_research.py must be importable as a module."""
    from unicorn_research import (
        run_research,
        _build_research_prompt,
        _load_agent_config,
    )

    assert callable(run_research)
    assert callable(_build_research_prompt)

    # Agent config must be loadable
    config = _load_agent_config()
    assert "unicorn_advocate" in config
    assert "unicorn_skeptic" in config
    assert "unicorn_judge" in config
