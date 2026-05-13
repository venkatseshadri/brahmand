# Tauric Framework Reuse Plan

**Date:** 2026-05-13  
**Status:** Reference for post-MVP integration  
**Decision:** Port Tauric's debate patterns into Brahmand Wave 2+

---

## 📚 Reference URLs

### Primary Sources
- **GitHub Repo:** https://github.com/tauricresearch/tradingagents
  - Open source, MIT license (assumed)
  - Contains: Analysts, Researchers, Trader, Risk/PM agents
  - Language: Python (LangGraph-based)
  - Status: ✅ Accessible

- **Research Page:** https://tauric.ai/research/tradingagents/
  - White paper / research documentation
  - Status: ❌ 403 Forbidden (may require auth or rate limiting)
  - Alternative: Check GitHub repo's `/docs` folder

---

## 🎯 Tauric Framework Overview (From GitHub Fetch)

### Architecture
**4 Functional Teams:**

1. **Analyst Team** (4 specialized agents)
   - Fundamentals Analyst — Company financials, valuations
   - Sentiment Analyst — News, social sentiment aggregation
   - News Analyst — Macroeconomic, global events
   - Technical Analyst — MACD, RSI, indicators

2. **Researcher Team** (2 debate agents)
   - Bullish Researcher — Bull case arguments
   - Bearish Researcher — Bear case arguments
   - (Synthesizer/Consensus role unclear from fetch)

3. **Trader Agent** (1)
   - Synthesizes analyst + researcher reports
   - Executes timed, sized trades

4. **Risk Management & Portfolio Manager** (2)
   - Assesses portfolio volatility, liquidity
   - Approves/rejects proposed trades

**Total: ~12+ agents**

### Technology Stack
- **Orchestration:** LangGraph (not CrewAI)
- **LLM Support:** OpenAI, Google, Anthropic, DeepSeek, others
- **Decision Logging:** Built-in for learning from trades
- **Checkpoint Recovery:** Supports interrupted run resumption

---

## 🔄 Reusable Patterns (High Priority)

### Pattern 1: Debate Framework ⭐⭐⭐
**What Tauric Does:**
- Bullish Researcher writes bull thesis
- Bearish Researcher writes bear thesis
- Synthesizer votes/decides based on both

**How to Reuse in Brahmand:**
```python
# Post-MVP: brahmand/crews/debate_crew.py
bullish_agent = Agent(...)
bearish_agent = Agent(...)
consensus_agent = Agent(...)

debate_crew = Crew(
    agents=[bullish_agent, bearish_agent, consensus_agent],
    tasks=[...],
    process=Process.sequential  # or hierarchical
)
```

**When:** Wave 2 (after MVP execution proves concept)

---

### Pattern 2: Analyst Decomposition ⭐⭐
**What Tauric Does:**
- Splits analysis into 4 dimensions (Fundamentals, Sentiment, News, Technical)
- Each analyst reports independently
- Synthesizer combines

**How to Reuse in Brahmand:**
- **Current (MVP):** Just Executor + Risk Agent
- **Post-MVP:** Add RegimeAgent (like Technical Analyst)
- **Phase 2:** Add multi-analyst team for options:
  - IV Rank Analyst
  - Theta Decay Analyst
  - Delta Hedge Analyst
  - Event Risk Analyst

---

### Pattern 3: Decision Logging ⭐⭐
**What Tauric Does:**
- Logs every agent decision with reasoning
- Enables learning from past trades

**How to Reuse in Brahmand:**
- ✅ Already doing: ResearchNote in ChromaDB
- ✅ Already doing: execution_reports in state.db
- **Enhance:** Add "agent_reasoning" field to capture WHY each agent decided

---

### Pattern 4: Risk-First Approval Gate ⭐⭐⭐
**What Tauric Does:**
- Portfolio Manager approves before execution
- Risk Management validates portfolio impact

**How to Reuse in Brahmand:**
- ✅ Already in design: Risk Agent validates TradeSignal
- **Enhance:** Add explicit approval flow (not just validation)

---

## 📋 Reuse Timeline

| Phase | What | Effort | Timeline |
|-------|------|--------|----------|
| **MVP (Now)** | Executor + Risk + Post-Mortem | — | 1 week |
| **Wave 2** | Add Debate Crew (Bullish/Bearish analysts) | Medium | Week 2 |
| **Wave 3** | Add Analyst Decomposition (IV, Theta, Delta, Event) | High | Week 3+ |
| **Phase 2** | Full team (12+ agents) like Tauric | Very High | Month 2+ |

---

## 🚀 Implementation Checklist (Post-MVP)

### When to Start Tauric Port
- [ ] Brahmand Wave 1-3 complete and tested ✅
- [ ] MVP runs for 1 hour successfully ✅
- [ ] Post-Mortem Agent writes to ChromaDB ✅
- [ ] Then: Start Debate Crew port

### What to Extract from Tauric Repo
- [ ] Clone `/tauricresearch/tradingagents`
- [ ] Read `researchers/bullish_researcher.py`
- [ ] Read `researchers/bearish_researcher.py`
- [ ] Read `synthesizer.py` or equivalent
- [ ] Understand prompt structure (how they debate)
- [ ] Adapt analyst prompts for options (Greeks, IV, Theta)

### CrewAI Adaptation Points
- [ ] Translate LangGraph nodes → CrewAI agents + tasks
- [ ] Map Tauric tools → Brahmand tools (market_data, risk_calc)
- [ ] Adapt analyst backstories for NIFTY options market
- [ ] Wire debate crew into Brahmand Flow (after Executor, before Risk)

---

## 🔗 Integration Points

### Brahmand Flow (Post-MVP)
```
Current:
  Initialize → Executor → Risk Agent → Post-Mortem

Enhanced with Tauric Debate:
  Initialize 
    → Executor (gets signal idea)
    → Debate Crew (bullish/bearish/consensus)
    → If consensus ≥ 70%: Risk Agent (validate)
    → If Risk approves: Place trade
    → Post-Mortem (log + learn)
```

### Antariksh PM Crew (Integration Target)
```
Current PM Crew:
  Strategist → Reporter

Enhanced with Tauric:
  Strategist
    ├── (keep as-is)
    └── Call Debate Crew for high-stakes decisions
  Reporter (report both bull + bear cases)
```

---

## 📝 Notes & Gotchas

### Differences: Tauric vs Brahmand
| Aspect | Tauric | Brahmand |
|--------|--------|----------|
| Scope | Equities (broad) | Options (NIFTY only) |
| Agents | LLM-driven | Mix LLM + deterministic |
| Risk | LLM-synthesized | Pure Python (immutable) |
| Latency | Multi-debate = slow | MVP = fast |

### Adaptation Needed
- **Analyst types:** Tauric focuses on macro/fundamentals → Adapt for options Greeks/IV
- **Risk metrics:** Tauric uses volatility/liquidity → Add gamma/vega risk
- **Market hours:** Tauric (US equities 9:30-16:00) → Brahmand (India 09:15-15:30)
- **Debate prompts:** Rewrite for options trading context

### No Copy-Paste
- Tauric uses LangGraph, Brahmand uses CrewAI
- Direct code reuse won't work
- **Reuse:** Logic, patterns, prompts, decision structure
- **Translate:** To CrewAI equivalents (agents, tasks, tools)

---

## 🎯 Success Criteria

After porting Tauric patterns:
- [ ] Debate Crew runs end-to-end
- [ ] Bull + Bear cases logged to ChromaDB
- [ ] Consensus votes override/confirm Executor's signal
- [ ] Post-Mortem learns from debate (e.g., "Bearish side was right")
- [ ] Test: Brahmand with debate vs without (A/B)

---

## 📞 Decision Gate

**Before starting Tauric port (Week 2):**
- Confirm Wave 1-3 MVP is working
- Ask: "Does adding debate slow execution too much?"
- Ask: "Is 3x cost (debate = 3 LLM calls) worth it?"
- If yes → Start port. If no → Keep MVP simple.

---

**Status: Ready to reference and port after MVP validation.**
