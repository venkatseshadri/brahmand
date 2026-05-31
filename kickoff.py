#!/usr/bin/env python3
"""
Brahmand Kickoff — Entry-only orchestrator for the 5-agent chain.

Triggered by cron/run_kickoff.sh ONLY when no active trade exists
(gated by order_status.py against the order_ledger.json).

Lock-protected: won't overlap with a previous run.

Usage:
    python kickoff.py                 # manual
    python kickoff.py --once          # single run (wrapped by cron shell script)

State tracked in data/brahmand_kickoff.json:
    - pid, last_run, active_trade, trades_today
"""

import os
import sys
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
load_dotenv()

from market_data import is_market_hours, now_str
from lock import acquire_lock, release_lock
from state import load_state, save_state

_SANDBOX = os.environ.get("BRAHMAND_SANDBOX", "")
if _SANDBOX:
    STATE_DIR = Path(_SANDBOX) / "state"
else:
    STATE_DIR = Path(__file__).parent / "data"
STATE_DIR.mkdir(parents=True, exist_ok=True)
LOCK_FILE = STATE_DIR / "brahmand_kickoff.lock"
STATE_FILE = STATE_DIR / "brahmand_kickoff.json"

from logger import (
    get_logger,
    log_exception,
)

_log = get_logger("kickoff").info


def run_entry_pipeline(state: dict):
    """Run Entry → Regime → Strategy → Contract → Execution → Risk chain.
    Entry Agent is the first gate — called inline, not from a stale file."""
    from e2e_chain import run_full_chain

    entry_time = now_str()
    try:
        trade = run_full_chain(entry_time)
    except Exception as e:
        from logger import log_exception

        log_exception(get_logger("kickoff"), e, "Chain failed")
        return state
    if trade is None:
        _log("  SKIP: Gate rejected")
        return state
    if isinstance(trade, dict) and trade.get("recommendation") == "skip":
        _log(f"  SKIP: {trade.get('regime', 'unknown')}")
        return state
    if isinstance(trade, dict) and trade.get("recommendation") == "no_go":
        _log("  SKIP: Entry Agent NO-GO")
        return state

    strategy_type = trade.get("strategy_type", "IRON_BUTTERFLY")

    # Store entry_scores on trade for pattern logging on exit
    trade["entry_gate_signal"] = trade.get(
        "entry_gate_signal", trade.get("entry_scores", {}).get("signal", "UNKNOWN")
    )
    trade["monitored_since"] = entry_time

    # Initialize monitoring phase tracking for postmortem analysis
    trade["monitoring_events"] = {
        "tsl_adjustments": [],  # TSL ratchet history
        "morph_actions": [],  # Signal reversal actions
        "shift_actions": [],  # Premium decay shifts
        "mtm_checks": [],  # P&L snapshots during monitoring
    }

    state["active_trade"] = trade
    state["trades_today"] += 1

    # Link to previous trade (re-entry chain)
    if state.get("all_trades"):
        prev = state["all_trades"][-1]
        trade["parent_trade_id"] = prev.get("trade_id", "?")
        trade["parent_exit_reason"] = prev.get("exit_reason", "?")
        trade["re_entry_count"] = (
            (prev.get("re_entry_count", 0) + 1) if prev.get("exit_reason") else 0
        )

    # Order creation is owned by the execution agent via place_entry_orders()
    # (tools/chain_tools.py), which writes to BOTH order_ledger.json AND
    # trade_execution.duckdb atomically. No duplicate writes here.

    # SL/TP placement is OWNED by the LLM RISK agent (primary). A deterministic
    # fallback in position_manager.run_bridge places them only when the LLM is down.
    # Do NOT hard-place SL/TP here — see risk_agent_crew.py docstring (reverted 2x).

    _log(
        f"ENTERED: {strategy_type} ({trade['leg_count']} legs) @ ₹{trade['net_credit']} [{entry_time}]"
    )
    return state


def main():
    if not acquire_lock(LOCK_FILE):
        _log("Lock held by another kickoff — exiting")
        sys.exit(0)

    try:
        state = load_state(STATE_FILE)
        today = datetime.now().strftime("%Y%m%d")
        if state["date"] != today:
            _log(f"New trading day: {today} (was {state['date']})")
            state["date"] = today

        if not is_market_hours():
            if state["active_trade"]:
                _log(
                    "Market closed — active trade still open (should be closed by risk monitor)"
                )
            _log("Market closed — exiting")
            return

        prev_count = state["trades_today"]
        _log(f"Entry run | Today: {prev_count}")

        run_entry_pipeline(state)

        if state["trades_today"] > prev_count:
            trade = state["active_trade"]
            _log(
                f"ENTERED: {state['trades_today']} today | "
                f"{trade.get('strategy_type', '?')} @ ₹{trade.get('net_credit', 0)}"
            )
        elif state["active_trade"] is None:
            _log("SKIP: Pipeline rejected entry")
        else:
            _log("SKIP: No new entry (trade already active)")

        save_state(STATE_FILE, state)
    finally:
        release_lock(LOCK_FILE)


if __name__ == "__main__":
    main()
