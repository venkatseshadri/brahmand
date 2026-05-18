# Brahmand Knowledge Architecture for Reinforcement Learning

**Date:** 2026-05-15  
**Status:** Design for CrewAI Knowledge Integration  
**Purpose:** Map agent roles to knowledge bases + RL feedback loop

---

## I. THE 7 TRADE EXECUTION ROLES

| # | Agent | Role | Input | Output | Knowledge Needs |
|----|-------|------|-------|--------|-----------------|
| **1** | **Regime Agent** | Market classification pre-decision | DuckDB (ADX, ST, EMA, VIX) | `{regime, confidence, recommendation}` | Past regimes + accuracy history |
| **2** | **Strategy Agent** | Strategy selection per regime | Regime output + VIX/ADX | `{strategy_type, wing_width, sl_pct, tp_pct}` | Strategy-per-regime outcomes, success rates |
| **3** | **Contract Agent** | Symbol resolution + lot sizing | Strategy + DuckDB snapshots | `[{tsym, strike, action, lot_size}]` | Contract availability patterns, delisted symbols |
| **4** | **Execution Agent** | Trade placement (mock/live) | Contracts + market data | TradeSignal (order_id, fills) | Entry timing patterns, fill quality history |
| **5** | **Risk Agent** | SL/TP management + breach prevention | ExecutionReport + live Greeks | Risk decisions (SL/TP orders) | SL hit patterns, optimal SL % by regime |
| **6** | **Post-Mortem Agent** | Trade analysis + lesson extraction | state.db + DuckDB + ChromaDB | ResearchNotes → ChromaDB + daily_config.json | **Publisher of all learnings** |
| **7** | **Margin Agent** *(Phase 2)* | Margin calculation + authorization | Trade + positions + account | Margin approval/rejection | Margin requirement history, account risk |

---

## II. KNOWLEDGE BASE DESIGN (PER AGENT)

Each agent gets a **CrewAI Knowledge collection**. Post-Mortem publishes findings → Knowledge gets updated → Next agent queries it.

### 1. **REGIME_KNOWLEDGE** — Market Classification Memory

**Documents stored by Post-Mortem:**
```json
{
  "date": "2026-05-15",
  "regime_predicted": "sideways",
  "actual_regime_at_1100": "sideways",
  "actual_at_1500": "trending_bearish",  // Changed mid-day
  "accuracy": true,
  "confidence_given": 0.85,
  "vix_at_entry": 18.4,
  "adx_at_entry": 22,
  "supertrend_direction": "neutral",
  "why_wrong": "ADX dropped from 28 to 18 between 10:00 and 14:00",
  "lesson": "ADX declining = regime about to shift; increase caution at >20 but trending <24"
}
```

**Regime Agent queries:**
```python
# "What regimes matched my current VIX=18.4 + ADX=22 conditions?"
results = knowledge.search(
    query="sideways regime VIX 18 ADX 22 accuracy confidence",
    filters={"date": {"$gte": "2026-05-01"}},
    limit=5
)
# Results include: accuracy rate for this exact combo, past confidence scores
```

**Reinforcement Loop:**
- Post-Mortem: "ADX 22 predicted sideways but actual was trending → lower confidence next time"
- Next Regime Agent: Queries knowledge → finds 3 prior instances of ADX 22 with 60% accuracy → adjusts confidence from 0.85 to 0.65

---

### 2. **STRATEGY_KNOWLEDGE** — Strategy Selection Memory

**Documents stored by Post-Mortem:**
```json
{
  "date": "2026-05-14",
  "regime": "sideways",
  "strategy_chosen": "IRON_BUTTERFLY",
  "wing_width": 200,
  "sl_pct": 0.25,
  "tp_pct": 0.50,
  "entry_time": "10:47",
  "exit_reasons": ["tp_hit_on_ce_wing", "sl_held_pe_sell"],
  "pnl_short": 850,
  "pnl_long": -120,
  "net_pnl": 730,
  "why_successful": "Wing width 200 was perfect for VIX 18.2; SL 25% was tight but prevented the 50pt move at 13:00",
  "alternate_choice": "Could've done Bull_Put if predicted bullish instead",
  "lesson": "Iron Butterfly in sideways + VIX <19 wins 75% of time. Bull/Bear spreads underperform."
}
```

**Strategy Agent queries:**
```python
# "What strategies worked in SIDEWAYS regimes with VIX < 20?"
results = knowledge.search(
    query="sideways strategy wing_width sl_pct iron butterfly credit spread",
    filters={"regime": "sideways", "net_pnl": {">": 0}},
    limit=10
)
# Results: 8/10 Iron Butterfly profitable, avg 650₹; 2/10 Bull_Put avg 400₹
# → Strategy Agent increases Iron Butterfly confidence, suggests wing_width=200
```

**Reinforcement Loop:**
- Post-Mortem: Iron Butterfly with wing 200 and SL 25% → winning recipe in sideways
- Next Strategy Agent: Queries knowledge → finds 75% win rate for this combo → selects it immediately

---

### 3. **CONTRACT_KNOWLEDGE** — Symbol/Liquidity Memory

**Documents stored by Post-Mortem:**
```json
{
  "date": "2026-05-14",
  "contract_tsym": "NIFTY12MAY26C23650",
  "strike": 23650,
  "option_type": "CE",
  "expiry": "2026-05-12",
  "entry_ltp": 45.5,
  "market_depth": "visible",
  "liquidity_issue": false,
  "fill_slippage": 0.0,
  "why_good": "Volume 50K+, bid-ask spread ₹1",
  "similar_contracts_failed": [
    "NIFTY12MAY26C23900 — spread ₹5, illiquid"
  ],
  "lesson": "ATM±200 strikes have 10x better liquidity than ATM±400"
}
```

**Contract Agent queries:**
```python
# "Which strike wings have best liquidity for NIFTY weekly expiry?"
results = knowledge.search(
    query="NIFTY weekly expiry liquidity wing strike spread slippage",
    filters={"fill_slippage": {"<": 1.0}, "date": {"$gte": "2026-05-01"}},
    limit=5
)
# Results: ATM±200 wins, avoid ATM±300+
```

**Reinforcement Loop:**
- Post-Mortem: "NIFTY ATM±200 CE has 50K volume, ATM±400 has 5K → use 200"
- Next Contract Agent: Queries knowledge → finds wing_width=200 always ✓, wing_width=400 always ✗ → hardcodes 200

---

### 4. **EXECUTION_KNOWLEDGE** — Entry Timing + Fill Quality Memory

**Documents stored by Post-Mortem:**
```json
{
  "date": "2026-05-14",
  "trade_id": "SIM-10:47-001",
  "entry_time": "10:47",
  "entry_quality": "good",
  "entry_reasons": [
    "market_hour_10_is_sweet_spot",
    "no_major_event_risk",
    "vix_stable_5min_prior"
  ],
  "fills": [
    {"leg": "SELL_CE", "ordered_at": "10:47:00", "filled_at": "10:47:02", "slippage_ticks": 0},
    {"leg": "SELL_PE", "ordered_at": "10:47:03", "filled_at": "10:47:05", "slippage_ticks": 0},
    {"leg": "BUY_CE_WING", "ordered_at": "10:47:06", "filled_at": "10:47:15", "slippage_ticks": 2},
    {"leg": "BUY_PE_WING", "ordered_at": "10:47:17", "filled_at": "10:47:22", "slippage_ticks": 1}
  ],
  "fill_time_total_sec": 22,
  "net_credit": 195,
  "lesson": "Morning 10:30-11:30 window = best fills; avoid 11:00 (liquidity dries up)"
}
```

**Execution Agent queries:**
```python
# "What entry times give best fill quality for Iron Butterfly?"
results = knowledge.search(
    query="entry time morning 10:47 fill quality slippage iron butterfly",
    filters={"entry_quality": "good", "fill_time_total_sec": {"<": 30}},
    limit=5
)
# Results: 10:30-10:50 and 11:15-11:45 windows show 0 slippage
# → Execution Agent: "Enter now if 10:47, skip if 11:00"
```

**Reinforcement Loop:**
- Post-Mortem: "Entry at 10:47 → 0 slippage, entry at 11:05 → 3 ticks slippage"
- Next Execution Agent: Queries knowledge → avoids 11:00-11:15 zone, targets 10:47 window

---

### 5. **RISK_KNOWLEDGE** — SL/TP Breach Patterns

**Documents stored by Post-Mortem:**
```json
{
  "date": "2026-05-14",
  "trade_id": "SIM-10:47-001",
  "sl_pct_set": 0.25,
  "tp_pct_set": 0.50,
  "sell_legs": [
    {
      "leg": "SELL_CE_23650",
      "premium_received": 45.5,
      "sl_level_25pct": 56.9,
      "tp_level_50pct": 22.8,
      "max_reached": 58.0,
      "sl_hit": true,
      "hit_time": "13:22",
      "loss_at_hit": 1235,
      "could_have_been_saved": "If TSL at 50% of max instead of 25%"
    }
  ],
  "lesson": "VIX was 18.4; with VIX < 18, SL 25% is too tight. Should be 30-35% in low VIX."
}
```

**Risk Agent queries:**
```python
# "What SL % prevents breaches in low-VIX sideways trades?"
results = knowledge.search(
    query="SL tight VIX low 18 breach prevention trailing stop",
    filters={"vix": {"<": 19}, "regime": "sideways"},
    limit=10
)
# Results: SL 30%+ wins, SL 25% loses 40% of time
# → Risk Agent: Adjusts from SL 25% to SL 30% for next trade
```

**Reinforcement Loop:**
- Post-Mortem: "SL 25% hit at 13:22; VIX was low; tighter SL in high-VIX markets works"
- Next Risk Agent: Queries knowledge → for VIX < 19, sets SL 30%+ instead of 25%

---

### 6. **POSTMORTEM_KNOWLEDGE** — Self-Publishing Pipeline

**The Post-Mortem Agent publishes 4 types of documents:**

```python
# Each evening, Post-Mortem runs:

1. REGIME_ACCURACY_NOTE
   "regime_predicted=sideways vs actual=trending_bearish"
   
2. STRATEGY_OUTCOME_NOTE
   "strategy=IRON_BUTTERFLY won 730₹ with wing=200, sl=25%"
   
3. CONTRACT_LIQUIDITY_NOTE
   "NIFTY ATM±200 wings have 50K volume; use this wing width"
   
4. EXECUTION_TIMING_NOTE
   "entry at 10:47 gave 0 slippage; 11:00-11:15 zone had 3-tick slippage"
   
5. RISK_SL_PATTERN_NOTE
   "SL 25% too tight for VIX < 19; recommend SL 30%+ in low-VIX sidways"
   
6. DAILY_CONFIG_NOTE (→ daily_config.json)
   {
     "regime_confidence_boost": 0.65,  // Lower from 0.85
     "strategy_wing_width": 200,       // Hardcode this
     "execution_entry_window": "10:30-10:50,11:15-11:45",
     "risk_sl_pct": 0.30,              // Increase from 0.25
     "telegram_alert": "SL breach pattern detected in low-VIX. Increasing SL to 30%."
   }
```

**Post-Mortem publishes to CrewAI Knowledge:**
```python
# After analyzing all tables, Post-Mortem writes:
knowledge.add_documents(
    documents=[
        Document(
            id=f"regime_20260514_001",
            content="sideways prediction accurate. ADX 22 = 75% sideways confidence.",
            metadata={
                "type": "regime_accuracy",
                "date": "2026-05-14",
                "confidence": 0.85,
                "timestamp": "16:00"
            }
        ),
        Document(
            id=f"strategy_20260514_001",
            content="IRON_BUTTERFLY with wing=200, sl=25%, tp=50% won 730₹. Best combo for low-VIX sideways.",
            metadata={
                "type": "strategy_outcome",
                "strategy": "IRON_BUTTERFLY",
                "pnl": 730,
                "vix_range": "18-20",
                "regime": "sideways",
                "timestamp": "16:00"
            }
        ),
        # ... 4 more documents
    ]
)
```

---

### 7. **MARGIN_KNOWLEDGE** *(Phase 2)* — Account Risk Memory

**Documents stored by Post-Mortem:**
```json
{
  "date": "2026-05-14",
  "trade_id": "SIM-10:47-001",
  "margin_required": 18500,
  "margin_available": 500000,
  "margin_utilization": 3.7,
  "max_daily_margin_reached": 22000,
  "margin_spike_reason": "TSL moved to 59.0 on SELL_CE; risk jumped",
  "can_open_another": true,
  "lesson": "IRON_BUTTERFLY uses ~20K fixed margin. Plan for 2 simultaneous trades = 40K needed."
}
```

**Margin Agent queries:**
```python
# "Can I open another Iron Butterfly trade right now?"
results = knowledge.search(
    query="IRON_BUTTERFLY margin requirement simultaneous trades",
    filters={"regime": "sideways"},
    limit=5
)
# Results: avg 20K per trade; with 500K available, can safely do 2-3 trades
# → Margin Agent: "Yes, open trade"
```

---

## III. REINFORCEMENT LEARNING FEEDBACK LOOP

### Flow: Post-Mortem → Knowledge → Next Agent Decision

```
Day 1 (May 14):
  09:15 - Regime Agent: Predicts "sideways", confidence 0.85
  10:47 - Strategy Agent: Selects IRON_BUTTERFLY, wing_width=200
  10:47 - Execution Agent: Enters trade, fills at 10:47
  10:47 - Risk Agent: Sets SL 25%, TP 50%
  13:22 - Risk Agent: SL breached; loss 1235₹
  16:00 - Post-Mortem Agent: PUBLISHES 6 findings to CrewAI Knowledge
           ├─ "Sideways prediction accurate 85% of time for ADX 22"
           ├─ "IRON_BUTTERFLY + wing 200 won 730₹"
           ├─ "SL 25% TOO TIGHT for VIX < 19 in sideways"
           ├─ "Entry at 10:47 = zero slippage; 11:00 zone = 3 ticks"
           ├─ "NIFTY ATM±200 wings best liquidity"
           └─ "Updated daily_config.json: SL now 30%, entry window 10:30-10:50"

Day 2 (May 15):
  09:15 - Regime Agent: Queries knowledge
           "What regimes matched ADX=22 + VIX=18?"
           → Finds Day 1 record: 85% sideways, confidence 0.85
           → Predicts "sideways", confidence 0.85 (consistent)
  
  10:30 - Strategy Agent: Queries knowledge
           "Best strategy for sideways + VIX < 20?"
           → Finds Day 1: IRON_BUTTERFLY + wing 200 won ✓
           → Selects IRON_BUTTERFLY, wing=200 (learned!)
  
  10:35 - Execution Agent: Queries knowledge
           "Best entry time for Iron Butterfly?"
           → Finds Day 1: 10:47 = 0 slippage, 11:00 = 3 ticks
           → Targets 10:40-10:50 window (learned!)
  
  10:42 - Execution Agent: Enters trade
  
  10:42 - Risk Agent: Queries knowledge
           "Optimal SL % for VIX < 20 + sideways?"
           → Finds Day 1: SL 25% breached; SL 30% recommended
           → Sets SL 30% instead of 25% (LEARNED IMPROVEMENT!)
  
  14:00 - Trade outcome: TP hit, profit 950₹ (better than Day 1!)
           → Day 2 SL 30% prevented Day 1's breach

Post-Mortem Day 2:
  16:00 - Post-Mortem Agent: Publishes Day 2 findings
           ├─ "SL 30% worked! Prevented breach that would've occurred at Day 1 levels."
           ├─ "Entry 10:42 = 1 tick slippage (even better than Day 1's 0 ticks)"
           ├─ "IRON_BUTTERFLY + sideways still winning"
           └─ "Regime prediction 85% accurate 2 days in a row"
```

---

## IV. KNOWLEDGE DOCUMENT SCHEMA (CrewAI Compatible)

```python
from crewai.knowledge.document import Document
from datetime import datetime

# Each document published by Post-Mortem:
doc = Document(
    id=f"{source}_{date}_{sequence}",
    
    # Semantic text (what gets embedded)
    content="""
    Market regime sideways detected with ADX 22, VIX 18.4.
    IRON_BUTTERFLY strategy with 200-pt wing width generated 730₹ profit.
    SL set at 25% breached; recommend 30% for low-VIX conditions.
    Entry at 10:47 filled with zero slippage; 11:00-11:15 zone showed 3-tick slippage.
    Daily config updated: SL→30%, entry_window→10:30-10:50.
    """,
    
    # Filterable metadata
    metadata={
        "type": "trade_postmortem",  # postmortem, regime_accuracy, strategy_outcome, etc.
        "date": 20260514,
        "trade_id": "SIM-10:47-001",
        "regime": "sideways",
        "strategy": "IRON_BUTTERFLY",
        "pnl": 730,
        "vix": 18.4,
        "adx": 22,
        "sl_pct": 0.25,
        "sl_breached": True,
        "recommendation": "increase_sl_to_30pct",
        "confidence": 0.95,
        "agent_version": "brahmand-v1",
        "timestamp": "2026-05-14T16:00:00Z",
        "tags": ["low_vix", "sideways", "sl_optimization", "entry_timing"]
    }
)

# Next agent queries:
regime_agent.knowledge.search(
    query="sideways ADX 22 regime accuracy",
    filters={"type": "regime_accuracy", "date": {"$gte": 20260501}},
    limit=5
)
```

---

## V. KNOWLEDGE PERSISTENCE: SQLite + CrewAI Knowledge

### Two-Layer Architecture:

```
┌─────────────────────────────────────────────────────────┐
│  CrewAI Knowledge (In-Memory, Fast, Semantic Search)    │
│  ├─ regime_knowledge                                     │
│  ├─ strategy_knowledge                                   │
│  ├─ contract_knowledge                                   │
│  ├─ execution_knowledge                                  │
│  ├─ risk_knowledge                                       │
│  └─ margin_knowledge (Phase 2)                           │
│                                                          │
│  Queried by: Agents during decision-making              │
│  Updated by: Post-Mortem Agent every evening            │
│  TTL: Current session (can be persisted with snapshots) │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  SQLite state.db (Audit Trail, Long-Term)              │
│  ├─ research_notes table                                │
│  │  └─ Stores Post-Mortem findings (same content)      │
│  ├─ execution_reports table                             │
│  │  └─ Stores all trade fills & outcomes               │
│  └─ daily_configs table                                 │
│     └─ Stores each day's recommended parameters         │
│                                                          │
│  Queried by: Post-Mortem, auditors, backtesters        │
│  Persisted: Forever (legal/compliance requirement)      │
└─────────────────────────────────────────────────────────┘
```

---

## VI. IMPLEMENTATION CHECKLIST: CrewAI Knowledge Integration

### Phase 1 (NOW): Design + Post-Mortem Publishing
- [ ] Define CrewAI Knowledge collections for each agent (6 collections)
- [ ] Extend ResearchNote Pydantic model with `for_knowledge` field
- [ ] Add `knowledge.add_documents()` to Post-Mortem Agent
- [ ] Write daily_config.json updates that encode learnings
- [ ] Test: Post-Mortem publishes → Knowledge receives

### Phase 2 (Week 2): Agent Knowledge Queries
- [ ] Regime Agent: Query regime_knowledge before classification
- [ ] Strategy Agent: Query strategy_knowledge before selection
- [ ] Contract Agent: Query contract_knowledge for wing_width
- [ ] Execution Agent: Query execution_knowledge for entry_window
- [ ] Risk Agent: Query risk_knowledge for SL/TP percentages

### Phase 3 (Week 3): Reinforcement Loop Validation
- [ ] Run 5 consecutive days of trades
- [ ] Measure: Did agents improve decisions based on prior learnings?
- [ ] Metrics:
  - Day 1 accuracy: Regime, Strategy, Entry Timing
  - Day 5 accuracy: Same (should be higher)
  - PnL trend: Day 1→5 should improve or stabilize at higher level

### Phase 4 (Week 4): Margin Agent + Multi-Trade Scenarios
- [ ] Add margin_knowledge collection
- [ ] Test: 2-3 simultaneous trades with proper margin gating

---

## VII. SAMPLE RL FEEDBACK EQUATIONS

### Regime Agent Confidence Update:
```
confidence_day_2 = confidence_day_1 × accuracy_rate_for_this_combo

Example:
- Day 1: Predicts sideways (ADX 22), confidence 0.85
- Post-Mortem: "Sideways correct 85% of time for ADX 20-24"
- Day 2: Predicts sideways (ADX 21), confidence 0.85 × 0.85 = 0.72
  → More conservative (good!)
```

### Strategy Selection Probability:
```
P(IRON_BUTTERFLY | sideways, VIX < 20) = 
  (wins_with_IB / total_sideways_trades) × confidence_regime

Example:
- Post-Mortem finds: 8/10 Iron Butterfly profitable in sideways + VIX < 20
- P(IB) = 0.80 × 0.85 = 0.68
- P(Bull_Put) = 0.20 × 0.85 = 0.17
→ Strategy Agent selects Iron Butterfly (68% vs 17%)
```

### Risk SL Tightness Update:
```
optimal_sl_pct = median_sl_pct_that_prevented_breach × vix_multiplier

Example:
- Days with VIX < 19: SL 30% prevented all breaches; SL 25% failed 40%
- optimal_sl_pct = 0.30 × (19 / vix_today)
- If VIX today = 19: SL = 30%
- If VIX today = 22: SL = 30% × (19/22) = 26%
```

---

## VIII. DOES IT ACCOMMODATE REINFORCEMENT LEARNING?

### ✅ **YES — FULL RL CAPABILITY**

| Requirement | How Brahmand Delivers |
|-------------|----------------------|
| **Agent learns from outcomes** | Post-Mortem publishes ResearchNotes → Knowledge |
| **Learning compounds** | Day N findings used by Day N+1 agents automatically |
| **Feedback is specific** | "SL 25% breached" vs "SL 30% didn't breach" — actionable |
| **Multi-agent coordination** | All agents query shared knowledge → decisions reinforce each other |
| **Long-term memory** | SQLite research_notes table = 6-month audit trail + RL replay |
| **Semantic search** | ChromaDB + CrewAI Knowledge = find relevant past patterns instantly |
| **Parameter tuning** | daily_config.json encodes learned SL%, entry_window, wing_width |
| **Confidence decay** | Older learnings weighted less; recent patterns weighted more |
| **Failure recovery** | Each breach analyzed; next iteration corrects |

### ✅ **CONCRETE RL EXAMPLES IN BRAHMAND:**

1. **Regime Accuracy RL:**
   - Day 1: Predict sideways, actual sideways ✓ → confidence++
   - Day 2: Predict sideways with higher confidence
   
2. **Strategy Selection RL:**
   - Days 1-3: IRON_BUTTERFLY wins 3/3 times
   - Day 4: Strategy Agent sees 100% win rate → selects immediately
   
3. **SL/TP Tightness RL:**
   - Day 1: SL 25% breached → "too tight"
   - Day 2: Risk Agent reads knowledge → SL 30%
   - Day 2: SL 30% didn't breach → "worked!"
   - Day 3: Risk Agent increases confidence in SL 30%
   
4. **Entry Timing RL:**
   - Day 1: Entry 10:47 = 0 slippage
   - Days 2-5: Execution Agent targets 10:47 window
   - Day 5: Entry 10:47 average slippage = 0.2 ticks → "confirmed pattern"

### ❌ **NOT REINFORCEMENT LEARNING** (What Brahmand Is NOT):

- **Not neural network training** — no gradient descent, no weights
- **Not Bayesian updating** — no prior distributions
- **Not Q-learning** — no action-value function
- **Not policy gradient** — no policy network

### ✅ **WHAT IT IS: Experiential Learning + Memory-Driven Adaptation**

Brahmand implements **agentic RL** via:
1. **Observation** — Post-Mortem analyzes outcomes
2. **Refinement** — Findings encoded in Knowledge documents
3. **Application** — Next agent queries knowledge, adjusts decisions
4. **Repetition** — Loop daily, learning compounds

This is more like **human trader learning** than ML:
- A trader makes a mistake, reviews it, adjusts next time
- 30 days of reviews → pattern recognition → systematic improvement
- This is what Brahmand does with agents

---

## IX. NEXT STEPS

1. **Read RESEARCH REFERENCES** (`RESEARCH_REFERENCES.md`) — CrewAI Knowledge API docs
2. **Implement Post-Mortem knowledge.add_documents()** — Make it publish
3. **Update agents to query knowledge** — Regime → Strategy → Execution → Risk
4. **Run 5-day dry run** — Measure RL improvement
5. **Automate daily config loading** — From learned parameters → tomorrow's trade

---

**Status: Ready for knowledge integration implementation** 🚀
