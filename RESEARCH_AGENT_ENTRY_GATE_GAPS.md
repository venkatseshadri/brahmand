# Research Agent → Entry Gate Wiring Gaps

**Date:** May 23, 2026 | **Found by:** Session review

---

## Summary

Research agents discover patterns (including VIX, PCR, ADX, multi-indicator combos), but those discoveries never reach the entry gate's GO/NO-GO decision. The entire research → backtest → ChromaDB pipeline is built but disconnected from the live trading path.

---

## Gap 1: Untracked Files (Not in Git)

Four critical files exist on disk but were never committed or pushed:

| File | Lines | Purpose | Git Status |
|------|-------|---------|-----------|
| `research_agents.py` | ~605 | Pattern discovery (4 families + ST_ADX_VIX_001) | ❌ Untracked |
| `research_agents_full_db.py` | ~435 | Full-DB pattern analysis | ❌ Untracked |
| `entry_agent.py` | ~388 | Entry validation with corrected field names | ❌ Untracked |
| `entry_signal_broker.py` | ~359 | Signal generation with full market context (VIX/PCR/ADX) | ❌ Untracked |

**Risk:** Next `git pull` or reset wipes all fixes. Field name corrections (st_5min → st_5min_direction, RED → bearish, rsi_14 → rsi) and the ST_ADX_VIX_001 multi-indicator pattern only exist on this disk.

---

## Gap 2: entry_signal_broker Not Imported Anywhere

`entry_signal_broker.py` is the only file that feeds research agent patterns into entry decisions. It produces signals with VIX, PCR, ADX, and match scores. But **nothing calls it**:

```bash
# Zero results:
grep -rn "entry_signal_broker" entry_check.py e2e_chain.py kickoff.py
# → (empty)
```

The entry gate (`entry_check.py:30-32`) only calls:
```python
trend = score_trend_redis(index)           # Redis: ema, rsi, adx, st_direction, bb_pct_b
tl = score_traffic_light_redis(index)      # Redis: 6-TF candle colors only
decision = combine_entry_scores(trend, tl)  # Trend + TL fusion — no VIX, no PCR
```

**What entry_signal_broker produces but the gate ignores:**
- VIX level + context (LOW < 14, NORMAL 14-20, ELEVATED 20-25, HIGH > 25)
- PCR total + PCR ATM + PCR signal (bullish/bearish/neutral)
- ADX value + trend strength
- Pattern match score (from ChromaDB research patterns)
- Multi-indicator patterns (ST_ADX_VIX_001: "ALL-RED + ADX > 25 + VIX > 18")

---

## Gap 3: VIX/PCR Context Missing from entry_weights.json

The RL weight learner (`entry_tools.py:1773`) adjusts `entry_weights.json` post-session, but the config has no VIX or PCR sections:

**What exists in entry_weights.json:**
```json
{
  "trend": { "ema_weights": {...}, "adx": {...} },
  "traffic_light": { "patterns": {...} },
  "combine": { "rules": {...} }
}
```

**What's missing:**
```json
{
  "market_context": {
    "vix_threshold_low": 14,
    "vix_threshold_high": 20,
    "vix_weight": 0.15,
    "pcr_threshold_bearish": 1.15,
    "pcr_threshold_bullish": 0.85,
    "pcr_weight": 0.10,
    "adx_weight": 0.10,
    "research_pattern_boost": 0.10
  }
}
```

Without this, the RL learner can never optimize VIX/PCR thresholds.

---

## Gap 4: Research Agent Patterns Don't Feed Back to Entry Gate

The full pipeline that DOES exist:
```
nightly_research_scheduler.py → research_agents.py → ChromaDB → entry_agent.py
(discover patterns)              (store triggers)    (validate)
```

But the pipe stops there. There are **two paths into the entry gate** and neither uses the research output:

### Path A: Live Trading (entry_check.py) — Redis-only
```
Redis v3_ohlcv_queue → score_trend_redis() + score_traffic_light_redis() → combine_entry_scores() → GO/NO-GO
```
Uses: 15 indicator fields. Ignores: VIX, PCR, ChromaDB patterns.

### Path B: E2E Chain (e2e_chain.py) — DuckDB
```
DuckDB market_data → _deterministic_fallback() → vix > 18 → "caution"
```
Uses: VIX > 18 as binary caution flag only. Ignores: PCR, OI, ChromaDB patterns, multi-indicator combos.

Neither path queries ChromaDB for matching research patterns. Neither path calls `entry_agent` or `entry_signal_broker`.

---

## What Would a Complete Flow Look Like

```
entry_check.py (every 5 min)
│
├─ score_trend_redis()       → Trend signal       (Redis, 15 fields)
├─ score_traffic_light_redis() → TL signal        (Redis, 6-TF candles)
│
├─ query_market_context()    → VIX, PCR, ADX      (DuckDB — exists in toolkit.py!)
│       │
│       └─ VIX > 18 → confidence penalty
│       └─ PCR > 1.15 → bearish bias
│       └─ PCR < 0.85 → bullish bias
│
├─ query_chromadb_patterns() → Research patterns  (entry_signal_broker — exists!)
│       │
│       └─ ST_ADX_VIX_001 match → confidence boost/suppression
│
└─ combine_all(trend, tl, market_context, patterns) → GO/NO-GO
```

---

## Concrete Steps to Wire

### Step 1: Commit Untracked Files (5 min)
```bash
cd /home/trading_ceo/brahmand
git add research_agents.py research_agents_full_db.py entry_agent.py entry_signal_broker.py
git commit -m "feat: research agent field name fixes + ST_ADX_VIX_001 pattern + entry signal broker"
git push
```

### Step 2: Add Market Context to entry_weights.json (5 min)
Add `market_context` section with VIX thresholds, PCR thresholds, and weights.

### Step 3: Wire market_context into combine_entry_scores() (15 min)
Modify `entry_tools.py:combine_entry_scores()` to accept a third input:
```python
def combine_entry_scores(trend_score: dict, tl_score: dict, market_ctx: dict = None) -> dict:
```
- VIX > threshold → reduce confidence by weight
- PCR extreme → add directional bias
- Market context score factored into final confidence

### Step 4: Wire entry_signal_broker into entry_check.py (10 min)
```python
from brahmand.entry_signal_broker import EntrySignalBroker
broker = EntrySignalBroker()
market_ctx = broker.get_full_context()  # VIX, PCR, ADX, patterns
decision = combine_entry_scores(trend, tl, market_ctx)
```

### Step 5: Test (10 min)
- Verify ST_ADX_VIX_001 pattern fires when all conditions met
- Verify VIX > 18 reduces confidence on CAUTION trades
- Verify PCR extremes influence direction

---

## Files Involved

| File | Action Needed |
|------|---------------|
| `research_agents.py` | Already fixed — commit |
| `research_agents_full_db.py` | Already fixed — commit |
| `entry_agent.py` | Already fixed — commit |
| `entry_signal_broker.py` | Wire into entry_check.py |
| `entry_check.py` | Add market context + pattern queries |
| `entry_tools.py` | Add market context scoring to combine_entry_scores() |
| `config/entry_weights.json` | Add market_context section |

---

## Impact of Not Fixing

- Research agents run nightly but discoveries are never used
- ST_ADX_VIX_001 pattern (100% hit rate, 93pt avg move) discovered but ignored
- VIX/PCR/OI data available in DuckDB but entry gate is blind to it
- RL weight learner only optimizes Trend TL weights — can't learn VIX/PCR relationships
- Post-mortem analysis sees VIX patterns but can't feed them back into next day's decisions
