# Project UNICORN — Architecture & Implementation

**Date:** 2026-06-03  
**Status:** Phases 0-6 complete (63 tests) — deterministic path operational, LLM path pending live API  
**Design docs:** `brahmand/docs/PROJECT_UNICORN.md`, `PROJECT_UNICORN_TDD.md`, `PROJECT_UNICORN_DEEPSEEK_HANDOFF.md`

---

## Overview

UNICORN replaces the current Brahmand entry gate (trend + traffic_light deterministic tools → LLM passthrough → provenance clamp) with an **adversarial LLM debate architecture**. Two agents — Advocate and Skeptic — interpret the SAME raw data from opposing biases. Their claims are verified by a deterministic Python module BEFORE any LLM sees them. A Judge produces the final entry signal.

### Why

The current gate has the LLM acting as a JSON passthrough — it adds no reasoning but costs tokens and introduces hallucination risk. UNICORN makes the LLM ADD VALUE (interpretation + synthesis) while keeping numeric truth deterministic (C2 correction).

---

## Architecture — Data Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│  ANTARIKSH (Data Layer)                                                 │
│  query_trend / momentum / volatility / volume / options / flow / macro  │
│  (7 individual calls — NOT query_all_families)                          │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  unicorn_raw_query.py — CrewAI Tool                                     │
│                                                                          │
│  Calls 7 individual family fns. Extracts candle data from traffic_light │
│  (body_pct, color, wick_pct per TF). STRIPS scored verdicts: pattern,   │
│  confidence, summary, exhaustion, reversal_signal.                       │
│                                                                          │
│  Returns ~50 raw fields across 8 top-level keys:                        │
│  {trend, momentum, volatility, volume, options, flow, macro, candles}   │
│                                                                          │
│  60s TTL cache — all agents in a debate cycle see the same snapshot.    │
│  ZERO verdict tokens (test-enforced).                                    │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │  (same dict injected as context)
                 ┌────────────────┴────────────────┐
                 ▼                                  ▼
┌─────────────────────────────┐   ┌─────────────────────────────┐
│  ADVOCATE                   │   │  SKEPTIC                    │
│  (deepseek-chat, temp=0)    │   │  (deepseek-chat, temp=0)    │
│                             │   │                             │
│  Role: Argue to ENTER       │   │  Role: Argue to SKIP        │
│  NOT_UP → CALL_SPREAD       │   │  NOT_UP → don't enter       │
│  NOT_DOWN → PUT_SPREAD      │   │  NOT_DOWN → don't enter     │
│                             │   │                             │
│  Output:                     │   │  Output:                     │
│  { recommendation: "ENTER",  │   │  { recommendation: "SKIP",  │
│    gate_type,                │   │    gate_type,                │
│    points: [ {family,        │   │    points: [ {family,        │
│    claim, evidence} ] }      │   │    claim, evidence} ] }      │
└──────────────┬──────────────┘   └──────────────┬──────────────┘
               │                                   │
               └───────────────┬───────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  unicorn_verify.py — DETERMINISTIC PYTHON (C2: NO LLM)                  │
│                                                                          │
│  For every claim point {family, claim, evidence: {field: value}}:       │
│    • Look up raw[family][field] via _find_raw_value()                   │
│    • Numeric: |claimed - raw| ≤ tolerance → VERIFIED                    │
│    • String (direction fields): lowercase equality → VERIFIED           │
│    • Beyond tolerance → CONTRADICTED (+0.0 score, logged)               │
│    • Field absent or None → UNVERIFIABLE (+0.5 score)                   │
│                                                                          │
│  Tolerance: abs_default=0.5, pct_fields=0.02                            │
│  Direction fields: sma_position, st_consensus, cmf_signal, etc.         │
│  Returns: {score, raw_score, tags:[], hallucinations:[], families_covered}│
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │  (VERIFIED / CONTRADICTED / UNVERIFIABLE)
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  unicorn_judge.py — Decision Logic                                       │
│                                                                          │
│  Deterministic path (no LLM required):                                   │
│    • Uses raw_score (not normalized) — rewards evidence breadth          │
│    • Advocate raw_score > Skeptic raw_score + 0.3 → ENTER               │
│    • Hallucination penalty: -0.05 per fabricated claim                   │
│    • Max confidence: 0.75 (conservative)                                 │
│    • Tie/ambiguity → SKIP (signal=NONE)                                  │
│                                                                          │
│  LLM path (optional, needs API):                                         │
│    • build_judge_prompt() → sends pre-verified claims to deepseek-reasoner│
│    • Judge receives TAGGED claims — NEVER recomputes numbers             │
│    • LLM failure → graceful fallback to deterministic path               │
│                                                                          │
│  Output: entry_decision dict compatible with e2e_chain contract:         │
│  {go, signal, confidence, strategy_to_execute, reasoning,                │
│   not_up_signal, not_down_signal, not_up_confidence, not_down_confidence,│
│   hallucinations_detected, hallucination_count, hallucination_details,   │
│   families_covered}                                                      │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  unicorn_anomaly.py — Safety Gate                                        │
│                                                                          │
│  check_anomaly(decision) → {anomaly: bool, flags: [str], safe: bool}    │
│  Detects: go=true+NONE contradiction, >5 hallucinations,                 │
│           <2 families on ENTER, go=true with confidence=0                │
│                                                                          │
│  safe_debate(raw, gate, pts) → run → check → fallback on anomaly         │
│  Fallback: signal=NONE, source=unicorn_anomaly_fallback                  │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  verify_provenance() — Existing outer clamp (kept per §7.4)              │
│  From brahmand/verification.py. Only applied if legacy trend/traffic_    │
│  light fields are present in the decision.                               │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  e2e_chain.py — Brahmand Execution Engine                                │
│  Integration point: lines 213-289 (entry crew). Replaced with:           │
│    run_unicorn_debate(raw, "NOT_UP")   → not_up_decision                 │
│    run_unicorn_debate(raw, "NOT_DOWN") → not_down_decision               │
│  Regime, Strategy, Contract, Execution agents UNCHANGED (§7.3).          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## File Inventory

### Core Modules (all in `brahmand/`)

| # | File | Lines | Role |
|---|------|-------|------|
| 1 | `unicorn_raw_query.py` | 167 | CrewAI tool — raw data query with 60s cache, verdict stripping |
| 2 | `unicorn_verify.py` | 268 | Deterministic claim verifier — pure Python, no LLM |
| 3 | `unicorn_judge.py` | 260 | Judge scoring + LLM prompt builder |
| 4 | `unicorn_debate.py` | 153 | Debate orchestrator + deterministic fallback |
| 5 | `unicorn_anomaly.py` | 113 | Anomaly detector + safe debate wrapper |
| 6 | `config/unicorn_agents.yaml` | 146 | Advocate, Skeptic (deepseek-chat), Judge (deepseek-reasoner) YAML blueprints |

### Test Modules (all in `brahmand/tests/unicorn/`)

| # | File | Tests | Covers |
|---|------|-------|--------|
| 1 | `test_raw_query.py` | 8 | 7 families output, no verdicts, 60s cache, candle preservation |
| 2 | `test_verify.py` | 18 | VERIFIED/CONTRADICTED/UNVERIFIABLE, tolerance, determinism, _MISSING sentinel |
| 3 | `test_debate.py` | 26 | Agent config validation, prompt audits, E2E debate, anomaly detection, fallback |
| 4 | `test_judge.py` | 11 | Fabrication detection, scoring, correct signals, output contract, prompt builder |
| 5 | `conftest.py` | — | Frozen fixture loaders (per-family) |

### Test Fixtures (all in `brahmand/tests/unicorn/fixtures/`)

| # | File | Description |
|---|------|-------------|
| 1 | `raw_data_sample.json` | Frozen snapshot of live `query_all_families("NIFTY")` from 2026-06-03 |
| 2 | `debate_bearish_not_up.json` | Synthetic strong bearish scenario — NOT_UP should ENTER CALL_SPREAD |
| 3 | `debate_bullish_not_down.json` | Synthetic strong bullish scenario — NOT_DOWN should ENTER PUT_SPREAD |
| 4 | `debate_ambiguous.json` | Synthetic sideways/ambiguous — should SKIP (signal=NONE) |

### Design & Progress Docs (all in `brahmand/docs/`)

| # | File | Contents |
|---|------|----------|
| 1 | `PROJECT_UNICORN.md` | Original design — 448 lines, architecture, agent design, testing strategy |
| 2 | `PROJECT_UNICORN_TDD.md` | TDD plan — 6-phase implementation with test-first steps |
| 3 | `PROJECT_UNICORN_DEEPSEEK_HANDOFF.md` | Corrected spec (C1-C4) — single source of truth for build |
| 4 | `UNICORN_PHASE0_FINDINGS.md` | Field inventory — confirmed 7 families RAW, traffic_light SCORED |
| 5 | `UNICORN_ARCHITECTURE.md` | This file — comprehensive architecture documentation |

### Modified External Files

| # | File | Change |
|---|------|--------|
| 1 | `antariksh/tools/entry_tools.py` | Fixed 23 import alias bugs (`json`→`_json`, `datetime`→`_dt`) |

---

## Design Corrections Applied (from DEEPSEEK_HANDOFF.md)

| # | Correction | Implementation | Verified |
|---|-----------|---------------|----------|
| **C1** | Judge uses `deepseek-reasoner` (different model family) | `config/unicorn_agents.yaml:146` — Judge `llm: deepseek/deepseek-reasoner` | ✅ G2 test |
| **C2** | Deterministic Python verifier — NO LLM for numeric checks | `unicorn_verify.py` — field-level tolerance comparison, `_MISSING` sentinel | ✅ 18 tests |
| **C3** | No "bull"/"bear" — Advocate/Skeptic, parameterized by `gate_type` | All agent prompts use `{gate_type}` variable, canonical §2 table | ✅ Prompt audit test |
| **C4** | Assert invariants, never exact LLM text | Tests check schema, signal set, fabrication caught — never string-equal | ✅ 4 tests |

---

## Canonical Direction Table (Single Source of Truth)

| Gate | Market View | Strategy | Advocate Argues | Skeptic Argues | ENTER Signal |
|------|-------------|----------|-----------------|----------------|--------------|
| `NOT_UP` | Rejects upside (bearish) | `CALL_SPREAD` | "upside rejected → enter" | "upside NOT rejected → skip" | `NOT_UP` |
| `NOT_DOWN` | Rejects downside (bullish) | `PUT_SPREAD` | "downside rejected → enter" | "downside NOT rejected → skip" | `NOT_DOWN` |

On SKIP: `signal = "NONE"`, `go = false`, `confidence = 0.0`.

---

## Scoring Rules (Judge)

### Deterministic Path (always available, no API needed)
- Uses `raw_score` (unnormalized) — every verified evidence field contributes +1.0 × weight
- Advocate must beat Skeptic by gap > 0.3 to ENTER
- >3 hallucinations on either side → SKIP
- Max confidence: 0.75 (conservative)
- Hallucination penalty: -0.05 per fabricated claim
- Ties → SKIP (edge is in not overtrading — single position, 60% sideways thesis)

### LLM Path (optional, requires deepseek-reasoner API)
- `build_judge_prompt()` renders pre-verified scores and tags
- Judge instructed: CONTRADICTED → zero, UNVERIFIABLE → half, VERIFIED → full
- Prompt includes canonical direction table + output format
- LLM failure → silent fallback to deterministic path

---

## Verification Rules (unicorn_verify.py)

| Verdict | Condition | Score |
|---------|-----------|-------|
| **VERIFIED** | `|claimed - raw| ≤ tolerance` (numeric) or string match (direction) | +1.0 × family_weight |
| **CONTRADICTED** | Beyond tolerance or string mismatch | +0.0, logged in `hallucinations[]` |
| **UNVERIFIABLE** | Field not in raw data, or field exists but value is `None` | +0.5 × family_weight |
| **EMPTY** | Point has no evidence fields | +0.3 × family_weight |

**Tolerance:** `abs_default=0.5`, `pct_fields` (iv_rank, bb_pct_b, cmf, pcr_total, pcr_atm) = 0.02.  
**Direction fields** (compared by string): sma_position, st_consensus, st_direction, candle, rsi_zone, cmf_signal, sentiment, iv_regime, session_phase, color.

### _MISSING Sentinels
`_find_raw_value()` uses an `_MISSING` sentinel to distinguish:
- **Truly absent** → UNVERIFIABLE (the field was never part of the schema)
- **Present but None** → UNVERIFIABLE (exists but no data — post-market, empty)

---

## Anomaly Detection (unicorn_anomaly.py)

Detects inconsistencies in debate output that indicate bugs or excessive hallucination:

| Condition | Action |
|-----------|--------|
| `go=true` but `signal=NONE` | Anomaly → fallback to SKIP |
| `go=false` but signal ≠ NONE with confidence > 0 | Anomaly → fallback |
| `go=true` but `confidence ≤ 0` | Anomaly → fallback |
| `hallucination_count > 5` | Anomaly → fallback |
| ENTER with `< 2 families` covered | Anomaly → fallback |

---

## Integration with e2e_chain.py (Phase 5, pending live wiring)

The existing entry gate at `e2e_chain.py:213-289` builds a CrewAI entry crew:
```python
entry_crew = Crew(agents=[not_up_entry_agent, not_down_entry_agent, regime_agent],
                  tasks=[not_up_entry_task, not_down_entry_task, regime_task])
entry_result = entry_crew.kickoff()
```

Unicorn replaces this with two `run_unicorn_debate()` calls:
```python
raw_data = json.loads(UnicornRawQuery()._run("NIFTY"))

not_up_result = run_unicorn_debate(raw_data, "NOT_UP", advocate_pts, skeptic_pts)
not_down_result = run_unicorn_debate(raw_data, "NOT_DOWN", advocate_pts, skeptic_pts)
```

**Note:** The Advocate and Skeptic LLM agents need CrewAI wiring to produce `advocate_pts`
and `skeptic_pts` from the agent config. This requires live API. The deterministic
path works without API using pre-built point lists.

The downstream keys (`go`, `signal`, `confidence`, `strategy_to_execute`,
`not_up_signal`, `not_down_signal`, `not_up_confidence`, `not_down_confidence`)
are **byte-identical** to the existing contract (§5 guardrail).

---

## Guardrails Compliance

| # | Guardrail | Status |
|---|-----------|--------|
| 1 | No fabricated market data in tests claiming live validation | ✅ All fixtures are clearly-labeled frozen snapshots |
| 2 | No LLM in numeric verification or execution | ✅ `unicorn_verify.py` is pure Python; SL/TP/contracts untouched |
| 3 | Do not touch risk/exit agent | ✅ Entry gate only — risk, exit, order_routing unchanged |
| 4 | Do not remove `verify_provenance` | ✅ Called optionally in debate pipeline |
| 5 | Do not change `entry_decision` output contract | ✅ Keys, types, and signal values match existing contract |
| 6 | No real-money deploy without Claude sign-off | ✅ Paper-shadow run pending (G8) |
| 7 | Every claim traceable to raw field | ✅ Verifier enforces: fabricated values → CONTRADICTED + zero score |

---

## Test Coverage

```
tests/unicorn/test_raw_query.py  —  8 passed  (output structure, verdict stripping, cache)
tests/unicorn/test_verify.py     — 18 passed  (all verdict paths, tolerance, determinism)
tests/unicorn/test_debate.py     — 26 passed  (config, E2E, anomaly, fallback)
tests/unicorn/test_judge.py      — 11 passed  (fabrication, scoring, signals, prompts)
                                  ─────────
                                   63 passed, 0 failed
```

### Key Acceptance Tests Verified

| Gate | Requirement | Status |
|------|-------------|--------|
| G1 | Fabricated ADX=55 caught as CONTRADICTED, scores 0 | ✅ `test_judge_detects_fabrication` |
| G2 | Judge uses deepseek-reasoner, Advocate/Skeptic use chat | ✅ `test_advocate_skeptic_use_chat_judge_uses_reasoner` |
| G3 | NOT_UP→CALL_SPREAD, NOT_DOWN→PUT_SPREAD, tie→NONE | ✅ `test_not_up_gate_strong_bearish_enters`, `test_not_down_gate_strong_bullish_enters`, `test_ambiguous_sideways_skips` |
| G5 | Contract keys match existing entry_decision | ✅ `test_judge_output_has_all_keys`, `test_debate_returns_expected_keys` |
| G6 | Tool failure → deterministic fallback, never crashes | ✅ `test_llm_failure_falls_back_to_deterministic`, `test_fallback_on_tool_failure` |

---

## Pending for Live Deployment

| Gate | Requirement | Status |
|------|-------------|--------|
| **Phase 0.2** | Confirm deepseek-reasoner API reachability | ⏳ Needs live API key |
| **G4** | Same fixture 10× → stable decision ≥9/10 | ⏳ Needs LLM API |
| **G7** | Measure wall-clock for full cycle (6 LLM calls) | ⏳ Needs LLM API |
| **G8** | Paper-shadow run ≥5 sessions alongside current gate | ⏳ Needs trading hours |
| **Phase 5** | Wire CrewAI Advocate/Skeptic agents for live LLM calls | ⏳ Deterministic path works without API |
