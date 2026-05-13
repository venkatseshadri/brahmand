# Brahmand MVP — Review & Clarifications Before Wave 1

**Date:** 2026-05-13  
**Status:** Planning phase complete ✅ | Ready for Wave 1 clarifications  
**Reviewer:** Claude (token-efficient checkpoint)

---

## ✅ What's Approved

### BUILD_PLAN.md
- Clear 11-step build order across 3 waves ✓
- Dependencies correctly mapped (Wave 1 → 2 → 3) ✓
- Smart reuse of existing antariksh modules ✓
- Decisions documented with context references ✓

### SCHEMAS.md
- 5 Pydantic models well-designed ✓
- Proper validation (pattern, ge/le, default_factory) ✓
- Producers/consumers clearly documented ✓
- Realistic JSON examples provided ✓
- All JSON-serializable via `.model_dump()` ✓

**Move forward with Wave 1 coding.** But resolve 3 clarifications first.

---

## 🎯 Clarifications Needed (Wave 1 Blockers)

### 1. **schemas.py Location**

**Question:** Should `schemas.py` be at:

**Option A (Flat):**
```
/home/trading_ceo/brahmand/
├── schemas.py          ← Top level
├── config/
├── agents/
└── flow.py
```

**Option B (Nested):**
```
/home/trading_ceo/brahmand/
├── brahmand/
│   ├── __init__.py
│   ├── schemas.py      ← Inside package
│   ├── config/
│   ├── agents/
│   └── flow.py
└── tests/
```

**Recommendation:** **Option A (Flat)** for MVP simplicity. Move to nested package structure in Phase 2.

---

### 2. **RiskLimits Source File**

**Question:** BUILD_PLAN.md says:
> Loaded from: `antariksh/config/antariksh_rules.yaml`

**Action:** Before coding persistence.py (Wave 1, step 4), verify:

```bash
ls -la /home/trading_ceo/antariksh/config/antariksh_rules.yaml
```

**If file does NOT exist:**
- Option A: Create it in brahmand/config/ as `risk_limits.yaml` (self-contained)
- Option B: Inline RiskLimits defaults directly in schemas.py with hardcoded values

**Recommendation:** **Option A** — Create `/home/trading_ceo/brahmand/config/risk_limits.yaml` with reasonable defaults:
```yaml
risk_limits:
  max_drawdown: 4500.0        # Daily loss limit in ₹
  max_lots: 1                 # Only 1 lot for MVP
  sl_enabled: true
  tp_enabled: true
  margin_cap: 500000.0
  hard_exit: "14:30"          # IST
  entry_window_start: "10:30"
  entry_window_end: "11:30"
  vix_max: 20.0
```

---

### 3. **Persistence Strategy: @persist vs Custom SQLite**

**Question:** BUILD_PLAN step 4 mentions TWO SQLite systems:

1. **CrewAI's `@persist`** — SQLiteFlowPersistence (automatic per Flow)
2. **Custom `state.db`** — Manual SQLite for execution reports, research notes

**Decision needed:** Which is primary for MVP?

**Option A (CrewAI Native @persist):**
- ✅ Automatic state saving
- ✅ Simpler (one system)
- ❌ Limited schema control
- ❌ Harder to query for RAG

**Option B (Custom state.db only):**
- ✅ Full schema control
- ✅ Better for RAG queries
- ✅ Separate from Flow concerns
- ❌ Manual save/load

**Option C (Hybrid: @persist + custom):**
- ✅ Best of both
- ❌ More complex for MVP

**Recommendation:** **Option B (Custom state.db only)** for MVP simplicity.
- Let CrewAI manage Flow state internally (@persist optional)
- Use custom SQLite for agent outputs (execution_reports, research_notes, daily_config)
- Update persistence.py to manage ONLY `state.db`, not Flow persistence

---

## 📋 Pre-Wave 1 Checklist

Before implementing Wave 1 files (steps 1-5), confirm:

- [ ] schemas.py location chosen (recommend: flat at /home/trading_ceo/brahmand/schemas.py)
- [ ] RiskLimits YAML ready (either antariksh/config/antariksh_rules.yaml OR brahmand/config/risk_limits.yaml)
- [ ] Persistence strategy decided (recommend: Custom state.db only, not CrewAI @persist)
- [ ] All 5 schemas from SCHEMAS.md implemented in schemas.py with docstrings

---

## Wave 1 File Checklist (After Clarifications)

```
[ ] 1. brahmand/schemas.py
      - Import: Pydantic BaseModel, Field, typing
      - Define: TradeSignal, RiskLimits, FlowState, ExecutionReport, ResearchNote
      - Include: __all__ list for clean imports
      - Include: Example factory methods or validators if needed
      
[ ] 2. brahmand/config/agents_registry.yaml
      - Define: 3 agent blueprints (Executor, RiskAgent, PostMortem)
      - Use: {variable} slots for market_type, strategy, etc.
      - Example: role: "Execution Agent for {market_type}"
      
[ ] 3. brahmand/config/tools_registry.yaml
      - Define: Tool mappings by market (NSE_OPTIONS, MCX_FUTURES, etc.)
      - Example: NSE_OPTIONS: [order_placement_tool, sl_tool, tp_tool]
      
[ ] 4. brahmand/persistence.py
      - SQLite init (state.db schema)
      - Functions: init_db(), save_state(), load_state(), query_reports()
      - Tables: execution_reports, research_notes, daily_configs
      
[ ] 5. brahmand/factory.py
      - AgentFactory class (reads agents_registry.yaml → CrewAI Agent)
      - ToolFactory class (reads tools_registry.yaml → CrewAI Tool instances)
      - Include: Variable substitution ({market_type} → "NSE_OPTIONS")
```

---

## Next Steps After Wave 1

Once Wave 1 is complete and tested:
- **Wave 2:** Build the 3 agents (execution, risk, postmortem)
- **Wave 3:** Build Flow orchestrator + test suite
- **Test run:** `python3 brahmand_flow.py --test-duration 1h`

---

## 📬 Response (2026-05-13)

### Q1: schemas.py location
**Decision:** Flat — `/home/trading_ceo/brahmand/schemas.py`. No nested package.

### Q2: RiskLimits source
**Decision:** Self-contained `brahmand/config/risk_limits.yaml` seeded from `antariksh/config/antariksh_rules.yaml` values. Brahmand is a sister project — can inspire from antariksh but stays self-contained.

### Q3: Persistence strategy
**Decision:** Custom `state.db` only for MVP (Option B). CrewAI `@persist` can be layered on later with zero schema migration — one-line decorator change. Custom SQLite chosen because:
- Post-Mortem Agent needs structured queries (`SELECT * FROM execution_reports WHERE pnl < 0`) to enrich ChromaDB metadata
- ChromaDB can't index into `@persist`'s opaque state blob
- Adding `@persist` later is trivial refactor

---

**All 3 clarifications resolved. Wave 1 ready to code.**

**Expected Wave 1 time:** ~2-3 hours (5 files, ~500 lines total)
