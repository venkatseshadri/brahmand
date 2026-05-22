# Risk Agent Crew — Architecture

**File:** `brahmand/risk_agent_crew.py` (340 lines)  
**Bridge:** `brahmand/position_manager.py` (run_bridge at line 640)  
**Cron:** `*/1 9-15 * * 1-5 run_position_manager.sh` (flock-guarded)

---

## Overview

Three CrewAI agents run sequentially every 1 minute for each active trade:

```
position_manager.py --bridge (every 1 min, flock-guarded)
│
├── Reads trade_execution_db.get_active_trades()  (DuckDB)
│
└── For each ACTIVE trade, dispatches to:

    risk_agent_crew.evaluate_trade(trade)
    ┌──────────────────────────────────────────────────────────────────┐
    │                        SEQUENTIAL CREW                           │
    │                                                                  │
    │  Task 1: MORPHER Agent (LLM)                                    │
    │  ┌────────────────────────────────────────────────────────────┐ │
    │  │ Tools:                                                      │ │
    │  │  - detect_morph(current_pos, entry_signal, morph_count)     │ │
    │  │  - query_pattern() → P(UP|DOWN|SIDE) 15m horizon           │ │
    │  │  - execute_morph(from_type, to_type, legs)                  │ │
    │  │                                                             │ │
    │  │ LLM decides:                                                │ │
    │  │  - Is signal change genuine? (check pattern probabilities)  │ │
    │  │  - Morph or hold?                                           │ │
    │  │  - If morph: which type? (add CE, close PE, full 180°)     │ │
    │  └────────────────────────────────────────────────────────────┘ │
    │                              │                                   │
    │                              ▼                                   │
    │  Task 2: SHIFTER Agent (LLM)                                    │
    │  ┌────────────────────────────────────────────────────────────┐ │
    │  │ Tools:                                                      │ │
    │  │  - detect_theta_decay(legs_json, atm) → decay % per leg    │ │
    │  │  - execute_roll(leg_type, old_strike, new_strike, fills)   │ │
    │  │                                                             │ │
    │  │ LLM decides:                                                │ │
    │  │  - Is theta > 37.5%? If borderline (35%), check pattern    │ │
    │  │  - Which strike to roll to? (ATM? farther?)                 │ │
    │  │  - Roll or wait?                                           │ │
    │  └────────────────────────────────────────────────────────────┘ │
    │                              │                                   │
    │                              ▼                                   │
    │  Task 3: RISK Coordinator (LLM)                                 │
    │  ┌────────────────────────────────────────────────────────────┐ │
    │  │ Tools:                                                      │ │
    │  │  - monitor_pnl_greeks(legs) → current P&L + LTPs           │ │
    │  │  - place_sl_order(strike, type, trigger_price)             │ │
    │  │  - place_tp_order(strike, type, limit_price)               │ │
    │  │  - tsl_engine(entry_price, current_price, tp_profit)       │ │
    │  │  - modify_sl_order(order_id, new_trigger)                   │ │
    │  │  - report_position_closed(trade_id, reason, pnl)           │ │
    │  │                                                             │ │
    │  │ LLM decides:                                                │ │
    │  │  - First cycle: place SL/TP orders                          │ │
    │  │  - TSL activation? @50% of TP profit → ratchet SL          │ │
    │  │  - SL/TP hit? → close trade                                 │ │
    │  │  - Market closing? → close trade                            │ │
    │  └────────────────────────────────────────────────────────────┘ │
    └──────────────────────────────────────────────────────────────────┘
```

---

## Communication Flow

```
┌──────────────┐     new trade      ┌─────────────────────┐
│  kickoff.py  │ ─────────────────→ │ trade_execution.     │
│  (entry)     │  add_active_trade  │ duckdb               │
│              │                    │  active_trades       │
│              │                    │  trade_history       │
│  check:      │                    │  monitoring_log      │
│  should_     │                    └──────────┬──────────┘
│  enter()     │                               │
│  ┌─────────┐ │                    ┌──────────▼──────────┐
│  │JSON:    │ │     close signal   │ position_manager.py │
│  │no active│◄│────────────────────│  --bridge           │
│  │trade?   │ │ update state JSON  │                     │
│  │YES → go │ │                    │ read active trades  │
│  │         │ │                    │ dispatch to crew    │
│  │DuckDB:  │ │                    │ fallback to P1-P7   │
│  │no active│ │                    └──────────┬──────────┘
│  │trades?  │ │                               │
│  │YES → go │ │                    ┌──────────▼──────────┐
│  └─────────┘ │                    │ risk_agent_crew.py  │
│              │                    │                     │
│              │                    │ Morpher → Shifter → │
│              │                    │ Risk Coordinator    │
│              │                    └─────────────────────┘
└──────────────┘
```

---

## Handoff Points

| # | From | To | What | Commit |
|---|------|----|------|--------|
| 1 | kickoff | trade_execution_db | `add_active_trade()` after entry | `fb16ba8` |
| 2 | position_manager | risk_agent_crew | `evaluate_trade()` every 1 min | `fb16ba8` |
| 3 | risk_agent_crew | trade_execution_db | `close_trade()` on exit | `fb16ba8` |
| 4 | risk_agent_crew | kickoff JSON | Clear `active_trade`, save to `all_trades` | `fb16ba8` |

---

## Fallback: Deterministic P1-P7

When LLM is unavailable (no API key, connection error), `position_manager.run_bridge()` falls back to the existing deterministic P1-P7 checks in `position_manager.run()`:

| Priority | Trigger | Action |
|----------|---------|--------|
| P1 | Theta decay ≥ 37.5% | ROLL to ATM |
| P2 | Hedge gap ≤ 150pt | TIGHTEN |
| P3 | Entry gate signal changed | MORPH |
| P4 | SL hit | CLOSE side |
| P5 | TP hit | CLOSE side |
| P6 | Cumulative P&L ≤ -500 | CLOSE ALL |
| P7 | Market close (15:30) | CLOSE ALL |

---

## Wired Cron

```
# Position Manager Bridge — 1-min cycle, flock-guarded
*/1 9-15 * * 1-5 /home/trading_ceo/brahmand/run_position_manager.sh

# Kickoff Entry — 5-min cycle (entry only in new architecture)
1,6,11,16,21,26,31,36,41,46,51,56 9-15 * * 1-5 kickoff.py
```

---

## LLM Optimization Levers

The LLM can adjust these based on live pattern probabilities:

| Parameter | Default | LLM can override | When |
|-----------|---------|-----------------|------|
| TSL activation % | 50% of TP profit | 30-60% | High confidence → earlier activation |
| TSL lock ratio | 0.5 | 0.3-0.7 | Bullish pattern → lock more |
| SL tightness | 0.50 (50% above entry) | 0.35-0.60 | Trending pattern → tighter SL |
| Morph threshold | Signal changed | Pattern confidence ≥ 60% | LLM decides if change is noise |
| Roll strike | ATM | ATM ± 50 | LLM picks optimal based on backtest |

---

## Verification

```bash
# Check active trades in ledger
python3 -c "from trade_execution_db import get_active_trades; print(get_active_trades())"

# Run position manager bridge (once)
python3 position_manager.py --bridge

# Evaluate specific trade through risk agent
python3 risk_agent_crew.py --trade-id=TRADE-20260522-001

# Check kickoff JSON sync
cat /tmp/brahmand_kickoff.json | python3 -m json.tool | grep -E "active_trade|status"

# Watch logs
tail -f logs/position_manager_$(date +%Y%m%d).log
```
