"""Test trading system with Kaggle price data"""
import json
from pathlib import Path
from datetime import datetime

# 1. Create a test trade in order_ledger manually
ledger_path = Path("data/order_ledger.json")
ledger = json.loads(ledger_path.read_text())

# Create test trade with proper structure
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
            "quantity": 75
        }
    ],
    "sl": {"pe": 4.0},
    "tp": {"pe": 1.0}
}

# Add to ledger
ledger["_trades"]["TEST-KAGGLE-001"] = test_trade
ledger_path.write_text(json.dumps(ledger, indent=2, default=str))

print("✅ Created test trade: TEST-KAGGLE-001")
print(f"   Entry: ₹{test_trade['legs'][0]['fill_price']} (SELL 11750 PE)")
print(f"   SL: ₹{test_trade['sl']['pe']}, TP: ₹{test_trade['tp']['pe']}")
print(f"\nNow run: python3 -c \"from risk_monitor import monitor_trades; monitor_trades()\"")
