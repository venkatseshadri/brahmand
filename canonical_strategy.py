#!/usr/bin/env python3
"""Canonical deterministic entry strategy — THE system (SHERPA Phase 1).

Board decision 2026-06-11 (Option A): the deterministic logic is the trading
system; the LLM layer (UNICORN debate, CrewAI agents) is an overlay that may
tune parameters but is never required to trade, and its absence must never
change this module's behavior.

This is the ONLY deterministic entry implementation. It replaces:
  - fallback.py::deterministic_fallback        (chain-level fallback — now a shim)
  - unicorn_debate._deterministic_fallback     (per-gate fallback — now a shim)
Those two disagreed on 2026-06-10 (different data paths + thresholds) and the
old fallback.py mapped BULLISH/BEARISH through a NOT_UP/NOT_DOWN dict whose
.get() default sent every GO — including bullish days — into CALL_SPREAD.

Decision core = antariksh entry_tools (score_trend_redis + score_traffic_light_redis
+ combine_entry_scores), the same family the 2024 backtest exercised.

Direction → executable gate:
  BEARISH  → NOT_UP   → CALL_SPREAD  (cap the upside)
  BULLISH  → NOT_DOWN → PUT_SPREAD   (cap the downside)
  NEUTRAL  → no entry (no directional spread in the executable set)

Fail-closed rules (bug #4 class): unknown VIX → no entry; blocked session
(preopen/closing) → no entry.
"""

import importlib.util
import json
from pathlib import Path

from logger import get_logger

_log = get_logger("canonical").info

_PARAMS_FILE = Path(__file__).parent / "data" / "strategy_params.json"

DEFAULT_PARAMS = {
    "wing_width": 200,
    "sl_pct": 0.25,
    "tp_pct": 0.50,
    "blocked_sessions": ["preopen", "closing"],
}


def get_params() -> dict:
    """Strategy parameters. data/strategy_params.json overrides defaults — that
    file is the LLM overlay's only write seam (Phase 4: versioned parameter
    deltas land there after beating baseline in the A/B journal)."""
    params = dict(DEFAULT_PARAMS)
    if _PARAMS_FILE.exists():
        try:
            params.update(json.loads(_PARAMS_FILE.read_text()))
        except (json.JSONDecodeError, OSError):
            pass
    return params


def _entry_tools():
    """Load antariksh entry_tools by explicit path. A bare `from tools.entry_tools
    import ...` resolves to brahmand's own `tools` package once imported, raising
    ModuleNotFoundError (same workaround the old fallback.py carried)."""
    path = Path(__file__).parent.parent / "antariksh" / "tools" / "entry_tools.py"
    spec = importlib.util.spec_from_file_location("antariksh_entry_tools", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _no_go(reason: str, extra: dict = None) -> dict:
    decision = {
        "go": False,
        "signal": "NONE",
        "direction": "NEUTRAL",
        "confidence": 0,
        "strategy_to_execute": "NONE",
        "strategy": {"strategy_type": "NONE"},
        "reasoning": reason,
        "source": "canonical_strategy",
    }
    if extra:
        decision.update(extra)
    return decision


def decide_entry(
    index: str = "NIFTY",
    vix=None,
    adx=None,
    session: str = None,
    market_ctx: dict = None,
) -> dict:
    """Single GO/NO-GO entry decision.

    Returns {go, signal NOT_UP|NOT_DOWN|NONE, direction, confidence (0-100),
    strategy_to_execute, strategy{...}, reasoning, source}.
    """
    params = get_params()

    if session is not None and str(session).lower() in params["blocked_sessions"]:
        d = _no_go(f"session '{session}' blocked for entries")
        _log(f"  Canonical entry: NO-GO | {d['reasoning']}")
        return d

    ctx = dict(market_ctx or {})
    if vix is not None:
        ctx.setdefault("vix", vix)
    if adx is not None:
        ctx.setdefault("adx", adx)

    # Fail closed on unknown VIX (bug #4 class — score_regime's `vix or 0`
    # turns None into 0 and ENTERs; an unknown regime must not trade).
    if not isinstance(ctx.get("vix"), (int, float)):
        d = _no_go("VIX unknown — regime unassessable, failing closed")
        _log(f"  Canonical entry: NO-GO | {d['reasoning']}")
        return d

    try:
        et = _entry_tools()
        trend = et.score_trend_redis(index)
        tl = et.score_traffic_light_redis(index)
        combined = et.combine_entry_scores(trend, tl, ctx)
    except Exception as e:
        d = _no_go(f"scoring failed: {e}")
        _log(f"  Canonical entry: NO-GO | {d['reasoning']}")
        return d

    direction = str(combined.get("signal", "NEUTRAL")).upper()
    go = bool(combined.get("go"))
    confidence = combined.get("confidence", 0)
    reasoning = combined.get("reasoning", "")

    if go and direction == "BEARISH":
        signal, strategy_type = "NOT_UP", "CALL_SPREAD"
    elif go and direction == "BULLISH":
        signal, strategy_type = "NOT_DOWN", "PUT_SPREAD"
    else:
        if go:
            reasoning += "; NEUTRAL direction — no directional spread to take"
        go, signal, strategy_type = False, "NONE", "NONE"

    decision = {
        "go": go,
        "signal": signal,
        "direction": direction,
        "confidence": confidence,
        "strategy_to_execute": strategy_type,
        "strategy": {
            "strategy_type": strategy_type,
            "wing_width": params["wing_width"],
            "sl_pct": params["sl_pct"],
            "tp_pct": params["tp_pct"],
            "entry_signal": signal,
        },
        "reasoning": reasoning,
        "source": "canonical_strategy",
        "combined": {
            k: combined.get(k)
            for k in (
                "score",
                "trend_signal",
                "traffic_light_signal",
                "trend_confidence",
                "traffic_light_confidence",
            )
        },
    }
    _log(
        f"  Canonical entry: {'GO' if go else 'NO-GO'} | "
        f"{direction}→{signal} {confidence}% | → {strategy_type}"
    )
    return decision


def decide_gate(gate_type: str, raw_data: dict = None, gate: dict = None) -> dict:
    """Per-gate (NOT_UP / NOT_DOWN) decision in the unicorn fallback dict shape.

    Note: confidence in THIS shape is 0-1 (existing consumer contract);
    decide_entry's is 0-100.
    """
    mac = ((raw_data or {}).get("macro") or {}).get("indicators", {})
    d = decide_entry(
        vix=mac.get("vix"),
        adx=mac.get("adx"),
        session=mac.get("session_phase"),
    )
    matches = d["go"] and d["signal"] == gate_type
    conf01 = round(d["confidence"] / 100.0, 4) if matches else 0.0
    result = {
        "go": matches,
        "signal": gate_type if matches else "NONE",
        "confidence": conf01,
        "strategy_to_execute": d["strategy_to_execute"] if matches else "NONE",
        "reasoning": d["reasoning"],
        "source": "canonical_strategy",
        "not_up_signal": "NOT_UP" if matches and gate_type == "NOT_UP" else "NONE",
        "not_up_confidence": conf01 if gate_type == "NOT_UP" else 0,
        "not_down_signal": "NOT_DOWN" if matches and gate_type == "NOT_DOWN" else "NONE",
        "not_down_confidence": conf01 if gate_type == "NOT_DOWN" else 0,
    }
    return result
