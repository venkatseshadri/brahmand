# BRAHMAND BUILD SPECIFICATION - Ready for DeepSeek Implementation

**Status:** Complete specification with all decisions made  
**Date:** 2026-05-15  
**Owner:** DeepSeek  
**Objective:** Build the complete Post-Mortem Agent knowledge system + Planning agents

---

## PART A: BLOCKING QUESTIONS ANSWERED

### Q1: Data Capture in state.db (Entry)
**Answer:** Just store: `time, price, qty, contract`
- Full market data captured by datacapture script
- Post-Mortem Agent queries DuckDB by time + contract to get correlations
- Design: Keep state.db minimal; DuckDB is source of truth

### Q2: Data Capture in state.db (Exit)
**Answer:** Just store: `time, price, qty, contract`
- Same approach as entry
- Post-Mortem Agent correlates exit time + contract against DuckDB market data
- Design: Minimal trade record; rich context from DuckDB joins

### Q3: Strategy Decision Logic
**Answer:** Multi-factor (but research should continue exploring!)
```
Strategy Planning Agent should score:
├─ Win-rate (Iron Butterfly 82% vs Bull Put 60%)
├─ Entry signal reliability (which signals work for this strategy?)
├─ Exit timing success (does this strategy reach TP consistently?)
├─ Greek suitability (is portfolio delta balanced?)
├─ Current VIX vs historical (adjust strategy by vol regime)
└─ Market structure health (HH trend vs deteriorating HL)

Score = Weighted average of above factors
Pick strategy with highest score

BUT: Research shouldn't stop there!
├─ Explore new strategies as win-rates improve
├─ Discover new entry signal combinations
├─ Learn Greeks-based exit triggers
└─ Keep innovating based on learnings
```

---

## PART B: ARCHITECTURE DECISIONS

### Agent Structure (FINAL):

**PHASE 1: PRE-MARKET PLANNING (09:15 AM)**
```python
# 7 agents run sequentially, each outputs to next
Regime Agent 
  → Strategy Planning Agent (NEW)
  → Entry Planning Agent (NEW)
  → Exit Planning Agent (NEW)
  → Risk Agent (adapted)
  → Daily Plan Synthesizer Agent (NEW)
  → Output: daily_trade_plan.json
```

**PHASE 2: INTRADAY (every 5 min)**
```python
Regime Monitor (NEW)
  → (If regime changed, trigger replan)
Execution Agent
Risk Agent
```

**PHASE 3: POST-MARKET (16:00 PM)**
```python
StrategyPostMortemAgent (NEW)
EntryPostMortemAgent (NEW)
ExitPostMortemAgent (NEW)
Daily Config Updater (NEW)
  → Output: daily_config.json (for tomorrow's planning)
  → Output: research_notes (for knowledge system)
```

---

## PART C: NEW FILES TO CREATE

### 1. `/home/trading_ceo/brahmand/planning/strategy_planner.py`
```python
class StrategyPlanningAgent:
    """Plans which strategy to use based on market regime + learnings."""
    
    def __init__(self):
        self.kb = BrahmandKnowledge()  # Access to strategy_knowledge
    
    def plan_strategy(self, market_regime: str, market_data: dict) -> dict:
        """
        Input: 
        - market_regime (from Regime Agent): "sideways" / "trending_bullish" / "trending_bearish"
        - market_data: VIX, ADX, IV rank, structure type
        
        Process:
        1. Query strategy_knowledge: "Which strategies won in this regime?"
        2. Score each strategy:
           - win_rate: % of profitable trades
           - entry_signal_reliability: do recommended entry signals work?
           - exit_timing_success: does this strategy reach TP consistently?
           - greek_suitability: is delta/gamma balanced for this strategy?
           - vix_adjustment: adjust by current VIX vs historical
           - market_structure: HH (strong) vs HL (weakening)
        3. Pick highest-scoring strategy
        4. Attach confidence score and rationale
        
        Output: {
            "strategy": "IRON_BUTTERFLY",
            "confidence": 0.85,
            "score_breakdown": {
                "win_rate": 0.82,
                "entry_signal_reliability": 0.90,
                "exit_success": 0.88,
                "greek_suitability": 0.80,
                "vix_adjustment": 0.95,
                "market_structure": 0.85
            },
            "rationale": "Iron Butterfly scored 0.85 (highest). 82% win-rate in sideways regimes, entry signals 90% reliable, exits TP 88% of time."
        }
        """
        pass  # DeepSeek to implement
```

### 2. `/home/trading_ceo/brahmand/planning/entry_planner.py`
```python
class EntryPlanningAgent:
    """Plans which entry signals to use + entry window."""
    
    def plan_entry(self, strategy: str, regime: str, market_data: dict) -> dict:
        """
        Input:
        - strategy: "IRON_BUTTERFLY" (from Strategy Planning Agent)
        - regime: "sideways"
        - market_data: Current market conditions
        
        Process:
        1. Query entry_knowledge: "Which signals work for Iron Butterfly?"
        2. Score each entry signal:
           - success_rate: % of profitable entries using this signal
           - premium_captured: average % of max premium captured
           - slippage: average fill slippage in ticks
           - time_of_day: which hours have best fills?
           - confluence: combining 2+ signals (EMA + support) = higher score
        3. Rank signals by score
        4. Recommend primary signal + backup signals
        
        Output: {
            "primary_signal": "ema5_bounce_at_support",
            "backup_signals": ["rsi_divergence", "fvg_pullback"],
            "entry_window": "10:30-11:00",
            "entry_window_backup": "11:15-11:45",
            "quality_target": 4.5,  # Min quality score for entry to trigger
            "premium_target": 190,   # Target net credit
            "confluence_required": 2,  # Require at least 2 signals aligning
            "confidence": 0.90,
            "rationale": "EMA5 bounce at support works 100% (5/5). Time window 10:30-11:00 has 0 avg slippage."
        }
        """
        pass  # DeepSeek to implement
```

### 3. `/home/trading_ceo/brahmand/planning/exit_planner.py`
```python
class ExitPlanningAgent:
    """Plans exit conditions + optimal hold time."""
    
    def plan_exit(self, strategy: str, regime: str, market_data: dict) -> dict:
        """
        Input:
        - strategy: "IRON_BUTTERFLY"
        - regime: "sideways"
        - market_data: Current VIX, ADX, structure
        
        Process:
        1. Query exit_knowledge: "For Iron Butterfly in sideways, what's optimal exit?"
        2. Score exit methods:
           - Time-based: Hold 3-4 hours, capture 90% profit
           - TP hit: 50% premium decay, 92% success rate
           - Resistance: Price at R1, 30% success rate (rare)
           - Structure break: HH→HL, early exit trigger
           - Greeks: Delta acceleration, theta deceleration
        3. Recommend primary + secondary exit triggers
        
        Output: {
            "optimal_hold_hours": 3.5,
            "exit_triggers_primary": ["tp_50_percent_decay"],
            "exit_triggers_secondary": ["time_based_14:30", "structure_reversal"],
            "profit_target_percent": 0.92,  # Expect to capture 92% of max
            "confidence": 0.95,
            "avoid_triggers": ["resistance_level"],  # R1 rarely reached before TP
            "rationale": "3-4 hour hold optimal for Iron Butterfly. TP hit at 50% decay 92% reliable."
        }
        """
        pass  # DeepSeek to implement
```

### 4. `/home/trading_ceo/brahmand/planning/daily_plan_synthesizer.py`
```python
class DailyPlanSynthesizerAgent:
    """Combines all planning agents' outputs → daily_trade_plan.json"""
    
    def synthesize_plan(self, 
        regime_output: dict,
        strategy_output: dict,
        entry_output: dict,
        exit_output: dict,
        risk_output: dict) -> dict:
        """
        Input: Outputs from 5 agents
        
        Output: {
            "date": "2026-05-15",
            "timestamp_created": "2026-05-15T09:15:00Z",
            
            "market_regime": {
                "classification": "sideways",
                "confidence": 0.85,
                "adx": 22,
                "vix": 18.4,
                "structure": "LL+HH_consolidating"
            },
            
            "strategy_plan": {
                "strategy": "IRON_BUTTERFLY",
                "confidence": 0.85,
                "score": 0.845,
                "rationale": "Iron Butterfly scored 0.85 (highest). 82% win-rate in sideways regimes."
            },
            
            "entry_plan": {
                "primary_signal": "ema5_bounce_at_support",
                "entry_window": "10:30-11:00",
                "quality_target": 4.5,
                "premium_target": 190
            },
            
            "exit_plan": {
                "optimal_hold_hours": 3.5,
                "exit_triggers": ["tp_50_percent_decay", "time_14:30"],
                "profit_target_percent": 0.92
            },
            
            "risk_plan": {
                "sl_pct": 0.30,  # Learned from risk_knowledge
                "tp_pct": 0.50,
                "max_drawdown": 4500,
                "margin_cap": 500000
            },
            
            "contracts": [
                "NIFTY12MAY26C23650",  # SELL ATM CE
                "NIFTY12MAY26P23650",  # SELL ATM PE
                "NIFTY12MAY26C23850",  # BUY OTM CE
                "NIFTY12MAY26P23450"   # BUY OTM PE
            ],
            
            "execution_sequence": [
                {"order": 1, "contract": "NIFTY12MAY26C23650", "action": "SELL"},
                {"order": 2, "contract": "NIFTY12MAY26P23650", "action": "SELL"},
                {"order": 3, "contract": "NIFTY12MAY26C23850", "action": "BUY"},
                {"order": 4, "contract": "NIFTY12MAY26P23450", "action": "BUY"}
            ]
        }
        """
        pass  # DeepSeek to implement
```

### 5. `/home/trading_ceo/brahmand/learning/strategy_postmortem.py`
```python
class StrategyPostMortemAgent:
    """Analyzes: Was the strategy choice correct for the regime?"""
    
    def analyze_strategy(self, trade: dict, market_data_at_entry: dict) -> dict:
        """
        Input:
        - trade: {strategy: "IRON_BUTTERFLY", entry_time, exit_time, pnl, ...}
        - market_data_at_entry: From DuckDB @ entry_time (ADX, VIX, structure, etc.)
        
        Analyze:
        1. What was the regime at entry? (sideways, trending_bullish, trending_bearish)
        2. Was the chosen strategy correct for that regime?
        3. Did the trade profit or lose?
        4. If profitable: "This strategy works for this regime" → confidence++
        5. If loss: "This strategy failed for this regime" → confidence-- OR "Bad entry/exit, not strategy"
        
        Output: {
            "trade_id": "SIM-10:47-001",
            "strategy": "IRON_BUTTERFLY",
            "regime_at_entry": "sideways",
            "was_correct": true,
            "pnl": 730,
            "lesson": "Iron Butterfly correct for ADX=22, VIX=18.4, sideways regime",
            "confidence_earned": 0.85
        }
        
        Publish to: strategy_knowledge
        """
        pass  # DeepSeek to implement
```

### 6. `/home/trading_ceo/brahmand/learning/entry_postmortem.py`
```python
class EntryPostMortemAgent:
    """Analyzes: Was the entry timing optimal? Which signal worked?"""
    
    def analyze_entry(self, trade: dict, market_data_at_entry: dict) -> dict:
        """
        Input:
        - trade: {entry_time, entry_price, contract, premium_received, slippage, ...}
        - market_data_at_entry: From DuckDB @ entry_time
        
        Analyze:
        1. Distance from support (pivot_s1 / fib levels): 20 ticks = good, 100 ticks = poor
        2. EMA alignment at entry: EMA5 > EMA20 > EMA50 = excellent
        3. RSI level: 30-70 = neutral, <30 or >70 = extreme (good for reversal)
        4. Premium captured: 90% of max = good, 60% = poor
        5. Fill slippage: 0-1 ticks = excellent, 4+ = poor
        6. Time-of-day: 10:30-11:00 = best liquidity
        
        Output: {
            "trade_id": "SIM-10:47-001",
            "entry_signal": "ema5_bounce_at_support",
            "entry_quality_score": 4.5,
            "premium_captured_pct": 92,
            "slippage_ticks": 0,
            "confluence_count": 2,  # EMA bounce + support
            "lesson": "EMA5 bounce at support works 100%. Time 10:47 in sweet window.",
            "confidence_earned": 0.95
        }
        
        Publish to: entry_knowledge
        """
        pass  # DeepSeek to implement
```

### 7. `/home/trading_ceo/brahmand/learning/exit_postmortem.py`
```python
class ExitPostMortemAgent:
    """Analyzes: Was the exit timing optimal? Should we hold longer/shorter?"""
    
    def analyze_exit(self, trade: dict, market_data_at_exit: dict) -> dict:
        """
        Input:
        - trade: {entry_time, exit_time, entry_price, exit_price, pnl, max_profit, ...}
        - market_data_at_exit: From DuckDB @ exit_time
        
        Analyze:
        1. Time held: 3.7 hours = optimal for Iron Butterfly
        2. Profit captured: Captured 92% of max possible = excellent
        3. Exit reason: TP hit (50% decay) = good vs SL hit = bad
        4. Market at exit: Still sideways (ADX=21) or reversed (ADX=28)?
        5. Counterfactual: What if held 1 more hour?
        
        Output: {
            "trade_id": "SIM-10:47-001",
            "hold_time_hours": 3.7,
            "profit_captured_pct": 92,
            "was_optimal": true,
            "exit_reason": "tp_hit",
            "lesson": "3-4 hour hold optimal for Iron Butterfly. Exiting at TP perfect.",
            "confidence_earned": 0.95
        }
        
        Publish to: exit_knowledge
        """
        pass  # DeepSeek to implement
```

### 8. `/home/trading_ceo/brahmand/learning/daily_config_updater.py`
```python
class DailyConfigUpdaterAgent:
    """Synthesizes post-mortem learnings → updates daily_config.json for tomorrow."""
    
    def update_config(self, 
        strategy_findings: list,
        entry_findings: list,
        exit_findings: list) -> dict:
        """
        Input: 
        - Analyzed trades from today (3 post-mortem agents)
        
        Synthesize:
        1. Did Iron Butterfly win again today? (confidence += 0.05)
        2. Which entry signals worked best?
        3. Was 3-4 hour hold still optimal?
        4. Did SL% need adjustment?
        
        Output: daily_config.json for tomorrow
        {
            "date": "2026-05-16",
            "strategy_preference": {
                "IRON_BUTTERFLY": {
                    "win_rate": 0.82,
                    "confidence": 0.85,
                    "samples": 5
                },
                "BULL_PUT_SPREAD": {
                    "win_rate": 0.60,
                    "confidence": 0.65,
                    "samples": 3
                }
            },
            "entry_signals": {
                "ema5_bounce_at_support": {"success_rate": 1.0, "samples": 5},
                "rsi_divergence": {"success_rate": 0.5, "samples": 2}
            },
            "optimal_entry_window": "10:30-11:00",
            "optimal_hold_hours": 3.5,
            "risk_params": {
                "sl_pct": 0.30,
                "tp_pct": 0.50
            },
            "telegram_alert": "SL optimization confirmed: 30% prevents breaches in low-VIX markets."
        }
        """
        pass  # DeepSeek to implement
```

---

## PART D: IMPLEMENTATION SEQUENCE

### Week 1: Foundation (Planning Agents)
1. Create `/brahmand/planning/` directory
2. Implement `strategy_planner.py`
3. Implement `entry_planner.py`
4. Implement `exit_planner.py`
5. Implement `daily_plan_synthesizer.py`
6. Test: Does daily_trade_plan.json generate correctly?

### Week 2: Learning Agents
1. Create `/brahmand/learning/` directory
2. Implement `strategy_postmortem.py`
3. Implement `entry_postmortem.py`
4. Implement `exit_postmortem.py`
5. Implement `daily_config_updater.py`
6. Test: Do agents publish to knowledge correctly?

### Week 3: Integration
1. Wire planning agents into Phase 1 (pre-market)
2. Wire learning agents into Phase 3 (post-market)
3. Adapt Execution/Risk agents to READ daily_trade_plan.json
4. Test: Full 1-hour dry run

### Week 4: Validation
1. Run 5 consecutive trading days
2. Measure: Do learnings improve day-by-day?
3. Metrics: Strategy confidence, entry quality, exit timing

---

## PART E: DUCKDB QUERIES NEEDED

```python
# Strategy Planning Agent queries strategy_knowledge
SELECT strategy, win_rate, sample_count
FROM strategy_knowledge
WHERE regime = 'sideways'
ORDER BY win_rate DESC

# Entry Planning Agent queries entry_knowledge
SELECT entry_signal, success_rate, avg_premium_captured
FROM entry_knowledge
WHERE strategy = 'IRON_BUTTERFLY'
ORDER BY success_rate DESC

# Exit Planning Agent queries exit_knowledge
SELECT hold_time_hours, profit_capture_pct, was_optimal
FROM exit_knowledge
WHERE strategy = 'IRON_BUTTERFLY'
ORDER BY profit_capture_pct DESC
```

---

## PART F: KNOWLEDGE COLLECTIONS STRUCTURE

```python
# strategy_knowledge documents
{
    "date": "2026-05-14",
    "strategy": "IRON_BUTTERFLY",
    "regime": "sideways",
    "pnl": 730,
    "was_correct": true,
    "confidence_earned": 0.85
}

# entry_knowledge documents
{
    "date": "2026-05-14",
    "entry_signal": "ema5_bounce_at_support",
    "entry_quality": 4.5,
    "premium_captured_pct": 92,
    "success": true,
    "confidence_earned": 0.95
}

# exit_knowledge documents
{
    "date": "2026-05-14",
    "hold_hours": 3.7,
    "profit_captured_pct": 92,
    "was_optimal": true,
    "confidence_earned": 0.95
}
```

---

## PART G: daily_config.json EVOLUTION

**Day 1 (May 14):** Bootstrap with defaults
```json
{
    "strategy_preference": {"IRON_BUTTERFLY": 0.50, "BULL_PUT": 0.50},
    "entry_window": "10:30-12:00",
    "optimal_hold_hours": 4.0,
    "sl_pct": 0.25
}
```

**Day 2 (May 15):** After learning from Day 1
```json
{
    "strategy_preference": {"IRON_BUTTERFLY": 0.82, "BULL_PUT": 0.60},
    "entry_window": "10:30-11:00",  # Refined!
    "optimal_hold_hours": 3.7,      # Learned!
    "sl_pct": 0.30                  # Optimized!
}
```

**Days 3-5:** Keep improving

---

**Ready for DeepSeek to build! All blockers answered, architecture decided, code templates provided.**

