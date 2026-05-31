# Autonomous Nightly Research → Entry Agent Workflow

**Version:** 1.0  
**Status:** Implementation Ready  
**Last Updated:** 2026-05-21

---

## Overview

```
NIGHTLY (11:00 PM - 12:00 AM)              DAYTIME (9:15 AM - 3:30 PM)
├─ Research Phase (11:00-11:15)            ├─ Entry Agent startup
│  └─ 4 agents discover patterns           │  └─ Load approved patterns from ChromaDB
│
├─ Backtest Phase (11:15-11:45)            ├─ Live signal generation
│  └─ Test against May 4-21 data           │  └─ Every 1-minute: check patterns
│                                          │     └─ Execute entries based on weights
├─ Validation Phase (11:45-11:50)          │
│  └─ Auto-approve patterns                └─ Next night: measure effectiveness
│     (win rate > 70%, matches >= 3)          └─ Update weights for tomorrow
│
├─ Storage Phase (11:50-12:00)
│  └─ Store to ChromaDB
│  └─ Send Telegram summary
│  └─ Ready for Entry Agent

Entry Agent receives: Yesterday's approved patterns + backtest results
                    ↓
                   Use weights from nightly backtest
                    ↓
                   Generate signals in real-time
                    ↓
                   Measure today's actual effectiveness
                    ↓
                   Feed back into next night's research
```

---

## Daily Timeline

### 11:00 PM - 12:00 AM (Nightly Autonomous Research)

**Run Command:**
```bash
python3 /home/trading_ceo/brahmand/nightly_research_scheduler.py
```

**What Happens:**

#### Phase 1: Research (11:00-11:15 PM)
```python
# research_backtest_framework.py

research_agents = [
    SuperTrendResearchAgent(),     # ST5/ST15, ADX, trend flips
    PCRResearchAgent(),             # PCR sentiment, OI skew
    EMAResearchAgent(),             # EMA crosses, RSI extremes
    VolatilityResearchAgent()       # VIX, IV, Bollinger Bands
]

for agent in research_agents:
    patterns = agent.discover_patterns(
        date="2026-05-21",          # Yesterday's data
        candles_v31=full_day_data,
        candles_v4=multitf_data
    )
    discovered_patterns.extend(patterns)

print(f"✓ Discovered {len(discovered_patterns)} candidate patterns")
# Example: ST5/ST15 Divergence, PCR Divergence, EMA Slope + RSI, OI Imbalance
```

#### Phase 2: Backtest (11:15-11:45 PM)
```python
# research_backtest_framework.py

backtest_engine = BacktestEngine()
historical_dates = backtest_engine.get_historical_dates()
# Returns: ['2026-05-04', '2026-05-05', '2026-05-06', ..., '2026-05-21'] (13 days)

for pattern in discovered_patterns:
    summary = backtest_engine.backtest_pattern_all_dates(pattern)
    
    # Results for ST5/ST15 Divergence pattern:
    # ├─ May 4: 2 matches, 100% win rate, avg 65 pts
    # ├─ May 5: 1 match, 100% win rate, 72 pts
    # ├─ May 6: 0 matches
    # ├─ ... (rest of dates)
    # ├─ May 21: 4 matches, 100% win rate, avg 87 pts
    # │
    # └─ OVERALL:
    #    ├─ Total matches: 15
    #    ├─ Total wins: 14
    #    ├─ Win rate: 93%
    #    ├─ Avg move: 76 pts
    #    ├─ Consistency: 62% of days
    #    └─ Status: APPROVED ✓
```

#### Phase 3: Validation (11:45-11:50 PM)
```python
# Auto-validate based on criteria:

APPROVAL_CRITERIA = {
    "min_total_matches": 3,          # Must appear in >= 3 candles historically
    "min_win_rate": 0.70,            # Must win 70%+ of the time
    "min_avg_move": 50,              # Must average 50+ point moves
    "min_consistency": 0.30,          # Must appear in 30%+ of trading days
}

approved_patterns = [
    pattern for pattern in patterns
    if (summary.total_matches >= 3 and
        summary.overall_win_rate >= 0.70 and
        summary.avg_move_magnitude >= 50 and
        summary.consistency_across_days >= 0.30)
]

# Example approval:
# ✓ ST5/ST15 Divergence: 15 matches, 93% win, 76 pts, 62% consistency → APPROVED
# ✓ EMA Slope + RSI: 11 matches, 82% win, 68 pts, 54% consistency → APPROVED
# ✗ OI Imbalance: 2 matches, 50% win, 40 pts, 15% consistency → REJECTED
```

#### Phase 4: Storage (11:50 PM-12:00 AM)
```python
# Store to ChromaDB

for pattern in approved_patterns:
    record = {
        "pattern_id": "ST_ADX_20260521_001",
        "pattern_name": "ST5/ST15 Divergence + ADX Spike",
        "family": "supertrend",
        "discovery_date": "2026-05-21T23:00:00Z",
        
        "backtest_results": {
            "total_matches": 15,
            "win_rate": 0.93,
            "avg_move_magnitude": 76,
            "consistency": 0.62,
            "backtest_period": "2026-05-04 to 2026-05-21"
        },
        
        "trigger_conditions": {
            "st5_direction": "RED",
            "st15_direction": "GREEN",
            "adx_min": 25
        },
        
        "entry_agent_config": {
            "weight": 0.84,              # 0.93 win rate × 0.9 discount
            "active": True,
            "expires_at": "2026-05-28T09:15:00Z"  # 7-day expiry
        }
    }
    
    chroma_collection.upsert(records=[record])
```

#### Phase 5: Notification
```
Telegram Message Sent:

📊 NIGHTLY RESEARCH + BACKTEST COMPLETE (2026-05-21)

✅ Approved Patterns: 2

ST5/ST15 Divergence + ADX Spike
├─ Win Rate: 93%
├─ Historical Matches: 15
├─ Avg Move: 76 pts
├─ Weight: 0.84
└─ Ready for Entry Agent ✓

EMA Slope + RSI Extreme
├─ Win Rate: 82%
├─ Historical Matches: 11
├─ Avg Move: 68 pts
├─ Weight: 0.74
└─ Ready for Entry Agent ✓

⏰ Entry Agent ready at 9:15 AM with approved patterns
```

---

### 9:15 AM - 3:30 PM (Live Entry Agent)

**Entry Agent Startup (9:15 AM):**
```python
# entry_agent_with_research.py

class EntryAgent:
    def __init__(self):
        # Load approved patterns from ChromaDB
        self.patterns = self.load_approved_patterns()
        # Returns:
        # {
        #   "ST_ADX_20260521_001": {
        #     "name": "ST5/ST15 Divergence + ADX",
        #     "weight": 0.84,
        #     "trigger_conditions": {...},
        #     "historical_backtest": {...}
        #   },
        #   "EMA_RSI_20260521_001": {
        #     "name": "EMA Slope + RSI",
        #     "weight": 0.74,
        #     ...
        #   }
        # }
    
    def load_approved_patterns(self):
        """Load patterns approved by last night's research"""
        try:
            import chromadb
            chroma = chromadb.PersistentClient(path="/tmp/chroma_research")
            collection = chroma.get_collection(name="discovered_patterns")
            
            # Query today's approved patterns
            results = collection.get(
                where={"date": "2026-05-22"},
                where_document={"$contains": "APPROVED"}
            )
            
            patterns = {}
            for i, doc in enumerate(results['documents']):
                record = json.loads(doc)
                patterns[record['pattern_id']] = record
            
            return patterns
        except Exception as e:
            logger.error(f"Failed to load patterns: {e}")
            return {}
```

**Real-Time Signal Generation (9:15 AM - 3:30 PM):**
```python
# Called every 1 minute with new candle data

def check_entry_signal(current_candle):
    """
    Check if current candle triggers any approved patterns
    """
    
    matching_patterns = []
    
    # Check each approved pattern
    for pattern_id, pattern in self.patterns.items():
        if self.pattern_triggers(current_candle, pattern):
            confidence = self.calculate_confidence(
                pattern_score=pattern['backtest_results']['win_rate'],
                family_weight=pattern['entry_agent_config']['weight'],
                current_indicators=current_candle
            )
            
            matching_patterns.append({
                "pattern_id": pattern_id,
                "pattern_name": pattern["pattern_name"],
                "confidence": confidence,
                "historical_win_rate": pattern['backtest_results']['win_rate'],
                "historical_avg_move": pattern['backtest_results']['avg_move_magnitude'],
            })
    
    # Generate entry signal if confidence high
    if matching_patterns:
        best_match = max(matching_patterns, key=lambda x: x['confidence'])
        
        if best_match['confidence'] > 0.70:
            return {
                "entry": "YES",
                "pattern": best_match['pattern_name'],
                "confidence": best_match['confidence'],
                "expected_move": best_match['historical_avg_move'],
                "backtest_evidence": f"{best_match['historical_win_rate']:.0%} win rate on 15 historical trades",
                "targets": [
                    best_match['historical_avg_move'] * 0.5,  # Conservative
                    best_match['historical_avg_move'],        # Target
                    best_match['historical_avg_move'] * 1.3   # Aggressive
                ]
            }
    
    return {"entry": "NO"}

# Example output at 9:20 AM on 2026-05-22:
# {
#   "entry": "YES",
#   "pattern": "ST5/ST15 Divergence + ADX Spike",
#   "confidence": 0.84,
#   "expected_move": 76,
#   "backtest_evidence": "93% win rate on 15 historical trades",
#   "targets": [38, 76, 99]
# }
```

**Performance Tracking (Throughout Day):**
```python
# Track each trade signal

trade_log = {
    "2026-05-22": [
        {
            "time": "09:20:00",
            "pattern": "ST5/ST15 Divergence",
            "entry_price": 23680,
            "exit_price": 23756,
            "move_points": 76,
            "confidence": 0.84,
            "backtest_win_rate": 0.93,
            "actual_result": "WIN",
            "backtest_match": True
        },
        {
            "time": "11:35:00",
            "pattern": "EMA Slope + RSI",
            "entry_price": 23720,
            "exit_price": 23680,
            "move_points": -40,
            "confidence": 0.74,
            "backtest_win_rate": 0.82,
            "actual_result": "LOSS",
            "backtest_match": False  # Pattern worked in backtest but not today
        }
    ]
}
```

---

### 11:00 PM Next Night (Cycle Continues)

**Feedback Loop:**
```
Today's actual results → Update next night's weights

Research Agent will notice:
  "ST5/ST15 Divergence had 93% backtest win rate, but went 1-1 (50%) today.
   Maybe conditions are changing? Reduce weight to 0.78 for tomorrow?"

OR

  "EMA Slope + RSI had 82% backtest, today was 1-1 (50%).
   Consistent with historical variance. Keep weight at 0.74."
```

---

## Cron Job Setup

### Add to crontab (11:00 PM every trading day):
```bash
# Edit crontab
crontab -e

# Add this line (runs at 11 PM Mon-Fri)
0 23 * * 1-5 cd /home/trading_ceo/brahmand && /usr/bin/python3 nightly_research_scheduler.py >> /tmp/research_scheduler.log 2>&1

# Verify installation
crontab -l
```

### Log Monitoring:
```bash
# Watch logs in real-time
tail -f /tmp/research_scheduler.log

# Expected output:
# 2026-05-21 23:00:00 - INFO - NIGHTLY RESEARCH + BACKTEST SCHEDULER STARTED
# 2026-05-21 23:00:05 - INFO - [PHASE 1] Running research agents...
# 2026-05-21 23:00:15 - INFO - Discovered 5 patterns
# 2026-05-21 23:15:00 - INFO - [PHASE 2] Backtesting patterns...
# 2026-05-21 23:45:00 - INFO - Approved patterns: 2
# 2026-05-21 23:50:00 - INFO - [PHASE 3] Storing approved patterns...
# 2026-05-21 23:55:00 - INFO - [PHASE 4] Sending notification...
# 2026-05-21 23:55:30 - INFO - Telegram notification sent
```

---

## Data Flow Diagram

```
NIGHTLY RESEARCH
│
├─ Input: Yesterday's 1-min candles (390 candles)
│  └─ From: varaha_data.duckdb
│
├─ Process: 4 research agents discover patterns
│  ├─ SuperTrendAgent: Analyzes ST5/ST15/ST60, ADX
│  ├─ PCRAgent: Analyzes PCR, OI, sentiment
│  ├─ EMAAgent: Analyzes EMAs, RSI, slopes
│  └─ VolAgent: Analyzes VIX, IV, Bollinger Bands
│
├─ Validate: Backtest against full historical dataset
│  ├─ Input: May 4-21 (13 trading days × 390 candles = 5,070 candles)
│  ├─ For each pattern:
│  │  └─ Test on all 13 days → Calculate win rate, consistency, avg move
│  └─ Auto-approve if: matches >= 3, win_rate >= 70%, avg_move >= 50
│
├─ Store: Approved patterns in ChromaDB
│  ├─ Record includes:
│  │  ├─ Pattern ID, name, family
│  │  ├─ Trigger conditions
│  │  ├─ Backtest results (win_rate, avg_move, consistency)
│  │  ├─ Weight for Entry Agent
│  │  └─ Expiry date (7 days)
│  └─ Location: /tmp/chroma_research/
│
└─ Notify: Send Telegram summary to user


ENTRY AGENT (NEXT MORNING)
│
├─ Startup (9:15 AM): Load approved patterns from ChromaDB
│  ├─ Query: Get all patterns with expires_at > now and active=True
│  └─ Result: 2-5 approved patterns with weights
│
├─ Live Trading (9:15 AM - 3:30 PM):
│  ├─ Every 1-minute: Receive new candle
│  ├─ Check: Does current candle match any approved pattern?
│  ├─ Calculate: Confidence = pattern_backtest_score × pattern_weight
│  ├─ Decide: If confidence > 0.70, generate entry signal
│  └─ Execute: Place trade with targets based on historical results
│
└─ Monitor: Track actual results vs backtest expectations


FEEDBACK LOOP (NEXT NIGHT)
│
├─ Analyze: Did approved patterns work today?
│  ├─ ST5/ST15 pattern: backtest says 93%, today was 75% → neutral
│  ├─ EMA pattern: backtest says 82%, today was 67% → declining
│  └─ New pattern: backtest says 100%, today was 100% → excellent
│
└─ Update: Adjust weights for tomorrow's research
   └─ Good patterns: increase weight
   └─ Declining patterns: decrease weight or retire
   └─ New patterns: validate again before using
```

---

## Quality Safeguards

### 1. Validation Rules
```python
# Before approving a pattern:

MUST_HAVE = {
    "matches": 3,              # Appeared in 3+ candles historically
    "win_rate": 0.70,          # Won 70%+ of the time
    "lead_time": 2,            # At least 2 min lead time
    "consistency_days": 2,     # Appeared in 2+ different trading days
}

# If any fail → REJECTED
```

### 2. Expiration
```python
# Each pattern expires after 7 days
# If market regime changes (bull → bear), old patterns auto-retire
# Prevents stale patterns from generating false signals
```

### 3. Confidence Thresholds
```python
# Entry only if confidence > 0.70
# Low confidence (0.50-0.70) → monitor only
# Very low (< 0.50) → skip

Entry_Confidence = (
    pattern_backtest_score × 0.60 +    # Core effectiveness
    pattern_weight × 0.25 +             # Research confidence
    current_indicator_alignment × 0.15  # Real-time match quality
)
```

### 4. Regime Tracking
```python
# Backtest results broken down by market regime:
# ├─ Bullish days: 85% win rate
# ├─ Bearish days: 75% win rate
# └─ Sideways days: 65% win rate

# If today's regime is bearish, use bearish-specific weights
```

---

## Checklist for Implementation

- [ ] **BacktestEngine** (research_backtest_framework.py)
  - [ ] Can query all dates from varaha_data.duckdb
  - [ ] Can backtest single pattern against one date
  - [ ] Can aggregate results across 13 trading days
  - [ ] Can calculate win rate, consistency, lead time

- [ ] **ResearchBacktestOrchestrator**
  - [ ] Run 4 research agents (dummy for now, real later)
  - [ ] Run backtest on discovered patterns
  - [ ] Validate patterns against approval criteria
  - [ ] Generate summary report

- [ ] **NightlyScheduler** (nightly_research_scheduler.py)
  - [ ] Run via `python3 nightly_research_scheduler.py`
  - [ ] Store approved patterns in ChromaDB
  - [ ] Send Telegram notification
  - [ ] Log to /tmp/research_scheduler.log

- [ ] **Entry Agent Integration** (entry_agent_with_research.py)
  - [ ] Load patterns from ChromaDB on startup
  - [ ] Check patterns every 1-minute
  - [ ] Calculate confidence using weights
  - [ ] Generate signals when confidence > 0.70

- [ ] **Cron Job Setup**
  - [ ] Add to crontab: `0 23 * * 1-5 python3 nightly_research_scheduler.py`
  - [ ] Test cron execution
  - [ ] Monitor logs

---

## Testing Workflow

### 1. Manual Test (Before Cron):
```bash
# Run research + backtest manually
python3 /home/trading_ceo/brahmand/nightly_research_scheduler.py

# Expected output:
# ✓ Discovered 5 patterns
# ✓ Approved 2 patterns
# ✓ Stored in ChromaDB
# ✓ Telegram sent
```

### 2. Dry Run (7 days):
```bash
# Run nightly for one week
# Monitor:
# - Do patterns get discovered each night?
# - Are they backtested correctly?
# - Do approved patterns work the next day?
# - Do weights update based on daily performance?
```

### 3. Live Validation (2 weeks):
```bash
# Run full pipeline in production
# Compare:
# - Backtest accuracy (expected 70% win rate)
# - Entry Agent signals (should match backtest expectations)
# - Daily P&L (should be positive on average)
```

---

## Key Success Metrics

| Metric | Target | How to Measure |
|--------|--------|----------------|
| **Research Speed** | < 60 min | Time from 11 PM start to Telegram sent |
| **Backtest Accuracy** | > 95% match | Do approved patterns match next day? |
| **Entry Agent Effectiveness** | > 70% win rate | (Winning trades / Total trades) |
| **Pattern Approval Rate** | 20-40% | (Approved / Discovered) |
| **Daily Refresh** | 100% | All patterns refreshed within 7 days |
| **Cron Reliability** | 100% | Runs every trading day automatically |

---

## Next Steps

**Week 1:**
- [ ] Implement BacktestEngine
- [ ] Test on historical data (May 4-21)
- [ ] Verify 13-day backtest accuracy

**Week 2:**
- [ ] Implement ResearchBacktestOrchestrator
- [ ] Connect 4 research agents
- [ ] Test pattern discovery & approval

**Week 3:**
- [ ] Setup ChromaDB integration
- [ ] Implement nightly scheduler
- [ ] Setup cron job

**Week 4:**
- [ ] Integrate with Entry Agent
- [ ] Live testing with approved patterns
- [ ] Monitor performance + adjust weights

---

**Status:** 🟢 Ready for Implementation  
**Estimated Timeline:** 4 weeks  
**Complexity:** Medium (heavy lifting is research agents themselves)
