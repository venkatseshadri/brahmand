"""position_research.py — slow (15-min) discretionary research for open trades.

The position-manager analogue of unicorn_research. Runs OFF the hot path (a
0,15,30,45 cron), produces a per-trade DISCRETIONARY assessment (morph / roll /
tighten / hold), and caches it. The 1-min run_bridge then loads the cache and
applies it in sub-second time, while protective triggers (SL/TP/floor/EOD) are
evaluated live every cycle (never cached).

Today the assessment is computed DETERMINISTICALLY (it reuses position_manager's
own P1–P3 logic — "even a python tool can do it"). `_llm_refine` is the explicit
seam where, in future, an LLM optimises WHEN to shift/morph and the SL/TP levels —
this is why the LLM stays in the loop even though today's work is deterministic.

Usage:
    python3 position_research.py --all              # assess every active trade
    python3 position_research.py --trade-id <id>    # assess one trade
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from position_research_cache import save_assessment, compute_position_signature


def _discretionary_actions(trade: dict) -> list:
    """Compute the discretionary (morph/roll/tighten) candidates via the SAME
    deterministic logic run_bridge would use, then drop the protective ones
    (SL/TP/floor/EOD are never cached — run_bridge owns them live)."""
    import position_manager as pm

    discretionary = {pm.ROLL, pm.TIGHTEN, pm.MORPH}
    try:
        actions = pm.run(dict(trade))  # copy: run() may mutate via _pattern_risk_adjust
    except Exception as e:
        return [{"type": "ERROR", "reason": f"run() failed in research: {e}"}]
    return [a for a in actions if a.get("type") in discretionary]


def _llm_refine(trade: dict, assessment: dict) -> dict:
    """SEAM for the future LLM optimiser. Today: passthrough (deterministic).

    Tomorrow this is where an LLM, given the trade + market context + the
    deterministic candidate, decides whether/when to morph/shift and at what
    SL/TP levels — learning from outcomes. Keeping the call here (even as a
    passthrough) is what keeps "the risk agent stays LLM": the deterministic
    result is the LLM's *default*, not a replacement for it."""
    assessment.setdefault("source", "deterministic")
    return assessment


def assess_trade(trade: dict, mtm: float = 0.0, spot: float = 0.0) -> dict:
    """Produce (and return) the discretionary assessment for one trade."""
    actions = _discretionary_actions(trade)
    real = [a for a in actions if a.get("type") != "ERROR"]
    assessment = {
        "trade_id": trade.get("trade_id"),
        "actions": real,
        "recommendation": real[0]["type"] if real else "HOLD",
        "reason": "; ".join(a.get("reason", "") for a in real) or "no discretionary trigger",
    }
    if any(a.get("type") == "ERROR" for a in actions):
        # Don't cache a bad recommendation; surface it and let run_bridge fall to live.
        assessment["error"] = next(a["reason"] for a in actions if a.get("type") == "ERROR")
    return _llm_refine(trade, assessment)


def assess_and_cache(trade: dict) -> dict:
    """Assess one trade and persist it under its current signature."""
    import position_manager as pm

    try:
        mtm = pm._check_sl_tp(trade).get("mtm", 0.0)
    except Exception:
        mtm = 0.0
    assessment = assess_trade(trade, mtm=mtm)
    if "error" in assessment:
        print(f"  {trade.get('trade_id')}: research error → not cached ({assessment['error'][:80]})")
        return assessment
    sig = compute_position_signature(trade, mtm=mtm)
    save_assessment(trade.get("trade_id"), assessment, signature=sig)
    print(f"  {trade.get('trade_id')}: {assessment['recommendation']} "
          f"({len(assessment['actions'])} action(s)) — {assessment['reason'][:80]}")
    return assessment


def assess_all() -> int:
    from trade_execution_db import get_active_trades

    trades = get_active_trades()
    if not trades:
        print("position_research: no active trades")
        return 0
    print(f"position_research: assessing {len(trades)} active trade(s)")
    for t in trades:
        assess_and_cache(t)
    return len(trades)


def main():
    ap = argparse.ArgumentParser(description="Position discretionary research (cached)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--all", action="store_true", help="assess every active trade")
    g.add_argument("--trade-id", help="assess a single trade by id")
    a = ap.parse_args()

    if a.all:
        assess_all()
    else:
        from trade_execution_db import get_active_trades

        match = [t for t in get_active_trades() if t.get("trade_id") == a.trade_id]
        if not match:
            print(f"position_research: no active trade {a.trade_id}")
            return
        assess_and_cache(match[0])


if __name__ == "__main__":
    main()
