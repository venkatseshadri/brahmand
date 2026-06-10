#!/usr/bin/env python3
"""Golden-table regression for canonical_strategy (SHERPA Phase 1).

Pins:
  - direction → gate mapping (the old fallback.py .get() default sent BULLISH
    days into CALL_SPREAD — wrong side)
  - fail-closed on unknown VIX (bug #4 class)
  - blocked-session guard
  - decide_gate consumer contract (0-1 confidence, gate mismatch → no-go)
  - single-implementation guard: no decision logic left in the shims
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import canonical_strategy as cs


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


def main() -> int:
    failures = []
    real_loader = cs._entry_tools

    def case(name, ok):
        if not ok:
            failures.append(name)

    # 1) BEARISH go → NOT_UP / CALL_SPREAD
    cs._entry_tools = lambda: _stub_tools("BEARISH", True, 62)
    d = cs.decide_entry(vix=15.0)
    case("bearish→NOT_UP", d["go"] and d["signal"] == "NOT_UP"
         and d["strategy_to_execute"] == "CALL_SPREAD" and d["confidence"] == 62)

    # 2) BULLISH go → NOT_DOWN / PUT_SPREAD (old bug gave CALL_SPREAD)
    cs._entry_tools = lambda: _stub_tools("BULLISH", True, 55)
    d = cs.decide_entry(vix=15.0)
    case("bullish→NOT_DOWN", d["go"] and d["signal"] == "NOT_DOWN"
         and d["strategy_to_execute"] == "PUT_SPREAD")

    # 3) NEUTRAL go → no entry (no directional spread in executable set)
    cs._entry_tools = lambda: _stub_tools("NEUTRAL", True, 80)
    d = cs.decide_entry(vix=15.0)
    case("neutral→no-go", not d["go"] and d["signal"] == "NONE")

    # 4) combine says no-go → no-go
    cs._entry_tools = lambda: _stub_tools("BEARISH", False, 20)
    d = cs.decide_entry(vix=15.0)
    case("combine-nogo", not d["go"])

    # 5) unknown VIX → fail closed, scorers never consulted
    cs._entry_tools = lambda: (_ for _ in ()).throw(AssertionError("must not score"))
    d = cs.decide_entry(vix=None)
    case("vix-none-fails-closed", not d["go"] and "VIX unknown" in d["reasoning"])

    # 6) blocked session → no-go
    d = cs.decide_entry(vix=15.0, session="preopen")
    case("session-blocked", not d["go"])

    # 7) decide_gate: BEARISH day, NOT_UP gate matches (conf 0-1), NOT_DOWN doesn't
    cs._entry_tools = lambda: _stub_tools("BEARISH", True, 62)
    raw = {"macro": {"indicators": {"vix": 15.0, "adx": 18, "session_phase": "mid"}}}
    g_up = cs.decide_gate("NOT_UP", raw, {"signal": "NOT_UP", "strategy": "CALL_SPREAD"})
    g_dn = cs.decide_gate("NOT_DOWN", raw, {"signal": "NOT_DOWN", "strategy": "PUT_SPREAD"})
    case("gate-match", g_up["go"] and g_up["confidence"] == 0.62
         and g_up["not_up_signal"] == "NOT_UP")
    case("gate-mismatch", not g_dn["go"] and g_dn["signal"] == "NONE"
         and g_dn["confidence"] == 0.0)

    # 8) single-implementation guard: shims must hold no decision logic
    root = Path(__file__).parent.parent
    fb = (root / "fallback.py").read_text()
    ud = (root / "unicorn_debate.py").read_text()
    case("fallback-is-shim", "canonical_strategy" in fb
         and "combine_entry_scores" not in fb and "entry_tools" not in fb)
    case("unicorn-is-shim", "canonical_strategy" in ud
         and "st_scores" not in ud and "_make_fallback_decision" not in ud)

    cs._entry_tools = real_loader
    if failures:
        for f in failures:
            print(f"  FAIL: {f}")
        return 1
    print("  OK canonical-strategy 10/10")
    return 0


if __name__ == "__main__":
    sys.exit(main())
