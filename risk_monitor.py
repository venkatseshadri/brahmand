#!/usr/bin/env python3
"""
DEPRECATED — superseded by position_manager.py (run via run_position_manager.sh).

The live 1-min risk monitor is now position_manager.run_bridge(); that is the only
path the cron invokes. This module and run_risk_monitor.sh are retained only for
the legacy tests that import monitor_trades. Do NOT schedule this in cron.

------------------------------------------------------------------------------
Risk Monitor — Runs every 1 minute during market hours.

Only executes when there are active positions.
Checks: SL/TP triggers, MORPH detection, leg shifts.
Closes trades and cleans up when SL/TP hit.

Audit log: /home/trading_ceo/brahmand/logs/risk_monitor_YYYYMMDD.log
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from duckdb_tool import _connect

LOG_DIR = Path("/home/trading_ceo/brahmand/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOCK_FILE = Path(__file__).parent / "data" / "risk_monitor.lock"
STATE_FILE = Path(__file__).parent / "data" / "brahmand_kickoff.json"
LEDGER_FILE = Path(__file__).parent / "data" / "order_ledger.json"


def _log(msg: str):
    """Log message with timestamp."""
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line)
    sys.stdout.flush()


def acquire_lock() -> bool:
    """Prevent overlapping runs."""
    if LOCK_FILE.exists():
        pid = LOCK_FILE.read_text().strip()
        try:
            os.kill(int(pid), 0)
            return False  # Already running
        except (OSError, ValueError):
            pass
    LOCK_FILE.write_text(str(os.getpid()))
    return True


def release_lock():
    """Release lock."""
    LOCK_FILE.unlink(missing_ok=True)


def load_state() -> dict:
    """Load state from brahmand_kickoff.json."""
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"active_trade": None}


def save_state(state: dict):
    """Save state to brahmand_kickoff.json."""
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


def has_active_trade() -> bool:
    """Check if there's an active trade in state file OR order ledger."""
    state = load_state()
    active_in_state = state.get("active_trade") is not None and (
        isinstance(state["active_trade"], dict)
        and state["active_trade"].get("status") == "OPEN"
    )
    if active_in_state:
        return True

    # Fallback: check order_ledger for any ACTIVE trades today
    try:
        from order_routing import get_active_trades

        return len(get_active_trades()) > 0
    except Exception:
        return False


def get_active_trade() -> dict:
    """Get active trade from state file, else from order ledger."""
    state = load_state()
    trade = state.get("active_trade")
    if trade and isinstance(trade, dict) and trade.get("status") in ("OPEN", "ACTIVE"):
        return trade

    # Fallback: get first active trade from order ledger
    try:
        from order_routing import get_active_trades

        active = get_active_trades()
        if active:
            return active[0]
    except Exception:
        pass
    return {}


# CSV LTP source (no DuckDB lock) — written by data_capture_v3.1 every minute
OPTIONS_CSV = Path("/home/trading_ceo/data/csv")


def _get_ltp_from_csv(strike: int, option_type: str, expiry: str = None) -> float:
    """Read latest option LTP from daily options CSV (no DuckDB lock needed)."""
    today = datetime.now().strftime("%Y-%m-%d")
    csv_path = OPTIONS_CSV / f"{today}_options.csv"
    if not csv_path.exists():
        return 0

    try:
        # Read file from end to find latest matching row faster
        with open(csv_path) as f:
            lines = f.readlines()
        # Scan in reverse for latest match
        ot = option_type.upper()
        s = str(strike)
        for line in reversed(lines):
            parts = line.strip().split(",")
            if len(parts) < 8:
                continue
            # CSV: timestamp,date,expiry_label,expiry_date,strike,strike_offset,option_type,ltp,...
            if parts[4] == s and parts[6] == ot:
                # expiry filter if provided (index 3)
                if expiry and parts[3] != expiry:
                    continue
                return float(parts[7])
    except Exception:
        pass
    return 0


def check_sl_tp_triggers(trade: dict) -> dict:
    """Check if SL or TP is hit. Uses daily options CSV (no DuckDB lock)."""
    expiry = trade.get("expiry", "")
    try:
        con = _connect()
        _use_duckdb = True
    except IOError:
        _use_duckdb = False

    try:
        for leg in trade.get("legs", []):
            if leg.get("action") != "SELL":
                continue

            t = leg["type"].lower()
            strike = leg["strike"]

            if _use_duckdb:
                row = con.execute(
                    "SELECT ltp FROM option_snapshots "
                    "WHERE expiry_date = ? AND strike = ? AND option_type = ? "
                    "AND tsym IS NOT NULL ORDER BY timestamp DESC LIMIT 1",
                    (expiry, strike, leg["type"]),
                ).fetchone()
                ltp = float(row[0] or 0) if row else 0
            else:
                ltp = _get_ltp_from_csv(strike, leg["type"], expiry)
                if ltp <= 0:
                    _log(f"  ⚠️ No CSV LTP for {strike}{leg['type']} (expiry={expiry})")
                    continue

            if ltp > 5000 or ltp <= 0:  # Sanity checks
                continue

            # Check SL
            sl = trade.get("sl", {}).get(t)
            if sl and ltp >= sl:
                _log(
                    f"🔴 SL HIT — {leg.get('tsym', strike)}{leg['type']}: LTP={ltp} >= SL={sl}"
                )
                return {"hit": True, "reason": "SL_HIT", "leg": leg, "ltp": ltp}

            # Check TP
            tp = trade.get("tp", {}).get(t)
            if tp and ltp <= tp:
                _log(
                    f"🟢 TP HIT — {leg.get('tsym', strike)}{leg['type']}: LTP={ltp} <= TP={tp}"
                )
                return {"hit": True, "reason": "TP_HIT", "leg": leg, "ltp": ltp}

    finally:
        if _use_duckdb:
            con.close()

    return {"hit": False}


def close_trade_and_cleanup(trade: dict, reason: str, ltp: float):
    """Close trade in state and update order ledger."""
    entry_time = trade.get("entry_time", "")

    # Calculate PnL (simplified: for short options, profit = entry - current)
    final_pnl = 0
    for leg in trade.get("legs", []):
        if leg.get("action") == "SELL":
            entry = leg.get("fill_price", 0)
            final_pnl += (entry - ltp) * leg.get("quantity", 1)

    _log(f"  Closing trade {entry_time}: {reason} | PnL: ₹{final_pnl:.0f}")

    # Update state file
    state = load_state()
    if state.get("active_trade"):
        state["active_trade"]["status"] = "CLOSED"
        state["active_trade"]["close_time"] = datetime.now().isoformat()
        state["active_trade"]["close_reason"] = reason
        state["active_trade"]["final_pnl"] = final_pnl

        # Move to all_trades history
        if "all_trades" not in state:
            state["all_trades"] = []
        state["all_trades"].append(state["active_trade"])
        state["active_trade"] = None

        save_state(state)
        _log(f"  ✅ Updated state for {entry_time}")

    # Also update order ledger
    trade_id = trade.get("trade_id")
    if trade_id:
        try:
            from order_routing import update_trade

            update_trade(
                trade_id,
                {
                    "status": "CLOSED",
                    "exit_time": datetime.now().isoformat(),
                    "exit_reason": reason,
                    "exit_price": ltp,
                    "final_pnl": final_pnl,
                },
            )
        except Exception as e:
            _log(f"  ⚠️ Failed to update order ledger: {e}")


def main():
    """Main risk monitor loop."""
    if not acquire_lock():
        return  # Already running, skip

    try:
        # Check if there are active trades in state file
        if not has_active_trade():
            return  # No active trades, exit silently

        _log("🔍 Risk Monitor: Checking active trades")

        trade = get_active_trade()
        if not trade:
            return

        entry_time = trade.get("entry_time", "?")
        strategy = trade.get("strategy_type", "?")

        # Calculate time open
        try:
            if "T" in str(entry_time):
                entry_dt = datetime.fromisoformat(str(entry_time).split(".")[0])
            else:
                # entry_time is HH:MM format, use today's date
                h, m = map(int, str(entry_time).split(":"))
                entry_dt = datetime.now().replace(
                    hour=h, minute=m, second=0, microsecond=0
                )
            open_mins = int((datetime.now() - entry_dt).total_seconds() / 60)
            _log(f"  {strategy} | Entry: {entry_time} | Open: {open_mins}m")
        except Exception as e:
            _log(f"  {strategy} | Entry: {entry_time} | ⚠️ time error")
            open_mins = 0

        # Check SL/TP
        result = check_sl_tp_triggers(trade)
        if result.get("hit"):
            close_trade_and_cleanup(trade, result["reason"], result.get("ltp", 0))
        else:
            _log(f"  ✅ Position OK | {entry_time}")

    except Exception as e:
        _log(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()

    finally:
        release_lock()


if __name__ == "__main__":
    main()
