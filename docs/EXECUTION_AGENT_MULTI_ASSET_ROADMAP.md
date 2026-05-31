# Execution Agent: Multi-Asset Expansion Roadmap

## Current Role (Phase 1: NIFTY/SENSEX Options)

**Purpose:** Build paper trades and route entry orders. DUMB EXECUTOR — no decision-making.

**Current Workflow:**
```
Execution Agent (receives resolved instructions)
  ├─ Parses Contract Agent output (resolved option contracts)
  ├─ Parses Strategy Agent output (wing_width, sl_pct, tp_pct)
  ├─ Calls execute_paper_trade() to build trade dict with SL/TP levels
  ├─ Calls place_entry_orders() to route orders → Order Agent hub
  └─ Extracts trade_id + order_ids for Risk Agent
  
  CRITICAL: No decision-making. All decisions made upstream.
```

**Current Scope:**
- Market: NIFTY + SENSEX indices only (no selection needed)
- Instruments: Weekly/Monthly options
- Order Routing: Shoonya API (or paper ledger in PAPER mode)
- Position Size: Fixed (65 lots per leg)
- Decision-Making: ZERO (contracts already resolved, strategy already picked)

**Current Tools:**
- `execute_paper_trade` — builds trade dict with net_credit, SL/TP
- `place_entry_orders` — routes orders through order_agent hub

---

## Why execution_agent Stays DUMB (Even in Phase 2+)

Execution Agent does NOT gain learning scope. It stays a **dumb executor** because:

**Asset selection decisions belong UPSTREAM**, not in execution_agent.

- Entry Agent: "Is there a signal?" → YES/NO
- Regime Agent: "What's the market regime?" → trending/sideways
- Strategy Agent: "What strategy?" → CALL_SPREAD/PUT_SPREAD/IRON_BUTTERFLY
- **Asset Selector Agent (NEW Phase 2): "Which asset?" → NIFTY/Reliance/Crude/BTC**
- Contract Agent: "What are the contracts?" → resolved contracts
- **Execution Agent: "Just execute it."** ← STAYS DUMB

This is CORRECT architecture because:
1. ✅ Separation of concerns (decide vs execute)
2. ✅ execution_agent reusable across any asset
3. ✅ Easy to test (give it contracts, verify execution)
4. ✅ Learning happens in Asset Selector Agent, not execution_agent

---

## Phase 2: Multi-Asset Expansion (NEW: Asset Selector Agent)

**Key Insight:** Asset selection is a STRATEGIC decision, not an execution decision.

**New Agent Inserted:** Asset Selector Agent (runs between Strategy Agent and Contract Agent)

### Pipeline: Phase 1 → Phase 2

```
PHASE 1 (TODAY):
  Entry Agent 
    → Regime Agent 
      → Strategy Agent 
        → Contract Agent (NIFTY only)
          → execution_agent (dumb executor)
            → Risk Agent

PHASE 2 (TOMORROW):
  Entry Agent 
    → Regime Agent 
      → Strategy Agent 
        → [NEW] Asset Selector Agent ← INTELLIGENT
          → Contract Agent (for picked asset)
            → execution_agent (still dumb executor)
              → Risk Agent
```

### Asset Selector Agent: The Intelligent One

```python
asset_selector_agent:
  role: "Asset Selection Commander"
  goal: "Decide WHICH asset to trade based on signal + regime + historical performance"
  
  INPUT from upstream:
    {
      "signal": "NOT_UP",
      "confidence": 90,
      "vix": 18.5,
      "regime": "sideways",
      "available_assets": ["NIFTY", "RELIANCE", "TCS", "CRUDE"]
    }
  
  LEARNING SCOPE:
    1. Historical win rates per asset-signal combo
       "NOT_UP on NIFTY: 70% WR, Reliance: 52%, Crude: 48%"
    
    2. Regime fit per asset
       "Sideways regime: NIFTY spreads work, Crude fails"
    
    3. Position sizing constraints per asset
       "NIFTY: 65 lots OK, Reliance: max 50 (liquidity), Crude: 1 contract"
    
    4. Optimal entry time per asset
       "NIFTY: 9:45-10:15 best, Reliance: 11:00-12:00"
  
  TOOLS:
    - asset_performance_query (ChromaDB historical outcomes)
    - liquidity_checker (current market depth)
    - position_sizer (margin availability)
  
  OUTPUT:
    {
      "asset_class": "NIFTY",
      "reason": "70% historical WR for NOT_UP signals + sideways regime. Liquidity: 65 lots safe.",
      "confidence": 0.85,
      "position_size": 65,
      "margin_required": 7500
    }
```

### execution_agent: Still DUMB

```python
execution_agent:
  role: "Paper Trade Executor"
  goal: "Take execution instructions and execute them. No decisions."
  
  INPUT from upstream:
    {
      "asset_class": "NIFTY",  ← Already decided by Asset Selector
      "strategy_type": "CALL_SPREAD",
      "contracts": {...},  ← Already resolved by Contract Agent
      "wing_width": 200,
      "sl_pct": 0.25,
      "tp_pct": 0.50
    }
  
  EXECUTION:
    1. Call execute_paper_trade(contracts, strategy_type, ...)
       → Builds trade dict
    2. Call place_entry_orders(legs)
       → Routes orders
    3. Return: {trade_id, entry_orders}
  
  DOES NOT:
    ❌ Query historical data
    ❌ Pick asset (Asset Selector did this)
    ❌ Optimize parameters (Strategy Agent did this)
    ❌ Make any decisions
  
  BENEFIT: Same logic works for NIFTY, Reliance, Crude, BTC, etc.
  Just receives different contracts from Contract Agent.
```

### Tools Needed (Belong to Asset Selector, NOT execution_agent)

```python
class AssetPerformanceQueryTool(BaseTool):
    """Query ChromaDB for historical asset performance."""
    
    Input: signal, regime, timeframe
    Output: {
        "NIFTY": {"win_rate": 0.70, "trades": 42},
        "RELIANCE": {"win_rate": 0.52, "trades": 31},
        "CRUDE": {"win_rate": 0.48, "trades": 18}
    }

class LiquidityCheckerTool(BaseTool):
    """Check current market liquidity for position size."""
    
    Input: asset, position_size
    Output: {
        "executable": true,
        "slippage_estimate": 0.05,
        "max_safe_size": 65
    }

class PositionSizerTool(BaseTool):
    """Determine optimal lot size per asset."""
    
    Input: asset, available_capital, margin_constraint
    Output: {
        "optimal_size": 65,
        "capital_used": 45000,
        "margin_used": 7500
    }
```

### Phase 2 Data Flow (Correct)

```
Asset Selector Agent:
  1. Query: "NOT_UP signal, VIX=18.5, sideways regime"
  2. Search ChromaDB (postmortem_agent's learning)
  3. Get: "NIFTY=70%, Reliance=52%, Crude=48%"
  4. Check: "Can I size 65 lots on NIFTY right now?"
  5. Decide: "Pick NIFTY (best WR, sufficient liquidity)"
  6. Pass: {"asset_class": "NIFTY", "position_size": 65}

Contract Agent:
  1. Receives: asset_class="NIFTY"
  2. Queries: DuckDB for NIFTY option contracts
  3. Resolves: tsyms, ltps, strikes
  4. Passes: resolved contracts

execution_agent:
  1. Receives: contracts (resolved), strategy (picked), asset (decided)
  2. Builds: trade dict
  3. Routes: orders via order_agent
  4. Returns: trade_id + order_ids
```

---

## Phase 2.5: Commodity Expansion (MCX)

### New Challenges

| Aspect | Solution |
|--------|----------|
| **Contract Size** | Crude Oil = 100 barrels/contract, Gold = 100 grams, NG = 1500 units → different position sizing |
| **Margin Leverage** | Futures = 5-10% margin vs options = 15% → higher leverage = adjust SL width |
| **Order Routing** | MCX broker ≠ Shoonya → support multiple brokers |
| **Delivery Rules** | Futures have delivery deadlines → avoid contracts close to expiry |
| **Spread Width** | Commodity spreads wider than index options → adjust wing_width defaults |

### New Learning Areas

- Best commodity for signal (crude more volatile in supply shocks, gold in USD strength)
- Optimal contract month (near month vs next month trade-offs)
- Margin efficiency (futures allow higher leverage)
- Correlation with index (hedge via commodity or amplify?)

---

## Phase 3: Crypto Expansion

### New Challenges

| Aspect | Solution |
|--------|----------|
| **Spot vs Perpetual** | BTC spot purchase vs perpetuals/shorts → different execution paths |
| **24/7 Trading** | No market hours → time-of-day learning irrelevant |
| **Extreme Volatility** | VIX equivalent = Crypto Fear & Greed index → dynamic SL width |
| **Liquidation Risk** | Perpetuals have auto-liquidation at margin → very tight SL management |
| **Funding Rates** | Perpetual costs (pay/receive funding) → factor into P&L calculation |

### New Learning Areas

- Signal reliability across different market caps (BTC vs altcoins)
- Optimal leverage (high vol = lower leverage to avoid liquidation)
- Best timeframe per signal (4h vol vs 1d trend)
- Correlation with traditional markets

---

## Learning Architecture: Outcome Tracking

To make execution_agent intelligent across all phases, need:

### Trade Outcome Database Schema

```sql
CREATE TABLE execution_outcomes (
    trade_id TEXT,
    execution_date DATE,
    asset_class TEXT,  -- NIFTY, Reliance, Crude, BTC
    strategy_type TEXT,
    entry_gate_signal TEXT,
    regime_vix_equivalent FLOAT,
    position_size INT,
    entry_price FLOAT,
    exit_price FLOAT,
    pnl FLOAT,
    hit_sl BOOLEAN,
    hit_tp BOOLEAN,
    days_to_exit INT,
    confidence_score FLOAT,  -- From asset_selector
    
    -- Metrics
    win BOOLEAN,
    return_pct FLOAT,
    sharpe_ratio FLOAT,
    max_drawdown FLOAT,
    
    -- For learning
    asset_selection_correct BOOLEAN,  -- Did picked asset outperform alternatives?
    position_size_optimal BOOLEAN,    -- Did size fit liquidity well?
    sl_tp_placement_good BOOLEAN,     -- Was SL/TP at good confluence?
    
    INDEX (asset_class, strategy_type, win),
);
```

### Learning Queries

```sql
-- Best asset for NOT_UP signals
SELECT asset_class, COUNT(*) trades, AVG(CASE WHEN win THEN 1 ELSE 0 END) win_rate
FROM execution_outcomes
WHERE entry_gate_signal = 'NOT_UP'
GROUP BY asset_class
ORDER BY win_rate DESC;

-- Optimal position size by asset
SELECT asset_class, position_size, AVG(return_pct) avg_return, COUNT(*) trades
FROM execution_outcomes
GROUP BY asset_class, position_size
HAVING trades > 10
ORDER BY avg_return DESC;

-- Best regimes per asset
SELECT asset_class, 
       CASE WHEN regime_vix_equivalent < 15 THEN 'LOW_VIX'
            WHEN regime_vix_equivalent < 20 THEN 'MID_VIX'
            ELSE 'HIGH_VIX' END regime,
       AVG(CASE WHEN win THEN 1 ELSE 0 END) win_rate
FROM execution_outcomes
GROUP BY asset_class, regime
ORDER BY win_rate DESC;
```

---

## Implementation Roadmap

### Phase 1 (Current): ✅ Complete
- [x] NIFTY/SENSEX option spreads
- [x] Fixed 65-lot sizing
- [x] Shoonya API routing
- [x] Paper mode with ledger

### Phase 2.0: Individual Stocks (Months 1-2)
- [ ] Add AssetSelectorTool
- [ ] Support Reliance, TCS, Infy, HDFC
- [ ] Dynamic position sizing per ADV
- [ ] Extend order_agent to multi-stock
- [ ] Build trade outcome tracking DB
- [ ] First learning: asset selection win rates

### Phase 2.5: Commodities (Months 2-3)
- [ ] Add LiquidityCheckerTool for MCX
- [ ] Support Crude, Gold, Natural Gas
- [ ] Contract month selection logic
- [ ] Multi-broker order routing
- [ ] Margin-adjusted position sizing

### Phase 3.0: Crypto (Months 3-4)
- [ ] Support BTC, ETH perpetuals
- [ ] Liquidation-safe SL placement
- [ ] Funding rate P&L tracking
- [ ] 24/7 execution scheduling

### Phase 3.5: Cross-Asset Learning (Months 4+)
- [ ] Analyze asset correlation
- [ ] Hedge via alternative asset class
- [ ] Joint optimization across classes
- [ ] Unified risk dashboard

---

## order_agent vs execution_agent: No Conflict (Correct Architecture)

**Common Confusion:** "Will order_agent and execution_agent fight over who controls multi-asset routing?"

**Answer:** NO. They have ZERO overlap.

### Clear Role Separation

| Agent | Phase 1 | Phase 2+ | Responsibility |
|-------|---------|---------|---|
| **execution_agent** | Dumb executor | Dumb executor | Build trade dict + extract legs |
| **order_agent** | Route NIFTY orders | Route any asset's orders | Centralized PAPER/LIVE hub |
| **[NEW] Asset Selector** | Doesn't exist | Intelligent picker | Decide which asset + size |

### Data Flow (Both Phases)

```
execution_agent:
  RECEIVES: resolved contracts, strategy params, asset_class
  DOES: 
    1. trade = execute_paper_trade(contracts, strategy, spot, vix, ...)
    2. entry_legs = trade["legs"]
    3. order_result = place_entry_orders(entry_legs)  ← Calls order_agent
  
  RETURNS: trade dict with trade_id + order_ids

order_agent.place_entry_orders():
  RECEIVES: legs from execution_agent
  DOES:
    1. Generate trade_id
    2. For each leg: place_order(symbol, action, qty, price, ...)
    3. Save to order_ledger.json (PAPER) or forward to Shoonya (LIVE)
    4. Call add_active_trade() to write duckdb
  
  RETURNS: {trade_id, entry_orders: [order_ids], status, mode}
```

### Why No Conflict

| Phase | Scenario | order_agent | execution_agent | Resolution |
|-------|----------|-------------|--|---|
| Phase 1 | NIFTY spread entry | Routes 2 legs → ledger | Builds trade, calls place_entry_orders | Clear: exec → order |
| Phase 2 | Reliance spread entry | Routes 2 legs → ledger | Builds trade, calls place_entry_orders | Clear: exec → order |
| Phase 2.5 | Crude futures entry | Routes 1 contract → ledger | Builds trade, calls place_entry_orders | Clear: exec → order |
| Phase 3 | BTC perp entry | Routes spot+perp legs → ledger | Builds trade, calls place_entry_orders | Clear: exec → order |

**Pattern:** execution_agent is always the **caller**, order_agent is always the **hub**. One-direction flow. No conflict.

---

## Why execution_agent is KEPT (Phase 1+)

| Aspect | Phase 1 | Phase 2+ |
|--------|---------|---------|
| **Deterministic?** | ✅ Yes | ✅ Yes |
| **Learning Scope?** | ❌ None | ❌ None |
| **Necessary?** | ✅ Yes (builds trades) | ✅ Yes (still builds trades) |

**execution_agent is NOT intelligence.** It's a necessary orchestrator:
- Takes resolved contracts (from Contract Agent)
- Builds trade dict with SL/TP math
- Routes via order_agent
- Returns trade_id for Risk Agent

**Same code, different assets.** In Phase 2+, it receives NIFTY contracts vs Reliance contracts, but logic is identical.

---

## Current vs Future

### Phase 1 (Today)
```
execution_agent:
  Input: contracts (NIFTY), strategy (fixed)
  Decision: NONE (hardcoded)
  Output: trade + order_ids
  Learning: ZERO
```

### Phase 2+ (Tomorrow)
```
execution_agent:
  Input: signal, regime, available_assets, strategy
  Decision: 
    - Which asset class? (NIFTY vs Reliance vs Crude vs BTC)
    - Position size? (65 vs 50 vs 1 vs 0.05)
    - Which broker? (Shoonya vs NCDEX vs exchange)
    - SL/TP width? (risk-adjusted per asset)
  Output: trade + order_ids + asset_class + confidence
  Learning: Asset selection, sizing, outcome correlation
  Impact: 10-20% return improvement via smart asset selection
```

---

## Files to Update When Expanding

1. **e2e_chain.py** — Add asset selector tools, update execution_task
2. **tools/chain_tools.py** — New tools: AssetSelector, LiquidityChecker, PositionSizer
3. **order_agent.py** — Add asset-specific routing (place_nifty_orders vs place_stock_orders vs place_futures_orders)
4. **trade_execution_db.py** — Add asset_class + confidence columns for learning
5. **New:** execution_learning.py — Asset selection heuristics + historical analysis
6. **New:** asset_universe.py — Registry of tradeable assets + their properties

---

## Summary

**Today:** execution_agent is overhead.  
**Tomorrow (with multi-asset):** execution_agent is essential.

Keep it. Prepare it. Build toward this.
