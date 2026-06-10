#!/usr/bin/env python3
"""Regression: paper entries must never FILL at price 0 (SHERPA Phase 0).

The 2026-06-05 paper trade booked entry orders with execution_price 0.0 —
paper P&L computed from those fills is fiction. place_entry_orders must
either mark priceless legs to the live captured LTP or REJECT the entry.
"""

import os
import shutil
import sys
from pathlib import Path

SANDBOX = Path(__file__).parent / "fixtures" / "sherpa_sandbox"


def _fresh_sandbox():
    if SANDBOX.exists():
        shutil.rmtree(SANDBOX)
    (SANDBOX / "state").mkdir(parents=True)


def main() -> int:
    _fresh_sandbox()
    os.environ["BRAHMAND_SANDBOX"] = str(SANDBOX)
    sys.path.insert(0, str(Path(__file__).parent.parent))
    import order_routing

    failures = []

    # 1) No price anywhere → whole entry REJECTED, nothing in the ledger
    order_routing._live_ltp = lambda tsym: 0.0
    legs = [
        {"tsym": "NIFTY16JUN2026C25000", "action": "SELL", "strike": 25000,
         "type": "CE", "fill_price": 0, "quantity": 65},
        {"tsym": "NIFTY16JUN2026C25200", "action": "BUY", "strike": 25200,
         "type": "CE", "fill_price": 0, "quantity": 65},
    ]
    result = order_routing.place_entry_orders(legs)
    if result["status"] != "REJECTED":
        failures.append(f"expected REJECTED on 0-price legs, got {result['status']}")
    ledger = order_routing._load_ledger()
    if ledger.get("orders"):
        failures.append(f"REJECTED entry still wrote {len(ledger['orders'])} orders")

    # 2) Live LTP available → legs marked to it, entry fills at real price
    order_routing._live_ltp = lambda tsym: 42.5
    legs = [
        {"tsym": "NIFTY16JUN2026C25000", "action": "SELL", "strike": 25000,
         "type": "CE", "fill_price": 0, "quantity": 65},
    ]
    result = order_routing.place_entry_orders(legs)
    if result["status"] != "FILLED":
        failures.append(f"expected FILLED with live LTP, got {result['status']}")
    if legs[0]["fill_price"] != 42.5:
        failures.append(f"leg not marked to live LTP: {legs[0]['fill_price']}")
    ledger = order_routing._load_ledger()
    zero_fills = [
        o for o in ledger.get("orders", {}).values()
        if o.get("order_type") == "ENTRY" and not o.get("execution_price")
    ]
    if zero_fills:
        failures.append(f"{len(zero_fills)} ENTRY orders booked at price 0")

    # 3) Pre-priced legs pass through untouched
    legs = [
        {"tsym": "NIFTY16JUN2026P24800", "action": "SELL", "strike": 24800,
         "type": "PE", "fill_price": 87.3, "quantity": 65},
    ]
    result = order_routing.place_entry_orders(legs)
    if result["status"] != "FILLED" or legs[0]["fill_price"] != 87.3:
        failures.append("pre-priced leg was altered or rejected")

    shutil.rmtree(SANDBOX, ignore_errors=True)
    if failures:
        for f in failures:
            print(f"  FAIL: {f}")
        return 1
    print("  OK honest-entry-fills 3/3")
    return 0


if __name__ == "__main__":
    sys.exit(main())
