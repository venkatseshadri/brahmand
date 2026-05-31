# Complete Brahmand Flow: Planning → Execution → Learning

**Status:** Architecture Complete  
**Date:** 2026-05-15

---

## THE COMPLETE AGENT SYSTEM

### PHASE 1: PRE-MARKET PLANNING (09:15 AM)

```
09:15 AM - Planning Phase (Runs ONCE at market open)
│
├─ [EXISTING] Regime Agent
│  ├─ Input: Today's market snapshot (DuckDB)
│  ├─ Output: regime = "sideways" | "trending_bullish" | "trending_bearish"
│  └─ Example: {regime: "sideways", confidence: 0.85}
│
├─ [NEW] Strategy Planning Agent ← KEY!
│  ├─ Input: regime + yesterday's learnings (daily_config.json)
│  ├─ Process: Query strategy_knowledge
│  │          "For sideways, which strategy won?"
│  │          Iron Butterfly: 82% win rate
│  │          Credit Spreads: 60% win rate
│  │          → Pick Iron Butterfly
│  ├─ Output: {strategy: "IRON_BUTTERFLY", confidence: 0.82, rationale: "..."}
│  └─ Replaces: Blind if-else rules
│
├─ [EXISTING] Contract Agent
│  ├─ Input: strategy + ATM strike
│  ├─ Output: {leg1: "NIFTY12MAY26C23650", leg2: "NIFTY12MAY26P23650", ...}
│  └─ Example: 4-leg Iron Butterfly contract list
│
├─ [NEW] Entry Planning Agent ← KEY!
│  ├─ Input: strategy + yesterday's learnings (entry_knowledge)
│  ├─ Process: Query entry_knowledge
│  │          "For Iron Butterfly, best entry signal?"
│  │          EMA5 bounce at support: 100% success
│  │          Entry window 10:30-11:00: Best liquidity
│  │          → Use EMA5 bounce signal
│  ├─ Output: {
│  │   entry_signal: "ema5_bounce_at_support",
│  │   entry_window: "10:30-11:00",
│  │   quality_target: 4.5,  // Min entry quality score
│  │   premium_target: 190,  // Target net credit
│  │   rationale: "..."
│  │ }
│  └─ Replaces: Hardcoded entry logic
│
├─ [NEW] Exit Planning Agent ← KEY!
│  ├─ Input: strategy + yesterday's learnings (exit_knowledge)
│  ├─ Process: Query exit_knowledge
│  │          "For Iron Butterfly, optimal exit?"
│  │          Hold 3-4 hours: Captures 90% of profit
│  │          Exit at TP: 50% premium decay
│  │          Exit at 14:30: Risk management
│  │          → Use all three
│  ├─ Output: {
│  │   optimal_hold_hours: 3.5,
│  │   exit_signals: ["tp_hit", "time_based_14:30"],
│  │   profit_target: 0.92,  // Target 92% of max profit
│  │   rationale: "..."
│  │ }
│  └─ Replaces: Hardcoded exit logic
│
├─ [EXISTING] Risk Agent (adapted)
│  ├─ Input: strategy + VIX + yesterday's risk_knowledge
│  ├─ Process: "For Iron Butterfly + VIX 18, what SL%?"
│  │          From risk_knowledge: SL 30% (not 25%) for low VIX
│  ├─ Output: {
│  │   sl_pct: 0.30,
│  │   tp_pct: 0.50,
│  │   max_drawdown: 4500,
│  │   margin_cap: 500000
│  │ }
│  └─ Uses: Learned SL values, not defaults
│
└─ [NEW] Daily Plan Synthesizer Agent ← COORDINATOR!
   ├─ Input: Outputs from all 5 agents above
   ├─ Synthesizes: Complete daily_trade_plan.json
   ├─ Output: {
   │   date: "2026-05-15",
   │   strategy: "IRON_BUTTERFLY",
   │   strategy_confidence: 0.82,
   │   entry_plan: {signal: "ema5_bounce", window: "10:30-11:00", target: 4.5},
   │   exit_plan: {hold_hours: 3.5, signals: ["tp_50%", "time_14:30"]},
   │   risk_plan: {sl: 0.30, tp: 0.50, max_dd: 4500},
   │   legs: ["NIFTY12MAY26C23650", ...],
   │   reasoning: "Sideways regime (confidence 0.85). Iron Butterfly won 82% vs spreads 60%."
   │ }
   └─ Publishes: daily_trade_plan.json for execution
```

---

### PHASE 2: INTRADAY EXECUTION (09:15-15:30, every 5 min)

```
Every 5 minutes during market hours:
│
├─ [NEW] Regime Monitor Agent
│  ├─ Check: Has regime changed from this morning?
│  ├─ If SAME: Continue with daily_trade_plan.json ✓
│  ├─ If CHANGED: Trigger REPLAN (go back to Phase 1)
│  │               "Regime was sideways, now trending bullish!"
│  │               → Create new daily_trade_plan.json
│  └─ Example: "ADX jumped from 18 to 28, SuperTrend flipped bullish"
│
├─ [EXISTING] Execution Agent
│  ├─ Input: daily_trade_plan.json + entry_plan
│  ├─ Waits for: entry_signal + entry_window
│  ├─ When triggered:
│  │  ├─ Queries entry_knowledge: "Confirm EMA5 bounce is reliable"
│  │  ├─ Checks: Are we in 10:30-11:00 window?
│  │  ├─ Places: 4-leg trade (Iron Butterfly)
│  │  └─ Logs: Execution report to state.db
│  └─ Output: execution_report_001 (saved to state.db)
│
└─ [EXISTING] Risk Agent
   ├─ Input: execution_report + daily_trade_plan.json
   ├─ Places: SL and TP orders based on learned SL%
   │          (SL 30%, not default 25%)
   ├─ Monitors: Greeks, P&L, margin
   ├─ On exit trigger:
   │  ├─ TP hit → Close position
   │  ├─ SL hit → Close position (and learn: why did it breach?)
   │  └─ Time-based (14:30) → Force close (risk management)
   └─ Output: risk_report_001 (saved to state.db)
```

---

### PHASE 3: POST-MARKET LEARNING (16:00 PM)

```
16:00 PM - Post-Mortem Phase (Runs ONCE after close)
│
├─ [NEW] Strategy Post-Mortem Agent
│  ├─ Query: state.db trades from today
│  ├─ Analyze: Was IRON_BUTTERFLY the right choice for sideways?
│  ├─ Result: YES, won ₹730 profit
│  └─ Publish to: strategy_knowledge
│
├─ [NEW] Entry Post-Mortem Agent
│  ├─ Query: state.db entry reports + DuckDB market data @ entry time
│  ├─ Analyze: Was 10:47 entry good? Was EMA5 bounce reliable?
│  ├─ Result: YES, entry_quality=4.5, slippage=0 ticks
│  └─ Publish to: entry_knowledge
│
├─ [NEW] Exit Post-Mortem Agent
│  ├─ Query: state.db exit reports + DuckDB market data @ exit time
│  ├─ Analyze: Was 3h 45m hold optimal? Did TP capture 92% of profit?
│  ├─ Result: YES, optimal_hold=3h 45m, profit_capture=0.92
│  └─ Publish to: exit_knowledge
│
└─ [NEW] Daily Config Updater Agent
   ├─ Input: Outputs from 3 post-mortem agents
   ├─ Synthesize: What should TOMORROW'S plan be?
   │   ├─ If regime sideways again: Use IRON_BUTTERFLY (82% win rate)
   │   ├─ If trending bullish: Use BULL_PUT_SPREAD (75% win rate)
   │   ├─ Entry window: 10:30-11:00 (consistently best)
   │   ├─ SL%: Keep at 30% (working well)
   │   └─ TP%: Keep at 50% (captures enough profit)
   ├─ Output: daily_config.json (for tomorrow's planning phase)
   └─ Result: System learns and improves daily
```

---

## THE COMPLETE 24-HOUR CYCLE

```
Day 1 (May 14):
├─ 09:15: Daily Plan Synthesizer creates daily_trade_plan.json
│         "For today's sideways market, use Iron Butterfly"
├─ 10:47: Execution Agent enters trade (following plan)
├─ 14:30: Risk Agent exits trade (following plan)
├─ 16:00: Post-Mortem agents learn
│         └─ Daily Config Updater updates daily_config.json
│            "Iron Butterfly won. Entry signal worked. Exit timing perfect."
│
Day 2 (May 15):
├─ 09:15: Daily Plan Synthesizer reads daily_config.json from Day 1
│         "Yesterday: Iron Butterfly won 82%. Entry at 10:30-11:00 perfect."
│         "Today's regime: Still sideways"
│         → Plan uses Iron Butterfly again (with higher confidence!)
├─ 10:42: Execution Agent enters
│         Uses knowledge: "10:30-11:00 window = 0 slippage expected"
│         Result: Entry at 10:42, 0 ticks slippage (as expected!)
├─ 14:30: Risk Agent exits
│         Uses learned SL 30% (not default 25%)
│         Result: No SL breach (as expected!)
├─ 16:00: Post-Mortem agents learn again
│         Confidence in Iron Butterfly: 0.70 → 0.75 → 0.80 (increasing!)
│
Day 3-5: Cycle repeats, confidence increases, system improves
```

---

## AGENTS SUMMARY

### Pre-Trade Planning (Decide WHAT to trade):
1. **Regime Agent** (existing) — Classify market
2. **Strategy Planning Agent** (NEW!) — Pick strategy based on learnings
3. **Contract Agent** (existing) — Resolve symbols
4. **Entry Planning Agent** (NEW!) — Plan entry signals & window
5. **Exit Planning Agent** (NEW!) — Plan exit conditions & hold time
6. **Risk Agent** (adapted) — Plan SL/TP based on learnings
7. **Daily Plan Synthesizer** (NEW!) — Combine into daily_trade_plan.json

### Intraday Execution (Execute the plan):
8. **Regime Monitor** (NEW!) — Watch for regime changes, trigger replan
9. **Execution Agent** (existing) — Place trades
10. **Risk Agent** (existing) — Monitor & exit trades

### Post-Trade Learning (Learn & improve):
11. **Strategy Post-Mortem Agent** (NEW!) — Learn strategy effectiveness
12. **Entry Post-Mortem Agent** (NEW!) — Learn entry signal reliability
13. **Exit Post-Mortem Agent** (NEW!) — Learn exit timing optimality
14. **Daily Config Updater** (NEW!) — Update daily_config.json

**Total agents: 14** (vs. current 5-6)
But organized in clear phases, each with purpose.

---

## BLOCKING QUESTIONS FOR IMPLEMENTATION

Before building, clarify:

### 1. DATA CAPTURE IN state.db
```
When Execution Agent enters a trade, it MUST capture:
[ ] Which entry signal triggered? ("ema5_bounce" / "support_bounce" / etc)
[ ] What was the entry quality score? (0-5)
[ ] Market snapshot at entry time (ADX, VIX, RSI, EMA levels)
[ ] Premium received (vs. max premium available)
[ ] Fill slippage in ticks

When Risk Agent exits a trade, it MUST capture:
[ ] Exit reason ("tp_hit" / "sl_hit" / "time_based" / "manual")
[ ] Time held (hours)
[ ] Profit captured (% of max possible)
[ ] Market snapshot at exit time (ADX, structure change, VIX)
```

### 2. daily_trade_plan.json SCHEMA
```
What fields MUST daily_trade_plan.json have?
[ ] Strategy selected + confidence score
[ ] Entry plan (signal, window, quality target, premium target)
[ ] Exit plan (hold hours, exit triggers, profit target)
[ ] Risk plan (SL%, TP%, max drawdown, margin cap)
[ ] Legs (complete contract list)
[ ] Timestamp (when plan was created)
[ ] Rationale (why this strategy, based on what learnings?)
```

### 3. REPLAN TRIGGERS
```
If regime changes during the day, should we:
[ ] Always replan immediately?
[ ] Only replan if we have no open position?
[ ] Keep current position, but plan new entry based on new regime?
[ ] Set a confidence threshold (only replan if confidence high)?
```

### 4. STRATEGY DECISION LOGIC
```
How should Strategy Planning Agent decide?
[ ] Historical win-rate only? (Pick strategy with highest %)
[ ] Win-rate + confidence? (Pick strategy with high % AND many samples)
[ ] Win-rate + VIX adjustment? (Adjust strategy choice by current VIX)
[ ] Multi-factor? (Win-rate + entry signal reliability + exit timing + Greeks)
```

### 5. ENTRY PLAN GENERATION
```
Should Entry Planning Agent:
[ ] Pick ONE best entry signal? (Use EMA5 bounce only)
[ ] Pick signal + backup signals? (EMA5 bounce, backup RSI div)
[ ] Generate multiple entry options ranked by confidence?
[ ] Generate entry plan per strategy (different signals for IB vs spreads)?
```

These must be answered before we code!

