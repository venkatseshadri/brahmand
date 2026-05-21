# Unified Entry Check Architecture
**Date:** May 19 Evening → Implementation for May 20+

## The Problem (May 19)

Two independent systems making conflicting decisions:

```
Entry Check (Redis)              Regime Agent (LLM + DuckDB)
     ↓                                     ↓
BULLISH signal                    ADX 13.6 → SIDEWAYS
Suggests: SELL_PUT               Decides: IRON_BUTTERFLY
     ↓                                     ↓
     └──────────────── CONFLICT ──────────┘
          LLM wins, but signal mismatch
```

Result: Trade record has:
- `entry_scores.suggested_trade = "SELL_PUT"` ← Entry check said this
- `strategy_type = "IRON_BUTTERFLY"` ← But Regime Agent chose this

No accountability. No coherence.

---

## The Solution: Regime Agent Uses Entry Check as a Tool

**New Flow:**

```
┌──────────────────────────────────────────────────────────────┐
│ Regime Agent (LLM) Decision Process                          │
│                                                              │
│ STEP 1: Call query_entry_check tool (deterministic)         │
│  └─→ "BULLISH, confidence 75%, from Redis indicators"       │
│     └─→ Fallback chain if /tmp unavailable:                 │
│         1. Try /tmp/entry_check_latest.json                 │
│         2. Read from log file (safer, no lock issues)       │
│         3. Query DuckDB directly                            │
│                                                              │
│ STEP 2: Call query_market_data tool (DuckDB indicators)     │
│  └─→ "ADX 13.6, spot near EMA, ST bullish"                │
│                                                              │
│ STEP 3: LLM reasoning                                       │
│  "Entry check says BULLISH (ground truth).                 │
│   But DuckDB shows ADX 13.6 (weak trend) + LL structure.   │
│   Recommendation: SIDEWAYS regime, but honor entry_signal  │
│   for strategy selection (bullish bias)"                    │
│                                                              │
│ OUTPUT:                                                      │
│ {                                                            │
│   "regime": "sideways",                                      │
│   "confidence": 0.5,                                         │
│   "entry_signal": "BULLISH",  ← FROM entry_check tool      │
│   "recommendation": "caution"                                │
│ }                                                            │
└──────────────────────────────────────────────────────────────┘
        ↓
Strategy Agent receives:
  - regime: sideways
  - entry_signal: BULLISH ← GROUND TRUTH
  
Decision: "SIDEWAYS regime, but entry_signal BULLISH.
           Use BULL_PUT_SPREAD (trust entry signal) 
           with wider wings (acknowledge regime weakness)"
        ↓
COHERENT DECISION ✓
```

---

## Tool: EntryCheckTool (Fallback Chain)

**Location:** `/home/trading_ceo/brahmand/tools/entry_check_tool.py`

**Fallback Strategy:**

```python
def _run(index: str) -> dict:
    # Attempt 1: Read from /tmp (fastest, freshest)
    try:
        result = read_from_tmp_file()
        return {"signal": ..., "source": "tmp_file"}
    
    # Attempt 2: Read from log file (safer from lock issues)
    try:
        result = read_from_log_file()
        return {"signal": ..., "source": "log_file"}
    
    # Attempt 3: Query DuckDB directly (most robust)
    try:
        result = query_duckdb()
        return {"signal": ..., "source": "duckdb"}
    
    # All failed
    return {"error": "...", "signal": "NEUTRAL"}
```

**Why 3 Fallbacks?**

1. **`/tmp/entry_check_latest.json`**
   - Updated by v4 aggregator every 5 minutes
   - Freshest data
   - Risk: Race condition if v4 is writing while we read
   - Mitigation: Retry 3 times with delays

2. **Log file**
   - Append-only, safer from lock issues
   - Can read safely while datacapture writes
   - Format: Parse last line for signal + confidence
   - Slightly stale (depends on when v4 last ran)

3. **DuckDB**
   - Fallback if both above fail
   - Most robust (database transaction guarantees)
   - Slowest option
   - Uses ADX + ST logic to approximate entry_check

---

## Architecture Diagram (May 20+)

```
┌────────────────────────────────────────────────────────────┐
│ V3.1 Data Capture                                          │
│ • Reads Shoonya WebSocket                                  │
│ • Pushes 1-min bars to Redis + DuckDB every 60 sec         │
└───────────┬──────────────────────────────────────────────┘
            │
            ├──→ Redis v3_ohlcv_queue (15 indicators)
            │         ↓
            │    ┌─────────────────────────────────┐
            │    │ V4 Queue Aggregator             │
            │    │ • Aggregates to 6 TFs           │
            │    │ • Every 5 min: calls entry_check│
            │    │ • Updates /tmp/entry_check_latest│
            │    └────────────┬────────────────────┘
            │                 │
            ├──→ DuckDB                    ↓
            │    (varaha_data.duckdb)  /tmp/entry_check_latest.json
            │                          {
            │                            "signal": "BULLISH",
            │                            "timestamp": "2026-05-20T09:20:15"
            │                          }
            │                              ↓
            │                    ┌─────────────────────────────────┐
            │                    │ EntryCheckTool                  │
            │                    │ (Regime Agent's tool)           │
            │                    │                                 │
            │                    │ Reads /tmp file                 │
            │                    │ If fails: read log              │
            │                    │ If fails: query DuckDB          │
            │                    │ Returns: entry_signal           │
            │                    └────────────┬────────────────────┘
            │                                 │
            │                    ┌────────────↓────────────────────┐
            │                    │ Regime Agent (LLM)              │
            │                    │ • Call query_entry_check tool   │
            │                    │ • Call query_market_data tool   │
            │                    │ • Output: regime + entry_signal │
            │                    └────────────┬────────────────────┘
            │                                 │
            │                    ┌────────────↓────────────────────┐
            │                    │ Strategy Agent (LLM)            │
            │                    │ • Receive regime + entry_signal │
            │                    │ • entry_signal takes priority   │
            │                    │ • Output: strategy_type         │
            │                    └────────────┬────────────────────┘
            │                                 │
            └─────────────────────────────────┼──────────────────────
                                              │
                                    ┌─────────↓──────────┐
                                    │ Trade Execution    │
                                    │ (Contract Agent)   │
                                    │ (Execution Agent)  │
                                    │ (Risk Agent)       │
                                    └────────────────────┘
```

---

## Data Flow: Entry Signal Propagation

```
v3.1 (60 sec push)
  → Redis queue + DuckDB
  → v4 aggregator reads
  → v4 calls entry_check()
  → /tmp/entry_check_latest.json updated (timestamp T1)

Kickoff runs (5 min intervals)
  → (optional) kickoff reads /tmp if not using e2e_chain
  
E2E Chain runs (when regime agent executes)
  → Regime Agent calls query_entry_check tool
  → EntryCheckTool reads /tmp (or log, or DuckDB)
  → Returns entry_signal
  → Regime Agent outputs regime + entry_signal
  → Strategy Agent receives both
  → Strategy Agent prioritizes entry_signal for decision
  → Trade entered with coherent signal + regime info
```

---

## Trade JSON Output (May 20+)

```json
{
  "entry_time": "09:23",
  "entry_gate_signal": "BULLISH",
  "entry_scores": {
    "signal": "BULLISH",
    "confidence": 75,
    "timestamp": "2026-05-20T09:20:15.123456",
    "source": "tmp_file (Redis via v4)"
  },
  "regime_classification": {
    "regime": "sideways",
    "confidence": 0.5,
    "entry_signal": "BULLISH",
    "recommendation": "caution",
    "reason": "Entry check BULLISH, but ADX 13.6 shows weak trend..."
  },
  "strategy_type": "bull_put_spread",
  "reasoning": "entry_signal BULLISH takes priority, SELL_PUT chosen despite sideways regime",
  "monitored_since": "09:23"
}
```

---

## Verification for May 20

**Regime Agent Tool Access:**

```bash
# Check if tool is available
grep "query_entry_check" /home/trading_ceo/brahmand/config/agents_registry.yaml

# Verify tool can read all fallback sources
- [ ] /tmp/entry_check_latest.json (updated by v4)
- [ ] /home/trading_ceo/antariksh/logs/entry_check_YYYYMMDD.log
- [ ] DuckDB (varaha_data.duckdb)
```

**Log Verification:**

At first regime agent execution, logs should show:
```
[09:15:05] Regime Agent running...
[09:15:05]   Calling tool: query_entry_check
[09:15:06]   Tool returned: BULLISH (from tmp_file)
[09:15:07]   Calling tool: query_market_data
[09:15:08]   Regime classification: sideways, confidence 0.5, entry_signal BULLISH
```

---

## Benefits of Unified Architecture

✅ **Single Source of Truth:** entry_check signal is ground truth  
✅ **Coherent Decisions:** Regime + Strategy agree on entry_signal  
✅ **Audit Trail:** Trade records show why each decision was made  
✅ **Fault Tolerant:** 3-layer fallback ensures signal always available  
✅ **LLM Enhanced:** Regime Agent can add context without overriding signal  
✅ **No Conflicts:** Strategy Agent knows entry_signal is deterministic  

---

## May 19 vs May 20 Comparison

| Aspect | May 19 | May 20+ |
|--------|--------|---------|
| **Entry Signal Source** | Stale (May 18) | Fresh from v4 every 5 min |
| **Regime Classification** | Independent LLM call | LLM + entry_check tool |
| **Conflict Resolution** | LLM overrides gate | entry_signal takes priority |
| **Trade Record** | Confusing mismatch | Coherent decision chain |
| **Fallback** | None (stale data) | 3-layer fallback (tmp→log→DuckDB) |
| **Auditability** | Poor | Excellent |

---

**Ready for May 20 trading session with unified, coherent entry signals.**
