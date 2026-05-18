# HANDOFF TO DEEPSEEK - Brahmand Post-Mortem Agent System

**Date:** 2026-05-15  
**Status:** Complete specification ready for implementation  
**Branch:** master  

---

## EXECUTIVE SUMMARY

You have **6 comprehensive documents** in `/home/trading_ceo/brahmand/`:

1. **BRAHMAND_BUILD_SPECIFICATION.md** ← **START HERE**
   - 8 Python files to implement with full class signatures
   - Week-by-week implementation roadmap
   - All blocking questions answered
   - DuckDB queries + knowledge schemas

2. **POSTMORTEM_KNOWLEDGE_SCAFFOLD.md** ← Domain knowledge foundation
   - Trading strategy characteristics
   - Entry signal definitions + success rates
   - Exit signal effectiveness
   - Market structure analysis
   - Greeks understanding
   - Confidence scoring formulas
   - Anti-patterns to detect

3. **COMPLETE_BRAHMAND_FLOW.md** ← Architecture overview
   - 3-phase system (Planning → Execution → Learning)
   - 14 agents total (7 planning + 3 learning + 4 support)
   - 24-hour cycle diagram

4. **POSTMORTEM_AGENT_DESIGN.md** ← Deep specification
   - 3 agent architecture (StrategyPM + EntryPM + ExitPM)
   - Knowledge document examples
   - DuckDB query patterns
   - MVP + expansion roadmap

5. **POSTMORTEM_AGENT_ARCHITECTURE.md** ← Design comparison
   - Monolithic vs Split agents (full pros/cons)
   - **Decision: SPLIT 3 AGENTS chosen**

6. **KNOWLEDGE_ARCHITECTURE.md** ← RL system
   - 6 agent roles mapped to knowledge
   - RL feedback loop (Days 1-5 example)
   - 7 success metrics for validation

---

## KEY DECISIONS MADE

### Architecture
✅ **SPLIT 3 AGENTS** (not monolithic)
- StrategyPostMortemAgent (learns strategy correctness)
- EntryPostMortemAgent (learns entry signal effectiveness)
- ExitPostMortemAgent (learns exit timing optimality)

### Scope
✅ **Iron Butterfly first** → Credit Spreads → Iron Condor  
✅ **Multi-factor strategy selection** (not blind rules)  
✅ **Morning planning + intraday replan** if regime changes  
✅ **Minimal state.db** (time/price/qty/contract) + rich DuckDB context  

### Knowledge
✅ **3 collections:** strategy_knowledge, entry_knowledge, exit_knowledge  
✅ **Daily config.json** evolves from learnings (Day 1: 0.70 confidence → Day 5: 0.85)  
✅ **Post-mortem publishes** → Knowledge → Planning agents use it → Next trade improves

---

## WHAT'S READY TO BUILD

### Files to Create (Week 1-2)

```
/brahmand/planning/
├── strategy_planner.py (class: StrategyPlanningAgent)
├── entry_planner.py (class: EntryPlanningAgent)
├── exit_planner.py (class: ExitPlanningAgent)
└── daily_plan_synthesizer.py (class: DailyPlanSynthesizerAgent)

/brahmand/learning/
├── strategy_postmortem.py (class: StrategyPostMortemAgent)
├── entry_postmortem.py (class: EntryPostMortemAgent)
├── exit_postmortem.py (class: ExitPostMortemAgent)
└── daily_config_updater.py (class: DailyConfigUpdaterAgent)
```

### Data Flow

```
DAY N (Learning):
  Post-Mortem agents analyze completed trades
  → Publish findings to strategy_knowledge, entry_knowledge, exit_knowledge
  → Update daily_config.json with learned parameters

DAY N+1 (Planning):
  Strategy Planning Agent reads daily_config.json
  → "Iron Butterfly won 82% yesterday, confidence 0.85"
  → Picks strategy with higher confidence (informed, not blind)
  
  Entry Planning Agent reads daily_config.json
  → "EMA5 bounce at support works 100% (5/5 samples)"
  → Plans entry signals accordingly
  
  Exit Planning Agent reads daily_config.json
  → "3-4 hour hold optimal, SL 30% prevents breaches"
  → Plans exit conditions with learned timing
  
  Result: daily_trade_plan.json (intelligent, not hardcoded)
  
  Execution Agent executes the plan
  → Better decisions → Better outcomes → Better learnings → Better next day
```

---

## KNOWLEDGE SCAFFOLD PROVIDED

### Strategy Knowledge
- Iron Butterfly: Sideways (ADX<25), success factors, failure modes
- Bull Put Spread: Trending bullish (ADX>25), when to use
- Bear Call Spread: Trending bearish, characteristics
- Each has tracking metrics for post-mortem analysis

### Entry Signals
- **EMA5 bounce at support:** 100% success (5/5 trades)
- **RSI divergence:** 50% success (2/2, needs more data)
- **Fair Value Gap:** 80% success (4/5)
- **Time-of-day:** 10:30-11:00 best, 11:00-11:15 worst

### Exit Signals
- **TP hit (50% decay):** 92% success, 3h 45m avg
- **Time-based (14:30):** Risk management, avoid overnight
- **Structure reversal:** Early exit signal
- **SL breach:** Avoid! Learn why it happened

### Market Structure
- **HH+HL (bullish):** Strong trend, confidence+
- **LL+LH (bearish):** Reverse analysis
- **HL/LH (weakening):** Transition state, caution
- Post-mortem scores by structure health

### Greeks
- **Delta:** Should be 0 for Iron Butterfly, track acceleration
- **Theta:** Early decay accelerates, late decelerates
- **Vega:** Short vega = VIX drop helps, VIX rise hurts

### Risk Management
- **SL % by VIX:** VIX<18→30%, VIX>22→40%
- **TP = 50%** of credit, typical 3-4 hours
- **Confidence scoring:** Multi-factor (support + confluence + premium + slippage + time)

---

## IMPLEMENTATION SEQUENCE

### Week 1: Planning Agents
1. Create `strategy_planner.py` - Multi-factor strategy scoring
2. Create `entry_planner.py` - Signal ranking + confluences
3. Create `exit_planner.py` - Optimal hold time + triggers
4. Create `daily_plan_synthesizer.py` - Orchestrator combining all
5. **Output:** daily_trade_plan.json (complete trade plan)

### Week 2: Learning Agents
1. Create `strategy_postmortem.py` - Analyze strategy correctness
2. Create `entry_postmortem.py` - Analyze entry signal effectiveness
3. Create `exit_postmortem.py` - Analyze exit timing optimality
4. Create `daily_config_updater.py` - Aggregate learnings
5. **Output:** Updated daily_config.json for tomorrow

### Week 3: Integration
1. Wire planning agents into Phase 1 (pre-market 09:15 AM)
2. Wire learning agents into Phase 3 (post-market 16:00 PM)
3. Adapt Execution/Risk agents to READ daily_trade_plan.json
4. Test: Full 1-hour dry run

### Week 4: Validation
1. Run 5 consecutive trading days
2. Measure: 7 success metrics (confidence trend, PnL improvement, etc.)
3. Verify RL loop is working (learnings improve next day's decisions)

---

## FILES ALREADY IN REPO (Reference)

- `duckdb_tool.py` - Market data queries (80+ columns available)
- `chromadb_tool.py` - Semantic search (existing, can reuse)
- `persistence.py` - SQLite state.db (execution_reports, research_notes)
- `schemas.py` - Pydantic models (TradeSignal, ExecutionReport, ResearchNote)
- `factory.py` - Agent factory from YAML blueprints
- `config/agents_registry.yaml` - Agent definitions
- `e2e_chain.py` - Existing 5-agent chain (can adapt)

---

## BLOCKING QUESTIONS ANSWERED

**Q1: Data Capture in state.db (Entry)**  
A: Just time, price, qty, contract. Datacapture script gets full market data.

**Q2: Data Capture in state.db (Exit)**  
A: Just time, price, qty, contract. Post-Mortem queries DuckDB by time for correlations.

**Q3: Strategy Decision Logic**  
A: Multi-factor (win-rate + entry signal reliability + exit success + Greeks + VIX adjustment + market structure). Research continues exploring!

---

## GIT STATUS

All files committed to `master`:
```bash
$ git log --oneline | head -10
b921783 docs: complete Brahmand flow with Planning + Execution + Learning phases
131530c docs: Post-Mortem Agent knowledge scaffold - domain knowledge foundation
aee7700 docs: complete build specification ready for DeepSeek implementation
507c3dd docs: complete pros/cons comparison - Monolithic vs Split agents
971102e docs: knowledge architecture for RL + CrewAI integration
```

---

## HOW TO PROCEED

1. **Clone latest:** `git pull origin master`
2. **Read:** `BRAHMAND_BUILD_SPECIFICATION.md` (main spec)
3. **Reference:** `POSTMORTEM_KNOWLEDGE_SCAFFOLD.md` (domain knowledge)
4. **Implement:** Week 1 planning agents (8 Python files)
5. **Test:** 1-hour dry run
6. **Validate:** 5-day RL loop with metrics

---

## SUCCESS CRITERIA

By end of Week 4:
- ✅ Daily strategy decisions based on yesterday's learnings (not blind rules)
- ✅ Entry signals ranked by historical effectiveness
- ✅ Exit timing optimized by market structure + hold time analysis
- ✅ 5 consecutive days show confidence trend (0.70 → 0.85)
- ✅ PnL improvement trend (Day 1 ₹730 → Day 5 ₹1050+)
- ✅ Knowledge collections growing with each trade
- ✅ daily_config.json evolving with learnings

---

**You have everything needed. Build! 🚀**

Questions? All context is in the 6 documents above.

