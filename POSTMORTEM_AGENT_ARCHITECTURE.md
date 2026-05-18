# Post-Mortem Agent Architecture: Monolithic vs Split — Full Comparison

**Status:** Decision Framework  
**Date:** 2026-05-15  
**Purpose:** Show complete pros/cons of each approach so you can decide

---

## ARCHITECTURE OPTION 1: MONOLITHIC (One Big Agent)

```
PostMortemAgent (single)
├─ Does: Everything
│  ├─ Analyzes strategy correctness
│  ├─ Analyzes entry quality
│  ├─ Analyzes exit timing
│  ├─ Synthesizes findings
│  └─ Publishes to knowledge
└─ Output: One knowledge_collection with all findings
```

### Pros of Monolithic:

#### 1. **Unified Context** ✅
Agent sees full trade journey in one place:
```
PostMortemAgent reasoning:
"This trade chose IRON_BUTTERFLY (right choice for sideways ADX=22)
 Entered at 10:47 near Pivot S1 (good entry)
 Held 3h 45m and exited at TP (optimal exit)
 Everything aligned perfectly → pnl +730₹ ✓
 
 This was a TEXTBOOK trade. Next time: repeat this exact playbook."
```

#### 2. **Simple Orchestration** ✅
```python
# Simple: Just one agent
post_mortem = PostMortemAgent()
post_mortem.kickoff(trades_today)  # Done!

# vs. split would be more complex
strategy_pm = StrategyPostMortemAgent()
entry_pm = EntryPostMortemAgent()
exit_pm = ExitPostMortemAgent()
# ... coordinate outputs
```

#### 3. **Smaller Crew Size** ✅
```
Monolithic:
├─ Execution Agent
├─ Risk Agent
├─ PostMortem Agent (1)
└─ Total: 3 agents + 0 overhead

vs. Split:
├─ Execution Agent
├─ Risk Agent
├─ Strategy PostMortem Agent
├─ Entry PostMortem Agent
├─ Exit PostMortem Agent
└─ Total: 5 agents + coordination overhead
```

#### 4. **Easier Knowledge Reuse for Composite Queries** ✅
```python
# Want to understand: "Why did this trade fail?"
# One agent, one knowledge collection
results = kb.knowledge.search(
    query="Iron Butterfly entry at support exit at 14:30 failed",
    filters={"pnl": {"<": 0}}
)
# Gets full story: strategy + entry + exit all in one document
```

#### 5. **Simpler Debugging** ✅
```
If trade failed:
"Why?" → Check PostMortem Agent logs
"What did it find?" → Read one knowledge collection
"How to fix?" → One agent to update

vs. Split:
"Why?" → Check StrategyPM? EntryPM? ExitPM? All three?
"What did it find?" → Read strategy_knowledge? entry_knowledge? exit_knowledge?
"How to fix?" → Update which agent?
```

### Cons of Monolithic:

#### 1. **Knowledge Fragmentation (Mixed Concerns)** ❌
```
knowledge_collection documents are messy:
├─ "Iron Butterfly strategy was correct for regime"
├─ "Entry at support was good quality"
├─ "Exit hold time was optimal"
├─ "But SL was too tight"
├─ "Profit velocity was slow"
└─ All mixed together!

When Execution Agent queries:
"What are good entry signals?" 
→ Gets results mixed with strategy analysis
→ Has to filter and parse mixed data
→ Harder to extract clean signal
```

#### 2. **Role Ambiguity** ❌
Agent tries to do too much:
```
PostMortemAgent responsibilities:
├─ Expert strategist (knows which strategy for which regime)
├─ Entry timing specialist (knows best entry signals)
├─ Exit timing specialist (knows optimal hold times)
├─ Data analyst (queries DuckDB)
├─ Decision synthesizer (combines findings)
├─ Knowledge publisher (writes to CrewAI Knowledge)
└─ Config updater (updates daily_config.json)

Result: Agent is confused about its primary responsibility
"Am I a strategy expert? Or entry expert? Or exit expert?"
```

#### 3. **Scaling Pain** ❌
```
Day 1: Analyze Iron Butterfly
Day 5: Add Credit Spreads
Day 10: Add Iron Condor

New entry signals discovered:
- RSI divergence works great
- Fibonacci zones work great
- Order Block confluences work great

Problem: Agent output grows bloated
knowledge_collection becomes messy with all strategies + signals mixed

Now to find:
"Which signals work for Bull Put Spreads?"
→ Have to filter out Iron Butterfly findings
→ Have to filter out Iron Condor findings
→ Results polluted
```

#### 4. **Testing Nightmare** ❌
```python
# Can I test entry analysis without running strategy analysis?
# NO - they're in same agent

# Can I test exit timing without evaluating entry quality?
# NO - they're in same agent

# Result: Can't unit test each component
# Have to run full trade analysis every time
# Slow feedback loop, brittle tests
```

#### 5. **Knowledge Pollution** ❌
```
When Execution Agent queries entry signals:
results = kb.search("good entry signals")

Gets back 100 documents like:
├─ "Iron Butterfly was right strategy, entry at support"
├─ "Bull Put Spread wrong strategy, still entered, exit was good"
├─ "Entry signal worked but strategy was wrong"
├─ "Strategy correct but entry signal failed"
└─ Mixed signal! Can't extract clean "entry signal" knowledge

Execution Agent confused:
"Should I use this entry signal or not? 
 50% of results say yes, 50% say no,
 But half are about strategy, not entry!"
```

#### 6. **Difficult to Debug Problems** ❌
```
Trade lost money. Why?
├─ Was strategy wrong for regime?
├─ Was entry at poor location?
├─ Was exit timing bad?

With monolithic agent, one document says all three:
"Strategy: correct, Entry: good, Exit: poor, Profit: -200₹"

But which caused the loss? All three matter. Hard to isolate.

With split agents: 
Strategy PM: "Strategy was correct ✓"
Entry PM: "Entry was good ✓"
Exit PM: "Exit timing was poor ✗ ← This caused loss"

Clear attribution!
```

---

## ARCHITECTURE OPTION 2: SPLIT (Three Specialized Agents)

```
StrategyPostMortemAgent
├─ ONLY answers: "Was strategy choice correct?"
└─ Publishes to: strategy_knowledge

EntryPostMortemAgent
├─ ONLY answers: "Was entry timing good?"
└─ Publishes to: entry_knowledge

ExitPostMortemAgent
├─ ONLY answers: "Was exit timing optimal?"
└─ Publishes to: exit_knowledge

PostMortemOrchestrator
├─ Runs all 3 in parallel
├─ Coordinates outputs
└─ Updates daily_config.json
```

### Pros of Split:

#### 1. **Clean Knowledge Collections** ✅
```
strategy_knowledge documents:
├─ "Iron Butterfly correct for ADX=22, VIX=18"
├─ "Bull Put Spread correct for trending bullish"
└─ "Iron Condor correct for high VIX"

entry_knowledge documents:
├─ "EMA5 bounce at support works 100%"
├─ "RSI divergence works 67%"
├─ "FVG bounce works 80%"
└─ "Time window 10:30-11:00 best"

exit_knowledge documents:
├─ "3-4 hour hold optimal for Iron Butterfly"
├─ "Exit at R1 resistance works for spreads"
├─ "SL breach exit loses money"
└─ "Time-based exit at 14:30 is safe"

When Execution Agent queries:
"Give me good entry signals"
→ Gets ONLY entry signals (no strategy noise)
→ Clean, focused results
```

#### 2. **Single Responsibility Per Agent** ✅
```
StrategyPostMortemAgent: "Am I a strategy expert?"
→ YES, that's my ONLY job

EntryPostMortemAgent: "Am I an entry expert?"
→ YES, that's my ONLY job

ExitPostMortemAgent: "Am I an exit expert?"
→ YES, that's my ONLY job

Result: Clear roles, focused responsibility, no confusion
```

#### 3. **Scalability** ✅
```
Day 5: Discover RSI divergence works great for entries
→ Update EntryPostMortemAgent (add RSI analysis)
→ Other agents unaffected ✓

Day 10: Add new strategy (Ratio Spreads)
→ Update StrategyPostMortemAgent
→ Entry/Exit agents unaffected ✓

Day 20: Discover Greeks-based exit signals
→ Update ExitPostMortemAgent
→ Strategy/Entry agents unaffected ✓

New features don't pollute existing knowledge!
```

#### 4. **Testability** ✅
```python
# Test entry analysis in isolation
def test_entry_postmortem():
    analyzer = EntryPostMortemAgent()
    result = analyzer.analyze_entry(
        entry_time="10:47",
        entry_location="near_support",
        entry_signal="ema5_bounce"
    )
    assert result.entry_quality_score > 4.0
    # ✓ Can test without running strategy or exit analysis

# Test exit analysis in isolation
def test_exit_postmortem():
    analyzer = ExitPostMortemAgent()
    result = analyzer.analyze_exit(
        hold_time=3.7,
        profit_captured=0.92
    )
    assert result.was_optimal == True
    # ✓ Can test without running strategy or entry analysis

# Fast feedback loop!
```

#### 5. **Parallel Execution** ✅
```
Monolithic:
├─ Analyze strategy (1 second)
├─ Analyze entry (1 second)
├─ Analyze exit (1 second)
├─ Synthesize (1 second)
└─ Total: 4 seconds

Split (with orchestrator running in parallel):
├─ StrategyPM (1 second) ─┐
├─ EntryPM (1 second)    ├─ Run in parallel = 1 second total!
├─ ExitPM (1 second)     ─┤
└─ Orchestrator synthesis (0.5 seconds)
└─ Total: 1.5 seconds (3x faster!)

For 100 trades/day:
├─ Monolithic: 400 seconds = 6.6 minutes
├─ Split: 150 seconds = 2.5 minutes
└─ Saves 4+ minutes daily!
```

#### 6. **Clear Problem Attribution** ✅
```
Trade lost money. Why?

Split agents provide clear answer:
Strategy PM: "Strategy was correct ✓"
Entry PM: "Entry was good ✓"
Exit PM: "Exit was POOR ✗ ← Problem here!"

Conclusion: Fix exit logic, not strategy or entry
→ Easy to debug and improve

Monolithic would say:
"Overall trade analysis: unsuccessful"
→ Doesn't tell you which component failed
→ Hard to know what to fix
```

#### 7. **Knowledge Reuse Without Pollution** ✅
```
When any agent queries knowledge:

Execution Agent:
"Give me good entry signals"
→ kb.query(entry_knowledge, "good entry signals")
→ Gets ONLY clean entry signal results ✓

Strategy Agent:
"What's the best strategy for this regime?"
→ kb.query(strategy_knowledge, "regime sideways")
→ Gets ONLY clean strategy results ✓

Risk Agent:
"What exit signals have low SL hit rate?"
→ kb.query(exit_knowledge, "exit signal no sl_hit")
→ Gets ONLY clean exit results ✓

No cross-contamination!
```

### Cons of Split:

#### 1. **Coordination Overhead** ❌
```python
# Must coordinate three agents

orchestrator = PostMortemOrchestrator()
for trade in trades:
    # Run all three
    strategy_result = strategy_pm.analyze(trade)
    entry_result = entry_pm.analyze(trade)
    exit_result = exit_pm.analyze(trade)
    
    # Combine results
    combined = {
        "strategy": strategy_result,
        "entry": entry_result,
        "exit": exit_result,
        "overall_trade_quality": combine_all_three(...)
    }
    
    # Publish separately
    kb.publish_strategy(strategy_result)
    kb.publish_entry(entry_result)
    kb.publish_exit(exit_result)

# vs. Monolithic: just call one agent
pm.analyze_trade(trade)  # Done!
```

#### 2. **Larger Crew** ❌
```
5 agents → 8 agents (60% larger crew)

More agents = more complexity:
├─ More imports
├─ More initialization
├─ More tool definitions
├─ More orchestration logic
├─ More potential failure points

Memory footprint: 60% larger
Startup time: 60% slower
```

#### 3. **Knowledge Fragmentation for Composite Queries** ❌
```
Want to understand: "Why did this trade fail?"
→ Have to query 3 different collections

strategy_knowledge: "Strategy was correct"
entry_knowledge: "Entry was good"
exit_knowledge: "Exit timing was poor"

Have to stitch together results manually:
"So, correct strategy, good entry, but poor exit...
 That's why the trade failed."

vs. Monolithic would give you one document with full story
```

#### 4. **Each Agent Missing Context from Others** ❌
```
EntryPostMortemAgent analyzes entry:
"Entry was at good support level with EMA confirmation"
→ Rates it 4.5/5

But EntryPM doesn't know:
"Oh, the strategy chosen was wrong for this regime"
→ Should entry rating be lower? (good entry on bad strategy = still bad)

ExitPostMortemAgent analyzes exit:
"Exited at TP after 3.7 hours"
→ Rates it as optimal

But ExitPM doesn't know:
"Oh, the entry signal was weak (60% confidence)"
→ Should exit have been earlier?

Result: Agents make decisions in isolation, missing bigger picture
```

#### 5. **Difficulty Finding "Full Trade Story"** ❌
```
User asks: "Show me examples of GREAT trades"

With split agents:
Strategy PM: "Iron Butterfly correct for regime"
Entry PM: "Entry at support with EMA bounce"
Exit PM: "Held 3.7 hours, exited at TP"

Have to manually find trades where ALL THREE are "great"
Complex query across 3 collections

With monolithic:
"Find trades where strategy + entry + exit all rated 5/5"
→ Query one collection
→ Done!
```

---

## ARCHITECTURE OPTION 3: SPLIT + PORTFOLIO (Four Agents)

```
StrategyPostMortemAgent
EntryPostMortemAgent
ExitPostMortemAgent
PortfolioPostMortemAgent ← New!
├─ Answers: "How's the portfolio health today?"
├─ Analyzes: Daily drawdown, margin usage, win rate, Sharpe ratio
└─ Publishes to: portfolio_knowledge
```

### Additional Pros:
- ✅ Can detect "I had 3 winning trades but one SL breach ruined the day"
- ✅ Can track portfolio Greeks (delta, gamma, vega) across all open trades
- ✅ Can identify "concentration risk" (all trades same direction)
- ✅ Can learn: "What's the optimal number of simultaneous trades?"

### Additional Cons:
- ❌ Even larger crew (4 agents)
- ❌ More coordination overhead
- ❌ Portfolio analysis needs access to live positions (not just completed trades)

---

## QUICK COMPARISON TABLE

| Dimension | Monolithic | Split 3 | Split 4 + Portfolio |
|-----------|-----------|---------|-------------------|
| **Code Clarity** | ❌ Messy | ✅ Clean | ✅✅ Cleanest |
| **Testability** | ❌ Brittle | ✅ Unit-testable | ✅✅ Fully testable |
| **Scalability** | ❌ Hard | ✅ Easy | ✅✅ Easiest |
| **Knowledge Reuse** | ❌ Polluted | ✅ Clean | ✅✅ Very clean |
| **Execution Speed** | ❌ 4s | ✅ 1.5s | ✅ 2s |
| **Crew Size** | ✅ Small (3) | ❌ Medium (5) | ❌ Large (6) |
| **Orchestration Complexity** | ✅ Simple | ⚠️ Moderate | ❌ Complex |
| **Full Trade Context** | ✅ One doc | ⚠️ 3 docs | ⚠️ 4 docs |
| **Problem Attribution** | ❌ Hard | ✅ Easy | ✅✅ Very easy |
| **Debugging** | ❌ Painful | ✅ Simple | ✅✅ Very simple |

---

## DECISION MATRIX: Which Should YOU Use?

### Use MONOLITHIC if:
```
You want:
├─ Maximum simplicity
├─ Minimum code
├─ Quick prototype (MVP in 1 week)
└─ Don't care about scaling later

Tradeoff: Knowledge becomes messy, hard to test, hard to expand

Good for: Quick MVP to test if the whole idea works
```

### Use SPLIT 3 AGENTS if:
```
You want:
├─ Clean separation of concerns
├─ Easy to test each component
├─ Easy to add new signals/strategies
├─ Fast execution (parallel agents)
└─ Clear knowledge reuse by other agents

Tradeoff: More code, more orchestration, slightly more complex setup

Good for: Production system that needs to scale and evolve
Recommended for Brahmand!
```

### Use SPLIT 4 AGENTS if:
```
You want:
├─ Everything from Split 3
├─ Plus portfolio-level insights
├─ Plus risk management across all trades
├─ Plus "whole account" learning

Tradeoff: Larger crew, more orchestration, more complex

Good for: Advanced system with portfolio management needs
```

---

## RECOMMENDATION FOR BRAHMAND

**Use SPLIT 3 AGENTS:**

**Why?**
1. **You want to scale** (add Credit Spreads, Iron Condor, etc.)
   → Split agents keep code clean and testable
   
2. **You want clean knowledge** (Execution Agent reuses entry findings)
   → Split agents avoid pollution
   
3. **You want to debug** ("Why did SL breach?")
   → Split agents show clear attribution
   
4. **You want fast execution** (analyze 100 trades/day)
   → Parallel agents run 3x faster
   
5. **You want to test** ("Does my entry signal work?")
   → Split agents allow unit testing

**Architecture:**
```
StrategyPostMortemAgent
├─ Questions: Is this strategy right for the regime?
├─ Knows: ADX, VIX, SuperTrend, market structure
└─ Publishes: strategy_knowledge (2-3 findings/day)

EntryPostMortemAgent
├─ Questions: Was entry timing optimal? Which signal worked?
├─ Knows: EMA levels, support/resistance, RSI, time-of-day
└─ Publishes: entry_knowledge (3-5 findings/day)

ExitPostMortemAgent
├─ Questions: Was exit timing optimal? Should we hold longer?
├─ Knows: Hold time, profit capture %, resistance distance
└─ Publishes: exit_knowledge (2-3 findings/day)

PostMortemOrchestrator
├─ Runs all 3 in parallel
├─ Combines findings
└─ Updates daily_config.json
```

---

## PROTOTYPE PLAN

### If you choose MONOLITHIC:
- Week 1: Implement one PostMortemAgent
- Week 2: Add more strategies (refactor growing agent)
- Week 3: Add more entry signals (agent becomes bloated)
- Week 4: Realize it's hard to test → refactor to split :(

### If you choose SPLIT 3:
- Week 1: Implement all 3 agents (still simple)
- Week 2: Add more strategies (StrategyPM grows, others unchanged)
- Week 3: Add more entry signals (EntryPM grows, others unchanged)
- Week 4: Add portfolio analysis (add 4th agent, others unchanged)

**Split is the better long-term choice.**

---

## FINAL DECISION QUESTION FOR YOU

**What matters more to you?**

```
A) "I want maximum simplicity right now, I'll refactor later"
   → Use MONOLITHIC

B) "I want clean code that scales, even if it's slightly more complex"
   → Use SPLIT 3 AGENTS (RECOMMENDED)

C) "I want everything including portfolio-level insights"
   → Use SPLIT 4 AGENTS
```

Which resonates with Brahmand's long-term vision?

