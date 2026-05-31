#!/usr/bin/env python3
"""
REALISTIC Scaling Model — With Win Rate & Trade Frequency

Realistic Assumptions:
- Win rate: 51.7% (from backtest)
- Avg profit/trade: (win% × avg_win) + (loss% × avg_loss)
  = (0.517 × 7402) + (0.483 × -6096) = 3830 - 2945 = ₹885/butterfly
- Trade duration: 25 min average
- Trading day: 6 hours (360 min) → ~14 trades per lot per day
"""

import json
from pathlib import Path
from datetime import datetime

# ── Parameters (from backtest) ──
STARTING_CAPITAL = 200_000
BUTTERFLY_MARGIN = 142_500
WIN_RATE = 0.517
AVG_WIN = 7402
AVG_LOSS = -6096
TRADE_DURATION_MIN = 25
TRADING_DAY_MIN = 360

# Realistic avg profit per butterfly
AVG_PROFIT_PER_BUTTERFLY = (WIN_RATE * AVG_WIN) + ((1 - WIN_RATE) * AVG_LOSS)

TRADES_PER_LOT_PER_DAY = max(1, TRADING_DAY_MIN // TRADE_DURATION_MIN)  # ~14 trades
TRADING_DAYS = 250

print("\n" + "="*130)
print("REALISTIC SCALING MODEL — With 51.7% Win Rate & Trade Frequency")
print("="*130)

print(f"\n📊 Realistic Inputs (from 2024 backtest):")
print(f"   Starting capital: ₹{STARTING_CAPITAL:,.0f}")
print(f"   Butterfly margin: ₹{BUTTERFLY_MARGIN:,.0f}")
print(f"   Win rate: {WIN_RATE*100:.1f}%")
print(f"   Avg win: ₹{AVG_WIN:,.0f}")
print(f"   Avg loss: ₹{AVG_LOSS:,.0f}")
print(f"   **Realistic avg profit/butterfly: ₹{AVG_PROFIT_PER_BUTTERFLY:,.0f}**")
print(f"   Trade duration: {TRADE_DURATION_MIN} min")
print(f"   Trades per lot per day: {TRADES_PER_LOT_PER_DAY}")
print(f"   Trading days: {TRADING_DAYS}")

# ── Daily Simulation ──
capital = STARTING_CAPITAL
total_profit = 0
total_butterflies_traded = 0
concurrent_lots = 0
history = []

print(f"\n{'Day':<6} {'Capital':<18} {'Lots':<8} {'Trades/Day':<12} {'Daily Profit':<18} {'Cumulative P&L':<18}")
print("-" * 130)

for day in range(1, TRADING_DAYS + 1):
    # How many concurrent lots can we hold?
    concurrent_lots = max(1, capital // BUTTERFLY_MARGIN)

    # How many butterflies trade today?
    butterflies_today = concurrent_lots * TRADES_PER_LOT_PER_DAY

    # Daily profit (with win rate)
    daily_profit = butterflies_today * AVG_PROFIT_PER_BUTTERFLY

    # Update capital
    capital += daily_profit
    total_profit += daily_profit
    total_butterflies_traded += butterflies_today

    # Record key days
    is_month_end = (day % 21 == 0)
    is_decade = (day % 10 == 0)

    if is_decade or is_month_end or day == TRADING_DAYS:
        history.append({
            "day": day,
            "capital": round(capital, 0),
            "concurrent_lots": concurrent_lots,
            "total_butterflies": int(total_butterflies_traded),
            "cumulative_pnl": round(total_profit, 0),
        })
        print(f"{day:<6} ₹{capital:>16,.0f} {concurrent_lots:<8} {butterflies_today:<12,.0f} ₹{daily_profit:>16,.0f} ₹{total_profit:>16,.0f}")

print("-" * 130)

# ── Final Summary ──
final_capital = capital
final_lots = concurrent_lots
roi = (final_capital - STARTING_CAPITAL) / STARTING_CAPITAL * 100

print(f"\n{'='*130}")
print(f"📈 FINAL RESULTS (Day {TRADING_DAYS}):")
print(f"{'='*130}")

print(f"\n💰 Capital:")
print(f"   Starting: ₹{STARTING_CAPITAL:,.0f}")
print(f"   Final: ₹{final_capital:,.0f}")
print(f"   Total profit: ₹{total_profit:,.0f}")
print(f"   ROI: {roi:.1f}%")

print(f"\n📊 Trading Volume:")
print(f"   Total butterflies traded: {int(total_butterflies_traded):,.0f}")
print(f"   Final concurrent lots: {final_lots:,.0f}")
print(f"   Avg butterflies/day: {total_butterflies_traded/TRADING_DAYS:,.0f}")
print(f"   Avg butterfly P&L: ₹{AVG_PROFIT_PER_BUTTERFLY:,.0f}")

print(f"\n{'='*130}")
print(f"📌 COMPARISON:")

# Sequential baseline
sequential_butterflies = TRADING_DAYS * 1  # 1 butterfly per day sequentially
sequential_pnl = sequential_butterflies * AVG_PROFIT_PER_BUTTERFLY
comparison_mult = total_butterflies_traded / sequential_butterflies

print(f"   Sequential (1 butterfly/day): {sequential_butterflies:,.0f} butterflies = ₹{sequential_pnl:,.0f}")
print(f"   Scaling (reinvesting): {int(total_butterflies_traded):,.0f} butterflies = ₹{total_profit:,.0f}")
print(f"   Multiplier: {comparison_mult:.1f}x more butterflies")
print(f"   Profit multiplier: {(total_profit / sequential_pnl):.1f}x more profit")

print(f"\n{'='*130}\n")

# Save
results = {
    "timestamp": datetime.now().isoformat(),
    "scenario": "Realistic scaling with 51.7% win rate and 14 trades/lot/day",
    "parameters": {
        "win_rate": WIN_RATE,
        "avg_profit_per_butterfly": float(AVG_PROFIT_PER_BUTTERFLY),
        "trades_per_lot_per_day": TRADES_PER_LOT_PER_DAY,
    },
    "final_results": {
        "starting_capital": STARTING_CAPITAL,
        "final_capital": float(final_capital),
        "total_profit": float(total_profit),
        "total_butterflies": int(total_butterflies_traded),
        "roi_percent": float(roi),
    },
    "daily_history": history,
}

Path("data/scaling_realistic_2024.json").write_text(json.dumps(results, indent=2))
print(f"✅ Results saved: data/scaling_realistic_2024.json\n")
