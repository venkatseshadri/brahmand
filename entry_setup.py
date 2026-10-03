#!/usr/bin/env python3
"""
Brahmand Entry Setup — preflight guard for kickoff.

Called directly by cron every 5 min during market hours:
  1,6,11,16,21,26,31,36,41,46,51,56 9-15 * * 1-5 /usr/bin/python3 /home/trading_ceo/projects/brahmand/entry_setup.py

Handles ALL preparatory work:
  1. Process guard (pgrep self — skip if already running)
  2. Source .env (antariksh + brahmand)
  3. Acquire lock
  4. Load + roll over state
  5. Market hours check
  6. Order status check (active / max trades / cooldown)
  7. If all clear → run kickoff chain

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

# Source env files BEFORE other imports (may need env vars)
for env_file in [
    Path("/home/trading_ceo/projects/antariksh/.env"),
    Path(__file__).parent / ".env",
]:
    if env_file.exists():
        load_dotenv(env_file, override=True)

from logger import get_logger

_log = get_logger("entry_setup").info

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


def _has_active_order() -> tuple[bool, str]:
    """Check order_ledger.json for active trades. Returns (blocked, reason).
    Auto-clears stale test trades (>2 days) and aged trades (>7 days)
    before the blocking check so they don't jam the entry gate."""
    if not ORDER_LEDGER.exists():
        return False, "no ledger"

    try:
        ledger = json.loads(ORDER_LEDGER.read_text())
    except (json.JSONDecodeError, IOError):
        return False, "ledger unreadable"

    trades = ledger.get("_trades", {})
    from market_data import now_dt

    now = now_dt()
    today = now.strftime("%Y-%m-%d")
    ledger_dirty = False

    for tid in list(trades):
        t = trades[tid]
        if t.get("status") != "ACTIVE":
            continue
        entry_str = t.get("entry_time", "")
        entry_dt = None
        if isinstance(entry_str, str) and entry_str:
            try:
                entry_dt = datetime.fromisoformat(entry_str)
            except (ValueError, TypeError):
                pass

        if entry_dt is None:
            continue

        age_days = (now - entry_dt).days
        if tid.startswith("TEST-") and age_days > 2:
            t["status"] = "CLOSED"
            t["exit_reason"] = "AUTO_CLEAR_STALE_TEST"
            t["exit_time"] = now.isoformat()
            ledger_dirty = True
            _log(
                "AUTO_CLEAR_STALE_TEST: %s (entry=%s, age=%dd)",
                tid,
                entry_str,
                age_days,
            )
        elif age_days > 7:
            t["status"] = "CLOSED"
            t["exit_reason"] = "AUTO_CLEAR_AGED"
            t["exit_time"] = now.isoformat()
            ledger_dirty = True
            _log(
                "AUTO_CLEAR_AGED: %s (entry=%s, age=%dd)",
                tid,
                entry_str,
                age_days,
            )

    if ledger_dirty:
        tmp = ORDER_LEDGER.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(ledger, indent=2, default=str))
        os.replace(tmp, ORDER_LEDGER)
        _log("ledger updated: auto-cleared stale trades")

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
                    # entry_time is stamped naive (now_iso has no tz); keep the
                    # delta naive so it works under SIM_NOW too.
                    since = (
                        now_dt().replace(tzinfo=None) - entry_dt
                    ).total_seconds() / 60
                    if since < COOLDOWN_MIN:
                        return True, f"cooldown: {since:.0f}m < {COOLDOWN_MIN}m"
                except (ValueError, TypeError):
                    pass

    return False, "clear"


def main():
    from lock import acquire_lock, release_lock
    from market_data import is_market_hours
    from state import load_state, save_state, rollover_if_new_day
    from agentops_compat import init_agentops_if_enabled

    if not acquire_lock(LOCK_FILE):
        _log("Lock held — exiting")
        sys.exit(0)

    try:
        state = load_state(STATE_FILE)
        if rollover_if_new_day(state):
            _log(f"New trading day: {state['date']}")

        if not is_market_hours():
            _log("Market closed — exiting")
            return

        init_agentops_if_enabled()

        blocked, reason = _has_active_order()
        if blocked:
            _log(f"SKIP: {reason}")
            return

        _log(f"Entry run | Today: {state['trades_today']}")
        if "--dry-run" in sys.argv:
            _log("WOULD RUN: all gates clear")
            return

        from kickoff import run_entry_pipeline
        from market_data import now_str

        entry_time = now_str()
        trade = run_entry_pipeline(entry_time)

        if trade is not None:
            if state.get("all_trades"):
                prev = state["all_trades"][-1]
                trade["parent_trade_id"] = prev.get("trade_id", "?")
                trade["parent_exit_reason"] = prev.get("exit_reason", "?")
                trade["re_entry_count"] = (
                    (prev.get("re_entry_count", 0) + 1)
                    if prev.get("exit_reason")
                    else 0
                )

            state["active_trade"] = trade
            state["trades_today"] += 1

            _log(
                f"ENTERED: {state['trades_today']} today | "
                f"{trade.get('strategy_type', '?')} @ ₹{trade.get('net_credit', 0)}"
            )
        else:
            _log("SKIP: Pipeline rejected entry")

        save_state(STATE_FILE, state)
    finally:
        release_lock(LOCK_FILE)


if __name__ == "__main__":
    main()
