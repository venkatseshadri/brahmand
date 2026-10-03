#!/usr/bin/env python3
"""SHERPA signal-exit comparison — mirrors decide_entry() as an exit trigger.

For each open trade, re-runs canonical_strategy.decide_entry() every 5 min
(same cadence/logic as entry). If it now GOes the *opposite* direction of the
open trade, that's logged as a shadow SIGNAL_FLIP exit — compared against the
trade's real SL/TP/EOD exit. Does not change real trades or the SHERPA numbers;
this is analysis only.

Usage (from brahmand/):
    python3 -m backtest.sherpa.run_signal_exit_compare --start 2024-01-01 --end 2024-12-31
"""

import argparse
import json
from pathlib import Path

from backtest.sherpa.run_backtest import run

BRAHMAND = Path(__file__).resolve().parent.parent.parent


def compare(start: str, end: str, capital: float, out_path: Path) -> dict:
    signal_log: list = []
    base_out = out_path.with_name(out_path.stem + "_base.json")
    base_report = run(start, end, capital, base_out, signal_exit_log=signal_log)

    n_trades = base_report["trades"]["count"]
    n_flips = len(signal_log)
    better, worse, equal = [], [], []
    minutes_saved = []
    for rec in signal_log:
        delta = rec["signal_pnl"] - rec["actual_pnl"]
        rec["pnl_delta_signal_minus_actual"] = round(delta, 2)
        if delta > 0:
            better.append(rec)
        elif delta < 0:
            worse.append(rec)
        else:
            equal.append(rec)
        minutes_saved.append(
            (
                pd_to_minutes(rec["actual_exit_ts"]) - pd_to_minutes(rec["flip_ts"])
            )
        )

    sl_hit_with_flip = [r for r in signal_log if r["actual_exit_reason"] == "SL_HIT"]
    sl_hit_flip_wouldve_helped = [r for r in sl_hit_with_flip if r["pnl_delta_signal_minus_actual"] > 0]

    report = {
        "meta": {"period": f"{start}..{end}", "note": "signal exit = decide_entry() re-run vs open trade, mirrored"},
        "trades_total": n_trades,
        "trades_with_flip_before_actual_exit": n_flips,
        "flip_rate_pct": round(100 * n_flips / n_trades, 1) if n_trades else 0,
        "signal_exit_better_count": len(better),
        "signal_exit_worse_count": len(worse),
        "signal_exit_equal_count": len(equal),
        "total_pnl_delta_signal_minus_actual": round(sum(r["pnl_delta_signal_minus_actual"] for r in signal_log), 2),
        "sl_hit_trades_with_prior_flip": len(sl_hit_with_flip),
        "sl_hit_trades_flip_wouldve_reduced_loss": len(sl_hit_flip_wouldve_helped),
        "avg_minutes_flip_precedes_actual_exit": (
            round(sum(minutes_saved) / len(minutes_saved), 1) if minutes_saved else None
        ),
        "flip_records": signal_log,
    }
    out_path.write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps({k: v for k, v in report.items() if k != "flip_records"}, indent=2))
    print(f"\nfull report → {out_path}")
    return report


def pd_to_minutes(ts_str: str) -> float:
    import pandas as pd
    return pd.Timestamp(ts_str).timestamp() / 60.0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--capital", type=float, default=200_000.0)
    p.add_argument("--out", default=None)
    a = p.parse_args()
    out = Path(a.out) if a.out else BRAHMAND / "backtest" / "sherpa" / f"signal_exit_report_{a.start}_{a.end}.json"
    compare(a.start, a.end, a.capital, out)


if __name__ == "__main__":
    main()
