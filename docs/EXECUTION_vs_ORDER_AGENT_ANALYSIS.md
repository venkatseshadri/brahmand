---
name: execution_order_agent_analysis
description: Analysis of execution_agent vs order_agent and their actual usage
metadata:
  type: analysis
  date: 2026-05-23
---

# Execution Agent vs Order Agent — Architecture Analysis 🔍

**Problem:** Two agents seem to do the same thing. Unclear which one is actually used.  
**Finding:** One is used, one is dead code.

---

## The Two Agents

### 1️⃣ execution_agent (USED ✓)

**File:** `/home/trading_ceo/brahmand/e2e_chain.py:173-183`

```python
execution_agent = af.create_agent(
    "execution_agent",
    variables={
        "market_type": "NIFTY",
        "strategy_type": "deterministic",
        "ticker": "NIFTY",
        "mock_mode": "paper",
    },
    tools=[execution_tool, entry_orders_tool],  # ← These are the tools
)
```

**Task:** Task 5 in the crew (line 301-328)

**Purpose:** Build the trade dict and route entry orders  
**Tools:**
- `execution_tool` (ExecutePaperTradeTool) — builds trade dict
- `entry_orders_tool` (PlaceEntryOrdersTool) — calls order_agent.place_entry_orders()

**Execution Flow:**
```
execution_agent (Task 5)
  ↓
  execution_tool → execute_paper_trade() → builds trade dict
  ↓
  entry_orders_tool → place_entry_orders() → calls order_agent.place_entry_orders()
  ↓
  Returns: {trade_id, entry_orders, status, mode}
```

**Actual Code Flow:**
```python
execution_task = Task(
    description="Build trade and route entry orders...",
    agent=execution_agent,  # ← Used here
)
```

✅ **Used in crew as Task 5**

---

### 2️⃣ order_agent (NOT USED ✗ — DEAD CODE)

**File:** `/home/trading_ceo/brahmand/e2e_chain.py:192-198`

```python
order_agent = af.create_agent(
    "order_agent",
    variables={"market_type": "NIFTY", "ticker": "NIFTY"},
    tools=[entry_orders_tool, sl_tp_orders_tool],
)
```

**Task:** NONE

**Purpose:** ??? (unclear)  
**Tools:** `[entry_orders_tool, sl_tp_orders_tool]`

**Status:** Created but never referenced in any Task

❌ **NOT used in crew. Dead code.**

---

## The Tools (THESE ARE USED)

### PlaceEntryOrdersTool

**What it does:** Routes entry orders through order_agent module  
**Code:**
```python
class PlaceEntryOrdersTool(BaseTool):
    def _run(self, legs: list = None) -> str:
        from order_agent import place_entry_orders  # ← Calls the MODULE function
        result = place_entry_orders(legs)
        return json.dumps(result)
```

**Used by:**
- execution_agent (Task 5)
- risk_agent (via task context)

### PlaceSLTPOrdersTool

**What it does:** Routes SL/TP orders through order_agent module  
**Code:**
```python
class PlaceSLTPOrdersTool(BaseTool):
    def _run(self, trade_id: str, legs: list = None) -> str:
        from order_agent import place_sl_tp_orders  # ← Calls the MODULE function
        result = place_sl_tp_orders(trade_id, legs)
        return json.dumps(result)
```

**Used by:**
- risk_agent (Task 6)

---

## The Architecture (Current vs Correct)

### Current (CONFUSING)
```
CrewAI Agents:
  ├─ execution_agent (USED) → uses entry_orders_tool → calls order_agent module
  ├─ risk_agent (USED) → uses sl_tp_orders_tool → calls order_agent module
  └─ order_agent (NOT USED) ✗ — dead code

order_agent module (USED) ✓
  ├─ place_entry_orders(legs)
  ├─ place_sl_tp_orders(trade_id, legs)
  └─ other functions
```

### Should Be (CLEAN)
```
CrewAI Agents:
  ├─ execution_agent (USED) → uses entry_orders_tool
  └─ risk_agent (USED) → uses sl_tp_orders_tool

Tools:
  ├─ entry_orders_tool → order_agent.place_entry_orders()
  └─ sl_tp_orders_tool → order_agent.place_sl_tp_orders()

order_agent module (USED) ✓
  ├─ place_entry_orders(legs) — core business logic
  └─ place_sl_tp_orders(trade_id, legs) — core business logic
```

---

## What's Actually Happening

### Execution Flow (Real)

```
ENTRY PHASE:
┌─────────────────────────────────────┐
│ execution_agent Task (LLM)          │
│  - Builds trade dict               │
│  - Calls place_entry_orders_tool   │
└─────────────────────────────────────┘
         ↓
┌─────────────────────────────────────┐
│ PlaceEntryOrdersTool (Python)       │
│  - Parses legs from trade dict      │
│  - Calls order_agent.place_entry... │
└─────────────────────────────────────┘
         ↓
┌─────────────────────────────────────┐
│ order_agent.place_entry_orders()    │
│  - Paper: saves to order_ledger.json│
│  - Live: calls Shoonya API          │
│  - Returns: {trade_id, order_ids}   │
└─────────────────────────────────────┘

RISK PHASE:
┌─────────────────────────────────────┐
│ risk_agent Task (LLM)               │
│  - Calls place_sl_tp_orders_tool    │
└─────────────────────────────────────┘
         ↓
┌─────────────────────────────────────┐
│ PlaceSLTPOrdersTool (Python)        │
│  - Parses trade_id + legs           │
│  - Calls order_agent.place_sl_tp... │
└─────────────────────────────────────┘
         ↓
┌─────────────────────────────────────┐
│ order_agent.place_sl_tp_orders()    │
│  - Paper: saves to order_ledger.json│
│  - Live: calls Shoonya API          │
│  - Returns: {trade_id, sl_ids, tp_id}
└─────────────────────────────────────┘
```

**The order_agent CrewAI agent NEVER APPEARS in this flow.**

---

## Recommendation

### Remove Dead Code ✂️

**File:** `/home/trading_ceo/brahmand/e2e_chain.py`

**Delete lines 192-198:**
```python
# Order Agent (routes orders through centralized hub)
order_agent = af.create_agent(
    "order_agent",
    variables={"market_type": "NIFTY", "ticker": "NIFTY"},
    tools=[entry_orders_tool, sl_tp_orders_tool],
)
order_agent.llm = llm
```

**Why:**
- Never used in any Task
- Confuses the architecture
- Code already works without it
- The order_agent MODULE functions are called via tools (correct approach)

### Keep These ✓

**order_agent module** (`/home/trading_ceo/brahmand/order_agent.py`)
- Contains actual order routing logic
- Used by PlaceEntryOrdersTool and PlaceSLTPOrdersTool
- Central hub for paper/live switching

**PlaceEntryOrdersTool and PlaceSLTPOrdersTool**
- Correct abstraction layer
- Agents don't know about order routing details
- Tools handle the logistics

---

## Summary Table

| Component | Used? | Purpose | Location |
|-----------|-------|---------|----------|
| execution_agent (CrewAI) | ✓ | Build trade + route entry | e2e_chain.py:173 |
| order_agent (CrewAI) | ✗ | None | e2e_chain.py:192 |
| PlaceEntryOrdersTool | ✓ | Route entry orders | chain_tools.py |
| PlaceSLTPOrdersTool | ✓ | Route SL/TP orders | chain_tools.py |
| order_agent (module) | ✓ | Core order routing | order_agent.py |

**Action:** Remove the unused CrewAI agent to clean up architecture.

---

**Status: 🔴 DEAD CODE IDENTIFIED**

The order_agent CrewAI agent should be removed. The order_agent module functions are called correctly via tools.
