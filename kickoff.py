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

from logger import get_logger, log_exception


def run_entry_pipeline(entry_time: str) -> dict | None:
    from e2e_chain import run_full_chain

    try:
        trade = run_full_chain(entry_time)
    except Exception as e:
        log_exception(get_logger("kickoff"), e, "Chain failed")
        return None

    # None = chain returned nothing (entry gate: no signal or crew failure)
    if trade is None:
        return None
    # regime agent recommended "skip" (low VIX, choppy, no-go regime)
    if isinstance(trade, dict) and trade.get("recommendation") == "skip":
        return None
    # entry agent returned "no_go" (bearish/bullish entry blocked)
    if isinstance(trade, dict) and trade.get("recommendation") == "no_go":
        return None

    trade["monitored_since"] = entry_time
    return trade


if __name__ == "__main__":
    import sys

    print("kickoff.py → use entry_setup.py (the preflight) instead.", file=sys.stderr)
    print("Running via entry_setup for backward compat...", file=sys.stderr)
    from entry_setup import main

    main()
