# Entry Research Agent — Quick Start Guide

---

## What Is It?

The **Entry Research Agent** is an AI-powered backtesting tool that analyzes complete trading days to discover which technical indicators **predictively align** with significant price moves.

**In one sentence:** *Feed it 1-min data + it finds what indicators predicted moves.*

---

## Quick Examples

### Example 1: Analyze Today's NIFTY Data
```bash
cd /home/trading_ceo/brahmand
python entry_research_agent.py --date 2026-05-21 --index NIFTY --min-move 50
```

**What happens:**
1. Agent queries v3.1 + v4 DuckDB for all 1-min NIFTY candles on 2026-05-21
2. Detects all moves ≥ 50 points
3. For each move, examines what indicators aligned 15 min BEFORE
4. Groups patterns and ranks by effectiveness
5. Outputs JSON report with findings

**Expected output:**
```
═══════════════════════════════════════════
ENTRY RESEARCH AGENT — 2026-05-21 NIFTY
═══════════════════════════════════════════

📊 ANALYSIS COMPLETE

Found 8 significant moves (50+ pts)
Discovered 3 predictive patterns
Report saved to Chrome DB

Key Insights:
  ✓ ST15 GREEN + PCR BEARISH → UP move (67% accuracy, 6.5 min lead)
  ✓ Traffic light GGGRRR → Reversal warning (58% accuracy)
  ✗ ADX < 15 shows no directional bias
```

---

### Example 2: Analyze Past Day (e.g., May 15)
```bash
python entry_research_agent.py --date 2026-05-15 --index NIFTY
```

---

### Example 3: Find Larger Moves (100+ pts)
```bash
python entry_research_agent.py --date 2026-05-21 --min-move 100
```

**Note:** Min move defaults to 50 (NIFTY). Use 100 for SENSEX or for stricter filtering.

---

### Example 4: Use from Python Code
```python
from entry_research_agent import run_entry_research
import json

result = run_entry_research(
    date="2026-05-21",
    index="NIFTY",
    min_move=50
)

# Parse results
report = json.loads(result)
print(f"Moves found: {report['summary']['significant_moves_detected']}")
for pattern in report['pattern_insights']:
    print(f"  • {pattern['pattern_name']}: {pattern['success_rate']}% success rate")
```

---

## What Data It Accesses

### v3.1 Database (Primary)
✅ 50+ technical indicators  
✅ OHLC, spot price, Greeks  
✅ SuperTrend (15-min, 60-min)  
✅ Traffic light, PCR, VIX, ADX, RSI, Bollinger Bands, etc.

### v4 Database (Secondary)
✅ Cross-timeframe analysis (1-min, 5-min, 15-min, 60-min, 4-hour)  
✅ Multi-TF consensus signals  
✅ Enhanced data quality checks

---

## Output: What You Get

### 1. JSON Report (Machine Readable)
Location: Stored in ChromaDB for future reference

Contains:
- All significant moves with timestamps & magnitude
- Indicator alignment for each move
- Discovered patterns with success rates
- Recommendations for entry signals

### 2. Human Summary (Console Output)
- 🔍 Moves detected
- 📈 Top patterns discovered
- ✅ High-confidence recommendations
- ⚠️ Caveats & data quality notes

### 3. Pattern Library (Actionable)
Ready for Entry Agent to use:
```json
{
  "pattern_id": "ST15_GREEN_PCR_BEARISH",
  "trigger": "ST15 GREEN in lookback + PCR > 1.0",
  "expected_move": "50–75 pts UP",
  "success_rate": 0.67,
  "lead_time_minutes": 6,
  "confidence": "MEDIUM-HIGH",
  "conditions": "Use only 09:45–13:30, avoid after 14:00"
}
```

---

## Typical Findings

### Pattern #1: SuperTrend Alignment
```
WHEN:    ST15 is GREEN throughout 15-min lookback
THEN:    Move tends to be UP
LEAD:    5–10 minutes before
SUCCESS: 65–75% of the time
BEST TIME: 10:00–13:00 (avoids opening/closing volatility)
```

### Pattern #2: Traffic Light Reversal
```
WHEN:    Traffic light pattern: GGGGGR (3+ greens then red)
THEN:    Reversal move often follows
LEAD:    2–5 minutes
SUCCESS: 58% (high false positives)
NOTE:    Use as early warning, not primary signal
```

### Pattern #3: PCR Sentiment + Trend Alignment
```
WHEN:    PCR > 1.0 (bearish sentiment) + ST15 GREEN (bullish trend)
THEN:    Mean reversion UP (contrarian move)
LEAD:    3–8 minutes
SUCCESS: 65% (best on high VIX days)
NOTE:    Works when sentiment disagrees with trend
```

---

## Workflow: From Discovery to Entry

### Step 1: Run Backtest
```
Entry Research Agent analyzes → Identifies patterns → Stores in ChromaDB
```

### Step 2: Review Findings
```
Human reviews patterns → Validates logic → Approves for use
```

### Step 3: Entry Agent Uses Patterns
```
Real-time incoming 1-min candles → Match against discovered patterns
→ If match + confidence > threshold → ENTRY SIGNAL
```

### Example Real-Time Flow
```
14:00:00 — ST15 just turned GREEN
14:01:00 — ST15 still GREEN
14:02:00 — ST15 still GREEN
...
14:10:00 — ST15 still GREEN (10 straight greens, matches pattern)
          PCR = 1.02 (bearish, matches pattern)
          → ENTRY SIGNAL: Take bullish position
          → Expected move: 50–75 pts UP (based on backtest)
```

---

## Configuration Options

### Command Line
```bash
python entry_research_agent.py \
  --date 2026-05-21 \
  --index NIFTY \
  --min-move 50
```

### Python Code
```python
run_entry_research(
    date="2026-05-21",      # YYYY-MM-DD
    index="NIFTY",          # NIFTY or SENSEX
    min_move=50             # Minimum move threshold
)
```

---

## Key Parameters Explained

| Parameter | Default | Purpose | Example |
|-----------|---------|---------|---------|
| `--date` | Today | Which day to analyze | `2026-05-21` |
| `--index` | NIFTY | Which index | `NIFTY` or `SENSEX` |
| `--min-move` | 50 | Significant move threshold | 50 (NIFTY), 100 (SENSEX) |

---

## Interpretation Guide

### Confidence Levels
- **HIGH:** Pattern appeared 5+ times, success rate > 70%
- **MEDIUM:** Pattern appeared 3–4 times, success rate 60–70%
- **LOW:** Pattern appeared 2 times, success rate < 60%

### Lead Time Interpretation
- **3–5 min:** Very short warning, fast execution needed
- **5–10 min:** Reasonable time for entry decisions
- **10+ min:** Plenty of time, reliable for most entries

### Success Rate
- **>75%:** Highly reliable (use as primary signal)
- **65–75%:** Good reliability (use with other confirmation)
- **55–65%:** Moderate (use only with strong context)
- **<55%:** Low reliability (avoid or study more)

---

## Common Questions

### Q1: How far back should I look (lookback_minutes)?
**A:** Default 15 min works well. Shorter (5 min) = more responsive, higher false positives. Longer (30 min) = more stable, misses early signals.

### Q2: What if I want to find moves in the past?
**A:** Just change the date:
```bash
for date in 2026-05-{15..21}; do
    python entry_research_agent.py --date $date
done
```

### Q3: Can I combine v3.1 and v4 analysis?
**A:** Yes, agent automatically queries both. For each pattern, it cross-checks across databases for data quality validation.

### Q4: What's the difference between v3.1 and v4?
- **v3.1:** Single-timeframe data (1-min granularity)
- **v4:** Multi-timeframe aggregator (1-min + 5-min + 15-min + 60-min + 240-min consensus)

Use v4 for more robust patterns (multiple timeframes must align).

### Q5: How do I know if a pattern is real or just lucky?
**A:** Check:
1. **Sample size:** Did pattern occur 3+ times?
2. **Success rate:** Is it >60%?
3. **Lead time consistency:** Does lead time vary <50%?
4. **Regime independence:** Does pattern work in bull + bear markets?

If all 4 are yes → Pattern is likely real.

---

## Integration with Other Agents

### Output for Entry Agent
```
Entry Agent now knows:
✓ When ST15 is GREEN, expect 50–75 pt move in ~6 min
✓ When PCR > 1.0 + trend bullish, mean reversion likely
✓ When traffic light shows reversal pattern, be cautious
```

### Input from Historical Data
```
Entry Research Agent consumes:
← 1-min candles from Varaha v3.1 + v4
← All 90+ technical indicators
← Prior postmortem findings (what failed before)
```

### Feed to Risk Agent
```
Risk Agent learns:
✓ These patterns have 65–70% success rate
✓ Expected move size is 50–75 pts
✓ Lead time is typically 6 min
→ Can position sizing accordingly
```

---

## Next Steps

### Immediate: Run Your First Analysis
```bash
python entry_research_agent.py --date 2026-05-21 --index NIFTY --min-move 50
```

### Short-term: Review Results
- Read JSON report in ChromaDB
- Validate patterns make sense (not spurious correlations)
- Check confidence scores
- Note caveats/regime-specific warnings

### Medium-term: Build Pattern Library
- Run analysis for past 2–4 weeks
- Aggregate patterns across multiple days
- Find which patterns repeat consistently
- Score each by multi-day success rate

### Long-term: Live Integration
- Feed discovered patterns to Entry Agent
- Monitor in real-time (do patterns continue to work?)
- Update pattern library weekly
- A/B test against manual entry signals

---

## Troubleshooting

### Issue: "No data for that date"
**Solution:** Check that date exists in DuckDB and has trading
```bash
# Quick check
ls -l /home/trading_ceo/python-trader/varaha/data/*.duckdb
```

### Issue: Agent seems slow
**Solution:** Add limit to query
```bash
# Run on subset (first 100 candles)
python entry_research_agent.py --date 2026-05-21 --min-move 100
```

### Issue: Getting too many false positives
**Solution:** Increase min_move threshold
```bash
# Only analyze very significant moves
python entry_research_agent.py --date 2026-05-21 --min-move 100
```

### Issue: Want to validate v3.1 vs v4?
**Solution:** Query both directly
```python
from entry_research_agent import query_1min_candles_v31, query_1min_candles_v4
v31 = query_1min_candles_v31("2026-05-21")
v4 = query_1min_candles_v4("2026-05-21")
# Compare results
```

---

## Architecture Overview

```
┌─────────────────────────────────────────┐
│  Entry Research Agent (CrewAI)          │
│  Role: Pattern Discovery Analyst        │
└────────────┬────────────────────────────┘
             │
             ├─→ Tool: query_1min_candles_v31
             │   └─→ Access: Varaha v3.1 (50+ indicators)
             │
             ├─→ Tool: query_1min_candles_v4
             │   └─→ Access: Varaha v4 (cross-TF aggregator)
             │
             ├─→ Tool: detect_significant_moves
             │   └─→ Find all >50 pt moves
             │
             └─→ Tool: correlate_move_with_indicators
                 └─→ Analyze indicator state BEFORE move

                              ↓

┌─────────────────────────────────────────┐
│  Output: Pattern Discovery Report       │
│  • JSON (machine readable)              │
│  • HTML summary (human readable)        │
│  • Stored in ChromaDB                   │
└─────────────────────────────────────────┘

                              ↓

┌─────────────────────────────────────────┐
│  Consumed By:                           │
│  • Entry Agent (real-time signals)      │
│  • Risk Agent (position sizing)         │
│  • Post-Mortem Agent (effectiveness)    │
└─────────────────────────────────────────┘
```

---

## Complete Example Output

```json
{
  "metadata": {
    "date": "2026-05-21",
    "index": "NIFTY",
    "analysis_run_time": "2026-05-21T18:15:32Z",
    "databases_queried": ["varaha_v3.1", "varaha_v4"]
  },
  "summary": {
    "total_candles_analyzed": 390,
    "significant_moves_found": 8,
    "patterns_discovered": 3,
    "high_confidence_patterns": 2
  },
  "top_patterns": [
    {
      "rank": 1,
      "name": "ST15_GREEN_PCR_BEARISH",
      "description": "All 15 candles in lookback show ST15 GREEN, AND PCR > 1.0",
      "occurrences": 3,
      "success_rate": 0.67,
      "avg_move_magnitude": 68,
      "avg_lead_time_minutes": 6.5,
      "confidence_score": 0.72,
      "entry_signal": "LONG",
      "recommended_position_size": "1.0x",
      "conditions": "Use only 09:45–13:30, avoid post-14:00"
    }
  ],
  "detailed_moves": [
    {
      "timestamp": "2026-05-21 14:05:00",
      "move_magnitude": 75,
      "direction": "UP",
      "preceding_indicators": {
        "st15": "GREEN",
        "st60": "GREEN",
        "traffic_light": "GGGRRG",
        "pcr": 1.02,
        "adx": 15.2,
        "vix": 17.45
      },
      "matching_patterns": ["ST15_GREEN_PCR_BEARISH"],
      "pattern_match_confidence": 0.85
    }
  ]
}
```

---

Ready to discover entry patterns? Run:
```bash
python entry_research_agent.py --date 2026-05-21
```

Questions? Check `ENTRY_RESEARCH_AGENT_SPEC.md` for full documentation.
