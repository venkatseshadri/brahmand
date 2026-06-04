# PROJECT UNICORN — DeepSeek Build Handoff + Validation Gates

**Builder:** DeepSeek (implements)  ·  **Validator:** Claude (validate-only, signs off each gate)
**Source design:** `docs/PROJECT_UNICORN.md` + `docs/PROJECT_UNICORN_TDD.md`
**Status:** spec corrected after design review — build the CORRECTED version below, not the raw doc.
**Hard rule:** No real-money deploy until every validation gate in §8 is green. This is the May-24 lesson — verification-first, no invented data, no fake P&L.

---

## 0. Why this doc overrides the design doc (4 corrections)

The original `PROJECT_UNICORN.md` is directionally right but has 4 defects that MUST be fixed during the build. DeepSeek: implement the corrected behavior, not the doc's literal text.

| # | Defect in PROJECT_UNICORN.md | Correction (build THIS) |
|---|------------------------------|--------------------------|
| C1 | All 3 agents use `deepseek-chat` → correlated errors; the "0.05⁷ independence" math is false | **Judge uses `deepseek/deepseek-reasoner`**; Advocate/Skeptic use `deepseek/deepseek-chat`. Different model family for the arbiter = real error decorrelation, still 100% DeepSeek. |
| C2 | Judge verifies numeric claims with an LLM → reintroduces hallucination | **Claim verification is deterministic Python** (`unicorn_verify.py`). The Judge LLM receives claims that are ALREADY tagged verified/contradicted/unverifiable and only *weighs + synthesizes*. No LLM ever decides "does 38 == 55". |
| C3 | "Bull/Bear" naming is scrambled (Bull agent labelled "Bearish Advocate", argues for CALL_SPREAD) | **Rename to `ADVOCATE` / `SKEPTIC`, parameterized by `gate_type`.** No "bull/bear". The §2 canonical table is the single source of truth for direction. |
| C4 | Tests assert exact-equal LLM output with frozen data ("deterministic") | **Assert invariants, never exact LLM text.** `temperature=0` ≠ deterministic over an API. Schema-valid, signal ∈ allowed set, injected fabrication is caught. |

Plus two carry-forward guardrails:
- **Keep `verify_provenance()`** (`verification.py`) as the outer clamp around the debate output. Do NOT deprecate it (design Phase 3 said to — don't).
- **Default to SKIP** on ties/ambiguity. The edge is in not overtrading (single position, ~60% sideways thesis).

---

## 1. Roles & verified integration points (do not hallucinate these)

These were confirmed against the live tree on 2026-06-01. Build against them exactly.

| What | Where | Note |
|------|-------|------|
| Raw data source | `antariksh.tools.entry_tools.query_all_families(index="NIFTY") -> str` (line ~2234) | Returns a JSON **string**. 7 family fns also exist: `query_trend/momentum/volatility/volume/options/flow/macro`. |
| ⚠️ Open question for Phase 0 | — | **Unverified:** whether `query_all_families` returns RAW fields or already-SCORED verdicts (BULLISH/BEARISH). DeepSeek must check first (Step 0.1). If it returns verdicts, the Unicorn tool must strip them. |
| Entry gate to replace | `brahmand/e2e_chain.py::run_sequential_crew(entry_time) -> dict|None` (line 45) | Builds `entry_crew` (NOT_UP + NOT_DOWN agents) at lines ~213–289. |
| Output contract to PRESERVE | `entry_decision` dict, e2e_chain.py ~345–380 | Keys downstream depends on: `go`, `signal`, `confidence`, `strategy_to_execute` (`CALL_SPREAD`|`PUT_SPREAD`|`NONE`), `not_up_signal`, `not_down_signal`, `not_up_confidence`, `not_down_confidence`. **Unicorn must emit the same keys.** |
| Provenance clamp | `brahmand/verification.py::verify_provenance(decision, gate)` | Keep. Apply to Judge output. |
| LLM factory | `brahmand/llm.py`, `brahmand/factory.py:64` `blueprint.get("llm", "deepseek/deepseek-chat")` | YAML agents can set `llm:` per agent. Use this for the reasoner Judge. |
| DeepSeek wiring | `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL` (default `https://api.deepseek.com/v1`), `temperature=0` | Same env contract everywhere. Reuse it. |
| Agent registry | `brahmand/config/agents_registry.yaml` | Append agents; `factory.py` consumes them, no code change to add agents. |
| Tests root | `brahmand/tests/` (has `conftest.py`, `fixtures/`, `unit/`, `e2e/`) | Unicorn tests → `tests/unicorn/`. |

---

## 2. Canonical direction table (SINGLE SOURCE OF TRUTH — every prompt cites this)

This kills the C3 confusion. There is no "bull/bear". There are two **gates**, each a debate between an Advocate (argues to ENTER this gate's spread) and a Skeptic (argues to SKIP).

| Gate (`gate_type`) | Market view that triggers entry | Strategy to execute | Advocate argues | Skeptic argues | Judge `signal` on ENTER |
|--------------------|---------------------------------|---------------------|-----------------|----------------|--------------------------|
| `NOT_UP` | Market **rejects upside** (bearish pressure / won't rally) | `CALL_SPREAD` (bear call spread) | "upside is rejected → enter CALL_SPREAD" | "upside is NOT rejected → skip" | `NOT_UP` |
| `NOT_DOWN` | Market **rejects downside** (bullish floor / won't fall) | `PUT_SPREAD` (bull put spread) | "downside is rejected → enter PUT_SPREAD" | "downside is NOT rejected → skip" | `NOT_DOWN` |

On SKIP, `signal = "NONE"`. One `UnicornDebate` class is parameterized by `gate_type`; the Advocate/Skeptic prompts inject the relevant row. **No agent prompt may contain the words "bull" or "bear".**

---

## 3. Corrected architecture (data flow)

```
query_all_families(index)            # antariksh, JSON string
        │  (Phase 0: confirm raw vs scored; strip verdicts)
        ▼
unicorn_raw_query._run(index) ──────▶ ~50 raw fields, 7 families, NO verdicts (test-enforced)
        │  (same dict injected as context to all agents; 60s cache)
        ├───────────────┬───────────────────────────────┐
        ▼               ▼                                │
   ADVOCATE         SKEPTIC          (deepseek-chat, temp=0, parallel)
  (≥1..N points)  (≥1..N points)     each point = {family, claim, evidence:{field:value}}
        └───────┬───────┘
                ▼
   unicorn_verify.verify_points(raw, advocate_pts, skeptic_pts)   # PURE PYTHON, deterministic
                │   tags each point: VERIFIED | CONTRADICTED | UNVERIFIABLE
                │   computes advocate_score, skeptic_score, hallucinations[]
                ▼
   JUDGE  (deepseek-reasoner, temp=0)     # receives PRE-VERIFIED, PRE-SCORED claims
                │   weighs verified evidence, writes reasoning, picks signal per §2 rules
                │   MAY NOT recompute numbers; MAY NOT override a CONTRADICTED tag
                ▼
   unicorn_anomaly.check(scorecard)        # python sanity (e.g. both 0 but ENTER → SKIP)
                ▼
   verify_provenance(decision, gate_type)  # existing outer clamp — KEEP
                ▼
   entry_decision dict (existing keys §1)  ──▶ e2e_chain deterministic execution UNCHANGED
```

Key inversion vs the original doc: **the numeric verification moved OUT of the Judge LLM into `unicorn_verify.py`.** The Judge LLM's only job is judgment (weighing + synthesis + tie-breaking), which is what an LLM is actually good at.

---

## 4. The deterministic verifier — `brahmand/unicorn_verify.py` (the heart of C2)

This is the most important new file. It must be pure Python, no LLM, fully unit-testable.

```python
# Tolerances per field type — a claim "matches" raw data within tolerance.
TOLERANCE = {
    "abs_default": 0.5,      # absolute fields (adx, rsi, vix, atr...)
    "pct_fields": {"iv_rank", "bb_pct_b", "cmf", "pcr_total", "pcr_atm"},
    "pct_tol": 0.02,
}

def verify_points(raw: dict, points: list[dict], family_weights: dict) -> dict:
    """
    For each point {family, claim, evidence:{field: value}}:
      - look up raw[family][field]
      - VERIFIED      if |claimed - raw| <= tolerance       → +1.0 * weight
      - CONTRADICTED  if differs beyond tolerance            → +0.0, append to hallucinations[]
      - UNVERIFIABLE  if field absent / non-numeric claim    → +0.5 * weight
    Returns {score, tags:[...], hallucinations:[...], families_covered:set}
    """
```

Rules DeepSeek must honor:
- Verification is **field-level numeric comparison only**. No interpretation.
- A point that cites a field not present in `raw` for that family = `UNVERIFIABLE`, never auto-credited.
- `hallucinations[]` entries are human-readable: `"advocate: trend.adx claimed 55, raw=38 → CONTRADICTED"`.
- `families_covered` drives the minimum-coverage penalty (a side ignoring ≥4 families is weakened).
- Deterministic: same input → byte-identical output. This file gets exact-equality tests (it's not an LLM).

---

## 5. New files (build order) — each is a TDD phase

Follow `PROJECT_UNICORN_TDD.md` phases, with these file/behavior corrections:

```
brahmand/
  unicorn_raw_query.py     # UnicornRawQuery(BaseTool), wraps query_all_families, strips verdicts, 60s cache
  unicorn_verify.py        # ★ deterministic verifier (§4) — NO LLM
  unicorn_judge.py         # Judge wrapper: builds reasoner prompt from PRE-VERIFIED claims, parses JSON
  unicorn_debate.py        # run_unicorn_debate(raw, gate_type) orchestrator (Advocate→Skeptic→verify→Judge→anomaly→provenance)
  unicorn_anomaly.py       # scorecard sanity + fallback-to-deterministic
  config/unicorn_agents.yaml  # advocate_agent, skeptic_agent (deepseek-chat); judge_agent (deepseek-reasoner)
  tests/unicorn/
    __init__.py  conftest.py
    test_raw_query.py  test_verify.py  test_debate.py  test_judge.py
    test_integration.py  test_anomaly.py
    fixtures/ raw_data_sample.json  raw_data_not_up.json  raw_data_not_down.json  raw_data_ambiguous.json
```
Modified (Phase 5): `brahmand/e2e_chain.py` only.

---

## 6. Phase build instructions (with per-phase acceptance criteria)

**Phase 0 — Recon (DeepSeek, before any code).**
- 0.1 Print the actual output of `query_all_families("NIFTY")`. Document whether each family is raw or scored. If scored fields exist (e.g. `trend_signal: "BEARISH"`), list them — the raw tool strips exactly these.
- 0.2 Confirm `deepseek-reasoner` is reachable on the configured base_url with the existing key (one throwaway call).
- **Accept:** a `docs/UNICORN_PHASE0_FINDINGS.md` with the real field inventory + verdict-field list. No code until this exists.

**Phase 1 — `unicorn_raw_query.py`.** Per TDD 1.1–1.4, with: output MUST contain zero verdict tokens (test 1.2 list), 60s cache, returns the 7 families. 
- **Accept:** `tests/unicorn/test_raw_query.py` green; `test_no_verdicts_in_output` proves stripping works against REAL data (not a mock).

**Phase 2 — `unicorn_verify.py` (do this BEFORE agents).** Pure-Python verifier (§4).
- **Accept:** `test_verify.py` green incl: a CONTRADICTED point scores 0 + lands in hallucinations; an UNVERIFIABLE point scores 0.5; exact-equality tests pass (deterministic). This is the only module allowed exact-equality assertions.

**Phase 3 — Advocate & Skeptic agents.** `config/unicorn_agents.yaml`, `llm: deepseek/deepseek-chat`, parameterized by `gate_type` per §2. Soft evidence floor: "produce as many well-evidenced points as the data supports; if fewer than 2, say 'insufficient evidence' — do NOT manufacture points to hit a quota."
- **Accept:** `test_debate.py::test_advocate_valid_json`, `test_skeptic_valid_json` green; prompts contain no "bull"/"bear"; agents cite only fields present in the injected raw data.

**Phase 4 — Judge (`deepseek-reasoner`) + orchestrator.** Judge prompt receives the verifier's tagged/scored claims; it MUST NOT recompute numbers or overturn a CONTRADICTED tag. Tie/ambiguity → SKIP (`signal=NONE`). `run_unicorn_debate(raw, gate_type)` wires Advocate∥Skeptic → verify → Judge → anomaly.
- **Accept:** `test_judge.py` (fabrication caught via the verifier, not the LLM; correct signal on the not_up / not_down / ambiguous fixtures) + `test_debate.py::test_full_debate_e2e` green; output schema-valid; `signal ∈ {NOT_UP, NOT_DOWN, NONE}`.

**Phase 5 — Integration into `e2e_chain.py`.** Replace `entry_crew.kickoff()` block (~213–289) with two `run_unicorn_debate` calls (NOT_UP + NOT_DOWN). Map Judge output → the existing `entry_decision` keys (§1). Apply `verify_provenance`. Deterministic execution path below it UNCHANGED.
- **Accept:** ALL pre-existing e2e/full-cycle tests still pass; `entry_decision` keys byte-identical to before; integration test green.

**Phase 6 — Hardening.** `unicorn_anomaly.py`: scorecard sanity + graceful fallback to the current deterministic gate when `query_all_families`/LLM fails.
- **Accept:** `test_anomaly.py` green; `test_fallback_on_tool_failure` returns `{"source": "fallback", ...}` and never raises.

---

## 7. Guardrails — non-negotiable (DeepSeek MUST NOT)

1. **No fabricated/synthetic market data in any test that claims to validate live behavior.** Fixtures are clearly-labelled frozen snapshots only; never present a fixture result as a real backtest/P&L.
2. **No LLM in numeric verification or in execution.** Contracts, sizing, orders, SL/TP stay deterministic.
3. **Do not touch the risk/exit agent** or moduleize SL/TP/exit. Unicorn is the ENTRY gate only.
4. **Do not remove `verify_provenance`.**
5. **Do not change the `entry_decision` output contract.** Downstream (kickoff, regime_check) depends on it.
6. **No real-money / live deploy.** Build + tests + paper validation only. Claude signs off §8 before any live wiring.
7. Every claim in agent output must be traceable to a raw field; the verifier enforces this — do not add a code path that credits unverifiable claims.

---

## 8. Validation gates (Claude-owned — what I check before sign-off)

DeepSeek delivers; I validate each gate independently. A gate is RED until I confirm it on real artifacts (not DeepSeek's say-so).

**G1 — No-hallucination (the core claim).**
- Inject a fabricated field into an Advocate point (adx=55 when raw=38). Confirm `unicorn_verify` tags it CONTRADICTED, it scores 0, and it appears in `hallucinations[]`. Confirm the Judge LLM did NOT silently "fix" or credit it.
- Inject a fabricated field into a Skeptic point → same.
- **Pass:** both caught deterministically; Judge output references them.

**G2 — Model decorrelation in place.** Confirm `judge_agent.llm == deepseek/deepseek-reasoner` and Advocate/Skeptic == `deepseek-chat` (read the YAML + a live run log). 

**G3 — Direction integrity.** Across 20 fixtures spanning not_up / not_down / ambiguous: every ENTER maps to the correct strategy per §2 (NOT_UP→CALL_SPREAD, NOT_DOWN→PUT_SPREAD), every tie/ambiguous → NONE. Zero inverted mappings.

**G4 — Determinism honesty.** Re-run the same fixture through the full debate 10×. LLM text may differ; the *decision* (`signal`, `strategy_to_execute`) must be stable ≥9/10. If it flips, the tie-break/bias-to-skip is too weak — fix before sign-off. (No test may assert exact LLM-string equality — C4.)

**G5 — Contract preservation.** Diff `entry_decision` keys/types old vs new on the same input fixture — must be identical. All pre-existing e2e tests green.

**G6 — Graceful degradation.** Kill Redis (or mock tool failure) → gate returns deterministic fallback, never crashes, logs the degradation.

**G7 — Cost/latency reality.** Measure wall-clock for one full cycle (NOT_UP + NOT_DOWN = up to 6 LLM calls incl. reasoner). Record real p50/p95. Confirm it fits inside the entry-time budget (reasoner is slower than chat — budget ~30–60s, not the doc's 6s).

**G8 — Paper-shadow run.** Run Unicorn in shadow (compute signal, log it, do NOT trade) alongside the current deterministic gate for ≥5 sessions. Compare agree/disagree; review every disagreement by hand. Only after this do we discuss live wiring.

**Sign-off rule:** G1–G7 green on real artifacts + G8 shadow log reviewed → I write the acceptance note. Until then, no live money. (May-24 incident standard.)

---

## 9. Open questions deferred to Phase 2+ (don't block Phase 1)
- Cross-gate awareness (NOT_UP Advocate sees NOT_DOWN Skeptic) — design Q1. Start without it.
- Family weights stay equal (1.0) for Phase 1; tune only after G8 shadow data exists.
- Whether `deepseek-reasoner` latency forces moving the entry-gate cron earlier — decide from G7 numbers.
