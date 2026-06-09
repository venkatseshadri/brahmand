"""Regression: cached position-research (the position-manager analogue of UNICORN).

Covers the new slow-research → cache → fast-apply path:
  * position_research_cache: round-trip, TTL expiry, signature gating.
  * compute_position_signature: flips on material change, stable within buckets.
  * position_research.assess_trade: keeps only DISCRETIONARY (morph/roll/tighten)
    actions; protective triggers are never cached.

Safety property under test: the cache is consulted ONLY when fresh AND the
position signature matches — a material change forces run_bridge to recompute live.

A fake `position_manager` is injected so this stays a fast pure unit test (no DB,
no LLM). Sandbox dir lives under tests/ (not /tmp).

Run: python3 tests/test_position_research.py   (from brahmand/)
"""
import os
import sys
import types
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

# Sandbox the cache into tests/ BEFORE importing the cache module (CACHE_DIR is
# resolved at import time from BRAHMAND_SANDBOX).
_SANDBOX = _HERE / "_tmp_position_cache"
os.environ["BRAHMAND_SANDBOX"] = str(_SANDBOX)

# Inject a fake position_manager so position_research imports it without the heavy
# real module (dotenv, market_data, DB connections).
_fake_pm = types.ModuleType("position_manager")
_fake_pm.ROLL, _fake_pm.TIGHTEN, _fake_pm.MORPH = "ROLL", "TIGHTEN", "MORPH"
_fake_pm._run_return = []
_fake_pm.run = lambda trade: list(_fake_pm._run_return)
_fake_pm._check_sl_tp = lambda trade: {"action": "ACTIVE", "mtm": 0.0}
sys.modules["position_manager"] = _fake_pm

import position_research_cache as prc  # noqa: E402
import position_research as pr  # noqa: E402


def _ck(name, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    return cond


def main():
    ok = True
    prc.invalidate()  # clean slate

    trade = {
        "trade_id": "T1", "strategy": "IRON_FLY", "entry_gate_signal": "NOT_DOWN",
        "legs": [
            {"type": "CE", "action": "SELL", "strike": 23000},
            {"type": "PE", "action": "SELL", "strike": 22800},
        ],
    }

    # ── cache round-trip ──
    a = {"actions": [{"type": "ROLL"}], "recommendation": "ROLL", "reason": "theta"}
    sig = prc.compute_position_signature(trade, mtm=-200)
    prc.save_assessment("T1", a, signature=sig)
    ok &= _ck("round-trip with matching signature",
              prc.load_assessment("T1", signature=sig) == a)

    # ── signature gating: a material change → cache ignored ──
    sig2 = prc.compute_position_signature(trade, mtm=-3000)  # different mtm bucket
    ok &= _ck("signature mismatch → None (recompute live)",
              prc.load_assessment("T1", signature=sig2) is None)

    # ── TTL expiry ──
    ok &= _ck("expired (max_age 0) → None",
              prc.load_assessment("T1", max_age_sec=0, signature=sig) is None)

    # ── signature sensitivity ──
    t_moved = dict(trade, legs=[{"type": "CE", "action": "SELL", "strike": 23200},
                                {"type": "PE", "action": "SELL", "strike": 22800}])
    ok &= _ck("signature flips when a leg strike changes",
              prc.compute_position_signature(trade, mtm=-200)
              != prc.compute_position_signature(t_moved, mtm=-200))
    ok &= _ck("signature stable within mtm bucket (noise)",
              prc.compute_position_signature(trade, mtm=-200)
              == prc.compute_position_signature(trade, mtm=-300))

    # ── assess_trade keeps only discretionary actions ──
    _fake_pm._run_return = [
        {"type": "ROLL", "priority": 1, "reason": "theta decay"},
        {"type": "CLOSE_ALL", "priority": 6, "reason": "floor"},      # protective → drop
        {"type": "CLOSE_SIDE", "priority": 4, "reason": "SL"},        # protective → drop
        {"type": "MORPH", "priority": 3, "reason": "regime flip"},
    ]
    asm = pr.assess_trade(trade)
    kinds = {x["type"] for x in asm["actions"]}
    ok &= _ck("assess_trade keeps morph/roll/tighten only",
              kinds == {"ROLL", "MORPH"})
    ok &= _ck("assess_trade drops protective (CLOSE_ALL/CLOSE_SIDE)",
              "CLOSE_ALL" not in kinds and "CLOSE_SIDE" not in kinds)
    ok &= _ck("assess_trade recommendation set", asm["recommendation"] in ("ROLL", "MORPH"))

    # ── HOLD when no discretionary trigger ──
    _fake_pm._run_return = [{"type": "CLOSE_SIDE", "priority": 4, "reason": "SL"}]
    asm2 = pr.assess_trade(trade)
    ok &= _ck("HOLD when only protective actions present",
              asm2["recommendation"] == "HOLD" and asm2["actions"] == [])

    # ── assess_and_cache writes a loadable entry under the live signature ──
    _fake_pm._run_return = [{"type": "ROLL", "priority": 1, "reason": "theta"}]
    pr.assess_and_cache(trade)
    live_sig = prc.compute_position_signature(trade, mtm=0.0)  # fake _check_sl_tp → mtm 0
    loaded = prc.load_assessment("T1", signature=live_sig)
    ok &= _ck("assess_and_cache → run_bridge would HIT with same signature",
              loaded is not None and loaded["recommendation"] == "ROLL")

    prc.invalidate()  # clean up cache files (Python unlink, not shell rm)
    print(f"\n{'ALL PASS' if ok else 'FAILURES'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
