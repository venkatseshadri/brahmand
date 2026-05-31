---
name: monitoring_phase_logging
description: Comprehensive monitoring phase logging for TSL, MORPH, and SHIFT events
metadata:
  type: feature
  date: 2026-05-23
  status: implemented
---

# Monitoring Phase Logging — Complete Audit Trail ✅

**Date:** May 23, 2026  
**Status:** 🟢 **IMPLEMENTED**  
**Files Modified:** `/home/trading_ceo/brahmand/kickoff.py`

---

## What Was Added

### 1. Structured Event Logging
- **JSONL format** for easy parsing and analysis
- **File:** `logs/monitoring_events_YYYYMMDD.jsonl` (one per trading day)
- **Function:** `_log_monitoring_event(event_type, trade_id, **details)`

Every event is captured with timestamp, type, trade_id, and event-specific details.

### 2. Monitoring Cycle Structure
Each trade monitoring run captures:

```
[MONITOR-CYCLE-START] TRD-001 | IRON_FLY | 5min | 09:35:00
  → MONITOR_CYCLE_START event logged
  → Pre-morph state captured (signal, position_type, morph_count)

  Price snapshot: NIFTY23500CE=125.50 | NIFTY23450PE=45.25 | ...
  Profit snapshot: +250.00 (Open: 5min)
  → CYCLE_SNAPSHOT event with all leg prices and profit

  [TSL adjustments if applicable]
  → TSL_ADJUSTMENT events (leg, old_sl, new_sl, profit info)

  [SL/TP checks]
  → If triggered: SL_HIT or TP_HIT event (with profit captured)

  [MORPH/SHIFT evaluation]
  → PRE_MORPH_STATE event
  → MORPH_DECISION event (action taken, raw output, parsed output)
  → SHIFT_DECISION event (action taken, raw output, parsed output)
  → SIGNAL_CHANGE event (if signal reverses post-morph)

[MONITOR-CYCLE-END] TRD-001 | Duration: 5min | 09:35:15
  → MONITOR_CYCLE_END event logged
```

### 3. Event Types Captured

| Event Type | Purpose | Details |
|-----------|---------|---------|
| `MONITOR_CYCLE_START` | Entry to monitoring cycle | strategy, mins_open, current_signal |
| `MONITOR_CYCLE_END` | Exit from monitoring cycle | cycle_duration |
| `CYCLE_SNAPSHOT` | Leg prices and P&L | legs[], total_profit, minutes_open |
| `TSL_ADJUSTMENT` | SL ratchet | leg, old_sl, new_sl, shift_pct, ltp, profit, lock_ratio |
| `SL_HIT` | Stop loss triggered | leg_type, ltp, sl, profit |
| `TP_HIT` | Take profit triggered | leg_type, ltp, tp, profit |
| `PRE_MORPH_STATE` | State before morph check | signal, position_type, morph_count |
| `MORPH_DECISION` | Morpher agent output | action_taken, raw_output, parsed_output |
| `SHIFT_DECISION` | Shifter agent output | action_taken, raw_output, parsed_output |
| `SIGNAL_CHANGE` | Signal reversal detected | pre_signal, post_signal |
| `LLM_UNAVAILABLE` | DeepSeek API down | (none) |
| `MONITORING_CREW_ERROR` | Crew execution failed | error message |
| `TIME_EXIT` | 45-min auto-exit | minutes_open |

### 4. Console Log Enhancements

Readable text logs (kickoff_YYYYMMDD.log):

```
[MONITOR-CYCLE] TRD-LIVE-001 | IRON_FLY | 5min | 09:35:00
  Price snapshot: NIFTY23500CE=125.50 | NIFTY23450PE=45.25
  Profit snapshot: +250.00 (Open: 5min)
  TSL: CALL SL ratcheted 125.00 → 124.50 (2.5% favorable) [LTP=123.50]
  Checking MORPH/SHIFT eligibility...
  [MORPHER] ○ NO-ACTION | {"decision": "signal stable", "morphs_today": 1}
  [SHIFTER] ✓ ACTION | {"action": "HEDGE_SHIFT", "decay_pct": 65.5}
  ⏰ Auto-exit after 45 min
[MONITOR-CYCLE-END] TRD-LIVE-001 | Duration: 5min | 09:35:15
```

---

## How to Use These Logs

### View Structured Events (JSONL)
```bash
# All events for a trade
jq 'select(.trade_id == "TRD-LIVE-001")' logs/monitoring_events_20260523.jsonl

# All TSL adjustments
jq 'select(.event_type == "TSL_ADJUSTMENT")' logs/monitoring_events_20260523.jsonl | head -5

# All MORPH decisions
jq 'select(.event_type == "MORPH_DECISION") | {timestamp, action_taken, raw_output}' logs/monitoring_events_20260523.jsonl
```

### View Text Logs (Readable)
```bash
# Real-time tail
tail -f logs/kickoff_20260523.log | grep MONITOR

# Find a specific trade
grep "TRD-LIVE-001" logs/kickoff_20260523.log

# Extract all SL/TP hits
grep -E "SL HIT|TP HIT" logs/kickoff_20260523.log
```

### Python Analysis
```python
import json
from pathlib import Path

events_file = Path("logs/monitoring_events_20260523.jsonl")
events = [json.loads(line) for line in events_file.read_text().strip().split('\n') if line]

# Filter by trade
trade_events = [e for e in events if e['trade_id'] == 'TRD-LIVE-001']

# Reconstruct monitoring timeline
for e in sorted(trade_events, key=lambda x: x['timestamp']):
    print(f"{e['timestamp']} [{e['event_type']}] {e}")

# TSL history
tsl_adjustments = [e for e in events if e['event_type'] == 'TSL_ADJUSTMENT']
print(f"Total TSL adjustments: {len(tsl_adjustments)}")
print(f"Total SL shift: {sum(e['shift_pct'] for e in tsl_adjustments):.1f}%")

# Morph effectiveness
morph_events = [e for e in events if e['event_type'] == 'MORPH_DECISION']
morphs_executed = sum(1 for e in morph_events if e.get('action_taken'))
print(f"Morph executions: {morphs_executed}/{len(morph_events)}")
```

---

## Benefits

✅ **Complete audit trail** — Every decision is timestamped and logged  
✅ **Debugging** — Can see exactly why TSL changed, MORPH/SHIFT decided  
✅ **Performance analysis** — Track which strategies morph/shift most  
✅ **RL feedback** — Use event history to optimize weights  
✅ **Compliance** — All trades have decision records  
✅ **Separated concerns** — Structured events (JSONL) + readable logs (text)

---

## What Now Works

### Before (Blind Monitoring Phase):
```
Monitoring runs → SL/TP checked → MORPH/SHIFT evaluated → (no visibility)
Exit happened → "Why did it exit?" → Unclear
TSL changed → No record of which leg or by how much
```

### After (Observable Monitoring Phase):
```
Monitoring runs → [MONITOR-CYCLE-START logged]
  → Leg prices/profit snapshot [CYCLE_SNAPSHOT]
  → TSL evaluated → [TSL_ADJUSTMENT if ratcheted]
  → SL/TP checked → [SL_HIT / TP_HIT if triggered]
  → MORPH checked → [PRE_MORPH_STATE + MORPH_DECISION]
  → SHIFT checked → [SHIFT_DECISION]
  → [MONITOR-CYCLE-END logged]
  → Events written to JSONL + text log
```

**Full audit trail** — Can replay exactly what happened in every 5-minute monitoring cycle.

---

## Files Modified

| File | Changes | Lines |
|------|---------|-------|
| `brahmand/kickoff.py` | Added monitoring event logging, enhanced console logs, structured events | +80 |

---

## Testing

Run a live cycle and check outputs:

```bash
# Real-time monitoring
tail -f /home/trading_ceo/brahmand/logs/kickoff_$(date +%Y%m%d).log | grep MONITOR

# Structured events
jq '.' /home/trading_ceo/brahmand/logs/monitoring_events_$(date +%Y%m%d).jsonl | head -50
```

On next market open (May 27 if holiday), you'll see:
- Console logs with readable monitoring cycle output
- JSONL file with structured events for analysis
- Complete TSL, MORPH, SHIFT history

---

## Next Steps

1. ✅ Deploy logging to production (kickoff.py)
2. ⏳ Run one full trading day (May 27+) to collect events
3. ⏳ Analyze: Which SL shifts are most effective? When do morphs trigger?
4. ⏳ Feedback loop: Use event history to adjust TSL/MORPH/SHIFT weights

---

**Status: 🟢 READY FOR PRODUCTION**

Next monitoring cycle will have full audit trail.
