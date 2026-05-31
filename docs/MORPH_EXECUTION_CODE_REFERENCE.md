# Morph Execution — Code Reference

**File:** `brahmand/position_manager.py`
**Total:** 587 lines | **Morph code:** lines 220–229 (detection) + 386–560 (execution)

---

## Constants

```python
# position_manager.py:28
MAX_MORPHS = 3    # max morphs per day
MORPH = "MORPH"   # action type constant (line 36)

# Wing widths used during morph
WING_BUTTERFLY = 200   # used for BULLISH→NEUTRAL, BEARISH→NEUTRAL
WING_SPREAD = 200      # used for BULLISH↔BEARISH full rotations
SL_PCT = 0.50          # 50% above entry (line 17)
TP_PCT = 0.50          # 50% below entry (line 18)
```

---

## Detection — P3 Priority Check

**Lines 220–229** in `run()` — checks every 5-min cycle:

```python
# ── P3: Signal change → MORPH ──
current_pos = _classify_position(trade)          # PUT_SPREAD | CALL_SPREAD | IRON_BUTTERFLY
entry_signal = _load_entry_signal()              # reads /tmp/entry_check_latest.json

if entry_signal and trade.get("morph_count", 0) < MAX_MORPHS:
    new_signal = entry_signal["signal"]          # BULLISH | BEARISH | NEUTRAL
    if new_signal != current_pos:
        actions.append({
            "type": MORPH,
            "from_type": current_pos,
            "to_type": new_signal,
            "priority": 3,
            "reason": f"Signal changed {current_pos} → {new_signal}",
            "legs": trade.get("legs", []),
        })
```

**`_classify_position()`** maps leg composition to position type:
- CE legs only → `CALL_SPREAD`
- PE legs only → `PUT_SPREAD`
- Both CE + PE legs → `IRON_BUTTERFLY`

---

## Execution — All 6 Scenarios

**Lines 386–560** in `execute_action()`:

```
386: if action["type"] == MORPH:
387:     trade["morph_count"] += 1
```

### Scenario 1: BULLISH → NEUTRAL (Add CALL_SPREAD)
**Lines 393–417**

- State: PUT_SPREAD only (SELL PE + BUY PE)
- Action: Add SELL CE at ATM + BUY CE at ATM+200
- Sets `trade["sl"]["ce"]` and `trade["tp"]["ce"]`
- Result: IRON_BUTTERFLY (both sides protected)

### Scenario 2: BEARISH → NEUTRAL (Add PUT_SPREAD)
**Lines 420–444**

- State: CALL_SPREAD only (SELL CE + BUY CE)
- Action: Add SELL PE at ATM + BUY PE at ATM-200
- Sets `trade["sl"]["pe"]` and `trade["tp"]["pe"]`
- Result: IRON_BUTTERFLY (both sides protected)

### Scenario 3: NEUTRAL → BULLISH (Close CE, Keep PE)
**Lines 447–463**

- State: IRON_BUTTERFLY (CE + PE legs)
- Action: Book P&L on CE legs using LTP vs fill_price, remove CE legs
- Clear `trade["sl"]["ce"]` and `trade["tp"]["ce"]`
- Result: PUT_SPREAD (bullish exposure)

### Scenario 4: NEUTRAL → BEARISH (Close PE, Keep CE)
**Lines 466–481**

- State: IRON_BUTTERFLY (CE + PE legs)
- Action: Book P&L on PE legs using LTP vs fill_price, remove PE legs
- Clear `trade["sl"]["pe"]` and `trade["tp"]["pe"]`
- Result: CALL_SPREAD (bearish exposure)

### Scenario 5: BULLISH → BEARISH (Close PUT, Add CALL)
**Lines 484–520**

- State: PUT_SPREAD only
- Action: Book P&L on PE legs, remove them, then add CE spread
- New SELL CE at ATM + BUY CE at ATM+WING_SPREAD (200)
- Sets new CE SL/TP
- Result: CALL_SPREAD (180° rotation)

### Scenario 6: BEARISH → BULLISH (Close CALL, Add PUT)
**Lines 523–559**

- State: CALL_SPREAD only
- Action: Book P&L on CE legs, remove them, then add PE spread
- New SELL PE at ATM + BUY PE at ATM-WING_SPREAD (200)
- Sets new PE SL/TP
- Result: PUT_SPREAD (180° rotation)

---

## P&L Booking Logic

Every close-side scenario uses the same pattern:

```python
pnl = 0
for leg in legs_to_close:
    ltp = leg.get("ltp", leg.get("fill_price", 0))
    if leg["action"] == "SELL":
        pnl += leg["fill_price"] - ltp    # profit if price dropped
    else:
        pnl += ltp - leg["fill_price"]    # profit if price rose
trade["cumulative_pnl"] += pnl
```

LTP defaults to `fill_price` if not available (no mark-to-market change).

---

## Safety Limits

| Limit | Value | Enforcement |
|-------|-------|-------------|
| MAX_MORPHS/day | 3 | Checked at P3 detection (line 225) |
| morph_count | int | Incremented on every MORPH execution (line 387) |
| ATM extraction | `_get_atm_from_legs()` | Finds first SELL leg's strike (line 564) |

---

## P3.5: Adaptive Risk (Post-Morph SL/TP Adjustment)

**Lines 162–179** — runs after P3 MORPH, before P4 SL check:

```python
# ── P3.5: Pattern-based Adaptive Risk ──
_pattern_risk_adjust(trade)
```

`_pattern_risk_adjust()` (lines 52–90):
1. Queries live 6-TF pattern via `PatternAnalyzer.predict_live()`
2. Maps pattern confidence → SL/TP parameters:
   - BULLISH/BEARISH (conf ≥70%): `sl_pct=0.35`, `tsl_lock=0.7`
   - SIDEWAYS: `sl_pct=0.60`, `tsl_lock=0.4`
   - LOW confidence (<50%): `sl_pct=0.60`, `tsl_lock=0.3`, no change
3. Updates `trade["tsl_lock_ratio"]` and `trade["pattern_confidence"]` in-place

---

## State Diagram

```
                    ┌─────────────────────────┐
                    │     IRON_BUTTERFLY       │
                    │   CE legs + PE legs      │
                    │     (NEUTRAL)            │
                    └──────────┬──────────────┘
                     ▲    ▲    │    ▲    ▲
  Scenario 1:        │    │    │    │    │  Scenario 4:
  Add CE (393-417) ──┘    │    │    │    └── Close PE (466-481)
                           │    │    │
  Scenario 2:              │    │    │  Scenario 3:
  Add PE (420-444) ────────┘    │    └── Close CE (447-463)
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                 │
       ┌──────┴──────┐  ┌──────┴──────┐         │
       │ BUY + SELL  │  │ BUY + SELL  │         │
       │     PE      │  │     CE      │         │
       │ (PUT_SPREAD)│  │(CALL_SPREAD)│         │
       │  BULLISH    │  │  BEARISH    │         │
       └──────┬──────┘  └──────┬──────┘         │
              │                │                │
              │  Scenario 5:   │                │
              │  Close PE,     │  Scenario 6:   │
              │  Add CE        │  Close CE,     │
              └───────→   ←────┘  Add PE        │
                  (484-520)      (523-559)      │
```

---

## Verification

```bash
# Run position manager standalone with active trade
python3 position_manager.py

# Check morph count on active trade
python3 -c "
import json
s = json.load(open('/tmp/brahmand_kickoff.json'))
t = s.get('active_trade', {})
print(f'morph_count: {t.get(\"morph_count\", 0)}')
print(f'legs: {len(t.get(\"legs\", []))}')
"
```
