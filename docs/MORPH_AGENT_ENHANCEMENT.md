# Morph Agent — SMC / Greeks / IV Enhancement

## Current Morph Triggers (Signal-Based, Reactive)

The morph agent currently waits for the entry check to signal a direction change:

```
Trend + TL signal flips BULLISH → BEARISH
                      ↓
         Morph agent: "Close bullish leg, add bearish spread"
```

**Problem:** This is **reactive**. The signal flip happens AFTER the move is underway. Price already moved 50-80 pts before the morph catches it.

## New Morph Triggers (Level-Based, Pre-Emptive)

Feed SMC/Greeks/IV/Price Location data to the morph agent so it can act **before** the signal flips:

| # | New Trigger | Pre-Emptive Action | Confidence |
|---|-------------|-------------------|------------|
| 1 | Price within 15pts of pivot_r1 or cluster_res (bearish trade) | Close bearish leg, keep bullish → BULLISH | HIGH |
| 2 | Price within 15pts of pivot_s1 or cluster_sup (bullish trade) | Close bullish leg, keep bearish → BEARISH | HIGH |
| 3 | SMC structure_confirmed flips opposite | Close conflicted leg | HIGH |
| 4 | PCR crosses back inside 0.85-1.15 | Morph conflicted leg (sentiment neutralizing) | MEDIUM |
| 5 | VIX spike > 25 on bearish trade | HOLD (vol supports trend) — don't morph | MEDIUM (block trigger) |
| 6 | IV rank drops below 20 | Close both legs (premium dead) → EXIT | HIGH |
| 7 | Price fills FVG (fair value gap) | Close leg near fill zone | MEDIUM |
| 8 | Liquidity swept at target level | Book the leg that reached target | HIGH |
| 9 | Max pain within 30pts | Magnet pulling → morph toward max_pain direction | LOW |
| 10 | ADX drops from >30 to <25 | Trend weakening → close directional leg | MEDIUM |

---

## Architecture

```
Every 1-min candle during active trade:
                                          
  DuckDB latest candle                     EntryCheck tool (latest signal)
  ┌─────────────┐                          ┌──────────────┐
  │ SMC zones   │                          │ Trend signal │
  │ Pivots/Fibs  │                          │ TL signal    │
  │ IV rank      │                          │ Feedback     │
  │ Greeks       │                          │ Direction    │
  │ PCR          │                          └──────┬───────┘
  └──────┬──────┘                                  │
         │                                         │
         ▼                                         ▼
  ┌──────────────────────────────────────────────────┐
  │            MorphAgent.monitor()                  │
  │                                                  │
  │  1. Check distance to S/R zones vs position      │
  │  2. Check IV rank / Greeks / PCR for shifts      │
  │  3. Check entry signal for official flip         │
  │                                                  │
  │  MERGE: if both level-triggered + signal-triggered│
  │         agree → execute morph immediately        │
  │         level-triggered only → caution morph (50%)│
  │         signal-triggered only → normal morph     │
  │         disagree → HOLD                          │
  └───────────────────┬──────────────────────────────┘
                      │
                      ▼
          MORPH / SHIFT / EXIT / HOLD
```

---

## Iron Butterfly Morph Logic (User's Clarification)

Starting from an IRON_BUTTERFLY (both call spread + put spread):

```
If BULLISH probability rises:
  ├─ Close CALL spread (bearish leg)        ← strip downside protection
  └─ Keep PUT spread (bullish leg)           ← ride the bull move
  → Effectively becomes a single PUT spread

If BEARISH probability rises:
  ├─ Close PUT spread (bullish leg)         ← strip upside protection
  └─ Keep CALL spread (bearish leg)          ← ride the bear move
  → Effectively becomes a single CALL spread
```

## Trigger-to-Morph Mapping

### From NEUTRAL (Iron Butterfly):

| Trigger | Leg to Close | Resulting Position |
|---------|-------------|--------------------|
| Signal flips BULLISH + near support | CALL spread | PUT spread only |
| Signal flips BEARISH + near resistance | PUT spread | CALL spread only |
| VIX spike > 25 | PUT spread (fear = down) | CALL spread |
| IV rank collapse | BOTH | EXIT |

### From BULLISH (PUT spread only):

| Trigger | Action | Reason |
|---------|--------|--------|
| Price at resistance (pivot_r1, cluster_res) | Close 50% PUT, morph → NEUTRAL | "Bulls running out of room" |
| SMC structure break BEARISH | Close PUT, morph → NEUTRAL or BEARISH | Structure reversed |
| PCR > 1.15 (extreme bearish) | Morph → NEUTRAL | Sentiment says down |
| ADX < 25 (weakening trend) | Close 50% PUT | Trend fading |
| VIX spike > 25 | HOLD (keep PUT) | Fear = bears, but vol premium is good |

### From BEARISH (CALL spread only):

| Trigger | Action | Reason |
|---------|--------|--------|
| Price at support (pivot_s1, cluster_sup) | Close 50% CALL, morph → NEUTRAL | "Bears running out of room" |
| SMC structure break BULLISH | Close CALL, morph → NEUTRAL or BULLISH | Structure reversed |
| PCR < 0.85 (extreme bullish) | Morph → NEUTRAL | Sentiment says up |
| ADX < 25 (weakening trend) | Close 50% CALL | Trend fading |
| VIX spike > 25 | HOLD (keep CALL) | Fear supports bearish |

---

## Integration Points

### 1. Add to MorphCheckTool (`monitor_tools.py`)

Add a new method `check_for_level_morph()` that reads DuckDB SMC/Greeks/IV data:

```python
def check_for_level_morph(self, position_type, morph_count, candle_data):
    """
    Pre-emptive morph check based on price location vs SMC/IV/Greeks.
    Returns action BEFORE waiting for signal flip.
    """
    actions = []
    
    # Check distance to nearest resistance
    distance_to_res = candle_data.get("distance_to_resistance")
    distance_to_sup = candle_data.get("distance_to_support")
    
    if position_type == "BEARISH" and distance_to_res and distance_to_res < 15:
        actions.append({"type": "MORPH", "from": "BEARISH", "to": "NEUTRAL", 
                        "reason": "Zone: at resistance", "confidence": "HIGH"})
    
    if position_type == "BULLISH" and distance_to_sup and distance_to_sup < 15:
        actions.append({"type": "MORPH", "from": "BULLISH", "to": "NEUTRAL",
                        "reason": "Zone: at support", "confidence": "HIGH"})
    
    # IV rank collapse
    iv_rank = candle_data.get("iv_rank", 50)
    if iv_rank < 20:
        actions.append({"type": "EXIT", "reason": "IV rank < 20: dead premium",
                        "confidence": "HIGH"})
    
    # SMC structure break
    structure = candle_data.get("structure_type", "")
    if position_type == "BEARISH" and structure == "BULLISH":
        actions.append({"type": "MORPH", "from": "BEARISH", "to": "NEUTRAL",
                        "reason": "SMC structure flipped bullish", "confidence": "HIGH"})
    
    return actions
```

### 2. Add to `risk_agent_crew.py` Morpher Agent

Add a `check_levels` tool to the Morpher Agent's toolkit so the LLM can query:
- Distance to nearest S/R zone
- IV rank / IV regime
- Structure type / swing points
- PCR value vs thresholds

### 3. Fallback path (`position_manager.py` P3)

Add level-based morph checks to the deterministic fallback in `position_manager.py`.

---

## Priority Order for Morph Triggers

When multiple triggers fire simultaneously:

| Priority | Trigger | Action |
|----------|---------|--------|
| 1 | SMC structure break (confirmed) | EXIT conflicted leg |
| 2 | IV rank < 20 | EXIT both (no premium) |
| 3 | Price within 15pts of strong zone | MORPH 50% of leg |
| 4 | Signal flip (existing trigger) | MORPH (as today) |
| 5 | PCR extreme reversal | MORPH conflicted |
| 6 | ADX weakening | REDUCE size |

---

## Implementation Plan

1. **Add PriceLocationScorer** → computes distance-to-zone for entry check + morph agent
2. **Add `check_for_level_morph()`** → monitor_tools.py
3. **Add level-query tools** → risk_agent_crew.py Morpher Agent toolkit
4. **Integrate into kickoff.py** → pass DuckDB candle data to morph check
5. **Add to position_manager.py fallback** → deterministic path
6. **Unit tests** → verify each trigger fires correctly
