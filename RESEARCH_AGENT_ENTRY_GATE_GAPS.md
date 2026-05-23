# Research Agent → Entry Gate Wiring — RESOLVED

**Date:** May 23, 2026 | **Status:** ✅ RESOLVED (see RESEARCH_PATTERNS_WIRED.md + fix_research_agent_indicator_mismatch.md)

---

## Original Gaps (All Resolved)

### Gap 1: Untracked Files → ✅ RESOLVED
Four research files now committed in brahmand:
- `research_agents.py` — `20c89f4`
- `research_agents_full_db.py` — `20c89f4`
- `entry_agent.py` — `20c89f4`
- `entry_signal_broker.py` — `20c89f4` + `ec51a0b` (get_full_context)

### Gap 2: entry_signal_broker Not Called → ✅ RESOLVED
`entry_check.py` now imports EntrySignalBroker and calls `get_full_context()`. Committed in `antariksh/a05dc8c`.

### Gap 3: VIX/PCR Missing from Combine → ✅ RESOLVED
`entry_tools.py:combine_entry_scores()` accepts `market_ctx` parameter with:
- VIX > 20: confidence penalty (lines 1725-1730)
- PCR conflict: penalty when PCR+signal disagree (lines 1733-1741)
- Pattern boost: ST_ADX_VIX matches boost confidence (lines 1744-1750)
Committed in `antariksh/230f4b6`.

### Gap 4: Research Patterns Not Fed Back → ✅ RESOLVED
Full pipeline operational:
```
nightly_research → ChromaDB → entry_check_daemon → EntrySignalBroker → combine_entry_scores → GO/NO-GO
```

---

## Current State (May 23)

```
entry_check.py (every 5 min)
│
├─ score_trend_redis()            → Trend (Redis, 15 indicators)
├─ score_traffic_light_redis()    → Traffic Light (Redis, 6-TF candles)
├─ EntrySignalBroker.get_full_context() → VIX, PCR, ADX, patterns
└─ combine_entry_scores(trend, tl, market_ctx)
    ├─ VIX > 20 → confidence penalty
    ├─ PCR > 1.15 + BULLISH → conflict penalty
    ├─ PCR < 0.85 + BEARISH → conflict penalty
    └─ ST_ADX_VIX match → confidence boost
```
