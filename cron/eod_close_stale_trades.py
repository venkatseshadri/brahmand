#!/usr/bin/env python3
"""EOD backstop — close trades left ACTIVE at their session close.

Why this exists: the live position manager (position_manager.run_bridge) closes
trades only on SL/TP hit — its EOD market-close square-off lives in the dead
run() path and never fires. So a trade that doesn't hit SL/TP stays ACTIVE
forever, and entry_setup's single-position / MAX_TRADES guard then blocks every
new entry. This job force-closes any still-ACTIVE trade for the named indices
so the next session starts clean.

Scoped by index so each market is cleaned at its OWN close:
  - NIFTY/SENSEX cash close 15:30  → cron 31 15 (--indices NIFTY SENSEX)
  - MCX close ~23:30               → cron 35 23 (--indices MCX)  [only if MCX
    is ever traded; today the entry chain trades NIFTY/SENSEX only]
A trade is only touched if its legs identify it as one of the requested
indices. MCX (and any unparseable trade) is left alone by the equity job.

This is a paper-trading ledger backstop, NOT a substitute for real exit logic.
It marks the ledger CLOSED; it does not place square-off orders. The proper fix
is (a) add an EOD square-off to run_bridge and (b) reconcile the JSON<->DuckDB
split-brain. Until then, this prevents the entry guard from jamming.

Usage: python3 eod_close_stale_trades.py [--indices NIFTY SENSEX] [--dry-run]
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

LEDGER = Path(__file__).resolve().parent.parent / "data" / "order_ledger.json"
KNOWN_INDICES = ("NIFTY", "SENSEX", "MCX")
# MCX index options trade under per-commodity symbols, not an "MCX" prefix.
MCX_PREFIXES = ("GOLD", "SILVER", "CRUDE", "NATGAS", "COPPER", "ZINC",
                "ALUMINI", "LEAD", "NICKEL")


def _underlying(trade: dict) -> str | None:
    for leg in trade.get("legs", []) or []:
        tsym = (leg.get("tsym") or "").upper()
        if tsym.startswith("NIFTY"):
            return "NIFTY"
        if tsym.startswith("SENSEX"):
            return "SENSEX"
        if any(tsym.startswith(p) for p in MCX_PREFIXES):
            return "MCX"
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--indices", nargs="+", default=["NIFTY", "SENSEX"],
                    choices=KNOWN_INDICES, help="which indices to close")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    want = set(args.indices)

    now = datetime.now()
    stamp = now.strftime("%Y-%m-%d %H:%M:%S")
    tag = "+".join(sorted(want))

    if not LEDGER.exists():
        print(f"[{stamp}] eod_close[{tag}]: no ledger at {LEDGER}")
        return 0

    led = json.loads(LEDGER.read_text())
    trades = led.get("_trades", {})

    # Only ACTIVE trades whose legs identify them as a requested index.
    # Unparseable / other-index trades are deliberately left untouched.
    to_close = [
        (tid, t) for tid, t in trades.items()
        if t.get("status") == "ACTIVE" and _underlying(t) in want
    ]

    if not to_close:
        print(f"[{stamp}] eod_close[{tag}]: no ACTIVE {tag} trades — clean")
        return 0

    print(f"[{stamp}] eod_close[{tag}]: {len(to_close)} ACTIVE trade(s) to force-close"
          + (" (DRY-RUN)" if args.dry_run else ""))
    for tid, t in to_close:
        und = _underlying(t)
        print(f"  {'WOULD CLOSE' if args.dry_run else 'CLOSED'}: {tid} "
              f"[{und}] {t.get('strategy_type', '?')} entry={t.get('entry_time', '?')}")
        if not args.dry_run:
            t["status"] = "CLOSED"
            t["exit_reason"] = f"EOD_AUTO_CLOSE_{und}"
            t["exit_time"] = now.isoformat()

    if not args.dry_run:
        tmp = LEDGER.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(led, indent=2, default=str))
        os.replace(tmp, LEDGER)  # atomic
        print(f"[{stamp}] eod_close[{tag}]: ledger updated ({len(to_close)} closed)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
