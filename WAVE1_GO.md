# ✅ WAVE 1 — GREEN LIGHT

**Date:** 2026-05-13 22:00  
**Status:** All clarifications approved. **START WAVE 1 NOW.**

---

## Your Decisions Approved ✅

| # | Question | Your Answer | Verdict |
|---|----------|-------------|---------|
| 1 | schemas.py location? | Flat: `/home/trading_ceo/brahmand/schemas.py` | ✅ APPROVED |
| 2 | RiskLimits source? | Self-contained `brahmand/config/risk_limits.yaml` | ✅ APPROVED |
| 3 | Persistence strategy? | Custom `state.db` only (Post-Mortem needs queries) | ✅ APPROVED |

**Your reasoning on Q3 is excellent:** Post-Mortem needs `SELECT * FROM execution_reports WHERE pnl < 0` for ChromaDB metadata enrichment. Can't query CrewAI's opaque `@persist` blob. ✓

---

## Wave 1 Implementation Order

**Implement in this order** (dependencies matter):

1. **brahmand/schemas.py** (no dependencies)
   - All 5 Pydantic models from SCHEMAS.md
   - Include: `__all__` list, docstrings, example() methods if helpful

2. **brahmand/config/risk_limits.yaml** (no dependencies)
   - Seed with values shown in REVIEW_BEFORE_WAVE1.md
   - No imports needed — just YAML data

3. **brahmand/persistence.py** (depends on #1: schemas.py)
   - SQLite init, schema creation
   - Functions: `init_db()`, `save_state()`, `load_state()`, `query_reports()`

4. **brahmand/config/agents_registry.yaml** (no dependencies)
   - 3 blueprints: Executor, RiskAgent, PostMortem
   - Use `{market_type}`, `{strategy}` slots for parameterization

5. **brahmand/factory.py** (depends on #1, #4: schemas.py + registries)
   - AgentFactory (reads agents_registry.yaml)
   - ToolFactory (reads tools_registry.yaml — see below)

6. **brahmand/config/tools_registry.yaml** (no dependencies)
   - Market → Tool list mappings (NSE_OPTIONS, MCX_FUTURES)
   - Used by ToolFactory in factory.py

---

## Quality Checklist

Before committing each file:

- [ ] File imports only exist modules (no forward references)
- [ ] All Pydantic models validate correctly (`schema.model_validate({...})`)
- [ ] All YAML files parse (`yaml.safe_load()`)
- [ ] All functions have docstrings
- [ ] All paths are absolute or use `pathlib.Path(__file__).parent`

---

## What Success Looks Like

After Wave 1:
- 5 files created
- ~500 lines total
- All files are **importable** and **testable** independently
- No external dependencies beyond CrewAI, Pydantic, PyYAML
- Ready for Wave 2 (3 agents)

---

## Git Workflow

**After each file (or pair):**
```bash
cd /home/trading_ceo/brahmand
git add <file(s)>
git commit -m "feat(wave1): <what this adds>

<description>"
```

---

## Expected Time

~2-3 hours for all 5 files + 6 config entries.

---

**Questions before you start?** Otherwise: **BEGIN WAVE 1.** 🚀
