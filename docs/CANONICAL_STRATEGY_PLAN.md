# Project SHERPA — Canonical Deterministic Strategy (Option A)

**Date:** 2026-06-11 · **Status:** Board approved 2026-06-11; build in progress

## Progress log

| Date | Phase | Status |
|---|---|---|
| 2026-06-11 | Phase 0 — fail-loud + honest fills | ✅ DONE commit `1c377b9`: `notify.py` Telegram channel (verified live); `data_health.check_llm` (402 scan + fallback-ratio counter, Telegram-alerted, throttled 1/hr); `place_entry_orders` marks ₹0 legs to live LTP or REJECTs (regression `tests/test_honest_entry_fills.py` 3/3). DeepSeek topped up + verified live 2026-06-11 00:48. |
| 2026-06-11 | Phase 1 — canonical consolidation | ✅ CORE DONE commit `c23f40b`: `canonical_strategy.py` (entry_tools decision core; fixes live wrong-side bug — old fallback sent BULLISH→CALL_SPREAD; VIX-null fails closed; params via `data/strategy_params.json` = future LLM seam); `fallback.py` + `unicorn_debate._deterministic_fallback` now shims; golden tests 10/10. PORCUPINE `llm_down` scenario PASS 4/4 (antariksh `8413418`, driver `a906948`). **PHASE 1 COMPLETE.** |
| 2026-06-11 | Phase 2 — validate edge (backtest canonical, 3 Board numbers) | 🔨 IN PROGRESS. Data inventory: Kaggle NIFTY-50 minute bars 2015→2026-05 + INDIA VIX minute (Tier A); real options only 13 days Oct-Nov 2024 (Tier B anchor). **Bonus live fix `bb8c9ef` (antariksh):** traffic-light scorer ignored get_live_candles' string shape → TL family was permanently NEUTRAL 0% (half the entry signal dead); fixed + 3/3 regression; verify TL non-zero in chain logs at next market open. Replay engine BUILT (backtest/sherpa/: data_loader, replay_io, bs_pricer, trade_sim, run_backtest). Full-2024 run COMPLETE → **3 Board numbers delivered, verdict NEGATIVE expectancy (see §1b)**. Phase 2 deliverables DONE; gate fired → harness recalibration before any paper trade. |
| 2026-06-11 | Phase 2b — parameter recalibration (sweep in harness, H1 train / H2 validate) | ✅ DONE — **verdict: NO config survives out-of-sample.** 216-config grid (conf 35-70 × SL 0.25-0.60 × TP 0.30-0.70 × 1-3/day × window): only 6/216 positive on H1-train (best +₹20.8K/6mo, marginal), ALL collapse out-of-sample (H2: −₹80-96K; 2025: −₹210-338K) → H1 positives were pure overfit. Trace facts: gate says GO at **97% of decision points** (conf median 56). `sweep_results.json` kept. **Conclusion: the directional core (EMA-slope trend + traffic-light → CALL/PUT spreads) has NO edge in this execution shape — params can't fix it.** Note strategy drift: the original Varaha thesis is 60%-sideways premium selling (iron fly), but the canonical core trades DIRECTIONAL spreads. Next experiment: test the actual thesis — short premium (iron fly / dual spread) on NEUTRAL/low-conviction points in the same harness. |
| 2026-06-11 | Phase 2c — test the ORIGINAL thesis: neutral premium selling on sideways signals | ⏳ NEXT |
**Decision:** The deterministic logic IS the trading system. The LLM is an overlay that optimizes parameters — it can never be required for the system to trade, and its absence can never silently change behavior.

---

## 1. Why (evidence, 2026-06-10)

- DeepSeek balance hit 0 → every LLM call 402'd all day. No alert fired.
- The chain did NOT degrade to "existing logic": it has **two different deterministic fallbacks that disagreed on the same data**:
  - `unicorn_debate._deterministic_fallback` (SuperTrend consensus + VIX<20 + session): said **GO** NOT_UP conf 0.111
  - `fallback.py::deterministic_fallback` → antariksh `entry_tools` scoring: said **NO-GO** NEUTRAL 22%
- Root cause of disagreement: different data sources (enriched-snapshot `trend.timeframes` vs Redis-direct scoring) + different thresholds.
- Result: zero trades, and the day's "NO-GO" log is false evidence about the strategy.
- Separate finding: 06-05 paper trade entry orders FILLED at `execution_price: 0.0` — paper P&L is fiction until fills are marked to live LTP.

## 1b. PHASE 2 RESULT — the 3 Board numbers (2026-06-11, full-2024 run)

Engine: REAL `canonical_strategy.decide_entry` driven over Kaggle NIFTY+VIX minute
bars via the production I/O seams (zero strategy reimplementation). Premiums =
Black-Scholes @ IV=VIX (flat smile — Tier-B calibration vs 13 real option days
pending). Today's contract spec (Tue weekly, lot 65), honest costs, NSE margin
floor ₹30K/lot, MAX 3 trades/day (live re-entry discipline).

| Board number | Value |
|---|---|
| 1. Return on capital | **−13.0% / month** (−₹312,954 over 12 months on ₹2L — capital ruined ~1.5×; max DD ₹324K) |
| 2. Avg win / avg loss / win rate | +₹7,514 / −₹5,869 / 39.5% → **expectancy ≈ −₹580/trade** |
| 3. Max hedged lots on ₹2L | **6** (margin ≈ ₹30K/lot NSE floor) |

Detail: 539 trades (86% of decision points said GO — the gate barely filters);
exits = 289 SL / 126 TP / 124 EOD; costs ₹85,880 (~₹160/trade friction);
2 positive months out of 12 (Jun +34K, Aug +43K).

**VERDICT (per §Phase 2 gate): NEGATIVE expectancy — do NOT paper-trade these
params. Recalibrate in the harness, not live.** Dominant failure modes:
(a) entry gate too permissive (conf ≥35 passes nearly everything),
(b) SL 25% on a near-expiry ATM sold leg is hair-trigger (54% of exits),
(c) churn: 2.2 trades/day × costs.
Next: parameter sweep in the harness — confidence threshold, SL/TP, trades/day,
entry window — trained on 2024-H1, validated out-of-sample on 2024-H2 (and
2025 data exists for further validation). Caveat: synthetic premiums put error
bars on magnitude, not on sign.

## 2. Goal & realistic calibration

User target: ₹15–20K/month on ₹2L (7.5–10%/mo). Evidence check:

- 2024 backtest: ₹287k on 2,055 trades @75-lot sizing → ~₹140/trade avg; margin deployed ≫ ₹2L → return-on-margin likely low-teens %/yr.
- ₹2L at MINI sizing ≈ 2–3 hedged lots. Near-expiry net premium ~₹2–4K/lot/week. Theoretical perfect-capture ceiling ≈ ₹25–35K/mo; at 46.4% win rate realistic net = **₹4–10K/mo (2–5%/mo)**.
- 10% DD floor (₹20K) vs ₹5–10K per SL hit → 2–3 consecutive losses breach the floor. Floor or sizing must change.

**Calibration proposal (Board to confirm):** Phase-gate the target. Prove ≥2%/mo positive expectancy after costs on paper first; scale capital (not risk-per-trade) once proven. The number that matters is **% edge per rupee of margin**, not absolute ₹/day.

## 3. Phases

### Phase 0 — Fail-loud + honest accounting (1 day, prerequisite)
1. Top up DeepSeek balance (user).
2. `data_health.py`: add LLM-reachability check + 402 counter → Telegram (rides existing */5 cron, no new cron).
3. Daily counter in chain logs: `llm_decisions` vs `fallback_decisions` — every kickoff summary line states which brain decided.
4. **Fix ₹0 paper entry fills:** at paper order placement, mark fill to live `option_prices` LTP (same approach as the `_mark_legs_to_ltp` exit fix). Reject entry if LTP unavailable (fail-closed on data, not on LLM).

### Phase 1 — Consolidate to one canonical strategy (2–3 days)
1. New module `brahmand/canonical_strategy.py`:
   - Single entry decision function: inputs = one snapshot dict (enriched SQLite + Redis option hash), outputs = `{go, signal NOT_UP|NOT_DOWN|NONE, confidence, strategy{type, wing_width, sl_pct, tp_pct}, reasons[]}`.
   - Merge the two fallbacks: SuperTrend multi-TF consensus + EMA position + VIX gate + session gate + traffic-light completion scoring. ONE confidence definition (document the formula; kill the 1/9 artifact).
   - ONE data path: enriched snapshot (`market_data.get_latest_market_snapshot`) — no Redis-direct duplicate reads.
2. Re-route all call sites: 6 `deterministic_fallback` calls in `e2e_chain.py` + 2 in `unicorn_debate.py` → canonical. Delete `fallback.py` logic and `unicorn_debate._deterministic_fallback` (keep thin shims if imports demand).
3. Resolve the 3 DeepSeek-flagged critical issues in this logic (NOT_UP/NOT_DOWN mapping, TP/SL params, `combine_entry_scores`) — verify current fix status first, fix what's open.
4. Guards:
   - PORCUPINE scenario `fault:llm_down` — replay a signal day with an LLM-402 stub; assert system still produces the same entry decision as LLM-up deterministic path.
   - Unit tests pinning canonical decisions on fixed snapshots (golden table).
   - Conformance test: no second deterministic entry implementation exists (import/grep guard, same lesson as the reader-migration guard).

### Phase 2 — Validate edge (≈1 week, gates everything after)
1. Backtest **the canonical module itself** (same code object, not a reimplementation) on:
   - 2024 Kaggle NIFTY (volume of trades, regime diversity)
   - Penguin-captured 2026 data, only days after the low=0 fix (clean bars)
   - MONGOOSE 16-day scenario catalogue (behavioral correctness)
2. With honest costs: slippage model + brokerage + STT.
3. Deliver the 3 Board numbers:
   - return on margin deployed (%/mo)
   - avg win ₹ / avg loss ₹ / win rate at MINI sizing
   - max concurrent hedged lots on ₹2L
4. **Gate:** positive expectancy after costs → Phase 3. Negative → recalibrate strategy params (wings, SL/TP, entry windows) in the harness, NOT live.

### Phase 3 — Paper trade for real (2 weeks)
- 10 sessions, canonical strategy only, honest fills, full lifecycles (entry→monitor→exit→booked P&L).
- Daily Telegram report: decisions brain (LLM/deterministic), trades, P&L, data health.
- **Acceptance:** ≥5 completed lifecycles; booked P&L matches manual recompute from option_prices; zero silent failure days (every market day produces either trades or an explainable NO-GO with healthy data).

### Phase 4 — LLM overlay = the actual "self-learning" (after Phase 3 passes)
- LLM (UNICORN debate + position research cache) proposes **parameter deltas only**: wing width, SL/TP pcts, skip-day, strike shift. Never a hard gate.
- Every delta logged against the canonical baseline decision (A/B journal). Shadow mode first: deltas recorded, not applied.
- Adopt a delta class only when it beats baseline over N≥30 trades. The learning artifact = versioned parameter file + decision journal (this answers "what changes after a losing trade").

### Phase 5 — MCX session 2
- Only after ≥4 profitable paper weeks AND recalibrated targets signed off. Not before.

## 4. Feasible now vs optimize later

| Now (this plan) | Later (explicitly deferred) |
|---|---|
| Fallback consolidation | Option OI/IV Penguin source (needs BS solver) — better strike selection |
| 402 fail-loud + brain counter | Multi-TF SQLite cutover completion (staged) |
| Honest paper fills | H1–H3 process-resilience sim (systemd/heartbeat) |
| Kaggle + captured-data backtest of canonical code | LLM weight-optimizer fns in entry_tools (half-built, crewai imports missing) |
| LLM overlay A/B journal | MCX |

## 5. Honest risks

- Clean captured data is thin: low=0 corruption poisons bars before 2026-06-09; 2024 Kaggle is a different regime + different lot size. Edge numbers will carry wide error bars — treat Phase 2 output as a go/no-go on sign, not a precise forecast.
- Near-expiry short premium = short gamma. One unmanaged trend day can erase weeks. SL discipline is the strategy; the floor math in §2 must be resolved (smaller size or wider floor) before paper.
- 46.4% win rate ⇒ 6–8 loss streaks are normal. Recalibrated expectations prevent strategy-abandonment at the first streak.

## 6. Board calls needed

1. Confirm target recalibration: prove %-edge first, scale capital later (vs keep ₹1000/day on ₹2L).
2. Confirm deletion of both legacy fallback implementations (replaced by canonical + shims).
3. DD floor vs sizing: shrink to MICRO lots, or widen floor beyond 10%? (Current combo mathematically breaches in a normal streak.)
4. Phase 4 scope: morph/shift stays LLM-cached-research (per standing "risk agent stays LLM" rule) — confirm it remains overlay-only, protective SL/TP/EOD/floor stay deterministic.
