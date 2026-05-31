"""
Brahmand E2E Chain — Provenance Verification.

Deterministic recomputation of agent outputs to detect and clamp
LLM hallucinations. Entry gate, regime, and strategy outputs are
all verified against tool-level truth before downstream agents see them.
"""

from logger import get_logger, log_exception

_prov = get_logger("provenance")
_log = _prov.info
_err = lambda msg, exc=None: log_exception(_prov, exc, msg) if exc else _prov.error(msg)


def recompute_regime(vix: float, adx: float) -> dict:
    """Deterministic regime from VIX/ADX. Same rules as entry_tools.score_regime()."""
    if vix > 25:
        return {"recommendation": "skip", "vix": vix, "adx": adx}
    if adx and adx < 20:
        return {"recommendation": "skip", "vix": vix, "adx": adx}
    if vix > 18:
        return {"recommendation": "caution", "vix": vix, "adx": adx}
    if adx and adx < 25:
        return {"recommendation": "caution", "vix": vix, "adx": adx}
    return {"recommendation": "enter", "vix": vix, "adx": adx}


def verify_regime_provenance(regime: dict, vix: float, adx: float) -> bool:
    """Verify regime agent recommendation against deterministic recomputation.
    Clamps hallucinated VIX/ADX values and incorrect recommendations."""
    expected = recompute_regime(vix, adx)
    violations = []
    agent_vix = regime.get("vix", 0)
    agent_adx = regime.get("adx", 0)

    if agent_vix and abs(agent_vix - vix) > 0.5:
        violations.append(f"vix agent={agent_vix:.1f} actual={vix:.1f}")
        regime["vix"] = vix
    if agent_adx and abs(agent_adx - adx) > 1.0:
        violations.append(f"adx agent={agent_adx:.1f} actual={adx:.1f}")
        regime["adx"] = adx

    if regime.get("recommendation") != expected["recommendation"]:
        violations.append(
            f"rec agent={regime.get('recommendation')} expected={expected['recommendation']}"
        )
        regime["recommendation"] = expected["recommendation"]

    if violations:
        _err(f"PROVENANCE VIOLATION [REGIME]: {', '.join(violations)} — CLAMPED")
        return False

    _log(
        f"  Regime: {regime['recommendation'].upper()} "
        f"(VIX={vix:.1f}, ADX={adx:.1f}) — provenance OK"
    )
    return True


def verify_strategy_provenance(strategy: dict) -> bool:
    """Verify strategy agent output against deterministic parameter rules.
    Validates and clamps: wing_width, sl_pct, tp_pct, strategy_type."""
    violations = []

    VALID_TYPES = {"CALL_SPREAD", "PUT_SPREAD", "NONE"}
    if strategy.get("strategy_type") not in VALID_TYPES:
        violations.append(f"strategy_type={strategy.get('strategy_type')}")
        strategy["strategy_type"] = "NONE"

    ww = strategy.get("wing_width", 200)
    if not isinstance(ww, (int, float)) or ww < 50 or ww > 500:
        violations.append(f"wing_width={ww}")
        strategy["wing_width"] = 200

    sl_p = strategy.get("sl_pct", 0.25)
    if not isinstance(sl_p, (int, float)) or sl_p < 0.10 or sl_p > 0.50:
        violations.append(f"sl_pct={sl_p}")
        strategy["sl_pct"] = 0.25

    tp_p = strategy.get("tp_pct", 0.50)
    if not isinstance(tp_p, (int, float)) or tp_p < 0.15 or tp_p > 0.75:
        violations.append(f"tp_pct={tp_p}")
        strategy["tp_pct"] = 0.50

    if violations:
        _err(f"PROVENANCE VIOLATION [STRATEGY]: {', '.join(violations)} — CLAMPED")
        return False
    return True


def recompute_gate(decision: dict, gate_type: str) -> dict:
    """Recompute the deterministic gate output from agent's trend+TL signals."""
    t_sig = decision.get("trend_signal", "NEUTRAL").upper()
    t_conf = decision.get("trend_confidence", 50)
    tl_sig = decision.get("traffic_light_signal", "NEUTRAL").upper()
    tl_conf = decision.get("traffic_light_confidence", 50)

    go = False
    confidence = 0

    if gate_type == "NOT_UP":
        if t_sig == "BEARISH" and tl_sig == "BEARISH":
            go = True
            confidence = round((t_conf + tl_conf) / 2)
        elif (t_sig == "BEARISH" and tl_sig == "NEUTRAL") or (
            t_sig == "NEUTRAL" and tl_sig == "BEARISH"
        ):
            go = True
            confidence = round(max(t_conf if t_sig == "BEARISH" else tl_conf, 0) * 0.67)
        elif t_sig == "BULLISH" or tl_sig == "BULLISH":
            go = False
            confidence = 0
        else:
            go = False
            confidence = 0
    else:  # NOT_DOWN
        if t_sig == "BULLISH" and tl_sig == "BULLISH":
            go = True
            confidence = round((t_conf + tl_conf) / 2)
        elif (t_sig == "BULLISH" and tl_sig == "NEUTRAL") or (
            t_sig == "NEUTRAL" and tl_sig == "BULLISH"
        ):
            go = True
            confidence = round(max(t_conf if t_sig == "BULLISH" else tl_conf, 0) * 0.67)
        elif t_sig == "BEARISH" or tl_sig == "BEARISH":
            go = False
            confidence = 0
        else:
            go = False
            confidence = 0

    return {"go": go, "confidence": confidence}


def verify_provenance(decision: dict, gate_type: str) -> bool:
    """Verify agent decision numbers match deterministic gate recomputation.
    Returns True if clean, False if hallucination detected (patches decision)."""
    expected = recompute_gate(decision, gate_type)

    violations = []
    if decision.get("go") != expected["go"]:
        violations.append(f"go agent={decision.get('go')} expected={expected['go']}")
        decision["go"] = expected["go"]
    if decision.get("confidence", 0) != expected["confidence"]:
        violations.append(
            f"confidence agent={decision.get('confidence')} expected={expected['confidence']}"
        )
        decision["confidence"] = expected["confidence"]

    if violations:
        _err(
            f"PROVENANCE VIOLATION [{gate_type}]: {', '.join(violations)}  "
            f"trend={decision.get('trend_signal')}/{decision.get('trend_confidence')}% "
            f"tl={decision.get('traffic_light_signal')}/{decision.get('traffic_light_confidence')}% "
            f"— CLAMPED to deterministic values"
        )
        return False
    return True
