#!/usr/bin/env python3
"""
Full test cycle: entry → monitor with price data → exit → P&L
"""

import json
import pandas as pd
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def run_full_cycle_test():
    print("\n" + "=" * 60)
    print("FULL TRADING CYCLE TEST")
    print("=" * 60)

    # Sandbox ledger — NEVER the live data/order_ledger.json (would block real entries).
    ledger_path = PROJECT_ROOT / "tests" / "fixtures" / "sandbox_order_ledger.json"
    if not ledger_path.exists():
        print(f"SKIP: sandbox ledger not found at {ledger_path}")
        return

    ledger = json.loads(ledger_path.read_text())
    test_trade = ledger["_trades"].get("TEST-KAGGLE-001")

    if not test_trade:
        print("SKIP: Test trade not found in sandbox ledger")
        return

    print("\nTEST TRADE LOADED")
    print(f"   Trade ID: {test_trade['trade_id']}")
    print(f"   Entry time: {test_trade['entry_time']}")
    print(f"   Entry price: {test_trade['legs'][0]['fill_price']}")
    print(f"   SL: {test_trade['sl']['pe']}, TP: {test_trade['tp']['pe']}")

    prices_csv = PROJECT_ROOT / "data" / "csv" / "nifty_test_prices.csv"
    if not prices_csv.exists():
        print("SKIP: Price data not found")
        return

    prices = pd.read_csv(prices_csv)
    prices["datetime"] = pd.to_datetime(prices["datetime"])

    print(f"\nPRICE DATA LOADED")
    print(f"   Rows: {len(prices)}")
    print(f"   Date: {prices['datetime'].min()} to {prices['datetime'].max()}")

    # 3. MONITOR THE TRADE (replicate risk_monitor logic)
    entry_strike = test_trade["legs"][0]["strike"]
    entry_type = test_trade["legs"][0]["type"]
    entry_price = test_trade["legs"][0]["fill_price"]
    entry_time = test_trade["entry_time"]
    sl = test_trade["sl"].get(entry_type.lower(), None)
    tp = test_trade["tp"].get(entry_type.lower(), None)
    quantity = test_trade["legs"][0]["quantity"]

    strike_prices = prices[
        (prices["strike"] == entry_strike) & (prices["type"] == entry_type)
    ].copy()
    strike_prices = strike_prices.sort_values("datetime")

    print(f"\nMONITORING TRADE")
    print(f"   Strike: {entry_strike} {entry_type}")
    print(f"   Price points available: {len(strike_prices)}")

    exit_signal = None
    exit_price = None
    exit_time = None
    exit_row = None

    for idx, row in strike_prices.iterrows():
        current_ltp = row["ltp"]
        current_time = row["datetime"]

        if current_time < pd.to_datetime(entry_time):
            continue

        if tp and current_ltp <= tp:
            exit_signal = "TP_HIT"
            exit_price = current_ltp
            exit_time = current_time
            exit_row = row
            break

        if sl and current_ltp >= sl:
            exit_signal = "SL_HIT"
            exit_price = current_ltp
            exit_time = current_time
            exit_row = row
            break

    if exit_signal:
        pnl_points = entry_price - exit_price
        pnl_rupees = pnl_points * quantity

        duration_mins = int(
            (pd.to_datetime(exit_time) - pd.to_datetime(entry_time)).total_seconds()
            / 60
        )

        print(f"\n" + "=" * 60)
        print(f"EXIT DETECTED: {exit_signal}")
        print(f"=" * 60)
        print(f"   Exit price: {exit_price}")
        print(f"   Exit time: {exit_time}")
        print(f"   Duration: {duration_mins} minutes")
        print(f"\nP&L CALCULATION (risk_monitor.py logic):")
        print(f"   Entry price: {entry_price}")
        print(f"   Exit price: {exit_price}")
        print(f"   Points: {pnl_points:.2f} ({exit_signal})")
        print(f"   Quantity: {quantity}")
        print(f"   P&L: ({entry_price} - {exit_price}) x {quantity} = {pnl_rupees:.2f}")
        print(f"\n   Result: {'PROFIT' if pnl_rupees > 0 else 'LOSS'}")

        result = {
            "test_id": "TEST-KAGGLE-001",
            "timestamp": datetime.now().isoformat(),
            "entry_price": float(entry_price),
            "exit_price": float(exit_price),
            "exit_signal": exit_signal,
            "pnl_rupees": float(pnl_rupees),
            "duration_minutes": duration_mins,
            "status": "PASS" if abs(pnl_rupees) > 0 else "FAIL",
        }

        result_path = PROJECT_ROOT / "data" / "test_results.json"
        result_path.write_text(json.dumps(result, indent=2))

        print(f"\nResults saved to: {result_path}")
        print(f"\n{'=' * 60}")
        print(f"TEST STATUS: {result['status']}")
        print(f"{'=' * 60}")
        assert pnl_rupees != 0, "P&L should be non-zero for any exit"
    else:
        print(f"\nNo exit signal detected during period")


def test_full_cycle():
    run_full_cycle_test()


if __name__ == "__main__":
    run_full_cycle_test()
