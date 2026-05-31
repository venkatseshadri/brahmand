#!/usr/bin/env python3
"""
Brahmand Kickoff — run the 5-agent entry chain ONLY.

All preflight work (lock, state, market check, order check) is now
handled by entry_setup.py. This module is a pure chain runner.

The chain: Entry → Regime → Strategy → Contract → Execution → Risk
"""

import sys
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
load_dotenv()

from market_data import now_str
from logger import get_logger, log_exception

_log = get_logger("kickoff").info


def run_entry_pipeline(entry_time: str) -> dict | None:
    from e2e_chain import run_full_chain

    try:
        trade = run_full_chain(entry_time)
    except Exception as e:
        log_exception(get_logger("kickoff"), e, "Chain failed")
        return None

    if trade is None:
        _log("  SKIP: Gate rejected")
        return None
    if isinstance(trade, dict) and trade.get("recommendation") == "skip":
        _log(f"  SKIP: {trade.get('regime', 'unknown')}")
        return None
    if isinstance(trade, dict) and trade.get("recommendation") == "no_go":
        _log("  SKIP: Entry Agent NO-GO")
        return None

    trade["monitored_since"] = entry_time

    _log(
        f"ENTERED: {trade.get('strategy_type', '?')} "
        f"({trade.get('leg_count', 0)} legs) @ ₹{trade.get('net_credit', 0)} [{entry_time}]"
    )
    return trade


if __name__ == "__main__":
    import sys

    print("kickoff.py → use entry_setup.py (the preflight) instead.", file=sys.stderr)
    print("Running via entry_setup for backward compat...", file=sys.stderr)
    from entry_setup import main

    main()
