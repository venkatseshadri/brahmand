#!/usr/bin/env python3
"""LLM-down coherence driver (SHERPA Phase 1 / PORCUPINE llm_down scenario).

Pins the 2026-06-10 incident shape: with the LLM unreachable, the chain-level
fallback and BOTH unicorn gate fallbacks must derive from ONE canonical
decision — never disagree (old code: gate said GO NOT_UP 0.111 while the
chain fallback said NO-GO NEUTRAL on the same data).

Runs with no DEEPSEEK key in the environment — proves the deterministic
system needs no LLM. Emits `LD_RESULT {json}` for the PORCUPINE runner.
"""

import json
import os
import sys
import types
from pathlib import Path

os.environ.pop("DEEPSEEK_API_KEY", None)
sys.path.insert(0, str(Path(__file__).parent.parent))

import canonical_strategy as cs
import fallback
import unicorn_debate


def _stub_tools(direction, go, confidence):
    et = types.SimpleNamespace()
    et.score_trend_redis = lambda index="NIFTY": {"signal": direction, "confidence": confidence, "score": 1}
    et.score_traffic_light_redis = lambda index="NIFTY": {"signal": direction, "confidence": confidence, "score": 1}
    et.combine_entry_scores = lambda t, tl, ctx=None: {
        "go": go,
        "signal": direction,
        "confidence": confidence,
        "reasoning": f"stub {direction}",
        "score": 1,
    }
    return et


def coherence_for(direction, expect_signal, expect_strategy):
    """All three LLM-down paths must agree on one canonical decision."""
    cs._entry_tools = lambda: _stub_tools(direction, True, 60)
    raw = {"macro": {"indicators": {"vix": 15.0, "adx": 18, "session_phase": "mid"}}}
    snap = {"session_phase": "mid"}

    chain = fallback.deterministic_fallback("10:30", 25000, 25000, 15.0, 18, snap)
    g_up = unicorn_debate._deterministic_fallback(raw, "NOT_UP", {"signal": "NOT_UP", "strategy": "CALL_SPREAD"})
    g_dn = unicorn_debate._deterministic_fallback(raw, "NOT_DOWN", {"signal": "NOT_DOWN", "strategy": "PUT_SPREAD"})

    chain_go = "recommendation" not in chain or chain.get("recommendation") != "no_go"
    chain_strategy = chain.get("strategy", {}).get("strategy_type", "NONE")
    gates = {"NOT_UP": g_up, "NOT_DOWN": g_dn}
    match_gate = gates[expect_signal]
    other_gate = gates["NOT_DOWN" if expect_signal == "NOT_UP" else "NOT_UP"]

    return {
        "chain_go": chain_go,
        "chain_strategy_ok": chain_strategy == expect_strategy,
        "gate_match_go": bool(match_gate["go"]),
        "gate_other_no": not other_gate["go"],
        "all_canonical_source": (
            chain.get("entry_decision", {}).get("source") == "canonical_strategy"
            and g_up.get("source") == "canonical_strategy"
            and g_dn.get("source") == "canonical_strategy"
        ),
        "coherent": chain_go == bool(match_gate["go"]),
    }


def main() -> int:
    bear = coherence_for("BEARISH", "NOT_UP", "CALL_SPREAD")
    bull = coherence_for("BULLISH", "NOT_DOWN", "PUT_SPREAD")

    # No-signal day: every path must say no
    cs._entry_tools = lambda: _stub_tools("NEUTRAL", False, 10)
    raw = {"macro": {"indicators": {"vix": 15.0, "adx": 18, "session_phase": "mid"}}}
    chain = fallback.deterministic_fallback("10:30", 25000, 25000, 15.0, 18, {"session_phase": "mid"})
    g_up = unicorn_debate._deterministic_fallback(raw, "NOT_UP", {})
    flat = {
        "chain_no": chain.get("recommendation") == "no_go",
        "gate_no": not g_up["go"],
    }

    result = {
        "no_llm_key": "DEEPSEEK_API_KEY" not in os.environ,
        "bearish": bear,
        "bullish": bull,
        "flat": flat,
        "pass": all(
            [
                "DEEPSEEK_API_KEY" not in os.environ,
                all(bear.values()),
                all(bull.values()),
                all(flat.values()),
            ]
        ),
    }
    print("LD_RESULT " + json.dumps(result))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
