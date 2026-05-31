# Agent Conformance Harness — Build Spec

**Author:** Claude (validator) — spec for Deepseek to build
**Date:** 2026-05-24
**Goal:** Prove the live CrewAI agents (1) behave **consistently**, (2) **never hallucinate** numbers, (3) **never emit fake P&L** — before any real-money deployment.

> This is NOT the existing `NIFTY_BACKTEST_AGENT_TOOLS.py`. That script bypasses the LLM and only validates the deterministic tools. This harness runs the **real `e2e_chain.py` crew (LLM in the loop)** against replayed 2024 data and enforces invariants.

---

## Verified current state (the gaps this harness must close)

| Fact | Location | Implication |
|------|----------|-------------|
| LLM has no `temperature`/seed | `e2e_chain.py:45-49` (`LLM(model="deepseek/deepseek-chat", ...)`) | Agents are non-deterministic; same state → possibly different decisions |
| Agent JSON trusted verbatim | `e2e_chain.py:52-58` (`_parse_json_output`) | A hallucinated number in agent output reaches execution unchecked |
| P&L computed from fills, not LLM | `risk_monitor.py:206-245` (`final_pnl += (entry - ltp) * qty`) | Correct design — but "simplified" and unvalidated vs broker fills |
| No determinism/provenance/consistency tests | `tests/unit/`, `tests/e2e/` | No automated guard today |

---

## The three invariants

1. **PROVENANCE:** every numeric field in an agent's decision (`go`, `confidence`, `signal`, `trend_signal`, `traffic_light_signal`, strikes, premiums) must equal a value returned by a tool call in that same run. No tool-sourced match → hallucination → FAIL.
2. **CONSISTENCY:** for a fixed market state, (a) N repeated crew runs produce identical decisions, and (b) the crew decision equals the direct deterministic-tool decision (the oracle).
3. **P&L INTEGRITY:** P&L is produced only by the deterministic settlement function from recorded fills. No agent task output may contain a P&L field.

---

## Architecture

```
2024 Kaggle CSV  ──▶  replay loader  ──▶  Redis v3_ohlcv_queue + ema_state files
                                              │
                                              ▼
                        ┌──────────────────────────────────────────┐
                        │  PER FIXED STATE (date + entry_time)       │
                        │                                            │
                        │  A) REAL CREW  run_sequential_crew()       │  ← LLM in loop
                        │     with step_callback capturing every     │
                        │     (tool_name, input, raw_output)         │
                        │                                            │
                        │  B) ORACLE  direct deterministic-tool call │  ← reuse logic from
                        │     (score_*, combine_entry_scores,        │     NIFTY_BACKTEST_AGENT_TOOLS.py
                        │      Evaluate{NotUp,NotDown}Rejection._run)│
                        │                                            │
                        │  C) ASSERT invariants 1, 2, 3              │
                        └──────────────────────────────────────────┘
                                              │
                                              ▼
                            conformance_report.json  (pass/fail per state)
```

The replay loader already exists in substance inside `NIFTY_BACKTEST_AGENT_TOOLS.py` (spot reconstruction, EMA computation, bar push). Reuse it — do not reinvent.

---

## Pillar 1 — Provenance enforcement (anti-hallucination)

**Capture:** attach a CrewAI `step_callback` (or per-tool wrapper) that appends every tool call to a list:
```python
tool_trace.append({"tool": name, "input": args, "output": raw_return})
```

**Check:** after each agent emits its decision dict, extract every numeric value and assert it appears in some tool output for that run:
```python
def assert_provenance(decision: dict, tool_trace: list[dict]) -> list[str]:
    """Return list of violations. Empty = clean."""
    tool_numbers = collect_numbers_from(tool_trace)   # set of all numbers any tool returned
    violations = []
    for key, val in iter_numbers(decision):           # go/confidence/signal/strikes/premiums
        if isinstance(val, (int, float)) and val not in tool_numbers_with_tolerance(tool_numbers):
            violations.append(f"{key}={val} not produced by any tool (hallucination)")
    return violations
```
- Signals (`BULLISH/BEARISH/NEUTRAL`) must also match the tool that produced them.
- Tolerance: exact for discrete fields; small epsilon only where a documented transform applies.

**Stronger target (recommend):** the agent decision should be *rebuilt from the tool outputs*, with the LLM only choosing the path. Then provenance is structural, not a post-hoc check.

---

## Pillar 2 — Consistency (determinism + oracle cross-check)

**2a. Run-to-run identity**
- Pin `temperature=0` (see Immediate Fix #1).
- For each state, run `run_sequential_crew(entry_time)` **N=20 times**. Assert all 20 decisions are byte-identical (after JSON-normalizing). Report any field that varies.

**2b. Oracle cross-check**
- For each state, compute the decision directly from the deterministic tools (reuse `NIFTY_BACKTEST_AGENT_TOOLS.py` logic: gate tiers + strategy picker + entry gate).
- Assert `crew_decision.go == oracle.go`, `.signal == oracle.signal`, `.suggested_trade == oracle.suggested_trade`, and `abs(crew.confidence - oracle.confidence) == 0`.
- Any divergence = the LLM is altering deterministic tool output → FAIL with the diff.

---

## Pillar 3 — P&L integrity (no fake P&L)

1. **Source of truth:** P&L only from the deterministic settlement (`risk_monitor.py` close path) using recorded fills in `order_ledger.json` / `trade_execution.duckdb`.
2. **Assert agents are P&L-free:** scan every `tasks_output` JSON; fail if any contains `pnl`, `p&l`, `profit`, `final_pnl`, `realized`, etc. Agents decide; they do not report money.
3. **Validate settlement math:** for a set of recorded closed trades, recompute `final_pnl` from stored entry/exit fill prices × qty and assert it matches the logged `final_pnl`. Removes the "simplified" caveat.

---

## Immediate production fixes (separate from the harness — Deepseek to apply)

These are required regardless of any backtest. They touch the **live** `e2e_chain.py`, so apply deliberately.

**Fix #1 — Pin determinism** (`e2e_chain.py:45-49`):
```python
return LLM(
    model="deepseek/deepseek-chat",
    base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
    api_key=api_key,
    temperature=0,        # ADD: deterministic decisions
    # seed=<fixed>        # ADD if deepseek API supports it
)
```

**Fix #2 — Provenance guard at the trust boundary** (`e2e_chain.py:52-58`):
`_parse_json_output` currently trusts any JSON. Add a validation step that, given the agent's parsed decision + the captured `tool_trace`, rejects (or repairs to the tool value) any number that did not come from a tool. Fail closed — a decision that can't be verified must NOT proceed to execution.

---

## Acceptance criteria

- [ ] Replay loader pushes 2024 bars to Redis + ema_state; tools read 2024 data (already verified for `score_trend_redis` / `score_traffic_light_redis`).
- [ ] `step_callback` captures 100% of tool calls per run.
- [ ] Provenance check: 0 violations across all replayed states (or every violation explained by a documented transform).
- [ ] Determinism: 20/20 identical decisions per state at `temperature=0`.
- [ ] Oracle cross-check: crew decision == direct-tool decision for every state.
- [ ] P&L: no agent output contains a P&L field; settlement recomputation matches logged P&L on recorded trades.
- [ ] `conformance_report.json` emitted with per-state pass/fail and the evidence (tool_trace + decisions).

## Deliverables (Deepseek builds)
1. `AGENT_CONFORMANCE_HARNESS.py` — replay + real-crew run + oracle + invariant assertions.
2. `e2e_chain.py` Fix #1 + Fix #2.
3. `data/conformance_report.json` — machine-readable results.

## Validation (Claude)
After Deepseek builds: trace each assertion to real captured data, confirm no invented numbers, confirm divergences are real, sign off only if all acceptance criteria pass on real 2024 data.
