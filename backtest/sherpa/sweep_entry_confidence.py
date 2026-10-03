#!/usr/bin/env python3
"""SHERPA — sweep combine.go_threshold.min_confidence to test the "paper mode:
take ALL non-conflict trades" config (antariksh/config/entry_weights.json,
min_confidence=0) against the SHERPA no-edge finding.

In-process monkeypatch only — never writes the live entry_weights.json.
Safe to run while other live processes (NEUTRON/PROTON) are reading the real file.

Usage (from brahmand/):
    python3 -m backtest.sherpa.sweep_entry_confidence --start 2024-01-01 --end 2024-06-30
"""

import argparse
import copy
import json
import sys
from pathlib import Path

BRAHMAND = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BRAHMAND))

import canonical_strategy
from backtest.sherpa.run_backtest import run

entry_tools = canonical_strategy._entry_tools()  # same module instance decide_entry() calls
REAL_CFG_PATH = BRAHMAND.parent / "antariksh" / "config" / "entry_weights.json"
BASE_CFG = json.loads(REAL_CFG_PATH.read_text())


def _patched_loader(min_confidence: int):
    cfg = copy.deepcopy(BASE_CFG)
    cfg["combine"]["go_threshold"]["min_confidence"] = min_confidence
    return lambda: cfg


def sweep(start: str, end: str, capital: float, thresholds: list[int]) -> list[dict]:
    orig_loader = entry_tools._load_weights
    results = []
    try:
        for thresh in thresholds:
            entry_tools._load_weights = _patched_loader(thresh)
            out_path = BRAHMAND / "backtest" / "sherpa" / f"_sweep_conf{thresh}.json"
            report = run(start, end, capital, out_path)
            bn = report["board_numbers"]
            results.append({
                "min_confidence": thresh,
                "trades": report["trades"]["count"],
                "win_rate_pct": bn["2_win_rate_pct"],
                "pct_return_per_month": bn["1_return_on_capital_pct_per_month"],
                "total_pnl_net": report["trades"]["total_pnl_net"],
                "max_drawdown": bn["max_drawdown"],
            })
            out_path.unlink(missing_ok=True)
            print(f"min_confidence={thresh:>3} | trades={results[-1]['trades']:>4} | "
                  f"win_rate={results[-1]['win_rate_pct']:>5}% | "
                  f"pnl=₹{results[-1]['total_pnl_net']:>10,.0f} | "
                  f"%/mo={results[-1]['pct_return_per_month']:>7}")
    finally:
        entry_tools._load_weights = orig_loader
    return results


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--capital", type=float, default=200_000.0)
    p.add_argument("--thresholds", default="0,20,35,50,65,80")
    a = p.parse_args()
    thresholds = [int(x) for x in a.thresholds.split(",")]
    results = sweep(a.start, a.end, a.capital, thresholds)
    out = BRAHMAND / "backtest" / "sherpa" / f"sweep_report_{a.start}_{a.end}.json"
    out.write_text(json.dumps(results, indent=2))
    print(f"\nfull sweep report -> {out}")


if __name__ == "__main__":
    main()
