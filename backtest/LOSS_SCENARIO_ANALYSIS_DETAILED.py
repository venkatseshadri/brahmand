#!/usr/bin/env python3
"""
Detailed Loss Scenario Analysis: From Entry to Expiry
Tracks: Entry → Price moves → Decay → SL hit → Morphing trigger → Leg shift → Final P&L

Weekly Expiry (5 DTE): Monday entry → Friday expiry
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List

def simulate_butterfly_day_by_day(
    scenario_name: str,
    price_move_per_day: List[float],  # Daily % moves (negative = against us)
    expected_days_to_close: int = 5,
) -> Dict:
    """
    Day-by-day simulation of a butterfly trade.

    Entry: SELL 25000 PE @ ₹80, BUY 24800 PE @ ₹20 (200pt wing)
    TP: 20% = close at spread ₹48
    SL: 5% = close at spread ₹63

    Tracks both paths:
    - Path A: No intervention (just TP/SL)
    - Path B: With morphing + leg shifts
    """

    lot_size = 75

    # Entry setup
    entry = {
        'sell_strike': 25000,
        'sell_price': 80.0,
        'hedge_strike': 24800,
        'hedge_price': 20.0,
    }

    entry_spread = entry['sell_price'] - entry['hedge_price']  # 60
    tp_close = entry_spread * 0.8  # 48 (20% profit)
    sl_close = entry_spread * 1.03  # 61.8 (3% loss) — tighter SL to show real losses

    log = []
    morphs = []
    shifts = []

    # Path A: No intervention
    sell_a = entry['sell_price']
    hedge_a = entry['hedge_price']

    # Path B: With morphing + shifts
    sell_b = entry['sell_price']
    hedge_b = entry['hedge_price']
    sell_strike_b = entry['sell_strike']
    hedge_strike_b = entry['hedge_strike']

    close_day_a = None
    close_day_b = None
    pnl_a = None
    pnl_b = None
    reason_a = None
    reason_b = None

    # Daily simulation (5 days: Monday-Friday)
    for day in range(1, 6):
        # Apply daily price move
        price_move_pct = price_move_per_day[day - 1] if day - 1 < len(price_move_per_day) else 0

        # Market move affects both legs equally
        sell_a *= (1 - price_move_pct)
        hedge_a *= (1 - price_move_pct)
        sell_b *= (1 - price_move_pct)
        hedge_b *= (1 - price_move_pct)

        # Theta decay (DECREASES option prices as time passes)
        # Day 1-2: 0.5-1.0 pts/day, Day 3: 1.5 pts/day, Day 4: 3 pts/day, Day 5: 5+ pts/day
        theta_decay_sell = [0.75, 1.0, 1.5, 3.0, 5.0][day - 1]
        theta_decay_hedge = [0.25, 0.3, 0.5, 1.0, 2.0][day - 1]

        # For short position (SELL): price going down = profit
        # For long position (HEDGE): price going down = loss of premium (but slower decay)
        sell_a -= theta_decay_sell  # Short benefits from decay
        hedge_a -= theta_decay_hedge
        sell_b -= theta_decay_sell
        hedge_b -= theta_decay_hedge

        spread_a = sell_a - hedge_a
        spread_b = sell_b - hedge_b

        # Path A: Check TP/SL
        if spread_a <= tp_close and close_day_a is None:
            pnl_a = (entry_spread - spread_a) * lot_size
            close_day_a = day
            reason_a = "TP_HIT"

        if spread_a >= sl_close and close_day_a is None:
            pnl_a = (entry_spread - spread_a) * lot_size
            close_day_a = day
            reason_a = "SL_HIT"

        # Path B: Check for morphing trigger (SL hit)
        if spread_b >= sl_close and close_day_b is None and not morphs:
            # MORPHING: Close losing leg (SELL), re-enter fresh
            morph_entry = {
                'day': day,
                'reason': 'SL_HIT',
                'sell_closed_at': sell_b,
                'hedge_kept': hedge_b,
                'sell_loss': (entry['sell_price'] - sell_b) * lot_size,
            }
            morphs.append(morph_entry)

            # Re-entry: Assume we re-enter SELL at nearby strike (25050 PE)
            new_sell_price = sell_b * 0.95  # New SELL is further OTM, less premium
            morph_entry['new_sell_strike'] = 25050
            morph_entry['new_sell_entry_price'] = new_sell_price

            sell_b = new_sell_price
            sell_strike_b = 25050

            # Log the morph
            log.append({
                'day': day,
                'event': 'MORPH_EXECUTED',
                'details': f"SL HIT: Closed SELL 25000@{sell_b:.1f}, Re-entered SELL 25050@{new_sell_price:.1f}",
                'sell_closed_at': sell_b,
                'sell_loss': morph_entry['sell_loss'],
            })

        # Path B: Check for LEG SHIFTS on Day 5 (expiry day)
        if day == 5:  # Expiry day - maximum theta decay
            sell_decay_pct = ((entry['sell_price'] - sell_b) / entry['sell_price']) * 100
            hedge_decay_pct = ((entry['hedge_price'] - hedge_b) / entry['hedge_price']) * 100

            # SELL SHIFT: If decayed 50%+, shift to wider strike
            if sell_decay_pct >= 50 and sell_strike_b == 25000:
                sell_shift_profit = (entry['sell_price'] - sell_b) * lot_size
                new_sell_price = sell_b * 0.90  # Further OTM on new strike
                new_sell_credit = new_sell_price * lot_size

                shifts.append({
                    'type': 'SELL_SHIFT',
                    'old_strike': sell_strike_b,
                    'new_strike': 25050,
                    'old_price': sell_b,
                    'new_price': new_sell_price,
                    'profit_locked': sell_shift_profit,
                    'new_theta_capture': new_sell_credit,
                })

                log.append({
                    'day': day,
                    'event': 'SELL_SHIFT',
                    'details': f"50% decay: Closed SELL 25000@{sell_b:.1f}, Sold SELL 25050@{new_sell_price:.1f}",
                    'profit_locked': sell_shift_profit,
                })

                sell_b = new_sell_price
                sell_strike_b = 25050

            # HEDGE SHIFT: If decayed 50%+, shift to closer strike (reduce protection cost)
            if hedge_decay_pct >= 50 and hedge_strike_b == 24800:
                hedge_shift_cost_reduction = (hedge_b) * lot_size  # We recover decay profit
                new_hedge_price = hedge_b * 0.75  # Closer to ATM, cheaper premium
                new_hedge_cost = new_hedge_price * lot_size

                shifts.append({
                    'type': 'HEDGE_SHIFT',
                    'old_strike': hedge_strike_b,
                    'new_strike': 24850,
                    'old_price': hedge_b,
                    'new_price': new_hedge_price,
                    'cost_reduction': hedge_shift_cost_reduction - new_hedge_cost,
                })

                log.append({
                    'day': day,
                    'event': 'HEDGE_SHIFT',
                    'details': f"50% decay: Bought new HEDGE 24850@{new_hedge_price:.1f}, closed old 24800@{hedge_b:.1f}",
                    'cost_reduction': hedge_shift_cost_reduction - new_hedge_cost,
                })

                hedge_b = new_hedge_price
                hedge_strike_b = 24850

        # Path B: Check TP/SL
        if spread_b <= tp_close and close_day_b is None:
            pnl_b = (entry_spread - spread_b) * lot_size
            for shift in shifts:
                if shift['type'] == 'SELL_SHIFT':
                    pnl_b += shift['profit_locked']
                elif shift['type'] == 'HEDGE_SHIFT':
                    pnl_b += shift['cost_reduction']
            close_day_b = day
            reason_b = "TP_HIT"

        if spread_b >= sl_close and close_day_b is None and not morphs:
            pnl_b = (entry_spread - spread_b) * lot_size
            for shift in shifts:
                if shift['type'] == 'SELL_SHIFT':
                    pnl_b += shift['profit_locked']
                elif shift['type'] == 'HEDGE_SHIFT':
                    pnl_b += shift['cost_reduction']
            close_day_b = day
            reason_b = "SL_HIT"

        log.append({
            'day': day,
            'price_move_pct': price_move_pct * 100,
            'sell_a': sell_a,
            'hedge_a': hedge_a,
            'spread_a': spread_a,
            'sell_b': sell_b,
            'hedge_b': hedge_b,
            'spread_b': spread_b,
            'morphed': len(morphs) > 0,
        })

    # At expiry
    if close_day_a is None:
        pnl_a = (entry_spread - spread_a) * lot_size
        reason_a = "EXPIRY"

    if close_day_b is None:
        pnl_b = (entry_spread - spread_b) * lot_size
        reason_b = "EXPIRY"
        for shift in shifts:
            if shift['type'] == 'SELL_SHIFT':
                pnl_b += shift['profit_locked']
            elif shift['type'] == 'HEDGE_SHIFT':
                pnl_b += shift['cost_reduction']

    return {
        'scenario': scenario_name,
        'entry_spread': entry_spread,
        'tp_close': tp_close,
        'sl_close': sl_close,
        'path_a': {
            'pnl': pnl_a,
            'close_day': close_day_a,
            'reason': reason_a,
        },
        'path_b': {
            'pnl': pnl_b,
            'close_day': close_day_b,
            'reason': reason_b,
            'morphs': morphs,
            'shifts': shifts,
        },
        'improvement': pnl_b - pnl_a,
        'log': log,
    }


def main():
    print("\n" + "="*140)
    print("BUTTERFLY LOSS SCENARIOS: STEP-BY-STEP ANALYSIS")
    print("="*140)

    # Define loss scenarios (ranked by severity)
    # Need big rallies to overcome theta and hit SL (spread > 63)
    scenarios = [
        {
            'name': '🔴 CATASTROPHIC: Gap up 10% Day 1 (Earnings/News)',
            'moves': [0.10, 0.0, 0.0, 0.0, 0.0],  # Huge rally on Day 1
        },
        {
            'name': '🟠 SEVERE: Rally 8% Day 1, Partial recovery',
            'moves': [0.08, -0.02, -0.01, 0.0, 0.0],  # Rally, then small recovery
        },
        {
            'name': '🟡 BAD: Rally 5% Over Days 1-2',
            'moves': [0.025, 0.025, 0.0, 0.0, 0.0],  # Steady rally
        },
        {
            'name': '🟢 MANAGEABLE: Rally 3% Over Days 1-3, then stable',
            'moves': [0.01, 0.01, 0.01, 0.0, 0.0],  # Moderate rally
        },
        {
            'name': '💚 THETA WINS: Stable (theta overcomes no move)',
            'moves': [0.0, 0.0, 0.0, 0.0, 0.0],  # Pure theta
        },
    ]

    results = []

    for scenario in scenarios:
        result = simulate_butterfly_day_by_day(
            scenario['name'],
            scenario['moves'],
        )
        results.append(result)

        print(f"\n{'─'*140}")
        print(f"{scenario['name']}")
        print(f"{'─'*140}")

        # Show daily progression
        print(f"\nDaily progression:")
        print(f"{'Day':<5} {'Price %':<12} {'Spread (A)':<15} {'Spread (B)':<15} {'Status':<30}")
        print("-" * 80)

        for entry in result['log']:
            if 'spread_a' in entry:
                status = ""
                if entry['event'] if 'event' in entry else '':
                    status = entry.get('event', '')
                else:
                    if entry['morphed']:
                        status = "MORPHED"
                print(f"{entry['day']:<5} {entry['price_move_pct']:>+6.1f}% {entry['spread_a']:>13.1f} {entry['spread_b']:>13.1f} {status:<30}")

        print(f"\nResult:")
        print(f"  SL threshold: {result['sl_close']:.1f} (3% loss)")
        print(f"  Path A (No intervention): ₹{result['path_a']['pnl']:>10,.0f} ({result['path_a']['reason']} on Day {result['path_a']['close_day']})")
        print(f"  Path B (Morph + Shifts):  ₹{result['path_b']['pnl']:>10,.0f} ({result['path_b']['reason']} on Day {result['path_b']['close_day']})")
        print(f"  Improvement:              ₹{result['improvement']:>10,.0f}")

        if result['path_b']['morphs']:
            print(f"\n  Morphing events:")
            for morph in result['path_b']['morphs']:
                print(f"    Day {morph['day']}: {morph['reason']} → Closed SELL @ ₹{morph['sell_closed_at']:.1f} (loss ₹{morph['sell_loss']:,.0f})")
                print(f"             Re-entered SELL 25050 @ ₹{morph['new_sell_entry_price']:.1f}")

        if result['path_b']['shifts']:
            print(f"\n  Leg shifts on expiry:")
            for shift in result['path_b']['shifts']:
                if shift['type'] == 'SELL_SHIFT':
                    print(f"    SELL_SHIFT: {shift['old_strike']}→{shift['new_strike']} | Profit locked: ₹{shift['profit_locked']:,.0f}")
                else:
                    print(f"    HEDGE_SHIFT: {shift['old_strike']}→{shift['new_strike']} | Cost reduction: ₹{shift['cost_reduction']:,.0f}")

    # Summary ranking
    print(f"\n{'='*140}")
    print("SUMMARY: RANKED BY LOSS SEVERITY")
    print(f"{'='*140}\n")

    # Sort by worst P&L
    sorted_results = sorted(results, key=lambda x: x['path_a']['pnl'])

    print(f"{'Scenario':<40} {'No Intervention':<20} {'With Morph+Shifts':<20} {'Saved':<20}")
    print("-" * 100)

    for r in sorted_results:
        saved = r['improvement']
        print(f"{r['scenario'][:40]:<40} ₹{r['path_a']['pnl']:>15,.0f} ₹{r['path_b']['pnl']:>15,.0f} ₹{saved:>15,.0f}")

    # Save results
    output_path = Path("/home/trading_ceo/brahmand/data/loss_scenario_analysis.json")
    output_path.write_text(json.dumps({
        'timestamp': datetime.now().isoformat(),
        'scenarios': [
            {
                'scenario': r['scenario'],
                'path_a_pnl': r['path_a']['pnl'],
                'path_b_pnl': r['path_b']['pnl'],
                'improvement': r['improvement'],
                'morphs': r['path_b']['morphs'],
                'shifts': r['path_b']['shifts'],
            }
            for r in results
        ]
    }, indent=2, default=str))

    print(f"\n✅ Analysis saved: data/loss_scenario_analysis.json\n")


if __name__ == "__main__":
    main()
