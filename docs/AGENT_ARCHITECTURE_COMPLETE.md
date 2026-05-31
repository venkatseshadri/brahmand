# Brahmand Agent Architecture: Complete Map & Role Analysis

## System Overview: 11 Agents Across 3 Phases

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         ENTRY PHASE (ONE-TIME)                          │
│         Runs once at market open. Makes the entry decision.            │
├─────────────────────────────────────────────────────────────────────────┤
│  1. NOT_UP Entry Agent      → Is market rejecting upside? (BEARISH)    │
│  2. NOT_DOWN Entry Agent    → Is market rejecting downside? (BULLISH) │
│  3. Regime Agent            → Market regime (trending/sideways) + VIX  │
│  4. Strategy Agent          → Select CALL/PUT_SPREAD or IRON_BUTTERFLY │
│  5. Contract Agent          → Resolve exact option contracts/symbols   │
│  6. Execution Agent         → Build trade dict + route via Order Agent │
│  7. Order Agent             → Centralized order hub (PAPER vs LIVE)    │
│  8. Risk Agent              → Place SL/TP orders for ENTRY             │
├─────────────────────────────────────────────────────────────────────────┤
│                      MONITORING PHASE (CONTINUOUS)                      │
│           Runs every 5 minutes during market hours. Manages trade.     │
├─────────────────────────────────────────────────────────────────────────┤
│  9. Morpher Agent           → Detect signal reversals, morph position  │
│ 10. Shifter Agent           → Premium decay, shift legs to lock profit │
│ 11. Risk Agent (again)      → Cancel/modify SL/TP for morphs/shifts   │
├─────────────────────────────────────────────────────────────────────────┤
│                     POST-TRADE PHASE (END-OF-DAY)                       │
│              Runs after market close. Learns from outcomes.            │
├─────────────────────────────────────────────────────────────────────────┤
│ 12. Postmortem Agent        → Analyze all agent decisions vs outcomes  │
│                                Store learning in ChromaDB              │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Detailed Agent Matrix

### ENTRY PHASE

#### 1. NOT_UP Entry Agent
| Aspect | Details |
|--------|---------|
| **Role** | Gate for CALL_SPREAD entry |
| **Input** | None (fresh decision each cycle) |
| **Decision** | Market rejecting upside? (bearish pressure) |
| **Logic** | Deterministic: Trend + Traffic Light blend |
| **Output** | {go: true/false, signal: "NOT_UP", confidence, reasoning} |
| **Learning Scope** | ❌ NONE (deterministic) |
| **Called By** | Entry Crew (e2e_chain.py) |
| **Calls** | check_active_spreads, evaluate_not_up_rejection (tools) |

#### 2. NOT_DOWN Entry Agent
| Aspect | Details |
|--------|---------|
| **Role** | Gate for PUT_SPREAD entry |
| **Input** | None (fresh decision each cycle) |
| **Decision** | Market rejecting downside? (bullish pressure) |
| **Logic** | Deterministic: Trend + Traffic Light blend |
| **Output** | {go: true/false, signal: "NOT_DOWN", confidence, reasoning} |
| **Learning Scope** | ❌ NONE (deterministic) |
| **Called By** | Entry Crew (e2e_chain.py) |
| **Calls** | check_active_spreads, evaluate_not_down_rejection (tools) |

#### 3. Regime Agent
| Aspect | Details |
|--------|---------|
| **Role** | Validate entry signal against market regime |
| **Input** | Entry agent signal (NOT_UP/NOT_DOWN) from context |
| **Decision** | Is regime supportive? (trending vs sideways, VIX check) |
| **Logic** | Validates signal + classifies regime + provides VIX/ADX |
| **Output** | {regime, confidence, recommendation, vix, adx, reason} |
| **Learning Scope** | ❌ NONE (validation only, no optimization) |
| **Called By** | Entry Crew (e2e_chain.py) |
| **Calls** | query_market_data (tool) |

#### 4. Strategy Agent
| Aspect | Details |
|--------|---------|
| **Role** | Select strategy + optimize parameters |
| **Input** | Entry signal + Regime classification |
| **Decision** | CALL_SPREAD vs PUT_SPREAD + wing_width, sl_pct, tp_pct |
| **Logic** | Signal→Strategy (deterministic), VIX/ADX→parameters (rules-based) |
| **Output** | {strategy_type, wing_width, sl_pct, tp_pct, reason} |
| **Learning Scope** | ⚠️ PARTIAL (parameter optimization hardcoded, not learned) |
| **Called By** | Full Crew (e2e_chain.py) |
| **Calls** | query_market_data (tool) |

#### 5. Contract Agent
| Aspect | Details |
|--------|---------|
| **Role** | Resolve option contracts |
| **Input** | Strategy type + wing_width + ATM + expiry |
| **Decision** | Which tsyms (symbols) to trade? |
| **Logic** | Deterministic: DuckDB lookup for strikes |
| **Output** | {contracts: {tsym, ltp, strike...}, count, note} |
| **Learning Scope** | ❌ NONE (deterministic lookup) |
| **Called By** | Full Crew (e2e_chain.py) |
| **Calls** | resolve_option_contracts (tool) |

#### 6. Execution Agent
| Aspect | Details |
|--------|---------|
| **Role** | Build trade + route via Order Agent |
| **Input** | Contracts + Strategy params + Market data |
| **Decision** | NONE — just executes what's given |
| **Logic** | Deterministic: math-based trade building |
| **Output** | {trade_id, entry_orders, legs, net_credit, sl, tp} |
| **Learning Scope** | ❌ NONE (no decisions, pure execution) |
| **Called By** | Full Crew (e2e_chain.py) |
| **Calls** | execute_paper_trade, place_entry_orders (tools) |

#### 7. Order Agent
| Aspect | Details |
|--------|---------|
| **Role** | Centralized order routing hub |
| **Input** | Entry legs from Execution Agent |
| **Decision** | PAPER vs LIVE mode only |
| **Logic** | Fixed: LIVE_MODE flag determines destination |
| **Output** | {trade_id, entry_orders: [order_ids], status, mode} |
| **Learning Scope** | ❌ NONE (mode decision is one-time config) |
| **Called By** | Execution Agent (via tool) |
| **Calls** | place_entry_orders, place_sl_tp_orders (Python functions) |

#### 8. Risk Agent (ENTRY PHASE)
| Aspect | Details |
|--------|---------|
| **Role** | Place SL/TP orders for entry |
| **Input** | Trade dict from Execution Agent (with trade_id) |
| **Decision** | SL/TP levels (already calculated by Execution Agent) |
| **Logic** | Deterministic: trades → order_agent |
| **Output** | {sl_order_ids, tp_order_ids, confirmation} |
| **Learning Scope** | ❌ NONE (SL/TP math is in Execution Agent) |
| **Called By** | Full Crew (e2e_chain.py) |
| **Calls** | place_sl_tp_orders (tool) |

---

### MONITORING PHASE (Runs Every 5 Minutes)

#### 9. Morpher Agent
| Aspect | Details |
|--------|---------|
| **Role** | Detect signal reversals, morph position |
| **Input** | Active trade dict from previous entry |
| **Decision** | Should signal reverse? (BULLISH→BEARISH or vice versa) |
| **Logic** | Tool-based: check_for_morph compares original vs current signal |
| **Output** | Morph actions executed OR "no action" |
| **Learning Scope** | ❌ NONE (tool-based detection, no learning) |
| **Called By** | Monitoring loop (kickoff.py) |
| **Calls** | check_for_morph (tool), then calls Risk Agent tools |
| **Constraints** | MAX 3 morphs per day |

#### 10. Shifter Agent
| Aspect | Details |
|--------|---------|
| **Role** | Premium decay, shift legs to lock profit |
| **Input** | Active trade dict + margin available |
| **Decision** | When to shift? (50% HEDGE_SHIFT, 60% SELL_SHIFT thresholds) |
| **Logic** | Tool-based: check_for_shift calculates decay % |
| **Output** | Shift actions executed OR "no action" |
| **Learning Scope** | ❌ NONE (decay thresholds hardcoded, not learned) |
| **Called By** | Monitoring loop (kickoff.py) |
| **Calls** | check_for_shift (tool), then calls Risk Agent tools |

#### 11. Risk Agent (MONITORING PHASE)
| Aspect | Details |
|--------|---------|
| **Role** | Cancel/modify SL/TP for morphs/shifts |
| **Input** | Called BY Morpher/Shifter agents |
| **Decision** | Which orders to cancel? Which to place new? |
| **Logic** | Deterministic: cancel old, place new for morphed/shifted legs |
| **Output** | {cancelled_order_ids, new_order_ids} |
| **Learning Scope** | ❌ NONE (order management, no decisions) |
| **Called By** | Morpher Agent, Shifter Agent |
| **Calls** | place_sl_order, place_tp_order, cancel_order (tools) |

---

### POST-TRADE PHASE (End-of-Day)

#### 12. Postmortem Agent
| Aspect | Details |
|--------|---------|
| **Role** | Post-trade analysis + learning |
| **Input** | Complete trade data + all agent outputs + exit data |
| **Decision** | What worked? What failed? |
| **Logic** | Analyzes signals vs actual market outcomes, pattern matching |
| **Output** | Research notes stored in ChromaDB |
| **Learning Scope** | ✅ MASSIVE (learns signal accuracy, param optimization, success patterns) |
| **Called By** | End-of-day flow (kickoff.run_pm()) |
| **Calls** | query_chromadb, store_chromadb_note, update_daily_config (tools) |
| **Learns** | Entry signal accuracy, regime classification accuracy, parameter effectiveness, success patterns per signal+regime |

---

## Phase Flow & Execution Order

### Entry Phase (Morning)
```
START
  ↓
NOT_UP & NOT_DOWN Entry Agents (parallel)
  ↓
Regime Agent (validates signals)
  ↓
Strategy Agent (picks strategy + parameters)
  ↓
Contract Agent (resolves contracts)
  ↓
Execution Agent (builds trade)
  ↓
Order Agent (routes orders)
  ↓
Risk Agent (places SL/TP)
  ↓
TRADE ACTIVE (monitoring phase begins)
```

### Monitoring Phase (Every 5 Minutes)
```
MONITORING LOOP:
  ├─ Morpher Agent
  │   ├─ Check signal reversal?
  │   ├─ If yes: Risk Agent (cancel old, place new)
  │   └─ Max 3 morphs/day
  │
  └─ Shifter Agent
      ├─ Check premium decay?
      ├─ If HEDGE_SHIFT (50%): Risk Agent (new hedge, cancel old)
      ├─ If SELL_SHIFT (60%): Risk Agent (new sell, cancel old, book profit)
      └─ Continue monitoring
```

### Post-Trade Phase (End-of-Day)
```
AFTER MARKET CLOSE:
  ↓
Postmortem Agent
  ├─ Analyze Entry Signal accuracy
  ├─ Check Regime classification
  ├─ Evaluate Strategy parameters
  ├─ Review Monitoring phase (morphs/shifts timing)
  ├─ Store in ChromaDB (research notes)
  └─ Update daily_config for tomorrow
```

---

## Learning Scope Per Agent

### HIGH Learning Scope (Should be LLM)
| Agent | Learning Opportunity |
|-------|---|
| **Postmortem Agent** | Outcomes analysis: Which signals work in which regimes? Which parameters optimal? |

### MEDIUM Learning Scope (Could be LLM, but currently hardcoded)
| Agent | Learning Opportunity | Current State |
|--------|---|---|
| **Strategy Agent** | Parameter optimization (wing_width, sl_pct, tp_pct by regime) | Hardcoded rules (VIX > 18 → adjust sl) |
| **Regime Agent** | Regime classification + signal validation | Hardcoded thresholds (ADX < 25 = sideways) |

### LOW/NO Learning Scope (Should NOT be LLM)
| Agent | Why No Learning |
|--------|---|
| **NOT_UP Entry Agent** | Deterministic signal evaluation |
| **NOT_DOWN Entry Agent** | Deterministic signal evaluation |
| **Contract Agent** | Deterministic DuckDB lookup |
| **Execution Agent** | Deterministic trade building |
| **Order Agent** | Deterministic PAPER/LIVE routing |
| **Risk Agent** | Deterministic order management |
| **Morpher Agent** | Deterministic signal reversal detection |
| **Shifter Agent** | Deterministic decay threshold detection |

---

## Current Conflicts & Overlaps

### ❌ CONFLICT: Strategy Agent Parameters vs Postmortem Learning

**Problem:**
- Strategy Agent has **hardcoded rules** for parameter optimization:
  ```
  if VIX > 18: sl_pct = 0.35  (not 0.25)
  if ADX > 30: tp_pct = 0.40  (not 0.50)
  ```

- Postmortem Agent **learns** which parameters work best in ChromaDB

- **Flow:**
  1. Strategy Agent uses hardcoded rules
  2. Trade executes
  3. Postmortem learns: "Actually, VIX > 18 needs sl_pct=0.40, not 0.35"
  4. Next day: Strategy Agent still uses old hardcoded rules
  5. **Learning is NOT fed back to Strategy Agent**

**Solution (Phase 2):**
- Strategy Agent queries ChromaDB for learned parameters
- OR: Postmortem Agent updates daily_config.json, Strategy reads it
- Currently: Learning is written to ChromaDB but NOT consumed

---

### ⚠️ POTENTIAL OVERLAP: Regime Agent vs Strategy Agent

**Question:**
- Regime Agent classifies regime (trending/sideways)
- Strategy Agent uses regime for parameter optimization
- Should these be ONE agent or TWO?

**Current Design (TWO agents):**
- ✅ Separation of concerns (validation vs optimization)
- ❌ Duplicate regime classification logic

**Single Agent Alternative:**
- Regime+Strategy combined = "Regime Strategy Agent"
- Fewer LLM calls
- Less context passing

---

### ✅ GOOD: Order Agent as Centralized Hub

**No conflict.** Order Agent is the correct central router:
- Execution Agent → Order Agent (one-way call)
- Risk Agent → Order Agent (one-way call)  
- Morpher/Shifter → Risk Agent → Order Agent (one-way call)

All orders flow through Order Agent. No conflicts.

---

## Multi-Asset Expansion (Phase 2) Implications

### New Agent Needed: Asset Selector Agent

Insert between Strategy Agent and Contract Agent:

```
Strategy Agent → [NEW] Asset Selector Agent → Contract Agent
```

**Asset Selector Agent:**
| Aspect | Details |
|--------|---------|
| **Role** | Decide WHICH asset (NIFTY vs Reliance vs Crude) |
| **Input** | Entry signal + Strategy type + Regime |
| **Decision** | Which asset has best historical win rate? |
| **Learning Scope** | ✅ HIGH (learns asset selection from Postmortem) |
| **Queries** | ChromaDB for historical outcomes per asset |

**Modified Postmortem Agent:**
- Track which asset was picked
- Learn: "NOT_UP signal: NIFTY 70% WR, Reliance 52% WR"
- Asset Selector queries this learning

---

## Summary Table: All 12 Agents

| # | Agent | Phase | Learning? | Conflict? | Multi-Asset Impact |
|---|-------|-------|-----------|-----------|---|
| 1 | NOT_UP Entry | Entry | ❌ No | ❌ None | No change |
| 2 | NOT_DOWN Entry | Entry | ❌ No | ❌ None | No change |
| 3 | Regime | Entry | ⚠️ Partial | ⚠️ Overlaps Strategy | No change |
| 4 | Strategy | Entry | ⚠️ Partial | ⚠️ Not fed Postmortem learning | No change |
| 5 | Contract | Entry | ❌ No | ❌ None | Resolves for picked asset |
| 6 | Execution | Entry | ❌ No | ❌ None | Still dumb executor |
| 7 | Order | Both | ❌ No | ❌ None | Routes any asset |
| 8 | Risk | Both | ❌ No | ❌ None | Manages any asset |
| 9 | Morpher | Monitor | ❌ No | ❌ None | Works any asset |
| 10 | Shifter | Monitor | ❌ No | ❌ None | Works any asset |
| 11 | Postmortem | Post | ✅ YES | ❌ None | Learns asset-strategy fit |
| 12 | [Asset Selector] | Entry | ✅ YES (new) | ❌ None | NEW: Picks asset |

---

## Recommendations: Fix Before Multi-Asset Expansion

### CRITICAL (Block Phase 2):
1. **Fix learning feedback:** Postmortem Agent's ChromaDB insights → Strategy Agent's parameters
   - Currently: Learning written but not consumed
   - Solution: Strategy Agent queries ChromaDB for learned parameters per regime

### HIGH (Phase 2 prerequisite):
2. **Add Asset Selector Agent** between Strategy and Contract
   - Queries: Which asset has best historical WR for this signal+regime?
   - Learns: Asset-strategy fit from Postmortem outcomes

3. **Update Postmortem Agent:**
   - Track asset_class in analysis
   - Learn: Success rates per asset-strategy-regime combo
   - Store in ChromaDB with asset grouping

### MEDIUM (Nice-to-have):
4. **Merge Regime + Strategy agents** (eliminate overlap)
   - Reduce one LLM call
   - Single "Regime Strategy Agent" does both validation + optimization

5. **Push Shifter/Morpher thresholds to learning:**
   - Currently: 50% decay for HEDGE_SHIFT is hardcoded
   - Learn: "50% decay optimal for NIFTY, 45% better for Reliance"
