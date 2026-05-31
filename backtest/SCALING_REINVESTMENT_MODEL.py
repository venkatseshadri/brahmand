#!/usr/bin/env python3
"""
Scaling Reinvestment Model — Increase Lot Size as Capital Grows

Logic:
- Start: ₹2L capital → 1 butterfly lot
- After profit, if capital ≥ ₹2.85L → 2 butterfly lots
- After profit, if capital ≥ ₹4.27L → 3 butterfly lots
- Etc.

P&L per butterfly: ₹17,707 (from backtest)
Butterfly margin: ₹142,500
Trading days: 250 (21 trading days/month)
"""

import json
from pathlib import Path
from datetime import datetime

# ── Parameters ──
STARTING_CAPITAL = 200_000  # ₹2L
BUTTERFLY_MARGIN = 142_500
PROFIT_PER_BUTTERFLY = 17_707  # From backtest
TRADING_DAYS = 250
TRADING_DAYS_PER_MONTH = 21

print("\n" + "="*120)
print("SCALING REINVESTMENT MODEL — Lot Size Increases with Capital Growth")
print("="*120)

print(f"\n📊 Input:")
print(f"   Starting capital: ₹{STARTING_CAPITAL:,.0f}")
print(f"   Butterfly margin: ₹{BUTTERFLY_MARGIN:,.0f}")
print(f"   Profit per butterfly: ₹{PROFIT_PER_BUTTERFLY:,.0f}")
print(f"   Trading days: {TRADING_DAYS}")
print(f"   Avg trade duration: 25 minutes")

# ── Daily Simulation ──
capital = STARTING_CAPITAL
total_profit = 0
total_butterflies_traded = 0
concurrent_lots = 0
history = []

print(f"\n{'Day':<6} {'Capital':<18} {'Lots':<8} {'Butterflies':<15} {'Daily Profit':<18} {'Cumulative P&L':<18}")
print("-" * 120)

for day in range(1, TRADING_DAYS + 1):
    # How many concurrent lots can we hold?
    concurrent_lots = max(1, capital // BUTTERFLY_MARGIN)

    # On each trading day, how many butterflies can complete with these lots?
    # Avg duration 25 min, trading day ~360 min → ~14 trades per lot per day
    # But for simplicity, assume 1 trade per lot per day (conservative)
    butterflies_today = concurrent_lots

    # Daily profit
    daily_profit = butterflies_today * PROFIT_PER_BUTTERFLY

    # Update capital
    capital += daily_profit
    total_profit += daily_profit
    total_butterflies_traded += butterflies_today

    # Record every 10 days + months
    is_month_end = (day % TRADING_DAYS_PER_MONTH == 0)
    is_decade = (day % 10 == 0)

    if is_decade or is_month_end or day == TRADING_DAYS:
        history.append({
            "day": day,
            "capital": round(capital, 0),
            "concurrent_lots": concurrent_lots,
            "total_butterflies": total_butterflies_traded,
            "cumulative_pnl": round(total_profit, 0),
        })
        print(f"{day:<6} ₹{capital:>16,.0f} {concurrent_lots:<8} {total_butterflies_traded:<15} ₹{daily_profit:>16,.0f} ₹{total_profit:>16,.0f}")

print("-" * 120)

# ── Final Summary ──
final_capital = capital
final_lots = concurrent_lots
roi = (final_capital - STARTING_CAPITAL) / STARTING_CAPITAL * 100

print(f"\n{'='*120}")
print(f"📈 FINAL RESULTS (Day {TRADING_DAYS}):")
print(f"{'='*120}")

print(f"\n💰 Capital:")
print(f"   Starting: ₹{STARTING_CAPITAL:,.0f}")
print(f"   Final: ₹{final_capital:,.0f}")
print(f"   Total profit: ₹{total_profit:,.0f}")
print(f"   ROI: {roi:.1f}%")

print(f"\n📊 Trading Volume:")
print(f"   Total butterflies traded: {total_butterflies_traded:,.0f}")
print(f"   Final concurrent lots: {final_lots}")
print(f"   Avg butterflies/day: {total_butterflies_traded/TRADING_DAYS:.1f}")

print(f"\n🚀 Growth Milestones:")
milestones = [
    (2_000_000, "₹2M"),
    (5_000_000, "₹5M"),
    (10_000_000, "₹1Cr"),
    (20_000_000, "₹2Cr"),
]
for milestone_cap, label in milestones:
    if final_capital >= milestone_cap:
        print(f"   ✅ Reached {label} ({milestone_cap // 10_000_000} crore)")
    else:
        print(f"   ❌ Did not reach {label}")

print(f"\n{'='*120}\n")

# ── Comparison with 1,060 sequential butterflies (no reinvestment) ──
sequential_pnl = 1060 * PROFIT_PER_BUTTERFLY
comparison_multiplier = total_butterflies_traded / 1060

print(f"📌 COMPARISON:")
print(f"   Sequential (no reinvestment): 1,060 butterflies = ₹{sequential_pnl:,.0f}")
print(f"   Scaling (with reinvestment): {total_butterflies_traded:,.0f} butterflies = ₹{total_profit:,.0f}")
print(f"   Multiplier: {comparison_multiplier:.1f}x more butterflies traded")
print(f"   Profit increase: {((total_profit - sequential_pnl) / sequential_pnl * 100):.1f}% more profit")

print(f"\n{'='*120}\n")

# Save results
results = {
    "timestamp": datetime.now().isoformat(),
    "scenario": "Scaling lot size with capital growth (reinvestment)",
    "starting_capital": STARTING_CAPITAL,
    "final_capital": float(final_capital),
    "total_profit": float(total_profit),
    "total_butterflies": int(total_butterflies_traded),
    "roi_percent": float(roi),
    "final_concurrent_lots": int(final_lots),
    "comparison": {
        "sequential_pnl": float(sequential_pnl),
        "scaling_pnl": float(total_profit),
        "multiplier": float(comparison_multiplier),
    },
    "daily_history": history,
}

Path("data/scaling_reinvestment_2024.json").write_text(json.dumps(results, indent=2))
print(f"✅ Results saved: data/scaling_reinvestment_2024.json\n")
