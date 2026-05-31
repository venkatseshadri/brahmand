#!/usr/bin/env python3
"""
Capital Compounding Model with NIFTYBEES Pledge Strategy

Scenario:
- Start: ₹2L cash
- Daily profit split: 50% NIFTYBEES, 50% cash
- NIFTYBEES collateral LTV: 65%
- NIFTYBEES growth: 7% annually
- Trading P&L: ₹18.77L from 1,060 butterflies over 250 trading days

Output: Final capital, concurrent positions, margin available
"""

import json
from pathlib import Path
from datetime import datetime, timedelta

# ── Parameters ──
STARTING_CAPITAL = 200_000  # ₹2L
TOTAL_TRADING_PNL = 18_77_000  # ₹18.77L from backtest
TOTAL_BUTTERFLIES = 1060
TRADING_DAYS = 250
BUTTERFLY_MARGIN = 142_500  # 2024 lot size 75

NIFTYBEES_LTV = 0.65  # 65% collateral
NIFTYBEES_GROWTH_ANNUAL = 0.07  # 7% per year
NIFTYBEES_GROWTH_DAILY = (1 + NIFTYBEES_GROWTH_ANNUAL) ** (1/250) - 1  # Daily compounding

NIFTY_SPOT = 23_750  # From margin matrix
NIFTYBEES_PRICE = NIFTY_SPOT / 100  # Approximate (1 NIFTYBEES unit ≈ NIFTY/100)
NIFTYBEES_LOT_SIZE = 1

# Profit distribution
DAILY_PROFIT = TOTAL_TRADING_PNL / TRADING_DAYS
PROFIT_TO_NIFTYBEES = DAILY_PROFIT * 0.50
PROFIT_TO_CASH = DAILY_PROFIT * 0.50

print("\n" + "="*80)
print("CAPITAL COMPOUNDING MODEL — 2024 NIFTYBEES PLEDGE STRATEGY")
print("="*80)

print(f"\n📊 Input Parameters:")
print(f"   Starting capital: ₹{STARTING_CAPITAL:,.0f}")
print(f"   Total trading P&L: ₹{TOTAL_TRADING_PNL:,.0f}")
print(f"   Trading days: {TRADING_DAYS}")
print(f"   Average daily profit: ₹{DAILY_PROFIT:,.0f}")
print(f"   → 50% to NIFTYBEES: ₹{PROFIT_TO_NIFTYBEES:,.0f}/day")
print(f"   → 50% to cash: ₹{PROFIT_TO_CASH:,.0f}/day")
print(f"   Butterfly margin: ₹{BUTTERFLY_MARGIN:,.0f}")
print(f"   NIFTYBEES collateral LTV: {NIFTYBEES_LTV*100:.0f}%")
print(f"   NIFTYBEES annual growth: {NIFTYBEES_GROWTH_ANNUAL*100:.1f}%")

# ── Daily Simulation ──
cash_balance = STARTING_CAPITAL
niftybees_units = 0
niftybees_value = 0
margin_from_pledge = 0
total_margin_available = 0
concurrent_butterflies = 0

history = []

for day in range(1, TRADING_DAYS + 1):
    # Daily profit allocation
    cash_balance += PROFIT_TO_CASH
    niftybees_buy_amount = PROFIT_TO_NIFTYBEES

    # Buy NIFTYBEES (adjust price for daily growth)
    niftybees_price_today = NIFTYBEES_PRICE * ((1 + NIFTYBEES_GROWTH_DAILY) ** day)
    units_bought = niftybees_buy_amount / niftybees_price_today
    niftybees_units += units_bought

    # Recalculate NIFTYBEES value (with appreciation)
    niftybees_value = niftybees_units * niftybees_price_today

    # Collateral margin from NIFTYBEES
    margin_from_pledge = niftybees_value * NIFTYBEES_LTV

    # Total margin available
    total_margin_available = cash_balance + margin_from_pledge

    # Concurrent butterflies possible
    concurrent_butterflies = int(total_margin_available / BUTTERFLY_MARGIN)

    # Record every 10 days + end
    if day % 10 == 0 or day == TRADING_DAYS:
        history.append({
            "day": day,
            "cash": round(cash_balance, 2),
            "niftybees_units": round(niftybees_units, 4),
            "niftybees_price": round(niftybees_price_today, 2),
            "niftybees_value": round(niftybees_value, 2),
            "margin_from_pledge": round(margin_from_pledge, 2),
            "total_margin": round(total_margin_available, 2),
            "concurrent_butterflies": concurrent_butterflies,
        })

# ── Final Summary ──
print(f"\n{'='*80}")
print(f"📈 FINAL STATE (Day {TRADING_DAYS})")
print(f"{'='*80}")

print(f"\n💰 Capital Components:")
print(f"   Cash balance: ₹{cash_balance:,.0f}")
print(f"   NIFTYBEES units: {niftybees_units:,.2f}")
print(f"   NIFTYBEES value: ₹{niftybees_value:,.0f}")
print(f"   NIFTYBEES appreciation: ₹{niftybees_value - (PROFIT_TO_NIFTYBEES * TRADING_DAYS):,.0f}")
print(f"   → (Realized gain from 7% annual growth)")

print(f"\n🔐 Collateral & Margin:")
print(f"   Margin from NIFTYBEES pledge (65%): ₹{margin_from_pledge:,.0f}")
print(f"   Total margin available: ₹{total_margin_available:,.0f}")
print(f"   Concurrent butterflies possible: {concurrent_butterflies}")

print(f"\n💎 Total Net Worth:")
total_net_worth = cash_balance + niftybees_value
print(f"   Cash + NIFTYBEES value: ₹{total_net_worth:,.0f}")
print(f"   Starting capital: ₹{STARTING_CAPITAL:,.0f}")
print(f"   Growth: ₹{total_net_worth - STARTING_CAPITAL:,.0f}")
print(f"   ROI: {((total_net_worth - STARTING_CAPITAL) / STARTING_CAPITAL * 100):.1f}%")

print(f"\n📊 Breakdown of Final Growth:")
trading_profit = TOTAL_TRADING_PNL
niftybees_appreciation = niftybees_value - (PROFIT_TO_NIFTYBEES * TRADING_DAYS)
print(f"   From trading P&L: ₹{trading_profit:,.0f} ({trading_profit/(total_net_worth - STARTING_CAPITAL)*100:.1f}%)")
print(f"   From NIFTYBEES appreciation: ₹{niftybees_appreciation:,.0f} ({niftybees_appreciation/(total_net_worth - STARTING_CAPITAL)*100:.1f}%)")
print(f"   Total gain: ₹{trading_profit + niftybees_appreciation:,.0f}")

print(f"\n{'='*80}")
print(f"Key Insight: By day {TRADING_DAYS}, you can hold {concurrent_butterflies} concurrent butterflies")
print(f"without touching the original ₹2L (all margin comes from reinvested profits).")
print(f"{'='*80}\n")

# ── Timeline ──
print(f"📅 Daily Progress Timeline:\n")
print(f"{'Day':<5} {'Cash':<15} {'NIFTYBEES Units':<18} {'NIFTYBEES Value':<18} {'Total Margin':<15} {'Concurrent':<12}")
print("-" * 100)

for row in history:
    print(f"{row['day']:<5} ₹{row['cash']:>13,.0f} {row['niftybees_units']:>16,.2f} ₹{row['niftybees_value']:>16,.0f} ₹{row['total_margin']:>13,.0f} {row['concurrent_butterflies']:>11}")

# ── Save results ──
results = {
    "timestamp": datetime.now().isoformat(),
    "scenario": "50% NIFTYBEES pledge + 50% cash reinvestment",
    "starting_capital": STARTING_CAPITAL,
    "total_trading_pnl": TOTAL_TRADING_PNL,
    "final_state": {
        "cash_balance": float(cash_balance),
        "niftybees_units": float(niftybees_units),
        "niftybees_value": float(niftybees_value),
        "niftybees_appreciation": float(niftybees_value - (PROFIT_TO_NIFTYBEES * TRADING_DAYS)),
        "margin_from_pledge": float(margin_from_pledge),
        "total_margin_available": float(total_margin_available),
        "concurrent_butterflies": int(concurrent_butterflies),
        "total_net_worth": float(total_net_worth),
        "roi_percent": float((total_net_worth - STARTING_CAPITAL) / STARTING_CAPITAL * 100),
    },
    "timeline": history,
}

Path("data/capital_compounding_2024.json").write_text(json.dumps(results, indent=2))
print(f"✅ Results saved: data/capital_compounding_2024.json\n")
