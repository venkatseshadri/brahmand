#!/usr/bin/env python3
"""
Leg Shifting Impact Analysis - Detailed Scenario Breakdown

Scenarios:
1. No leg shift (close entire spread on TP/SL)
2. Shift SELL leg only (keep hedge, close short)
3. Shift HEDGE leg only (keep short, close long)
4. Shift BOTH legs (independent management)

Plus: Track a maximum-loss scenario with full execution trace
"""

import json
from pathlib import Path
from datetime import datetime, timedelta

print("\n" + "="*140)
print("LEG SHIFTING SCENARIO ANALYSIS")
print("="*140)

# ── Trade example: Maximum loss scenario ──
# Entry: SELL NIFTY ATM CALL @ 150, BUY OTM CALL @ 85 (WING 200)
# Entry credit: 65 points = ₹4,875 (65 contracts)
# TP: 20% profit = close at 52 points
# SL: 5% loss = close at 157 points

max_loss_trace = []

def log_event(timestamp, event_type, leg, price, action, pnl=None, reason=""):
    """Log trade event with full context"""
    entry = {
        "timestamp": timestamp,
        "event": event_type,
        "leg": leg,
        "price": price,
        "action": action,
        "pnl": pnl,
        "reason": reason,
    }
    max_loss_trace.append(entry)
    return entry

# ── SCENARIO: Maximum Loss Trade ──
print(f"\n{'='*140}")
print("📉 SCENARIO: MAXIMUM LOSS TRADE")
print("Position: CALL_SPREAD (SELL 23650 @ 150, BUY 23850 @ 85)")
print("="*140)

t0 = datetime(2026, 5, 23, 9, 33)  # Entry time

# Entry
log_event(t0, "ENTRY", "SELL", 150, "SELL_CALL_ATM", pnl=0, reason="Market open, pattern matched")
log_event(t0, "ENTRY", "HEDGE", 85, "BUY_CALL_OTM", pnl=0, reason="Bought OTM protection")
print(f"\n✅ Trade Entry @ {t0.strftime('%H:%M')}")
print(f"   SELL 23650 CE @ ₹150 (ATM short)")
print(f"   BUY  23850 CE @ ₹85 (OTM hedge)")
print(f"   Net credit: ₹65 (₹4,875 per contract × 65)")

# Price moves AGAINST us
t1 = t0 + timedelta(minutes=5)
sell_price_t1 = 165  # SELL leg up (loss growing)
hedge_price_t1 = 95  # HEDGE leg up (loss protection working)
spread_price = sell_price_t1 - hedge_price_t1  # 70 (loss of 5 points)

log_event(t1, "PRICE_UPDATE", "SELL", sell_price_t1, "QUOTE", pnl=-325,
          reason="Market rallies, SELL leg losing")
log_event(t1, "PRICE_UPDATE", "HEDGE", hedge_price_t1, "QUOTE", pnl=+650,
          reason="HEDGE protection gaining value")

print(f"\n⚠️  @ {t1.strftime('%H:%M')} - Market rallies (bad for short)")
print(f"   SELL now @ ₹165 (lost ₹975 = 15 points × 65)")
print(f"   HEDGE now @ ₹95 (gained ₹650 = 10 points × 65)")
print(f"   Net spread: ₹70 (loss of ₹325)")

# Price continues up → hits SL
t2 = t0 + timedelta(minutes=15)
sell_price_sl = 157.5  # SL trigger (5% loss)
hedge_price_sl = 87    # Hedge worth less
spread_sl = sell_price_sl - hedge_price_sl  # 70.5

log_event(t2, "SL_CHECK", "SELL", sell_price_sl, "SL_HIT", pnl=-487.5,
          reason="SELL leg hit SL (up 7.5 points)")
log_event(t2, "SL_CHECK", "HEDGE", hedge_price_sl, "QUOTE", pnl=-130,
          reason="HEDGE value collapsed, protection failed")

print(f"\n❌ @ {t2.strftime('%H:%M')} - SL HIT")
print(f"   SELL @ ₹157.5 (SL trigger, lost ₹487.5)")
print(f"   HEDGE @ ₹87 (now worth less, lost ₹130)")
print(f"   Current spread: ₹70.5 (total loss: ₹617.5)")

# ── Decision point: What happens next? ──
print(f"\n{'─'*140}")
print("DECISION POINT: What to do at SL?")
print(f"{'─'*140}")

scenarios_at_sl = {
    "A) Close entire spread": {
        "action": "Close both SELL and HEDGE",
        "sell_close_price": 157.5,
        "hedge_close_price": 87,
        "result_pnl": -617.5,
        "reasoning": "Lock loss, restart fresh",
        "problems": ["Lose hedge protection immediately", "Max loss captured"],
    },

    "B) Keep SELL, shift HEDGE only": {
        "action": "Keep SHORT 23650 @ 150, shift HEDGE to 24000 @ 40",
        "sell_price_now": 157.5,
        "old_hedge_close": 87,  # Close 23850 @ 87
        "new_hedge_entry": 40,  # Buy 24000 @ 40
        "cost_to_rehedge": 87 - 40,  # +47 more risk
        "result_pnl": -617.5 - 47 - 65,  # Original loss + shift cost + wider wing
        "problems": [
            "Wider hedge (200→350 pts) = higher SL risk",
            "Shift costs 47 points",
            "SELL leg still losing (now 157.5, can go to 165+)",
            "Maximum risk now: spread becomes worthless"
        ],
    },

    "C) Close SELL, keep HEDGE, re-enter SELL": {
        "action": "Close SELL @ 157.5, keep HEDGE, new SELL @ 23850 @ 120",
        "close_sell_loss": -617.5,
        "keep_hedge": 87,  # Now unprotected short
        "new_sell_price": 120,  # New entry at higher strike
        "net_credit_new": 120 - 87,  # Only 33 points credit (weak)
        "result_pnl": -617.5 + (33 * 65),  # Original loss + marginal new trade
        "problems": [
            "Unprotected HEDGE (long) while waiting for re-entry",
            "New SELL entry is weaker (33 pts vs original 65)",
            "Takes 2 trades to recover = higher cost",
            "Market still rallying = harder to re-enter"
        ],
    },

    "D) Close entire spread, re-enter fresh": {
        "action": "Close both, wait for better setup, re-enter as new position",
        "close_loss": -617.5,
        "waiting_cost": 0,  # No ongoing risk
        "re_entry_opportunity": "Markets cool, better entry at 23700",
        "result_pnl": -617.5,  # Clean loss
        "problems": [
            "Miss recovery opportunity if market reverses",
            "But also avoid cascading losses if market continues up"
        ],
    },
}

for scenario_name, details in scenarios_at_sl.items():
    print(f"\n{scenario_name}")
    print(f"  Action: {details['action']}")
    print(f"  Result P&L: ₹{details['result_pnl']:,.0f}")
    if "problems" in details:
        for problem in details["problems"]:
            print(f"    ⚠️ {problem}")

# ── Root cause analysis ──
print(f"\n{'='*140}")
print("🔴 ROOT CAUSE: WHY DID THIS TRADE LOSE MAXIMUM?")
print(f"{'='*140}\n")

root_causes = [
    ("Entry confidence too low", "0.75 gate means 25% of trades are still weak", "Filter more strictly to 0.85+"),
    ("SL too wide (5%)", "Entry @ 150, SL @ 157.5 = allowed 7.5 point move", "Tighten SL to 3% (150→145)"),
    ("Hedge too far (200pts)", "SELL 23650, BUY 23850 = wide gap", "Narrow to 150 point hedge"),
    ("No TSL activated", "Would have locked profit at 33% of way", "TSL at 51 points would have helped"),
    ("Morphing didn't fire", "SL hit but no morph to rescue", "Morph should have closed SELL, re-entered"),
]

for cause, detail, fix in root_causes:
    print(f"❌ {cause}")
    print(f"   Detail: {detail}")
    print(f"   Fix: {fix}\n")

# ── Output trace ──
print(f"{'='*140}")
print("📋 FULL EXECUTION TRACE")
print(f"{'='*140}\n")

for event in max_loss_trace:
    print(f"{event['timestamp'].strftime('%H:%M:%S')} | {event['event']:<15} | {event['leg']:<8} | ₹{event['price']:>7.2f} | {event['action']:<20} | P&L: {event['pnl']:>+7.0f} | {event['reason']}")

# ── Simulation: impact of different shift percentages ──
print(f"\n{'='*140}")
print("SHIFT PERCENTAGE IMPACT (if we shifted hedge leg only)")
print(f"{'='*140}\n")

shift_scenarios = {
    "No shift (close both)": 0,
    "50% shift (current)": 50,
    "75% shift (proposed)": 75,
    "100% shift (always shift)": 100,
}

base_loss = 617.5

for scenario, shift_pct in shift_scenarios.items():
    # Cost of shifting = closing old hedge + opening new hedge at wider wing
    shift_cost = (shift_pct / 100) * 47  # 47 points cost to shift
    total_loss = base_loss + shift_cost if shift_pct > 0 else base_loss
    additional_risk = (100 - shift_pct) / 100 * 50  # Unprotected risk

    print(f"{scenario:<30} | Loss: ₹{total_loss:>7,.0f} | Shift cost: ₹{shift_cost:>5,.0f} | Unprotected risk: {additional_risk:>3.0f}pts")

print(f"\n{'='*140}\n")

# Save results
results = {
    "timestamp": datetime.now().isoformat(),
    "scenario": "Maximum loss trade analysis",
    "root_causes": root_causes,
    "execution_trace": max_loss_trace,
    "shift_impact": shift_scenarios,
    "recommendation": "Morphing (not leg shifting) is what saves these trades. Leg shifting adds complexity without benefit.",
}

Path("/home/trading_ceo/projects/brahmand/data/leg_shift_max_loss_scenario.json").write_text(json.dumps(results, indent=2, default=str))

print("✅ Scenario saved: data/leg_shift_max_loss_scenario.json\n")
