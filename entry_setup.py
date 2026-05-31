#!/usr/bin/env python3
"""
Brahmand Entry Setup — preflight guard for kickoff.

Called by cron/run_kickoff.sh. Handles ALL preparatory work:
  1. Acquire lock
  2. Load + roll over state (date change)
  3. Market hours check
  4. Order status check (active trade / max trades / cooldown)
  5. If all clear → run kickoff chain

Roles:
  entry_setup.py → preflight + guard + state
  kickoff.py     → run the 5-agent chain ONLY

Usage:
    python entry_setup.py                # full flow (cron)
    python entry_setup.py --dry-run      # print would-run / skip + reason
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
load_dotenv()

from lock import acquire_lock, release_lock
from market_data import is_market_hours
from state import load_state, save_state, rollover_if_new_day
from logger import get_logger


SANDBOX = os.environ.get("BRAHMAND_SANDBOX", "")
if SANDBOX:
    STATE_DIR = Path(SANDBOX) / "state"
else:
    STATE_DIR = Path(__file__).parent / "data"
STATE_DIR.mkdir(parents=True, exist_ok=True)
LOCK_FILE = STATE_DIR / "brahmand_entry.lock"
STATE_FILE = STATE_DIR / "brahmand_entry.json"
ORDER_LEDGER = Path(__file__).parent / "data" / "order_ledger.json"
MAX_TRADES = int(os.environ.get("BRAHMAND_MAX_TRADES", 4))
COOLDOWN_MIN = int(os.environ.get("BRAHMAND_COOLDOWN_MIN", 15))

_log = get_logger("entry_setup").info


def _has_active_order() -> tuple[bool, str]:
    """Check order_ledger.json for active trades. Returns (blocked, reason)."""
    if not ORDER_LEDGER.exists():
        return False, "no ledger"

    try:
        ledger = json.loads(ORDER_LEDGER.read_text())
    except (json.JSONDecodeError, IOError):
        return False, "ledger unreadable"

    trades = ledger.get("_trades", {})
    today = datetime.now().strftime("%Y-%m-%d")
    active = []
    today_count = 0

    for tid, t in trades.items():
        if t.get("status") == "ACTIVE":
            active.append(tid)
        entry = t.get("entry_time", "")
        if isinstance(entry, str) and entry.startswith(today):
            today_count += 1

    if active:
        return True, f"{len(active)} active trade(s): {active}"

    if today_count >= MAX_TRADES:
        return True, f"max trades ({MAX_TRADES}) reached today"

    if today_count > 0:
        for tid, t in trades.items():
            if t.get("status") != "ACTIVE":
                continue
            entry = t.get("entry_time", "")
            if isinstance(entry, str) and entry.startswith(today):
                try:
                    entry_dt = datetime.fromisoformat(entry)
                    since = (datetime.now() - entry_dt).total_seconds() / 60
                    if since < COOLDOWN_MIN:
                        return True, f"cooldown: {since:.0f}m < {COOLDOWN_MIN}m"
                except (ValueError, TypeError):
                    pass

    return False, "clear"


def main():
    dry = "--dry-run" in sys.argv

    if not acquire_lock(LOCK_FILE):
        msg = "Lock held — exiting"
        _log(msg)
        if dry:
            print(f"BLOCKED: {msg}")
        sys.exit(0)

    try:
        state = load_state(STATE_FILE)
        if rollover_if_new_day(state):
            _log(f"New trading day: {state['date']}")

        if not is_market_hours():
            _log("Market closed — exiting")
            if dry:
                print("SKIP: market closed")
            return

        blocked, reason = _has_active_order()
        if blocked:
            _log(f"SKIP: {reason}")
            if dry:
                print(f"SKIP: {reason}")
            return

        _log(f"Entry run | Today: {state['trades_today']}")
        if dry:
            print("WOULD RUN: all gates clear")
            return

        from kickoff import run_entry_pipeline

        prev_count = state["trades_today"]
        state = run_entry_pipeline(state)

        if state.get("trades_today", 0) > prev_count:
            trade = state.get("active_trade", {})
            _log(
                f"ENTERED: {state['trades_today']} today | "
                f"{trade.get('strategy_type', '?')} @ ₹{trade.get('net_credit', 0)}"
            )
        elif state.get("active_trade") is None:
            _log("SKIP: Pipeline rejected entry")
        else:
            _log("SKIP: No new entry (trade already active)")

        save_state(STATE_FILE, state)
    finally:
        release_lock(LOCK_FILE)


if __name__ == "__main__":
    main()
