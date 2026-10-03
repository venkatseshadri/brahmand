---
name: order_ledger_execution_db_architecture
description: Complete architecture of order_ledger.json and trade_execution.duckdb
metadata:
  type: architecture
  date: 2026-05-23
---

# Order Ledger & Execution DB Architecture 📋

**Two persistent stores working together:**

```
order_ledger.json (JSON file)
  ├─ Quick local access
  ├─ Order-level tracking
  └─ Trade-level tracking

trade_execution.duckdb (DuckDB)
  ├─ Permanent audit trail
  ├─ Risk monitor reads from here
  └─ Analysis/backtest queries
```

---

## 1. order_ledger.json Structure

**Location:** `/home/trading_ceo/projects/brahmand/data/order_ledger.json`

**Purpose:** Track all orders and trades at the ledger level (PAPER mode execution)

**Structure:**

```json
{
  "orders": {
    "ORD-20260523-0001": {
      "order_id": "ORD-20260523-0001",
      "component": "execution_agent" | "risk_agent" | "morpher" | "shifter",
      "symbol": "NIFTY26MAY26C23500",
      "action_type": "SELL" | "BUY",
      "quantity": 65,
      "price": 125.50,
      "order_type": "ENTRY" | "SL" | "TP" | "MODIFY_SL" | "MODIFY_TP" | "SHIFT_CLOSE" | "SHIFT_OPEN",
      "trade_id": "TRD-20260523093012",
      "reason": "CE SELL @ 23500",
      "timestamp": "2026-05-23T09:30:12.123456",
      "status": "PLACED" | "FILLED" | "REJECTED" | "CANCELLED",
      "mode": "PAPER" | "LIVE",
      
      // PAPER mode only (filled immediately)
      "execution_time": "2026-05-23T09:30:12.123456",
      "execution_price": 125.50,
      
      // For MODIFY orders
      "modified_at": "2026-05-23T10:15:00",
      "modify_reason": "TSL adjustment"
    },
    "ORD-20260523-0002": {...}
  },
  
  "order_counter": 42,
  
  "_trades": {
    "TRD-20260523093012": {
      "trade_id": "TRD-20260523093012",
      "entry_time": "2026-05-23T09:30:12",
      "exit_time": null,
      "status": "ACTIVE" | "CLOSING" | "CLOSED",
      "strategy_type": "CALL_SPREAD" | "PUT_SPREAD" | "IRON_BUTTERFLY",
      "net_credit": 450.00,
      "legs": [
        {
          "tsym": "NIFTY26MAY26C23500",
          "action": "SELL",
          "strike": 23500,
          "type": "CE",
          "quantity": 65,
          "fill_price": 125.50
        },
        {
          "tsym": "NIFTY26MAY26C23700",
          "action": "BUY",
          "strike": 23700,
          "type": "CE",
          "quantity": 65,
          "fill_price": 45.25
        }
      ],
      "sl": {
        "call": 140,
        "put": 0
      },
      "tp": {
        "call": 225,
        "put": 0
      },
      "entry_gate_signal": "NOT_UP" | "NOT_DOWN",
      "entry_confidence": 68,
      "orders": ["ORD-20260523-0001", "ORD-20260523-0002", ...],
      "created_at": "2026-05-23T09:30:12",
      "updated_at": "2026-05-23T10:15:00"
    }
  }
}
```

**Key Points:**
- `orders` = Individual order records (entry, SL, TP, modifications, cancellations)
- `_trades` = Trade records (grouped orders with SL/TP)
- Each order links to its trade_id
- PAPER mode orders marked FILLED immediately
- LIVE mode orders track status (PENDING, FILLED, REJECTED)

---

## 2. trade_execution.duckdb Schema

**Location:** `/home/trading_ceo/projects/brahmand/data/trade_execution.duckdb`

**Purpose:** Permanent audit trail for risk monitor and analysis

**Tables:**

### Table: active_trades

```sql
CREATE TABLE active_trades (
    trade_id TEXT PRIMARY KEY,
    entry_time TIMESTAMP,
    strategy TEXT,              -- "CALL_SPREAD", "PUT_SPREAD", "IRON_BUTTERFLY"
    entry_gate_signal TEXT,     -- "NOT_UP", "NOT_DOWN"
    legs JSON,                  -- [{tsym, action, strike, type, fill_price}, ...]
    sl JSON,                    -- {call: 140, put: 80}
    tp JSON,                    -- {call: 225, put: 225}
    status TEXT,                -- "ACTIVE", "CLOSING", "CLOSED"
    created_at TIMESTAMP DEFAULT now()
)
```

**Use:** Risk monitor (risk_agent_crew.py) queries this to get active trades every minute

### Table: trade_history

```sql
CREATE TABLE trade_history (
    trade_id TEXT PRIMARY KEY,
    entry_time TIMESTAMP,
    close_time TIMESTAMP,
    strategy TEXT,
    close_reason TEXT,          -- "SL_HIT", "TP_HIT", "MORPH", "SHIFT", "TIME_EXIT", "MANUAL"
    entry_pnl FLOAT,            -- Premium collected at entry
    final_pnl FLOAT,            -- Actual P&L at exit
    duration_mins INTEGER,      -- How long trade was open
    legs JSON,
    created_at TIMESTAMP DEFAULT now()
)
```

**Use:** Postmortem analysis (correlate entry_gate_signal + strategy with outcomes)

### Table: monitoring_log

```sql
CREATE TABLE monitoring_log (
    id INTEGER PRIMARY KEY DEFAULT nextval('seq_monitoring'),
    trade_id TEXT,
    monitored_at TIMESTAMP,
    current_ltp JSON,           -- {call: 120, put: 85}
    current_pnl FLOAT,          -- P&L at this moment
    action_taken TEXT,          -- NULL | "SL_EXIT" | "TP_EXIT" | "MORPH" | "SHIFT"
    note TEXT,
    FOREIGN KEY (trade_id) REFERENCES active_trades(trade_id)
)
```

**Use:** Detailed audit trail of monitoring decisions (TSL, MORPH, SHIFT events)

---

## 3. Data Flow: Entry to Exit

```
ENTRY PHASE:
─────────────
execution_agent places entry orders
  ↓
order_agent.place_entry_orders(legs)
  ├─ Generate order_ids
  ├─ Write to order_ledger.json:
  │  └─ orders[order_id] = {order record}
  │
  └─ Return {trade_id, order_ids}
  
kickoff.py receives trade_id + order_ids
  ├─ Write to order_ledger.json:
  │  └─ _trades[trade_id] = {trade record with legs, sl, tp}
  │
  └─ Write to trade_execution.duckdb:
     └─ INSERT INTO active_trades (...)

risk_agent places SL/TP orders
  ↓
order_agent.place_sl_tp_orders(trade_id, legs)
  ├─ Generate SL/TP order_ids
  └─ Write to order_ledger.json:
     └─ orders[sl_order_id] = {SL order record}
        orders[tp_order_id] = {TP order record}

MONITORING PHASE (every 5 min):
─────────────────────────────────
monitor_trade() runs (in kickoff.py)
  ├─ Reads from order_ledger.json (active_trade state)
  ├─ Checks SL/TP triggers
  ├─ Adjusts TSL → updates order_ledger.json
  └─ If SL/TP HIT → exit_trade()

exit_trade() called
  ├─ Update order_ledger.json:
  │  └─ _trades[trade_id].status = "CLOSED"
  │
  └─ Update trade_execution.duckdb:
     ├─ UPDATE active_trades SET status = "CLOSED"
     └─ INSERT INTO trade_history (...)

POSTMORTEM PHASE (end of day):
──────────────────────────────
postmortem_agent queries duckdb:
  ├─ SELECT * FROM trade_history (today)
  ├─ JOIN with active_trades (for metadata)
  └─ Analyze outcomes vs entry signals
```

---

## 4. Who Reads What

| Component | Reads From | Writes To | When |
|-----------|-----------|-----------|------|
| **kickoff.py** | - | order_ledger.json, duckdb | Entry, exit |
| **order_agent** | order_ledger.json | order_ledger.json | Every order |
| **risk_agent** (entry) | - | order_ledger.json | Place SL/TP |
| **risk_agent_crew** | duckdb (active_trades) | duckdb (trade_history) | Monitoring, exit |
| **monitor_trade** | order_ledger.json | order_ledger.json | TSL updates |
| **morpher** | order_ledger.json | order_ledger.json | MORPH actions |
| **shifter** | order_ledger.json | order_ledger.json | SHIFT actions |
| **postmortem_agent** | duckdb (all tables) | - | End of day analysis |

---

## 5. Current State Issues

### ✅ Works Correctly
- **order_ledger.json** tracks all orders and trades
- **trade_execution.duckdb** has active_trades table (written by kickoff.py)
- **order_agent.place_entry_orders()** returns trade_id
- **order_agent.place_sl_tp_orders()** writes SL/TP orders to ledger
- **risk_agent_crew** reads from duckdb to get active trades

### ⚠️ Potential Gaps
1. **order_agent.place_entry_orders()** doesn't call add_active_trade()
   - kickoff.py calls it separately
   - Should be atomic: order placement + duckdb write together

2. **order_agent.place_sl_tp_orders()** doesn't write to duckdb
   - Only writes to order_ledger.json
   - Risk monitor needs to know SL/TP orders were placed

3. **Synchronization**
   - order_ledger.json and duckdb could diverge
   - No reconciliation mechanism

---

## 6. Recommended Improvements

### Move Writes Inside order_agent

Instead of:
```python
# kickoff.py
entry_result = execution_agent.execute(...)
add_active_trade(...)  # separate write
```

Do:
```python
# order_agent.place_entry_orders()
order_ids = place_orders(legs)
add_active_trade(trade_id, legs, sl, tp)  # atomic
return {trade_id, order_ids}
```

### Also Log SL/TP Placement to duckdb

```python
# order_agent.place_sl_tp_orders()
sl_order_ids = place_orders(sl_legs)
tp_order_ids = place_orders(tp_legs)

# Update duckdb to note SL/TP are placed
con.execute("UPDATE active_trades SET status='SL_TP_PLACED' WHERE trade_id=?", [trade_id])

return {trade_id, sl_order_ids, tp_order_ids}
```

### Reconciliation Check

On risk_agent startup, verify:
```python
active_in_duckdb = get_active_trades()
active_in_ledger = get_active_trades_from_ledger()

# Alert if mismatch
missing_in_ledger = active_in_duckdb - active_in_ledger
extra_in_ledger = active_in_ledger - active_in_duckdb
```

---

## Summary

| System | Purpose | Scope |
|--------|---------|-------|
| **order_ledger.json** | Hot cache for active trades | Order-level detail, real-time updates |
| **trade_execution.duckdb** | Permanent audit trail | Trade-level summary, historical analysis |

**Key:** Both should be written to **atomically** by order_agent, not split across multiple callers.

---

**Status:** Architecture is sound. Implementation has minor gaps (atomic writes, reconciliation).
