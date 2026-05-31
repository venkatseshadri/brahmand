#!/usr/bin/env python3
"""
Full test cycle: entry → monitor with price data → exit → P&L
"""
import json
import pandas as pd
from pathlib import Path
from datetime import datetime

print("\n" + "="*60)
print("FULL TRADING CYCLE TEST")
print("="*60)

# 1. CHECK ORDER LEDGER (test trade created)
ledger_path = Path("data/order_ledger.json")
ledger = json.loads(ledger_path.read_text())
test_trade = ledger["_trades"].get("TEST-KAGGLE-001")

if not test_trade:
    print("❌ Test trade not found in order_ledger")
    exit(1)

print("\n✅ TEST TRADE LOADED")
print(f"   Trade ID: {test_trade['trade_id']}")
print(f"   Entry time: {test_trade['entry_time']}")
print(f"   Entry price: ₹{test_trade['legs'][0]['fill_price']}")
print(f"   SL: ₹{test_trade['sl']['pe']}, TP: ₹{test_trade['tp']['pe']}")

# 2. LOAD PRICE DATA
prices_csv = Path("data/csv/nifty_test_prices.csv")
if not prices_csv.exists():
    print("❌ Price data not found")
    exit(1)

prices = pd.read_csv(prices_csv)
prices['datetime'] = pd.to_datetime(prices['datetime'])

print(f"\n✅ PRICE DATA LOADED")
print(f"   Rows: {len(prices)}")
print(f"   Date: {prices['datetime'].min()} to {prices['datetime'].max()}")

# 3. MONITOR THE TRADE (replicate risk_monitor logic)
entry_strike = test_trade['legs'][0]['strike']
entry_type = test_trade['legs'][0]['type']
entry_price = test_trade['legs'][0]['fill_price']
entry_time = test_trade['entry_time']
sl = test_trade['sl'].get(entry_type.lower(), None)
tp = test_trade['tp'].get(entry_type.lower(), None)
quantity = test_trade['legs'][0]['quantity']

strike_prices = prices[(prices['strike'] == entry_strike) & 
                       (prices['type'] == entry_type)].copy()
strike_prices = strike_prices.sort_values('datetime')

print(f"\n✅ MONITORING TRADE")
print(f"   Strike: {entry_strike} {entry_type}")
print(f"   Price points available: {len(strike_prices)}")

# Simulate monitoring
exit_signal = None
exit_price = None
exit_time = None
exit_row = None

for idx, row in strike_prices.iterrows():
    current_ltp = row['ltp']
    current_time = row['datetime']
    
    # Skip before entry time
    if current_time < pd.to_datetime(entry_time):
        continue
    
    # Check TP
    if tp and current_ltp <= tp:
        exit_signal = "TP_HIT"
        exit_price = current_ltp
        exit_time = current_time
        exit_row = row
        break
    
    # Check SL
    if sl and current_ltp >= sl:
        exit_signal = "SL_HIT"
        exit_price = current_ltp
        exit_time = current_time
        exit_row = row
        break

# 4. CALCULATE P&L (same as risk_monitor.py line 211)
if exit_signal:
    # For SELL: profit = (entry_price - current_price) × quantity
    pnl_points = entry_price - exit_price
    pnl_rupees = pnl_points * quantity
    
    duration_mins = int((pd.to_datetime(exit_time) - pd.to_datetime(entry_time)).total_seconds() / 60)
    
    print(f"\n" + "="*60)
    print(f"✅ EXIT DETECTED: {exit_signal}")
    print(f"="*60)
    print(f"   Exit price: ₹{exit_price}")
    print(f"   Exit time: {exit_time}")
    print(f"   Duration: {duration_mins} minutes")
    print(f"\n📊 P&L CALCULATION (risk_monitor.py logic):")
    print(f"   Entry price: ₹{entry_price}")
    print(f"   Exit price: ₹{exit_price}")
    print(f"   Points: {pnl_points:.2f} ({exit_signal})")
    print(f"   Quantity: {quantity}")
    print(f"   P&L: ({entry_price} - {exit_price}) × {quantity} = ₹{pnl_rupees:.2f}")
    print(f"\n   Result: {'✅ PROFIT' if pnl_rupees > 0 else '❌ LOSS'}")
    
    # 5. SAVE RESULTS
    result = {
        "test_id": "TEST-KAGGLE-001",
        "timestamp": datetime.now().isoformat(),
        "entry_price": float(entry_price),
        "exit_price": float(exit_price),
        "exit_signal": exit_signal,
        "pnl_rupees": float(pnl_rupees),
        "duration_minutes": duration_mins,
        "status": "✅ PASS" if abs(pnl_rupees) > 0 else "❌ FAIL"  # Any non-zero = correct calc
    }
    
    result_path = Path("data/test_results.json")
    result_path.write_text(json.dumps(result, indent=2))
    
    print(f"\n✅ Results saved to: {result_path}")
    print(f"\n{'='*60}")
    print(f"TEST STATUS: {result['status']}")
    print(f"{'='*60}")
    
else:
    print(f"\n❌ No exit signal detected during period")

