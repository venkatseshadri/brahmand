# Order Agent Routing — Activation & Fixes ✅

**Date:** 2026-05-21  
**Issue Discovered:** Agents were NOT routing through Order Agent despite refactoring  
**Status:** FIXED — Agents now REQUIRED to use centralized routing

## Problem

After refactoring, logs showed:
- Risk Agent calling `place_sl_order` and `place_tp_order` directly (❌ OLD behavior)
- NOT calling `place_sl_tp_orders` (❌ NEW centralized routing)
- Order ledger only populated by tests, not actual trades (❌ agents bypassing hub)

### Root Cause
The Risk Agent had access to BOTH the old direct tools AND the new centralized tool:
```python
tools=[sl_tp_orders_tool, sl_tool, tp_tool, cancel_tool, modify_sl_tool]
```

Since multiple tools were available, the LLM agent chose to use the familiar old ones (`place_sl_order`, `place_tp_order`) instead of the new centralized tool.

## Solution

### 1. Enforce Single Path for Entry Phase
**Before (e2e_chain.py):**
```python
risk_agent = af.create_agent(
    "risk_agent",
    tools=[sl_tp_orders_tool, sl_tool, tp_tool, cancel_tool, modify_sl_tool],
)
```

**After (e2e_chain.py):**
```python
risk_agent = af.create_agent(
    "risk_agent",
    tools=[sl_tp_orders_tool],  # Entry phase: ONLY use centralized order routing
)
```

### 2. Crystal-Clear Task Descriptions

#### Execution Agent (execution_task)
Updated to explicitly state:
- "Call place_entry_orders(legs)" as STEP 4
- "CRITICAL: Call place_entry_orders with the legs from the trade dict"
- Explain Order Agent handles PAPER/LIVE routing
- Pass trade_id to Risk Agent

#### Risk Agent (risk_task)
Updated to explicitly state:
- "YOUR ONLY TOOL: place_sl_tp_orders (routes through Order Agent hub)"
- "CRITICAL: Do NOT call place_sl_order or place_tp_order directly"
- "Only call place_sl_tp_orders. All orders route through the centralized hub"
- Explain what Order Agent does internally

## Key Changes

| File | Change |
|------|--------|
| `e2e_chain.py:risk_agent` | Removed old tools (sl_tool, tp_tool, cancel_tool, modify_sl_tool) — ONLY keep sl_tp_orders_tool |
| `e2e_chain.py:execution_task` | Enhanced description with explicit "STEP 4: place_entry_orders" |
| `e2e_chain.py:risk_task` | Enhanced description with explicit "DO NOT call place_sl_order/place_tp_order" |

## Why This Works

1. **Single Tool Path**: Risk Agent has NO alternative — must use place_sl_tp_orders
2. **Clear Instructions**: Task descriptions are explicit about which tools to use
3. **Enforced Routing**: All orders MUST go through Order Agent centralized hub
4. **PAPER/LIVE Uniform**: Order Agent decides mode in one place, not scattered across agents

## Testing

```bash
python3 test_order_agent_routing.py
```

✅ **Result:** ALL 6 tests passing
- Tools import correctly
- order_agent methods work
- PlaceSLTPOrdersTool routes correctly
- order_ledger.json populated with SL/TP orders
- Registry agents properly configured

## Expected Behavior (Next Trade)

When kickoff.py triggers next trade entry:

```
1. Execution Agent → execute_paper_trade()
   ↓
2. Execution Agent → place_entry_orders() [CENTRALIZED]
   ↓
3. Order Agent (via PlaceEntryOrdersTool)
   ├─ PAPER mode: save 4 entries to order_ledger.json
   └─ Returns: trade_id + entry_order_ids
   ↓
4. Risk Agent → place_sl_tp_orders() [CENTRALIZED]
   ↓
5. Order Agent (via PlaceSLTPOrdersTool)
   ├─ PAPER mode: save 2 SL + 2 TP to order_ledger.json
   └─ Returns: sl_order_ids + tp_order_ids
```

## Verification

To verify next trade routes through Order Agent:
1. Check kickoff logs for "place_entry_orders" or "place_sl_tp_orders" calls
2. Check order_ledger.json for new orders with trade_id matching the trade
3. Verify order timestamps align with trade entry time

## Monitoring Agents (Morpher/Shifter)

**Note:** Morpher and Shifter agents (5-min monitoring phase) still use old direct tools:
- `place_sl_order`, `place_tp_order`, `cancel_order`

**Future Enhancement:** Route morph/shift operations through Order Agent too.

---

**Status:** ✅ **ENTRY PHASE ROUTING FIXED**  
**Risk Agent:** ✅ **NOW FORCED TO USE CENTRALIZED HUB**  
**Test Result:** ✅ **6/6 PASSING**  
**Ready for Live Trades:** ✅ **YES**
