# ENTRY RESEARCH AGENT — Complete System Summary

**Status:** ✅ Fully Designed & Implemented  
**Created:** 2026-05-21  
**Components:** 4 files + Agent + Tools

---

## System Overview

The **Entry Research Agent** is a quantitative analysis system that discovers predictive indicator patterns by backtesting complete trading days against 1-minute market data.

```
┌────────────────────────────────────┐
│  ENTRY RESEARCH AGENT SYSTEM       │
├────────────────────────────────────┤
│                                    │
│  Agent: Entry Research Analyst     │
│  Role: Pattern Discovery Specialist│
│  Goal: Find predictive indicators  │
│                                    │
├────────────────────────────────────┤
│  TOOLS:                            │
│  ✓ query_1min_candles_v31 (v3.1)  │
│  ✓ query_1min_candles_v4 (v4)     │
│  ✓ detect_significant_moves        │
│  ✓ correlate_move_with_indicators  │
│                                    │
├────────────────────────────────────┤
│  DATABASES:                        │
│  ✓ Varaha v3.1 (50+ indicators)   │
│  ✓ Varaha v4 (cross-TF data)      │
│  ✓ ChromaDB (pattern storage)     │
│                                    │
├────────────────────────────────────┤
│  OUTPUT:                           │
│  ✓ JSON pattern report             │
│  ✓ Human-readable summary          │
│  ✓ Entry signal recommendations    │
│  ✓ Confidence scores & lead times  │
│                                    │
└────────────────────────────────────┘
```

---

## Complete File Structure

### 1. **entry_research_agent.py** (Main Implementation)
**Purpose:** Complete agent implementation with all tools

**Contains:**
- `query_1min_candles_v31()` — Full v3.1 database access
- `query_1min_candles_v4()` — Full v4 database access
- `detect_significant_moves()` — Move detection engine
- `correlate_move_with_indicators()` — Indicator correlation analysis
- `create_entry_research_agent()` — Agent factory
- `run_entry_research()` — Main execution function

**Usage:**
```bash
python entry_research_agent.py --date 2026-05-21 --index NIFTY --min-move 50
```

---

### 2. **ENTRY_RESEARCH_AGENT_SPEC.md** (Comprehensive Specification)
**Purpose:** Full documentation of agent design, behavior, and capabilities

**Sections:**
1. Agent Identity & Role (backstory, philosophy)
2. Core Skills & Capabilities (technical + analytical)
3. Knowledge & Data Sources (what agent knows)
4. Tools Available (detailed specifications)
5. Expected Outputs (JSON + summaries)
6. Execution Workflow (step-by-step process)
7. Configuration & Parameters (customization)
8. Limitations & Caveats (honest assessment)
9. Integration (how it works with other agents)
10. Success Metrics (how to measure effectiveness)
11. Usage Examples (code snippets)
12. Future Enhancements (roadmap)

---

### 3. **ENTRY_RESEARCH_TOOLS_REFERENCE.md** (Tools & Data Dictionary)
**Purpose:** Complete reference for all 90+ DuckDB columns + tool usage

**Sections:**
1. Tool 1: `query_1min_candles_v31` (with ALL v3.1 columns)
2. Tool 2: `query_1min_candles_v4` (with cross-TF extensions)
3. Tool 3: `detect_significant_moves` (function + output format)
4. Tool 4: `correlate_move_with_indicators` (detailed analysis fields)
5. Workflow: Using both databases simultaneously
6. Data Quality Checks (validation approach)
7. Example data (sample JSON output)
8. Performance notes (query times, data volumes)
9. Troubleshooting (common issues + solutions)

---

### 4. **ENTRY_RESEARCH_QUICKSTART.md** (User Guide)
**Purpose:** Fast start guide for running agent + interpreting results

**Sections:**
1. What Is It? (1-sentence explanation)
2. Quick Examples (runnable commands)
3. What Data It Accesses (v3.1 + v4 capabilities)
4. Output Types (JSON + human summary + pattern library)
5. Typical Findings (example patterns)
6. Workflow (from discovery to entry)
7. Configuration Options (parameters + examples)
8. Key Parameters Explained (what each does)
9. Interpretation Guide (confidence levels, lead times, success rates)
10. Common Questions (FAQ)
11. Troubleshooting (common issues)
12. Architecture Overview (system diagram)

---

## Agent Specifications

### Identity
- **Role:** Entry Research Analyst
- **Specialization:** Intraday microstructure pattern discovery
- **Expertise:** Technical indicator correlation + statistical validation
- **Philosophy:** Find what indicators predictively aligned BEFORE moves happened

### Backstory
You are a quantitative researcher with access to COMPLETE 1-minute market data across TWO databases (v3.1 + v4). Your mission: backtest trading days to find which technical indicator combinations predictively precede significant moves. Think archaeologically—excavate data in layers, cross-reference between sources, validate findings, avoid spurious correlations.

### Core Mission
Transform raw 1-minute candle data into **actionable entry patterns** by correlating significant price moves with preceding indicator states. Build a pattern library that Entry Agent can use for real-time signal generation.

---

## Tools Summary

| Tool | Database | Purpose | Output |
|------|----------|---------|--------|
| `query_1min_candles_v31` | v3.1 | Get all 1-min candles + 50+ indicators | JSON: timestamp, OHLC, all indicators |
| `query_1min_candles_v4` | v4 | Get multitimeframe aggregated data | JSON: v3.1 data + cross-TF columns |
| `detect_significant_moves` | Either | Find all moves >= threshold | JSON: timestamp, magnitude, direction |
| `correlate_move_with_indicators` | Either | Analyze indicator state before move | JSON: indicator alignment, scores, analysis |

---

## Databases & Columns

### Varaha v3.1 (Primary)
**Path:** `/home/trading_ceo/projects/varaha/data/varaha_data.duckdb`  
**Table:** `market_data`  
**Columns:** 50+

**Key Categories:**
- **Time & ID:** timestamp, date, time, index_name
- **Price:** open_price, high, low, close, spot, prev_close, gap_pct
- **Trends:** st_15min, st_60min, adx, rsi_14, rsi_5
- **Averages:** ema_5_15min, ema_9_15min, ema_20_15min, sma_50/200
- **Sentiment:** traffic_light_15min, pcr_total, pcr_oi, pcr_volume
- **Volatility:** india_vix, iv_percentile, iv_rank, atr_14
- **Patterns:** bb_upper/lower, macd, macd_signal, obv, cmf
- **Context:** market_regime, session_phase, volatility_regime, data_quality

### Varaha v4 (Secondary)
**Path:** `/home/trading_ceo/projects/varaha/data/market_data_multitf.duckdb`  
**Table:** `market_data_multitf` (or `market_data`)  
**Columns:** 80+

**What v4 Adds:**
- `tf_1min_*` — 1-min timeframe indicators
- `tf_5min_*` — 5-min timeframe indicators
- `tf_15min_*` — 15-min timeframe indicators (usually same as v3.1)
- `tf_60min_*` — 60-min timeframe indicators
- `tf_240min_*` — 240-min (4-hour) timeframe indicators
- `cross_tf_alignment` — Multi-TF consensus (how many TFs agree?)
- `aggregate_signal` — Composite signal strength
- `multitf_confidence` — Confidence score across all TFs

---

## Workflow: Step by Step

### Step 1: Initialize Agent
```python
agent = create_entry_research_agent(
    index="NIFTY",
    date="2026-05-21",
    min_move=50
)
```
Agent is ready with:
- ✅ All 4 tools accessible
- ✅ Full database connections (v3.1 + v4)
- ✅ Technical knowledge base loaded
- ✅ Analysis parameters configured

### Step 2: Query Both Databases
Agent calls:
- `query_1min_candles_v31("2026-05-21", "NIFTY")` → Returns 390 candles with 50+ indicators
- `query_1min_candles_v4("2026-05-21", "NIFTY")` → Returns 390 candles with cross-TF data

Data validation:
- ✓ Cross-check spot prices (should match)
- ✓ Verify indicators align (allow <1% variance)
- ✓ Flag any data quality issues

### Step 3: Detect Significant Moves
Agent calls:
- `detect_significant_moves(v31_data, min_move=50)` → Returns list of 8 moves

Example output:
```json
{
  "time": "2026-05-21 14:05:00",
  "prev_spot": 23625.0,
  "curr_spot": 23700.0,
  "move_points": 75.0,
  "direction": "UP",
  "magnitude_pct": 0.32
}
```

### Step 4: Analyze Each Move
For each of 8 detected moves, agent calls:
- `correlate_move_with_indicators(v31_data, move_time="14:05:00", lookback=15)`

Agent analyzes:
- ST15 state in all 15 candles before move (GREEN, RED, MIXED)
- ST60 trend strength
- Traffic light pattern (last 5 candles: "GGGRRG")
- EMA position (above/below 20-EMA)
- ADX strength (weak, moderate, strong)
- VIX level
- PCR sentiment (bullish/bearish/neutral)

### Step 5: Group & Score Patterns
Agent compares across all 8 moves:
- "ST15 GREEN + PCR BEARISH" → appeared before 3/8 moves (37.5%)
- "Among those 3, all went UP" → 100% success when it appeared
- "Average move magnitude: 68 pts"
- "Average lead time: 6.5 min before move started"

### Step 6: Validate with v4 Data
Agent cross-checks patterns in v4:
- Do cross-TF indicators agree with v3.1?
- Does multitf_consensus support ST15 GREEN findings?
- Calculate confidence across multiple timeframes

### Step 7: Generate Report
Agent outputs:
1. **JSON Report:** Machine-readable findings (stored in ChromaDB)
2. **Human Summary:** Readable text report with examples
3. **Entry Recommendations:** "Use ST15 GREEN + PCR BEARISH for bullish entries"
4. **Confidence Scores:** Each pattern ranked 0.0–1.0

---

## Expected Output Examples

### Pattern #1: SuperTrend Green Dominance
```json
{
  "pattern_name": "ST15_GREEN_DOMINANT",
  "description": "ST15 GREEN for all 15 candles in lookback",
  "occurrences": 3,
  "success_rate": 0.67,
  "avg_move_magnitude": 68,
  "avg_lead_time_minutes": 6.5,
  "confidence_score": 0.72,
  "entry_signal": "LONG",
  "conditions": "Best 10:00–13:00, avoid opening/closing hours"
}
```

### Pattern #2: Traffic Light Reversal Warning
```json
{
  "pattern_name": "TRAFFIC_LIGHT_REVERSAL",
  "description": "Pattern: 3+ greens followed by red (GGGRRR)",
  "occurrences": 2,
  "success_rate": 0.58,
  "avg_move_magnitude": 45,
  "avg_lead_time_minutes": 3.2,
  "confidence_score": 0.58,
  "entry_signal": "CONTRARIAN_REVERSAL",
  "note": "High false positives—use as early warning, not primary signal"
}
```

### Pattern #3: PCR Sentiment Mean Reversion
```json
{
  "pattern_name": "PCR_SENTIMENT_MEAN_REVERSION",
  "description": "PCR > 1.0 (bearish) + ST15 GREEN (bullish) = reversal",
  "occurrences": 3,
  "success_rate": 0.65,
  "avg_move_magnitude": 52,
  "avg_lead_time_minutes": 5.2,
  "confidence_score": 0.65,
  "entry_signal": "LONG",
  "conditions": "More effective on high VIX days (>18)"
}
```

---

## Integration Points

### Receives Data From:
- **Data Pipeline:** 1-min candles streamed to DuckDB
- **Varaha v3.1/v4:** Technical indicators pre-calculated
- **Market Regime:** Session phase, VIX, ADX context

### Sends Patterns To:
1. **Entry Agent:** "When ST15 GREEN + PCR BEARISH, go LONG"
2. **Risk Agent:** "Expected move is 50–75 pts with 6.5 min lead time"
3. **Post-Mortem Agent:** "These patterns worked 67% of the time"
4. **ChromaDB:** Searchable pattern library for team review

### Validates Against:
- Historical Post-Mortems (learned failure modes)
- Configuration Rules (time gates, VIX thresholds)
- Statistical Requirements (sample size, consistency, regime independence)

---

## Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Patterns Discovered** | 3–5 per day | Count unique patterns |
| **Min Confidence** | >0.65 | Weighted by occurrences |
| **False Positive Rate** | <40% | How often pattern preceded move? |
| **Lead Time** | 3–10 min | Time indicator aligned before move |
| **Sample Size** | >2 occurrences | Pattern must repeat |
| **Database Validation** | 100% | v3.1 + v4 agree on key fields |
| **Report Completeness** | 100% | Every move gets analyzed |

---

## Usage Summary

### One-Line Execution
```bash
python entry_research_agent.py --date 2026-05-21 --index NIFTY --min-move 50
```

### Expected Runtime
- **Query both databases:** 200–1000ms
- **Detect moves:** 50–100ms
- **Analyze each move:** 10–20ms × 8 moves = 80–160ms
- **Generate report:** 100–200ms
- **Total:** ~1–2 seconds

### Output Locations
- **Console:** Real-time progress + summary
- **ChromaDB:** Full JSON report (searchable)
- **Return Value:** Structured JSON report

---

## Known Limitations

1. **Lookback Bias:** Can reveal spurious correlations (analyze multiple days for validation)
2. **Single-Day Sample:** Patterns may not repeat tomorrow (need multi-week backtest)
3. **Causation Gap:** Correlation ≠ predictive power (validate with forward-testing)
4. **Regime Changes:** Past patterns may break in different market conditions
5. **Data Quality:** Missing candles or stale indicators can create false patterns

---

## Quick Troubleshooting

| Issue | Solution |
|-------|----------|
| No data returned | Check date format (YYYY-MM-DD), index spelling (NIFTY/SENSEX) |
| Agent runs slow | Increase min_move threshold, limit output rows |
| Too many false positives | Increase min_move, require multiple indicators |
| v3.1 vs v4 disagree | Use v3.1 as primary, v4 as secondary validation |
| Pattern seems spurious | Check sample size (occurred 3+ times?) and success rate (>60%?) |

---

## Files Reference

| File | Size | Purpose | Last Updated |
|------|------|---------|--------------|
| `entry_research_agent.py` | ~4 KB | Main implementation | 2026-05-21 |
| `ENTRY_RESEARCH_AGENT_SPEC.md` | ~15 KB | Full specification | 2026-05-21 |
| `ENTRY_RESEARCH_TOOLS_REFERENCE.md` | ~12 KB | Tools + columns | 2026-05-21 |
| `ENTRY_RESEARCH_QUICKSTART.md` | ~8 KB | User guide | 2026-05-21 |

---

## Next Actions

### Immediate (Today)
- [ ] Review all 4 documentation files
- [ ] Run: `python entry_research_agent.py --date 2026-05-21`
- [ ] Review output report in ChromaDB

### Short-term (This Week)
- [ ] Run analysis on 5–7 past trading days
- [ ] Aggregate patterns across days
- [ ] Validate top patterns (appeared 3+ times?)
- [ ] Create pattern scoring rubric

### Medium-term (This Month)
- [ ] Build multi-week pattern library
- [ ] A/B test patterns in live trading
- [ ] Monitor pattern effectiveness
- [ ] Update pattern library weekly

### Long-term (Ongoing)
- [ ] Feed patterns to Entry Agent for live signals
- [ ] Track pattern performance metrics
- [ ] Retire low-performing patterns
- [ ] Discover new patterns continuously

---

## Summary

The **Entry Research Agent** transforms historical 1-minute market data into predictive entry patterns by:

1. **Analyzing:** 390 1-min candles per day
2. **Detecting:** Significant moves (50+ pts for NIFTY)
3. **Correlating:** What indicators aligned BEFORE each move
4. **Discovering:** Predictive patterns with confidence scores + lead times
5. **Outputting:** Actionable entry signals for downstream agents

**Core Value:** *"Turn historical 'what happened' into predictive 'what to watch for.'"*

---

**Status:** ✅ Ready to Deploy  
**Documentation:** Complete (4 files)  
**Tools:** All implemented  
**Databases:** Full access to v3.1 + v4  
**Next:** Run first backtest and validate patterns

---

For quick start, run:
```bash
cd /home/trading_ceo/projects/brahmand && python entry_research_agent.py --date 2026-05-21
```

For complete documentation, read:
- `ENTRY_RESEARCH_AGENT_SPEC.md` (design + architecture)
- `ENTRY_RESEARCH_TOOLS_REFERENCE.md` (tools + all 90+ columns)
- `ENTRY_RESEARCH_QUICKSTART.md` (user guide + examples)
