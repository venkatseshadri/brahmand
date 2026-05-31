# Traffic Light System: 6 TF Colors + 7th Parameter (Gap)

## Overview

Entry check now scores market signals using:
1. **6 TF Candle Colors** (5m, 15m, 30m, 60m, 240m, 1440m) → Pattern detection
2. **Gap Direction** (7th parameter) → Separate weight with alignment/conflict logic

---

## Gap Parameter Details

**Source:** Redis previous day's close vs today's market open

```json
{
  "direction": "GREEN|RED|FLAT|unknown",
  "today_open": 23750.00,
  "prev_close": 23700.00,
  "gap_size_points": 50.00,
  "gap_size_pct": 0.216
}
```

---

## Gap Weighting Logic

**Gap Weight:** Configurable in `entry_weights.json` under `traffic_light.gap_weight` (default: 0.2 = 20%)

### Score Adjustment Rules

| Pattern Type | Gap Direction | Score Boost | Confidence Adjust | Reasoning |
|-------------|---------------|-------------|-------------------|-----------|
| **Bullish** (green_c ≥ 4) | GREEN ↑ | +0.4 × gap_weight | +15% | Strong continuation |
| **Bullish** (green_c ≥ 4) | RED ↓ | +0.3 × gap_weight | +10% | Recovery play |
| **Bearish** (red_c ≥ 4) | RED ↓ | -0.4 × gap_weight | +15% | Strong continuation |
| **Bearish** (red_c ≥ 4) | GREEN ↑ | -0.3 × gap_weight | -20% | Conflict, bearish stronger |
| **Neutral** (mixed) | Any | No gap boost | 0 | Insufficient pattern |

---

## Example Scenarios at 9:16 (First Minute)

### Scenario 1: Gap Up + All GREEN (6/6)

```
Pattern: STRONG_BULL_CONTINUATION (score: 9, conf: 90%)
Gap: GREEN (open 23750 > prev_close 23700)

Calculation:
  base_score = 9
  gap_boost = 0.4 × 0.2 = 0.08
  final_score = 9.08
  
  base_conf = 90%
  gap_conf_adjust = +15%
  final_conf = min(100, 90 + 15) = 100%

Output: BULLISH, score 9.08, confidence 100%
Interpretation: "Gapped up yesterday's close and all timeframes are bullish. Very strong entry."
```

### Scenario 2: Gap Up + All RED (6/6)

```
Pattern: STRONG_BEAR_CONTINUATION (score: -9, conf: 90%)
Gap: GREEN (open 23750 > prev_close 23700)

Calculation:
  base_score = -9
  gap_boost = -0.3 × 0.2 = -0.06  (conflict penalty)
  final_score = -9.06
  
  base_conf = 90%
  gap_conf_adjust = -20%  (bearish overrides gap)
  final_conf = max(5, 90 - 20) = 70%

Output: BEARISH, score -9.06, confidence 70%
Interpretation: "Failed gap up, market immediately sold off. Bearish dominates."
```

### Scenario 3: Gap Down + All GREEN (6/6)

```
Pattern: STRONG_BULL_CONTINUATION (score: 9, conf: 90%)
Gap: RED (open 23650 < prev_close 23700)

Calculation:
  base_score = 9
  gap_boost = 0.3 × 0.2 = 0.06  (recovery boost)
  final_score = 9.06
  
  base_conf = 90%
  gap_conf_adjust = +10%  (bullish recovery is positive)
  final_conf = min(100, 90 + 10) = 100%

Output: BULLISH, score 9.06, confidence 100%
Interpretation: "Gapped down but recovered strongly. Bullish resilience confirmed."
```

### Scenario 4: Gap Down + All RED (6/6)

```
Pattern: STRONG_BEAR_CONTINUATION (score: -9, conf: 90%)
Gap: RED (open 23650 < prev_close 23700)

Calculation:
  base_score = -9
  gap_boost = -0.4 × 0.2 = -0.08
  final_score = -9.08
  
  base_conf = 90%
  gap_conf_adjust = +15%  (gap + pattern alignment)
  final_conf = min(100, 90 + 15) = 100%

Output: BEARISH, score -9.08, confidence 100%
Interpretation: "Gapped down and stayed down. Very strong bearish entry."
```

---

## Configuration in entry_weights.json

```json
{
  "traffic_light": {
    "gap_weight": 0.2,
    "gap_rules": {
      "gap_up_bullish_pattern": {
        "score_boost": 0.4,
        "confidence_adjust": 15,
        "note": "Gap up + bullish = strong continuation"
      },
      "gap_up_bearish_pattern": {
        "score_penalty": -0.3,
        "confidence_adjust": -20,
        "note": "Gap up + bearish = conflict, bearish wins"
      },
      "gap_down_bearish_pattern": {
        "score_boost": -0.4,
        "confidence_adjust": 15,
        "note": "Gap down + bearish = strong continuation"
      },
      "gap_down_bullish_pattern": {
        "score_boost": 0.3,
        "confidence_adjust": 10,
        "note": "Gap down + bullish = recovery play"
      }
    }
  }
}
```

**Tunable Parameters:**
- `gap_weight`: How much gap affects score (0.0-1.0, default 0.2)
- Each gap_rule's `score_boost` and `confidence_adjust` can be adjusted by RL post-session

---

## Data Flow: Gap Capture

```
v3.1 Data Capture (9:15 market open)
  ↓
  Reads: previous day's close from DuckDB
  Reads: first 1m bar (today's open)
  Stores in Redis: prev_close_NIFTY (key)
  
Entry Check (every 5 min via v4)
  ↓
  score_traffic_light_redis()
    ↓
    _get_gap_from_redis()
      ↓
      Reads: prev_close_NIFTY from Redis
      Reads: latest_1m.open from Redis
      Calculates: gap_direction, gap_size, gap_pct
      
    Returns: gap struct
  
  Applies gap weight to pattern score
  Adjusts confidence based on gap alignment
  
Output JSON includes:
  "gap": { "direction": "GREEN", "gap_size_pct": 0.216, ... }
  "key_indicators": { "gap": "GREEN", "gap_boost": 0.08, ... }
```

---

## Entry Check Output Format (with Gap)

```json
{
  "family": "TrafficLight",
  "signal": "BULLISH",
  "score": 9.08,
  "confidence": 100,
  "reasoning": "pattern=STRONG_BULL_CONTINUATION (Redis, no DuckDB) + gap_weighted",
  "gap": {
    "direction": "GREEN",
    "today_open": 23750.00,
    "prev_close": 23700.00,
    "gap_size_points": 50.00,
    "gap_size_pct": 0.216
  },
  "key_indicators": {
    "pattern": "STRONG_BULL_CONTINUATION",
    "story": "1440m=GREEN | 240m=GREEN | 60m=GREEN | 30m=GREEN | 15m=GREEN | 5m=GREEN | G=6/6 R=0/6 | GAP=GREEN",
    "gap": "GREEN",
    "gap_boost": 0.08,
    "gap_conf_adjust": 15
  },
  "timestamp": "2026-05-20T09:16:00.123456",
  "_method": "redis"
}
```

---

## RL (Reinforcement Learning) Adjustment

Post-session, RL analyzes trades and can adjust:
1. **gap_weight:** Should gap have 20% influence or 30%?
2. **score_boost values:** Is 0.4 the right multiplier for gap_up_bullish?
3. **confidence_adjust:** Should we add +15% or +20% confidence?

Example: "Gap direction was wrong twice today. Reduce gap_weight from 0.2 to 0.1."

---

## Summary

✅ 7th parameter (gap) is now integrated with its own weight  
✅ Gap affects both score and confidence (not just score)  
✅ Tunable via entry_weights.json  
✅ RL can adjust weights post-session  
✅ Fallback: if prev_close unavailable, gap returns "unknown" and no adjustment applied  

Ready for May 20 trading with unified gap + pattern scoring.
