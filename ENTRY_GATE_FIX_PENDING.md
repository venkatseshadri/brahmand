# Entry Gate Fix — Threshold Analysis

**Source:** `ENTRY_GATE_IMPACT_ANALYSIS.md` — trade-off between trade volume and quality  
**Status:** ❌ NOT YET APPLIED

---

## Current Thresholds

| Path | File | Line | Current | Behavior |
|------|------|------|---------|----------|
| CrewAI LLM | `entry_agent.py` | 163 | `> 0.70` | RELAXED — enters YELLOW (0.70+) + GREEN (0.85+) |
| Redis deterministic | `entry_weights.json` | go_threshold | `min_confidence: 0` | Paper mode — takes ALL non-conflict |

---

## Backtest Results (3 Scenarios)

| Scenario | Threshold | Trades | Win Rate | Avg P&L | 250-day Cap |
|----------|-----------|--------|----------|---------|-------------|
| **RELAXED** (current) | ≥0.70 | 94% (~1000) | 51.7% | ₹882 | ₹1.34Cr |
| **MEDIUM** (recommended) | ≥0.75 | 65% (~650) | 55-56% | ₹1,100-1,200 | ₹850M |
| **STRICT** | ≥0.85 | 33% (~350) | 58-60% | ₹1,400-1,600 | ₹450M |

RELAXED wins on absolute capital but MEDIUM has better per-trade efficiency.

---

## What Needs to Change

### Change 1: LLM Path (entry_agent.py:163)
```python
# CURRENT:
entry = confidence > 0.70

# TO:
entry = confidence >= 0.75
```

### Change 2: LLM Path Traffic Light (entry_agent.py:251)
```python
# CURRENT:
elif confidence >= 0.70:
    return "YELLOW"

# TO:
elif confidence >= 0.75:
    return "YELLOW"
```

### Change 3: Redis Path (entry_weights.json)
```json
// CURRENT (paper mode):
"go_threshold": {"min_confidence": 0}

// TO (live mode, when ready):
"go_threshold": {"min_confidence": 35}
```
Paper mode at 0 collects maximum data. Switch to 35 when going live.

---

## Implementation Priority

| # | File | Change | When |
|---|------|--------|------|
| 1 | `entry_agent.py:163` | `0.70` → `0.75` | Before Monday 9:15 AM |
| 2 | `entry_agent.py:251` | `0.70` → `0.75` (YELLOW floor) | Before Monday 9:15 AM |
| 3 | `entry_weights.json` | `0` → `35` | When switching from paper to live |
