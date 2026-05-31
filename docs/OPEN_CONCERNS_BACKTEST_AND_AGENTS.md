# Open Concerns — Backtest & Agent Validation

**Author:** Claude (validator role; Deepseek builds)
**Date:** 2026-05-24
**Scope:** Consolidated, current-state concerns across the 2024 validation effort. Supersedes the point-in-time notes in `REPLAY_HARNESS_REVIEW.md` and `NIFTY_AGENT_TOOLS_VALIDATION.md` for status; build target is `AGENT_CONFORMANCE_HARNESS_SPEC.md`.

---

## 0. URGENT — do before tomorrow's live run
- **Production Redis db=0 still polluted.** The first replay run (before the db=1 fix) left **201 stale 2024 bars** in live `v3_ohlcv_queue` (db=0): O=H=L=C single-point bars at ~24,400, timestamps like `09:15:59`.
- The live capture only **appends** (`data_capture_v3.1_duckdb.py:1203-1204`, `lpush` + 7-day TTL, no flush), so tomorrow's real bars stack on top; `get_live_candles` reads a 360-bar lookback → **morning traffic-light signal corrupted** until ~360 fresh bars accumulate. TTL won't clear it until ~May 31.
- **Fix:** `redis-cli -n 0 DEL v3_ohlcv_queue` (safe — holds only 2024 garbage; live capture rebuilds it). Also verify/clear production `data/ema_state/60min/*.json` (overwritten by an earlier run) or restart the data-capture + EMA services so state rebuilds clean.
- Status: NOT YET DONE — awaiting go-ahead (writes to production).

---

## 1. REPLAY_KAGGLE_TO_REDIS.py (Deepseek)

### Fixed ✅
- Production isolation now correct: Redis → `db=1` (line 56) **and** tools forced to db=1 via monkey-patch (lines 364-373); EMA → `/tmp/backtest_ema_state` (line 35) **and** tools redirected via `_Path` patch (lines 376-387). Data + reader on same DB/path; production paths untouched going forward.
- Corrupted dead glob string removed (lines 68-73 clean).

### Open ❌
1. **60min EMA is fake.** `compute_emas` (lines 200-210) computes a **1-minute** EMA; `write_ema_state_files` (lines 213-238) writes that same value into **both** `60min/` and `1min/`. Production `score_trend_redis` reads primary from `60min/` (`entry_tools.py:982`) expecting hourly-candle EMAs. → trend signal ≠ production. Fix: aggregate 1-min → 60-min candles, compute EMA on those.
2. **Gates reimplemented, not invoked.** `evaluate_not_up/down` (lines 246/289) are local copies, not imported from `brahmand/tools/entry_gate_tools.py` (`EvaluateNotUpRejection/EvaluateNotDownRejection`). Can drift.
3. **`combine_entry_scores` skipped.** Imported (line 356) but never called; loop uses local gates (lines 446-447). Decision path ≠ production.
4. **Misleading comments.** Docstring/comments still say "no monkey-patching — native reads" (lines 4, 10, 442) though it now patches Redis and `_Path`. Cosmetic.
5. **Queue ordering** lpushes `reversed(bars)` → head = oldest; production convention is head = newest (`entry_tools.py:906`). Verify against production LPUSH order.
6. **Single-point bars** (O=H=L=C=spot via put-call parity) — TF colors survive aggregation, no real intrabar high/low. Medium fidelity.
7. **End-diff** compares `not_up_go/not_down_go/suggested_trade` against `NIFTY_BACKTEST_AGENT_TOOLS_LOG.json`, whose schema may lack those keys → `.get()` returns None → "ZERO diffs" can be false. Verify shared keys.

---

## 2. Conformance harness NOT yet built (the actual goal)
The replay is a tool-runner; it does **not** prove the live CrewAI agents are consistent / hallucination-free / fake-P&L-free. Per `AGENT_CONFORMANCE_HARNESS_SPEC.md`, still missing:
- **Pillar 1 — Provenance:** capture every tool call (CrewAI `step_callback`); assert every number in an agent decision traces to a tool output. Fail closed on unverifiable numbers.
- **Pillar 2 — Consistency:** `temperature=0`; run each fixed state N=20× → identical decisions; cross-check crew decision == direct-tool oracle.
- **Pillar 3 — P&L integrity:** P&L only from deterministic settlement (`risk_monitor.py:206-245`) on recorded fills; assert no agent task output contains a P&L field.

---

## 3. Production-layer fixes (independent of any backtest) — verified gaps
- **No LLM determinism.** `e2e_chain.py:45-49` builds `LLM(model="deepseek/deepseek-chat", ...)` with **no `temperature`/seed** → agents non-deterministic. Fix: `temperature=0`.
- **Agent JSON trusted blindly.** `_parse_json_output` (`e2e_chain.py:52-58`) accepts any JSON the LLM emits with **no check that numbers came from tools** → hallucination reaches execution. Fix: provenance guard at this boundary, fail closed.
- **P&L design is OK** (`risk_monitor.py:206-245` computes from fills, not LLM) but marked "simplified" — validate against real broker fills.

---

## 4. TP/SL unresolved (affects every P&L number)
- `NIFTY_BACKTEST_AGENT_TOOLS.py` uses `tp=spread×0.2`, `sl=spread×0.05` (function params `0.80/-0.50` are dead code).
- `NIFTY_AGENT_TOOLS_VALIDATION.md` claims "80% / -50% of max profit" — does NOT match the code.
- **Neither traces to any production config** (none found in `config/`, `risk_monitor.py`, `order_agent.py`). Must reconcile against the production source of truth before any P&L is trustworthy.

---

## 5. Fidelity gaps that cap how much ANY of this can tell us
- Backtest/tool runs **bypass the LLM** entirely; only the conformance harness (Section 2) tests agent behavior.
- `market_ctx` is empty in tool runs (`vix=None, pcr=None, patterns=[]`) → `combine_entry_scores` market adjustment inert → confidence ≠ production.
- Downstream agents (regime VIX/ADX→wing/SL/TP, strategy wing-width, contract resolution, execution) and risk management (morph / leg-shift / TSL) are **not simulated** → P&L not representative.

---

## Verdict / gate to trust
Do NOT deploy real money until: db=0 flushed (§0); 60min EMA real (§1.1); gates + `combine_entry_scores` invoked from production code (§1.2-1.3); conformance harness enforces the 3 invariants on real 2024 data (§2); `temperature=0` + provenance guard in production (§3); TP/SL reconciled to production source (§4). Re-validation by Claude required after each.
