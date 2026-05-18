# Post-Mortem Agent Design: The Brain of Brahmand

**Status:** Design Phase — Agent Architecture Decision  
**Date:** 2026-05-15  
**Purpose:** Deep-dive specification for Post-Mortem Agent's knowledge system  
**Scope:** Strategy selection + Entry timing + Exit timing (all 3 equally)

---

## PART 1: MONOLITHIC vs SPLIT AGENTS — Comparison & Recommendation

### MONOLITHIC AGENT (One Big Agent Does Everything)

```
PostMortemAgent (single)
├─ Analyze trade: Was strategy right? ✓
├─ Analyze entry: Was timing good? ✓
├─ Analyze exit: Did we hold too long? ✓
└─ Publish to knowledge (all findings mixed)
```

#### Pros:
- **Simplicity:** One agent, one entry point, less orchestration overhead
- **Unified context:** Agent sees full trade context (strategy→entry→exit chain)
- **Smaller crew footprint:** 5 agents total instead of 7
- **Natural analysis flow:** "We chose Iron Butterfly, entered at 10:47, exited at 14:30 → here's why it worked"

#### Cons:
- **Monolithic knowledge:** All findings mixed in one collection (harder to query)
- **Role confusion:** Agent does analysis, publishing, synthesis — too many hats
- **Scaling pain:** Adding more strategies/entry signals makes knowledge harder to search
- **Knowledge reuse:** If Execution Agent wants to query "good entry signals," it gets mixed data
- **Testing nightmare:** Can't test entry analysis without running full strategy analysis

#### Example Output:
```json
{
  "trade_id": "SIM-10:47-001",
  "strategy_chosen": "IRON_BUTTERFLY",
  "strategy_analysis": {
    "regime_at_entry": "sideways",
    "adx": 22,
    "vix": 18.4,
    "was_correct": true,
    "lesson": "Iron Butterfly won vs Bull Put because ADX<25"
  },
  "entry_analysis": {
    "entry_time": "10:47",
    "entry_location": "20 ticks above pivot S1",
    "entry_signal": "EMA5 bounce off support",
    "entry_quality_score": 0.85
  },
  "exit_analysis": {
    "exit_time": "14:30",
    "exit_reason": "time-based (4-hour hold)",
    "was_optimal": true,
    "pnl": 730
  }
}
```

---

### SPLIT AGENTS (Multiple Specialized Agents)

```
StrategyPostMortemAgent
├─ Which strategy was best for this regime? ✓
└─ Publish to strategy_knowledge

EntryPostMortemAgent
├─ Was entry timing good? ✓
├─ Which entry signal worked? ✓
└─ Publish to entry_knowledge

ExitPostMortemAgent
├─ Was exit timing optimal? ✓
├─ Did we exit too early/late? ✓
└─ Publish to exit_knowledge

PortfolioPostMortemAgent (Optional)
├─ Daily drawdown, margin usage, correlation ✓
└─ Publish to portfolio_knowledge
```

#### Pros:
- **Specialized knowledge:** Each agent → one focused knowledge collection
- **Cleaner queries:** Execution Agent queries entry_knowledge (not mixed data)
- **Scalability:** Add new entry signals without touching strategy agent
- **Parallel execution:** Can run StrategyPM + EntryPM + ExitPM in parallel
- **Testability:** Test entry analysis in isolation from strategy
- **Role clarity:** Each agent has one responsibility (SRP principle)
- **Easier debugging:** "Exit strategy is wrong" → check ExitPostMortemAgent

#### Cons:
- **Coordination overhead:** 3 agents must coordinate; one can't see other's analysis
- **Larger crew:** 5 agents → 8 agents (33% increase)
- **Knowledge fragmentation:** If you need "full trade story," must query 3 agents
- **Context passing:** EntryPM needs to know what StrategyPM decided

#### Example Output (Split):
```json
{
  "strategy_pm_output": {
    "regime": "sideways",
    "strategy_chosen": "IRON_BUTTERFLY",
    "strategy_confidence": 0.85,
    "win_rate_this_regime": 0.82,
    "vs_bull_put": 0.60
  },
  "entry_pm_output": {
    "entry_time": "10:47",
    "entry_signal": "EMA5 bounce + support level",
    "entry_location_quality": 0.85,
    "entry_premium_received": 195
  },
  "exit_pm_output": {
    "exit_time": "14:30",
    "exit_reason": "time-based",
    "time_held": "3h 43m",
    "was_optimal": true,
    "profit": 730
  }
}
```

---

### RECOMMENDATION: **HYBRID Split Approach**

**Use SPLIT agents, BUT keep them loosely coupled:**

```python
# Three separate agents, can run in parallel:

class StrategyPostMortemAgent:
    """Answers: Was the strategy choice correct for the regime?"""
    def analyze_strategy(self, trade: Trade, market_conditions: Dict) -> StrategyLearning
    
class EntryPostMortemAgent:
    """Answers: Was the entry timing optimal? Which signal worked?"""
    def analyze_entry(self, trade: Trade, market_conditions: Dict) -> EntryLearning

class ExitPostMortemAgent:
    """Answers: Was the exit timing optimal? Should we have held longer/exited earlier?"""
    def analyze_exit(self, trade: Trade, market_conditions: Dict) -> ExitLearning

# Orchestrator runs all three, collects findings:

class PostMortemOrchestrator:
    def analyze_day(self, date: str):
        for trade in get_trades(date):
            strategy_learning = strategy_pm.analyze_strategy(trade, market)
            entry_learning = entry_pm.analyze_entry(trade, market)
            exit_learning = exit_pm.analyze_exit(trade, market)
            
            # Publish to respective knowledge collections
            kb.publish_strategy(strategy_learning)
            kb.publish_entry(entry_learning)
            kb.publish_exit(exit_learning)
            
            # Also save composite view to research_notes
            save_research_note(combine(strategy, entry, exit))
```

**Why hybrid works:**
- ✅ Clear roles (each agent does one thing)
- ✅ Clean knowledge (3 focused collections)
- ✅ Orchestrator provides unified context
- ✅ Can scale: add new agents without refactoring
- ✅ Parallel execution: run all 3 simultaneously
- ✅ Testable: test each agent independently

---

## PART 2: POST-MORTEM KNOWLEDGE DATABASE SCHEMA

### For IRON BUTTERFLY (Strategic Knowledge)

```python
# strategy_knowledge collection documents:

Document(
    id="ib_20260514_001",
    content="""
    Iron Butterfly analysis for 2026-05-14.
    
    Market regime: Sideways (ADX 22, VIX 18.4, SuperTrend neutral)
    Strategy chosen: IRON_BUTTERFLY
    
    Performance:
    - Net credit received: ₹195
    - Net profit: ₹730 (374% of premium)
    - TP hit: YES at 14:30 (3h 43m hold)
    - SL breach: NO
    
    Why it worked:
    - ADX 22 = true sideways (not trending)
    - VIX 18.4 = optimal for Iron Butterfly (premium decay works)
    - Wing width 200pt = perfect for liquid strikes
    - Market stayed between Pivot S1-R1 (no breakout)
    
    Comparison with alternatives:
    - Bull Put Spread: Would capture only ₹85 premium (45% less)
    - Bear Call Spread: Wrong direction; would lose
    - Iron Condor: Same profit but requires 4 wide legs (harder fills)
    
    Decision rule for next time:
    IF regime=sideways AND adx<25 AND vix<19 THEN choose IRON_BUTTERFLY
    Confidence: 0.85 (3 of 3 prior trades profitable)
    """,
    metadata={
        "type": "strategy_learning",
        "date": "2026-05-14",
        "strategy": "IRON_BUTTERFLY",
        "regime": "sideways",
        "adx": 22,
        "vix": 18.4,
        "net_credit": 195,
        "pnl": 730,
        "pnl_positive": True,
        "tp_hit": True,
        "sl_hit": False,
        "hold_time_hours": 3.7,
        "confidence_given": 0.70,
        "confidence_earned": 0.85,
        "vs_bull_put_pnl": -145,
        "timestamp": "2026-05-14T16:00:00Z"
    }
)
```

### For CREDIT SPREADS (Bull Put & Bear Call)

```python
# strategy_knowledge for Bull Put Spread:

Document(
    id="bps_20260515_001",
    content="""
    Bull Put Spread analysis for 2026-05-15.
    
    Market regime: Trending bullish (ADX 28, ST direction bullish, HH+HL)
    Strategy chosen: BULL_PUT_SPREAD
    
    Configuration:
    - Sold PE strike: 23600 (ATM-100)
    - Bought PE strike: 23300 (ATM-400, wing=300)
    - Net credit: ₹145
    - Max profit: ₹145 (100%)
    - Max loss: ₹155 (defined risk)
    
    Performance:
    - Exit: TP at 14:15 (profit ₹140)
    - Market stayed above 23600 entire day
    - No SL breach
    - Hold time: 3h 28m
    
    Why it worked:
    - SuperTrend bullish + HH structure = strong upside conviction
    - ADX 28 = strong trend; PE premium decaying on upside
    - VIX 17 = low; theta works fast
    
    Decision rule:
    IF regime=trending_bullish AND adx>25 THEN consider BULL_PUT_SPREAD
    Confidence: 0.75 (2 of 2 prior trades profitable)
    """,
    metadata={
        "type": "strategy_learning",
        "date": "2026-05-15",
        "strategy": "BULL_PUT_SPREAD",
        "regime": "trending_bullish",
        "adx": 28,
        "vix": 17,
        "st_direction": "bullish",
        "net_credit": 145,
        "pnl": 140,
        "pnl_positive": True,
        "hold_time_hours": 3.5,
        "confidence_earned": 0.75,
        "timestamp": "2026-05-15T16:00:00Z"
    }
)
```

---

## PART 3: ENTRY POST-MORTEM KNOWLEDGE SCHEMA

### Entry Signals & Quality Analysis

```python
# entry_knowledge collection documents:

Document(
    id="entry_20260514_001",
    content="""
    Entry timing analysis for Iron Butterfly at 10:47 on 2026-05-14.
    
    Entry location: 20 ticks ABOVE pivot S1 (support at 23380, entry at 23400)
    Entry signal: EMA5 (23399) just bounced off EMA20 (23391)
    Entry time: 10:47 AM
    
    Market snapshot at entry:
    - Spot: 23400
    - ADX: 22 (turning from 19 → sideways confirmed)
    - RSI: 58 (neutral zone, not overbought)
    - Bollinger Band: Price at lower band 23396 (rejection point)
    - FVG: Fair Value Gap from 23401-23405 (order block above, confluence)
    
    Entry quality assessment:
    - Support proximity: 20 ticks away = GOOD (not too far, not too tight)
    - Confluence score: EMA bounce + Support + FVG top = 3 confluences
    - Premium captured: Got ₹195 (92% of max ₹210 on this day)
    - Fill slippage: 0 ticks (instant fill, excellent liquidity at 10:47)
    - Time-of-day: 10:47 = in sweet liquidity window
    
    Entry quality rating: 4.2 / 5.0
    
    Counterfactual analysis:
    - If entered 5 min later (10:52): Spot already at 23415
      → Premium would have decayed to ₹188 (3% loss)
      → Exit would have been same TP but premium worse
    - If entered at 11:00: Spot moved to 23420
      → Premium to ₹175 (10% loss)
      → This entry would have been POOR
    
    Learning: 10:47 entry was 3-5 min perfect window. Outside this = degraded.
    
    Entry signal effectiveness:
    - EMA5 bounce: Worked 5/5 times in past 5 trades (100%)
    - Support bounce: Worked 4/5 times (80%)
    - Combined (both): Worked 4/4 times (100%, but only 4 samples)
    
    Recommendation: Always wait for EMA5 confirmation at support for entries.
    """,
    metadata={
        "type": "entry_learning",
        "date": "2026-05-14",
        "entry_time": "10:47",
        "entry_signal": "EMA5_bounce_at_support",
        "entry_location": "20_ticks_above_pivot_s1",
        "entry_quality_score": 4.2,
        "premium_captured_pct": 92,
        "fill_slippage_ticks": 0,
        "confluence_count": 3,
        "confluence_types": ["ema_bounce", "support", "fvg"],
        "entry_signal_effectiveness": 1.0,
        "confidence_learned": 0.95,
        "timestamp": "2026-05-14T16:00:00Z"
    }
)
```

### Entry Signal Registry (Learnings Over Days)

```python
# After 5 trades, Post-Mortem publishes entry patterns:

Document(
    id="entry_pattern_20260515_weekly",
    content="""
    Entry signal effectiveness summary (May 13-15, 5 trades).
    
    SIGNAL: EMA5 bounce at support
    ├─ Success count: 5/5 trades (100%)
    ├─ Avg premium captured: 93%
    ├─ Avg time to TP: 3h 45m
    ├─ Avg slippage: 0.4 ticks
    └─ Recommendation: HIGH CONFIDENCE, always use this signal
    
    SIGNAL: RSI divergence (lower low in price, higher high in RSI)
    ├─ Success count: 1/2 trades (50%)
    ├─ Avg premium captured: 78%
    ├─ Note: Not enough samples, but promising
    └─ Recommendation: MONITOR, collect more data
    
    SIGNAL: Bollinger Band bounce
    ├─ Success count: 2/3 trades (67%)
    ├─ Avg premium captured: 85%
    ├─ Caveat: Only works if RSI < 70 (overbought protection)
    └─ Recommendation: CONDITIONAL, use only with RSI filter
    
    ANTI-SIGNAL: Enter in middle of empty space (no support)
    ├─ Success count: 0/2 trades (0%)
    ├─ All lost money (premium degradation before TP)
    └─ Recommendation: NEVER do this
    
    Time-of-day analysis:
    ├─ 10:30-10:50: 4/4 excellent entries (100% quality, 0.8 avg slippage)
    ├─ 11:00-11:30: 1/1 poor entry (high slippage, wide spread)
    ├─ 12:00-13:00: No data yet
    ├─ 13:00-14:30: No data yet
    └─ Recommendation: ALWAYS enter 10:30-10:50 window, AVOID 11:00-11:30
    """,
    metadata={
        "type": "entry_pattern",
        "date": "2026-05-15",
        "signal_ema5_bounce_success_rate": 1.0,
        "signal_rsi_div_success_rate": 0.5,
        "signal_bb_bounce_success_rate": 0.67,
        "best_time_window": "10:30-10:50",
        "worst_time_window": "11:00-11:30",
        "sample_size": 5,
        "timestamp": "2026-05-15T16:00:00Z"
    }
)
```

---

## PART 4: EXIT POST-MORTEM KNOWLEDGE SCHEMA

### Exit Timing Analysis

```python
# exit_knowledge collection documents:

Document(
    id="exit_20260514_001",
    content="""
    Exit timing analysis for Iron Butterfly, held May 14 10:47-14:30.
    
    Exit decision: TIME-BASED (4-hour hold rule)
    Exit time: 14:30 (exactly 3h 43m, within 4h target)
    Exit level: TP hit at 50% premium decay (195 → 97 option value)
    
    Market conditions at exit:
    - Spot: 23410 (still within Pivot S1-R1, no breakout)
    - ADX: 21 (still sideways)
    - VIX: 18.2 (stable, no vol spike)
    - Greeks: Theta = +₹180 (decay working perfectly)
    - Resistance ahead: R1 at 23576 (176 ticks away, safe)
    
    Was this optimal?
    ✓ EXCELLENT EXIT
    Reasons:
    - TP hit = no early exit, full profit captured
    - Time-based (14:30) = before 15:00 market close (good risk management)
    - Market still cooperating (sideways, no reversal)
    - Greeks showing theta still strong (not decelerating)
    
    Counterfactual: What if we held longer?
    - 14:30 → TP at 50%: Profit ₹97.50 per lot (3 lots = ₹293)
    - 15:00 → Could have gotten more theta decay but risk of:
      ├─ Last-30-min vol spike (happens 20% of time)
      ├─ Gap at open if held overnight (Iron Butterfly exposed to gap)
      └─ Greeks decelerate (theta doesn't keep decaying at same rate)
    - 15:30+ → Hard exit, locked in whatever P&L
    
    Learning: 14:30 exit was optimal. No benefit to holding longer.
    
    Exit signal types observed in 5 trades:
    ├─ TP hit (50% decay): 4/5 trades, avg hold 3h 45m
    ├─ SL hit: 1/5 trades (unwanted exit)
    ├─ Time-based: All trades exited by 14:30
    └─ Resistance break: 0/5 trades (market didn't reach R1)
    
    Optimal exit time windows (from 5-day sample):
    ├─ 2-3 hours: 1 trade (early exit, captured only 35% of max profit)
    ├─ 3-4 hours: 3 trades (captured 85-95% of max profit) ← OPTIMAL
    ├─ 4-5 hours: 1 trade (captured 75% due to theta deceleration)
    ├─ 5+ hours: 0 trades (no samples, too risky overnight)
    └─ Rule: Exit by 3-4 hour mark, NEVER hold past 4 hours
    """,
    metadata={
        "type": "exit_learning",
        "date": "2026-05-14",
        "exit_time": "14:30",
        "exit_reason": "tp_hit",
        "time_held_hours": 3.72,
        "profit_captured_pct": 100,
        "was_optimal": True,
        "theta_at_exit": 180,
        "market_structure_at_exit": "sideways_still",
        "optimal_hold_range_hours": "3-4",
        "confidence": 0.95,
        "timestamp": "2026-05-14T16:00:00Z"
    }
)
```

### Exit Pattern Learning: Support/Resistance Breaches

```python
# exit_knowledge: Pattern analysis for exit on resistance breach

Document(
    id="exit_pattern_resistance_20260515",
    content="""
    Exit on resistance breach analysis (5-day sample).
    
    PATTERN: Enter at support, plan exit at resistance
    
    Test cases:
    Trade 1 (May 13):
    ├─ Entered at S1 (23380)
    ├─ R1 resistance at 23576
    ├─ Market moved: 23380 → 23410 (30 ticks toward R1)
    ├─ Did not reach R1 before TP hit
    └─ Result: Exited on TP, not resistance (TIME won over SPACE)
    
    Trade 2 (May 14):
    ├─ Entered at S1 (23380)
    ├─ R1 resistance at 23576
    ├─ Market moved: 23380 → 23420 (40 ticks toward R1)
    ├─ Again, TP hit before reaching R1
    └─ Result: Exited on TP, not resistance
    
    Trade 3 (May 15):
    ├─ Entered at S1 (23420)
    ├─ R1 resistance at 23600
    ├─ Market moved: 23420 → 23580 (160 ticks, approaching R1!)
    ├─ Market then pulled back (reversal at R1?)
    ├─ Exited on TP at 14:30 (before R1 breach happened)
    └─ Result: TP saved us from worse exit
    
    Pattern finding:
    ✓ For Iron Butterfly with 3-4 hour holds: TP (50% decay) ALWAYS hits before R1 resistance
    ✓ R1 is typically 150-200 ticks away; price moves 30-50 ticks in 3h
    ✓ Conclusion: Don't watch for resistance exit; just use TP timing
    
    Implication for trading rules:
    - For Iron Butterfly: Ignore resistance levels, use time-based + TP combo
    - For Bull Put Spread: Watch resistance for early exit (directional, might hit R1)
    
    Decision rule:
    IF strategy = IRON_BUTTERFLY → Use time-based + TP combo (ignore R1)
    IF strategy = BULL_PUT_SPREAD → Use resistance levels as secondary exit
    """,
    metadata={
        "type": "exit_pattern",
        "date": "2026-05-15",
        "pattern": "resistance_vs_tp",
        "strategy": "IRON_BUTTERFLY",
        "tp_hits_before_resistance_pct": 100,
        "avg_distance_to_resistance": 175,
        "avg_price_move_3h": 40,
        "recommendation": "Use TP timing, ignore resistance for IB",
        "confidence": 0.90,
        "timestamp": "2026-05-15T16:00:00Z"
    }
)
```

---

## PART 5: KNOWLEDGE GROWTH TRAJECTORY (Simple → Complex)

### Week 1: Simple Support/Resistance

```
ENTRY KNOWLEDGE:
- Enter if price within 50 ticks of Pivot S1/S2
- Quality: Yes/No (binary)

EXIT KNOWLEDGE:
- Exit at 3-4 hour hold time
- OR exit if profit > 50% of max
- Method: Simple time-based
```

### Week 2: Add EMA Confirmation

```
ENTRY KNOWLEDGE:
- EMA5 > EMA20 > EMA50 AND price at support = EXCELLENT
- EMA5 crossed EMA20 = Good
- Price at support alone = Fair
- Quality: Score 1-5

EXIT KNOWLEDGE:
- Exit at TP hit (50% decay)
- Exit at 4h if TP hasn't hit
- Watch for EMA reversal = exit signal (new)
```

### Week 3: Add Market Structure Analysis

```
ENTRY KNOWLEDGE:
- Market structure HH+HL = trend is weakening, good for Iron Butterfly
- Market structure LL+LH = reversal coming, bad entry
- Quality score includes structure health

EXIT KNOWLEDGE:
- Monitor structure_type: Are we still in HH or has it turned to HL?
- Exit if HH converts to LL (reversal detected)
- Exit on resistance if structure shows reversal (new)
```

### Week 4: Add Advanced Pattern Recognition

```
ENTRY KNOWLEDGE:
- RSI divergence: Price LL but RSI HH = reversal signal
- Fibonacci bounce levels within S1/S2 = micro-entry timing
- Order Block zones = entry with confluence

EXIT KNOWLEDGE:
- Greeks acceleration: Delta speeding up = exit before sharp move
- Theta deceleration: Decay slowing = time to exit (can't make more)
- Breakout attempts (price above R1): Exit immediately (directional risk)
```

---

## PART 6: DUCKDB COLUMNS POST-MORTEM WILL ANALYZE

### For Strategy Selection:

```
Market Data DuckDB columns:
├─ adx (trend strength 0-100)
├─ supertrend_direction (bullish/bearish/neutral)
├─ structure_type (HH, HL, LL, LH)
├─ india_vix (volatility 15-30)
├─ iv_rank (IV percentile 0-100)
├─ rsi (momentum 0-100)
├─ atr (volatility in points)
└─ session_phase (open/midday/afternoon/close)

Decision logic:
IF adx < 20 AND supertrend = neutral AND iv_rank < 60
   → IRON_BUTTERFLY (sideways, low vol)
IF adx > 25 AND supertrend = bullish AND structure = HH
   → BULL_PUT_SPREAD (strong uptrend)
```

### For Entry Analysis:

```
Market Data DuckDB columns:
├─ ema_5, ema_20, ema_50 (moving averages)
├─ pivot_s1, pivot_s2, pivot_r1, pivot_r2 (support/resistance)
├─ fib_382, fib_50, fib_618 (fibonacci levels)
├─ bb_pct_b (Bollinger Band position 0-1)
├─ rsi (momentum)
├─ open_range_high, open_range_low (OR levels)
├─ fvg_high, fvg_low (Fair Value Gap zone)
├─ ob_zone_high, ob_zone_low (Order Block)
└─ spot (current price)

Entry signal detection:
├─ Support bounce: price within 20 ticks of pivot_s1/s2
├─ EMA confluence: ema_5 > ema_20 > ema_50
├─ RSI oversold: rsi < 30 AND price bouncing (reversal)
├─ FVG rejection: price bouncing off fvg_low (inefficiency filled)
└─ Time-of-day: During high-liquidity windows (10:30-11:00)
```

### For Exit Analysis:

```
Market Data DuckDB columns:
├─ adx (trending or sideways still?)
├─ supertrend_direction (reversed?)
├─ structure_type (still HH or turned to LL?)
├─ rsi (extended? near extremes?)
├─ india_vix (vol spike = risk)
├─ pivot_r1, pivot_r2 (price approaching resistance?)
├─ agg_theta (portfolio theta: is decay still strong?)
├─ agg_delta (position delta: getting too directional?)
└─ session_phase (approaching close? after 14:30?)

Exit signal detection:
├─ Time-based: 3-4 hours passed = exit
├─ Resistance: Price reaching pivot_r1
├─ Structure break: HH pattern breaks to HL
├─ Vol spike: VIX > 20 = risk management exit
├─ Theta deceleration: Decay rate dropping (can't make more profit)
└─ Greeks danger: Delta > 0.60 (too directional for Iron Butterfly)
```

---

## PART 7: DUCKDB QUERY EXAMPLES FOR POST-MORTEM

### Strategy Decision Query

```sql
-- Post-Mortem queries: "In sideways markets, which strategy wins?"

SELECT 
    strategy,
    COUNT(*) as trade_count,
    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) / COUNT(*) as win_rate,
    AVG(pnl) as avg_pnl,
    AVG(hold_time_hours) as avg_hold_time
FROM execution_reports
WHERE 
    regime = 'sideways'
    AND adx < 25
    AND india_vix < 20
GROUP BY strategy
ORDER BY win_rate DESC;

-- Example result:
-- | strategy | trade_count | win_rate | avg_pnl | avg_hold_time |
-- |----------|-------------|----------|---------|---------------|
-- | IRON_BUTTERFLY | 5 | 0.80 | 650 | 3.7 |
-- | BULL_PUT_SPREAD | 3 | 0.67 | 520 | 3.2 |
```

### Entry Signal Effectiveness Query

```sql
-- Post-Mortem queries: "Which entry signals have highest success rate?"

SELECT 
    entry_signal,
    COUNT(*) as signal_count,
    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) / COUNT(*) as success_rate,
    AVG(premium_captured_pct) as avg_premium_pct,
    AVG(fill_slippage_ticks) as avg_slippage
FROM execution_reports
WHERE entry_signal IS NOT NULL
GROUP BY entry_signal
ORDER BY success_rate DESC;

-- Example result:
-- | entry_signal | signal_count | success_rate | avg_premium_pct | avg_slippage |
-- |--------------|--------------|--------------|-----------------|--------------|
-- | EMA5_BOUNCE | 5 | 1.00 | 0.93 | 0.4 |
-- | SUPPORT_BOUNCE | 4 | 0.75 | 0.85 | 1.2 |
-- | RSI_DIV | 2 | 0.50 | 0.78 | 2.1 |
```

### Exit Timing Optimization Query

```sql
-- Post-Mortem queries: "Is 3-4 hour hold optimal or should we adjust?"

SELECT 
    CASE 
        WHEN hold_time_hours < 2 THEN '<2h'
        WHEN hold_time_hours < 3 THEN '2-3h'
        WHEN hold_time_hours < 4 THEN '3-4h'
        ELSE '4h+'
    END as hold_bucket,
    COUNT(*) as trade_count,
    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) / COUNT(*) as win_rate,
    AVG(pnl) as avg_pnl,
    AVG(pnl) / AVG(max_profit_possible) as profit_capture_rate
FROM execution_reports
WHERE strategy = 'IRON_BUTTERFLY'
GROUP BY hold_bucket
ORDER BY profit_capture_rate DESC;

-- Example result:
-- | hold_bucket | trade_count | win_rate | avg_pnl | profit_capture_rate |
-- |-------------|-------------|----------|---------|---------------------|
-- | 3-4h | 3 | 1.00 | 680 | 0.92 |
-- | 2-3h | 1 | 1.00 | 420 | 0.65 |
-- | <2h | 0 | null | null | null |
-- | 4h+ | 1 | 0.00 | -450 | -0.85 |
```

---

## PART 8: POST-MORTEM KNOWLEDGE PUBLISHING CHECKLIST

### Daily Evening Analysis (After market close at 15:30)

For each trade executed today:

```
[ ] Strategy Analysis:
    [ ] Load trade from state.db
    [ ] Query market_data @ entry_time (regime, ADX, VIX, structure)
    [ ] Determine: Was strategy choice correct for regime?
    [ ] Publish to strategy_knowledge
    [ ] Update daily_config.json: which strategy to prefer tomorrow?

[ ] Entry Analysis:
    [ ] Query market_data @ entry_time (EMA, support/resistance, RSI)
    [ ] Analyze: Was entry at good location? Good signal? Good time?
    [ ] Calculate entry_quality_score (0-5)
    [ ] Publish to entry_knowledge
    [ ] Identify: Which entry signals worked?

[ ] Exit Analysis:
    [ ] Query market_data @ exit_time (adx, structure, vix, greeks)
    [ ] Determine: Was exit timing optimal?
    [ ] Could we have held longer? Exited earlier?
    [ ] Publish to exit_knowledge
    [ ] Identify: Optimal hold time for this regime?

[ ] Aggregate Learnings:
    [ ] Query strategy_knowledge: Which strategy winning overall?
    [ ] Query entry_knowledge: Which entry signals most reliable?
    [ ] Query exit_knowledge: What's the optimal hold time?
    [ ] Synthesize: Tomorrow's daily_config.json parameters
    [ ] Publish aggregate findings to research_notes (SQLite)

[ ] Parameter Updates (in daily_config.json):
    [ ] best_strategy (Iron Butterfly? Bull Put? Confidence score?)
    [ ] best_entry_signal (EMA bounce? Support? Combo?)
    [ ] best_entry_window (10:30-11:00? 12:00-13:00?)
    [ ] optimal_hold_time (3 hours? 4 hours?)
    [ ] sl_pct, tp_pct (any adjustments based on learnings?)
    [ ] risk_level (VIX-adjusted SL/TP?)
```

---

## PART 9: MINIMUM VIABLE POST-MORTEM (MVP)

**Start here. Add complexity incrementally.**

### MVP Scope (Week 1):

```python
class PostMortemOrchestrator:
    def analyze_day(self, date: str):
        trades = get_trades(date)
        
        for trade in trades:
            # ═══════════════════════════════════════════════════════════
            # STRATEGY ANALYSIS (Simple)
            # ═══════════════════════════════════════════════════════════
            market_at_entry = query_duckdb(
                query_type="regime",
                date=date,
                time_range=trade.entry_time
            )
            adx = float(market_at_entry.get("adx"))
            vix = float(market_at_entry.get("india_vix"))
            
            # Rule 1: Sideways (ADX < 25, VIX < 20) → Iron Butterfly wins
            was_sideways = adx < 25 and vix < 20
            strategy_correct = (trade.strategy == "IRON_BUTTERFLY" and was_sideways)
            
            kb.publish_strategy(
                strategy=trade.strategy,
                regime="sideways" if was_sideways else "trending",
                pnl=trade.pnl,
                was_correct=strategy_correct,
                lesson="Iron Butterfly won in sideways" if strategy_correct else "Wrong strategy for regime"
            )
            
            # ═══════════════════════════════════════════════════════════
            # ENTRY ANALYSIS (Simple)
            # ═══════════════════════════════════════════════════════════
            market_at_entry = query_duckdb(
                query_type="all",
                date=date,
                time_range=trade.entry_time
            )
            entry_price = float(market_at_entry.get("spot"))
            pivot_s1 = float(market_at_entry.get("pivot_s1"))
            ema5 = float(market_at_entry.get("ema_5"))
            ema20 = float(market_at_entry.get("ema_20"))
            
            # Distance to support
            distance_to_s1 = entry_price - pivot_s1
            good_location = 0 <= distance_to_s1 <= 50  # Within 50 ticks of S1
            
            # EMA alignment
            ema_bullish = ema5 > ema20
            
            # Entry quality score
            entry_quality = 5.0
            if not good_location:
                entry_quality -= 1.5
            if not ema_bullish:
                entry_quality -= 1.0
            
            kb.publish_entry(
                entry_time=trade.entry_time,
                entry_location="near_support" if good_location else "random",
                entry_quality_score=entry_quality,
                signals_aligned=ema_bullish,
                premium_captured_pct=trade.premium_captured / trade.max_premium * 100
            )
            
            # ═══════════════════════════════════════════════════════════
            # EXIT ANALYSIS (Simple)
            # ═══════════════════════════════════════════════════════════
            time_held_hours = (trade.exit_time - trade.entry_time).total_seconds() / 3600
            
            # Rule 1: Exit by 4 hours for Iron Butterfly
            optimal_hold = 3 <= time_held_hours <= 4
            
            kb.publish_exit(
                exit_time=trade.exit_time,
                hold_time_hours=time_held_hours,
                was_optimal=optimal_hold,
                profit_pct=(trade.pnl / trade.max_profit_possible) * 100
            )
        
        # ═══════════════════════════════════════════════════════════
        # SYNTHESIZE & UPDATE daily_config.json
        # ═══════════════════════════════════════════════════════════
        daily_config = {
            "date": date,
            "best_strategy": "IRON_BUTTERFLY",  # From strategy_knowledge
            "best_entry_signal": "ema5_above_ema20_at_support",
            "optimal_hold_time_hours": 3.5,
            "entry_window": "10:30-11:00",
            "exit_at_tp": True,
            "exit_at_time": "14:30"
        }
        save_daily_config(daily_config)
```

**This MVP:**
- ✓ Analyzes strategy correctness (is it right for the regime?)
- ✓ Scores entry quality (location + signal alignment)
- ✓ Verifies exit timing (was 3-4 hour hold optimal?)
- ✓ Publishes learnings to knowledge
- ✓ Updates daily_config.json for next day
- ✗ Doesn't use complex indicators yet (RSI div, FVG, OB, structure analysis)
- ✗ Doesn't distinguish between support types (Pivot vs Fib)

---

## PART 10: NEXT PHASE EXPANSION (Week 2+)

### Phase 1 (Week 1): MVP above
### Phase 2 (Week 2): Add Market Structure + RSI Analysis
```
Entry signals:
- EMA bounce + support + structure = HH (confidence++)
- EMA bounce + support + structure = HL (confidence--)

Exit signals:
- Structure reversal (HH → HL) = sell signal
- RSI extreme + structure break = sell immediately
```

### Phase 3 (Week 3): Add Fibonacci + Order Block Zones
```
Entry refinement:
- Support @ Fib 38.2% = stronger than arbitrary support
- Entry @ Fib 50% bounce = excellent confluence

Exit refinement:
- Resistance @ Fib 61.8% = watch for exit
- Market breaking Fib 61.8% = exit immediately
```

### Phase 4 (Week 4): Add Greeks-Based Signals
```
Entry:
- Greeks delta balanced (not too directional) = good entry

Exit:
- Delta accelerating (0.50 → 0.60) = exit before sharp move
- Theta decelerating = can't make more money, exit
```

---

## CONCLUSION: Your Brain (Post-Mortem) Roadmap

**Week 1 (MVP):** Strategy + Entry location + Exit timing  
**Week 2:** Add structure analysis + momentum confirmation  
**Week 3:** Add Fibonacci + Order Block zones  
**Week 4:** Add Greeks-based decision making  

**By Week 4:** Brahmand's Post-Mortem Agent becomes genuinely intelligent, learning from experience and improving decisions daily.

---

**Status: Ready for MVP implementation 🚀**

**Next:** Implement `PostMortemOrchestrator` class from Part 9 above.
