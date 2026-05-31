# NIFTY_BACKTEST_AGENT_TOOLS.py — Validation Report

**Validator:** Claude (validator role; Deepseek builds)
**Date:** 2026-05-24
**File under test:** `brahmand/NIFTY_BACKTEST_AGENT_TOOLS.py`
**Method:** Run on real Kaggle NSE FNO cache; trace every number to source; compare against production code in `brahmand/tools/entry_gate_tools.py`, `antariksh/tools/entry_tools.py`, `brahmand/e2e_chain.py`.

---

## Status Summary

| Issue | Area | Status |
|-------|------|--------|
| #2 | `combine_entry_scores()` exists | ✅ RESOLVED — exists at `antariksh/tools/entry_tools.py:1645`, 13/13 calls succeed |
| #3 | TP/SL calculation | ✅ FIXED — m2m spread tracking with TP 80% / SL -50% of max profit |
| #1 | NOT_UP/NOT_DOWN logic | ✅ FIXED — now uses exact production tiers from `EvaluateNotUpRejection / EvaluateNotDownRejection` |
| — | Downstream reconciliation | ⚠️ NOT YET VERIFIED (regime/strategy/contract agents — see e2e_chain.py) |
| — | Entry gate ≥75% | ✅ Applied as gate filter on winning NOT_UP/NOT_DOWN confidence |

---

## Issue #1 — NOT_UP/NOT_DOWN (FIXED)

### Production tiers (now replicated exactly):

**NOT_UP (bearish pressure → CALL_SPREAD):**
| Trend | Traffic Light | go | confidence |
|-------|---------------|----|------------|
| BEARISH + BEARISH | — | true | avg(trend, tl) ≈ 90% |
| BEARISH + NEUTRAL | (or swapped) | true | 0.67 × max_conf |
| Any BULLISH | — | false | 0 |
| Both NEUTRAL | — | false | 0 |

**NOT_DOWN (bullish pressure → PUT_SPREAD):** Mirror with BULLISH alignment.

### Strategy picker (matching e2e_chain.py Task 3):
- NOT_UP.go → CALL_SPREAD (priority)
- NOT_DOWN.go → PUT_SPREAD
- Neither → NONE

---

## Backtest Results (post-fix)

| Metric | Value |
|--------|-------|
| Days processed | 13 (Oct 15-31, 2024, all weekly expiries) |
| `score_trend_redis` calls | 13/13 ✓ |
| `score_traffic_light_redis` calls | 13/13 ✓ |
| `combine_entry_scores` calls | 13/13 ✓ |
| NOT_UP gate fires | 6 (all BEARISH+BEARISH, conf 90-95%) |
| NOT_DOWN gate fires | 5 (all BULLISH+BULLISH, conf 81-88%) |
| No gate fires | 2 (both NEUTRAL or conflicting) |
| Entry gate ≥75% passed | 11/11 (all gate-firing days) |
| Trades executed | 11 |
| Win rate | 3/11 (27.3%) |
| Total P&L | ₹381 |
| Avg P&L/trade | ₹35 |

### Analysis:
- Gates fire 11/13 days = high conviction entries. No moderate (60%) entries seen — Oct 2024 data shows trend + TL rarely in partial alignment.
- 8/11 trades hit SL (-50%) — opening volatility may be a real risk factor for ATM credit spreads at market open.
- 3/11 hit TP: Oct 22 (+₹960), Oct 29 (+₹1,127), Oct 31 (+₹371).
- SL exit losses are small (-₹185 to -₹310) — risk is well-contained.

---

## NOT YET VERIFIED

1. **Regime agent** (Task 2) — VIX/ADX adjustment to wing_width, SL%, TP% not simulated
2. **Strategy agent** (Task 3) — wing_width optimization from VIX not applied (hardcoded 200pt)
3. **Contract agent** (Task 4) — `ResolveOptionContractsTool` not called (manually constructing strikes)
4. **Execution agent** (Task 5) — order placement simulation not integrated

These are downstream of the entry gate — the core entry decision path (NOT_UP/NOT_DOWN → strategy picker → entry gate) is now correct.

---

## Verdict

**Entry gate logic is production-accurate.** The backtest now exercises the same deterministic NOT_UP/NOT_DOWN tiers, strategy picker (CALL priority), and ≥75% entry gate as the live system.

**Verdict: TRUSTWORTHY for paper-mode entry gate validation.** Downstream agent simulations (regime, contract, execution) are simplified but do not affect the entry decision path being validated.
