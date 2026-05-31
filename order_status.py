#!/usr/bin/env python3
"""
Order Status Checker — reads order_ledger.json and outputs active-trade JSON.

This is a standalone pre-flight check used by the cron wrapper shell script.
If an active order exists, kickoff.py is NOT called — clean separation of concerns.

Order ledger: data/order_ledger.json (canonical source — DuckDB is research only)

Output (stdout): JSON with has_active, active_trades, timestamp.
Exit code: 0 always (shell reads the JSON to decide).

Usage:
    python3 order_status.py          # prints JSON, exits 0
    python3 order_status.py --quiet  # exits 1 if active, 0 if none
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

QUIET = "--quiet" in sys.argv

LEDGER_FILE = Path(__file__).parent / "data" / "order_ledger.json"
MAX_TRADES = int(os.environ.get("BRAHMAND_MAX_TRADES", 4))
COOLDOWN_MIN = int(os.environ.get("BRAHMAND_COOLDOWN_MIN", 15))

try:
    result = {
        "has_active": False,
        "active_trades": [],
        "active_count": 0,
        "max_trades_reached": False,
        "today_trade_count": 0,
        "in_cooldown": False,
        "cooldown_remaining": 0,
        "timestamp": datetime.now().isoformat(),
    }

    if not LEDGER_FILE.exists():
        if QUIET:
            sys.exit(1)
        print(json.dumps(result, default=str))
        sys.exit(0)

    ledger = json.loads(LEDGER_FILE.read_text())
    today = datetime.now().strftime("%Y-%m-%d")
    today_trades = [
        trade
        for trade in ledger.get("_trades", {}).values()
        if trade.get("entry_time", "").startswith(today)
    ]

    active_trades = [t for t in today_trades if t.get("status") == "ACTIVE"]

    # Cooldown: minutes since last entry (today)
    if today_trades:
        last_entry = max(t.get("entry_time", "00:00") for t in today_trades)
        try:
            last_dt = datetime.fromisoformat(last_entry)
            elapsed = (datetime.now() - last_dt).total_seconds() / 60
            in_cooldown = elapsed < COOLDOWN_MIN
            cooldown_remaining = max(0, COOLDOWN_MIN - elapsed)
        except Exception:
            in_cooldown = False
            cooldown_remaining = 0
    else:
        in_cooldown = False
        cooldown_remaining = 0

    result = {
        "has_active": len(active_trades) > 0,
        "active_trades": active_trades,
        "active_count": len(active_trades),
        "max_trades_reached": len(today_trades) >= MAX_TRADES,
        "today_trade_count": len(today_trades),
        "max_trades": MAX_TRADES,
        "in_cooldown": in_cooldown,
        "cooldown_remaining": round(cooldown_remaining, 1),
        "timestamp": datetime.now().isoformat(),
    }

except Exception as e:
    result = {
        "has_active": False,
        "active_trades": [],
        "active_count": 0,
        "max_trades_reached": False,
        "today_trade_count": 0,
        "max_trades": MAX_TRADES,
        "in_cooldown": False,
        "cooldown_remaining": 0,
        "timestamp": datetime.now().isoformat(),
        "error": f"ledger_unavailable: {e}",
    }

if QUIET:
    skip = result["has_active"] or result["max_trades_reached"] or result["in_cooldown"]
    sys.exit(0 if skip else 1)

print(json.dumps(result, default=str))
