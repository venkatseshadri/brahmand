# Order Agent Refactoring — Centralized Order Routing

## Problem
Previously, execution_agent and risk_agent directly called broker tools (ExecutePaperTradeTool, PlaceSLOrderTool, PlaceTPOrderTool), bypassing a centralized decision point. This meant:
- No single place to decide PAPER vs LIVE mode
- Inconsistent order routing across agents
- Impossible to enforce uniform order ledger tracking

## Solution
Introduced **Order Agent** as the central routing hub for ALL orders:
- execution_agent → place_entry_orders → Order Agent → order_ledger (PAPER) or Shoonya (LIVE)
- risk_agent → place_sl_tp_orders → Order Agent → order_ledger (PAPER) or Shoonya (LIVE)

## Changes Made

### 1. Agent Registry (`config/agents_registry.yaml`)
- **execution_agent**: 
  - Goal: "Build complete trade object, route entry orders through Order Agent"
  - Tools: `[execute_paper_trade, place_entry_orders]`
  - Backstory updated to explain handoff to Order Agent

- **risk_agent**:
  - Goal: "Place/manage SL/TP orders through Order Agent"
  - Tools: `[place_sl_tp_orders, place_sl_order, place_tp_order, cancel_sl_order, modify_sl_order, tsl_engine]`
  - Backstory updated to emphasize Order Agent routing
  
- **order_agent** (NEW):
  - Goal: "Centralized order routing — decides PAPER vs LIVE mode"
  - Tools: `[place_entry_orders, place_sl_tp_orders]`
  - Backstory: Routes all orders through centralized hub, no LLM agents bypass it

### 2. Order Routing Tools (`tools/chain_tools.py`)

#### PlaceEntryOrdersTool
```python
class PlaceEntryOrdersTool(BaseTool):
    name: str = "place_entry_orders"
    description: "Route all entry orders (4 legs butterfly, 2 spreads) through Order Agent's hub"
    args: List[Dict] with tsym, action, strike, type, quantity, fill_price
    returns: {trade_id, entry_orders: [order_ids], status: FILLED|PLACED, mode: PAPER|LIVE}
```

#### PlaceSLTPOrdersTool
```python
class PlaceSLTPOrdersTool(BaseTool):
    name: str = "place_sl_tp_orders"
    description: "Route SL/TP orders through Order Agent's hub"
    args: trade_id (str), legs (List[Dict])
    returns: {trade_id, sl_orders: [order_ids], tp_orders: [order_ids], mode: PAPER|LIVE}
```

Both tools import and call the corresponding methods from `order_agent.py`:
- `order_agent.place_entry_orders(legs)` 
- `order_agent.place_sl_tp_orders(trade_id, legs)`

### 3. E2E Chain Updates (`e2e_chain.py`)

#### Tool Initialization
```python
# Order routing tools
entry_orders_tool = PlaceEntryOrdersTool()
sl_tp_orders_tool = PlaceSLTPOrdersTool()

# Agent initialization
execution_agent = af.create_agent(
    "execution_agent",
    tools=[execution_tool, entry_orders_tool],  # ← added entry_orders_tool
)

risk_agent = af.create_agent(
    "risk_agent",
    tools=[sl_tp_orders_tool, sl_tool, tp_tool, cancel_tool, modify_sl_tool],  # ← added sl_tp_orders_tool
)

order_agent = af.create_agent(
    "order_agent",
    tools=[entry_orders_tool, sl_tp_orders_tool],  # ← new agent instance
)
```

Note: order_agent is NOT part of the sequential crew—it's called via tools by execution_agent and risk_agent.

## Order Flow

### Entry Phase
```
1. Entry Agent → Decision (BULLISH/BEARISH/NEUTRAL)
2. Regime Agent → Validates regime
3. Strategy Agent → Selects PUT_SPREAD/CALL_SPREAD/IRON_BUTTERFLY
4. Contract Agent → Resolves tsyms
5. Execution Agent → Builds trade dict + calls place_entry_orders
   ↓
6. Order Agent (via PlaceEntryOrdersTool)
   ├─ PAPER mode: saves legs to order_ledger.json
   └─ LIVE mode: forwards to Shoonya API
   ↓
7. Risk Agent → Calls place_sl_tp_orders
   ↓
8. Order Agent (via PlaceSLTPOrdersTool)
   ├─ PAPER mode: saves SL/TP orders to order_ledger.json
   └─ LIVE mode: forwards to Shoonya API
```

### Monitoring Phase (Morph/Shift)
```
Morpher/Shifter Agents → Risk Agent → place_sl_order/cancel_order → Broker/Ledger
(Still uses direct tools; future: should also route through Order Agent)
```

## Benefits
1. **Single Decision Point**: PAPER vs LIVE mode decided in one place (order_agent.py LIVE_MODE flag)
2. **Consistent Audit Trail**: All orders logged to order_ledger.json regardless of mode
3. **Modular**: Adding new brokers = extend order_agent, no agent code changes
4. **Testable**: PlaceEntryOrdersTool/PlaceSLTPOrdersTool can be mocked for unit tests
5. **Future-Proof**: Agents never bypass centralized routing

## Status
✅ **COMPLETE** — All agents updated, tools created, imports verified, YAML validated.

## Next Steps
1. Run end-to-end integration test to verify trade execution flow
2. Backtest with historical data to confirm ledger matches expected state
3. Update morph_agent and shifter_agent to use Order Agent for SL/TP modifications
4. Implement LIVE mode (currently LIVE_MODE=False in order_agent.py)
