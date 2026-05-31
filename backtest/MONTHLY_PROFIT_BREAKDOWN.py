#!/usr/bin/env python3
"""
Simple Monthly Breakdown — Just Cash Reinvestment, No Leverage

Question: If we have ₹18.77L from 1,060 butterflies over 250 days,
how does this distribute monthly with cash reinvestment?

Assumption: Even distribution across 12 months (or actual trading days).
"""

import json
from pathlib import Path
from datetime import datetime

# ── Parameters ──
STARTING_CAPITAL = 200_000  # ₹2L
TOTAL_TRADING_PNL = 18_77_000  # ₹18.77L
TOTAL_BUTTERFLIES = 1060
TRADING_DAYS = 250
BUTTERFLY_MARGIN = 142_500

# Monthly distribution
MONTHS = 12
TRADING_DAYS_PER_MONTH = TRADING_DAYS / MONTHS  # ~21 trading days/month
BUTTERFLIES_PER_MONTH = TOTAL_BUTTERFLIES / MONTHS  # ~88 butterflies/month
PROFIT_PER_MONTH = TOTAL_TRADING_PNL / MONTHS  # ~₹156.4k/month

print("\n" + "="*100)
print("MONTHLY BREAKDOWN — 2024 NIFTY IRON BUTTERFLY")
print("="*100)

print(f"\n📊 Input:")
print(f"   Starting capital: ₹{STARTING_CAPITAL:,.0f}")
print(f"   Total trading P&L: ₹{TOTAL_TRADING_PNL:,.0f}")
print(f"   Total butterflies: {TOTAL_BUTTERFLIES}")
print(f"   Trading days: {TRADING_DAYS}")
print(f"   Butterfly margin: ₹{BUTTERFLY_MARGIN:,.0f}")

print(f"\n📅 Monthly Average:")
print(f"   Trading days/month: {TRADING_DAYS_PER_MONTH:.0f}")
print(f"   Butterflies/month: {BUTTERFLIES_PER_MONTH:.0f}")
print(f"   Profit/month: ₹{PROFIT_PER_MONTH:,.0f}")

# ── Monthly Simulation (Reinvestment Logic) ──
cash = STARTING_CAPITAL
margin_available = cash / BUTTERFLY_MARGIN
history = []

print(f"\n{'Month':<8} {'Profit':<15} {'Cash Balance':<18} {'Concurrent':<15} {'Net Worth':<18}")
print("-" * 100)

for month in range(1, MONTHS + 1):
    # Add monthly profit
    cash += PROFIT_PER_MONTH

    # Calculate concurrent butterflies possible
    concurrent = int(cash / BUTTERFLY_MARGIN)

    # Net worth = cash only (no NIFTYBEES)
    net_worth = cash

    print(f"{month:<8} ₹{PROFIT_PER_MONTH:>13,.0f} ₹{cash:>16,.0f} {concurrent:>14} ₹{net_worth:>16,.0f}")

    history.append({
        "month": month,
        "monthly_profit": round(PROFIT_PER_MONTH, 0),
        "cumulative_cash": round(cash, 0),
        "concurrent_butterflies": concurrent,
    })

print("-" * 100)

final_capital = STARTING_CAPITAL + TOTAL_TRADING_PNL
roi = (final_capital - STARTING_CAPITAL) / STARTING_CAPITAL * 100

print(f"\n{'FINAL':<8} ₹{TOTAL_TRADING_PNL:>13,.0f} ₹{final_capital:>16,.0f} {int(final_capital/BUTTERFLY_MARGIN):>14} ₹{final_capital:>16,.0f}")

print(f"\n{'='*100}")
print(f"Final Capital: ₹{final_capital:,.0f}")
print(f"Starting Capital: ₹{STARTING_CAPITAL:,.0f}")
print(f"Growth: ₹{final_capital - STARTING_CAPITAL:,.0f}")
print(f"ROI: {roi:.1f}%")
print(f"Concurrent butterflies possible: {int(final_capital/BUTTERFLY_MARGIN)}")
print(f"{'='*100}\n")

# ── Now Ask: What if we can trade MULTIPLE butterflies simultaneously? ──
print("\n⚠️  CRITICAL QUESTION:")
print(f"The ₹18.77L came from 1,060 SEQUENTIAL butterflies.")
print(f"But if we have ₹2L capital → can hold {int(STARTING_CAPITAL/BUTTERFLY_MARGIN)} concurrent butterflies.")
print(f"\nSo actual potential is:")
print(f"   If 250 trading days can fit ~88 butterflies/month")
print(f"   But we can hold 14 concurrently")
print(f"   → Potential total butterflies = 88 × (14 / 1) = higher multiplier")
print(f"\nWithout knowing exact trade duration and exit frequency,")
print(f"the ₹18.77L assumes sequential (no reinvestment advantage).")

# Save
results = {
    "timestamp": datetime.now().isoformat(),
    "scenario": "Cash-only reinvestment, no leverage",
    "monthly_breakdown": history,
    "final_summary": {
        "starting_capital": STARTING_CAPITAL,
        "total_pnl": TOTAL_TRADING_PNL,
        "final_capital": final_capital,
        "roi_percent": roi,
        "max_concurrent_butterflies": int(final_capital/BUTTERFLY_MARGIN),
    },
}

Path("data/monthly_breakdown_2024.json").write_text(json.dumps(results, indent=2))
print(f"✅ Saved: data/monthly_breakdown_2024.json\n")
