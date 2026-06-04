"""Test trading system with Kaggle price data"""

import json
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_create_test_trade_in_ledger():
    # Sandbox ledger — NEVER the live data/order_ledger.json (the live entry
    # gate counts ACTIVE trades there; a test fixture would block real entries).
    ledger_path = PROJECT_ROOT / "tests" / "fixtures" / "sandbox_order_ledger.json"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {"_trades": {}}

    test_trade = {
        "trade_id": "TEST-KAGGLE-001",
        "entry_time": "2024-10-31T09:16:00",
        "status": "ACTIVE",
        "legs": [
            {
                "action": "SELL",
                "strike": 11750,
                "type": "PE",
                "fill_price": 2.35,
                "tsym": "BANKNIFTY31OCT24P11750",
                "quantity": 75,
            }
        ],
        "sl": {"pe": 4.0},
        "tp": {"pe": 1.0},
    }

    ledger.setdefault("_trades", {})["TEST-KAGGLE-001"] = test_trade
    ledger_path.write_text(json.dumps(ledger, indent=2, default=str))

    print(f"  Created test trade: TEST-KAGGLE-001")
    print(f"  Entry: {test_trade['legs'][0]['fill_price']} (SELL 11750 PE)")
    print(f"  SL: {test_trade['sl']['pe']}, TP: {test_trade['tp']['pe']}")


if __name__ == "__main__":
    test_create_test_trade_in_ledger()
