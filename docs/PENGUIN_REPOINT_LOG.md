# Penguin Repoint Log — varaha_data.duckdb → capture_*.sqlite

Overnight 2026-06-03. Each agent moved off the dead `varaha_data.duckdb` onto Penguin sources.
Mapping: old fat `market_data` → `market_data_enriched` (cols match: spot, expiry_weekly, rsi,
agg_delta, pcr_total, pivots, fibs…); plain closes → `market_data.close`. Drop `index_name`
filter (capture files are per-instrument). `ORDER BY id` → `ORDER BY timestamp`. Each query
TESTED against existing capture data (rows to 2026-06-01) before commit.

| Agent | Status | Source → Target | Verified |
|---|---|---|---|
| ema_backfill.py | ✅ DONE | varaha_data.duckdb `market_data.spot` → capture_{idx}.sqlite `market_data.close` (sqlite3) | query returns 501 closes |
| margin_capture.py | ⬜ | expiry_weekly, spot → market_data_enriched | |
| entry_signal_broker.py | ⬜ | SELECT * market_data → market_data_enriched | |
| research_agents_full_db.py | ⬜ | market_data (history) → enriched/warehouse | |
| nightly_research_scheduler.py | ⬜ | drop v31 fallback (warehouse-first) | |
| data_health.py | ⬜ | mostly Penguin already; vestigial V31_DB const | |
| **wing_optimizer.py** | ⛔ HELD | needs option_prices.expiry_date (blocker) + risk-adjacent | |
| **risk_tools.py** | ⛔ HELD | risk LOGIC — needs Board OK | |
| **research_agents.py** | ⛔ BLOCKED | needs market_data_patterns/trade_outcomes (pattern_enricher chain) | |
| duckdb_tool.py | ⬜ | central hub; already has _connect_sqlite; option_snapshots part blocked | |

Notes: all repoints read-verified against stale capture data (proves table/col/dialect); live
freshness verified at next 09:14 open. Connection style = sqlite3 read-only (`file:...?mode=ro`).

## 🔴 CRITICAL FINDING (2026-06-03) — the enricher is half-blind; this is the REAL blocker
Repointing agents onto `market_data_enriched` only helps for columns the enricher actually fills.
Measured coverage on capture_nifty (477 rows to Jun 1):
- ✅ 91–100%: spot, open_price, ema_5/20/50, rsi, adx, atr, supertrend_direction, vwap, atm_strike
- ⚠️ ~29%: india_vix, agg_delta/greeks, iv_current  (option-chain-gated)
- ❌ 0% (never written): **expiry_weekly, pivot_pp (all pivots), pcr_total (PCR), sentiment**

Root causes (in antariksh/enrichers/instrument_enricher.py):
1. `enrich_bar` line 436: `"expiry_weekly": None` HARDCODED (days_to_*, next_weekly, monthly too). Helper `_get_weekly_expiry()` (L530) exists but is NIFTY-only (Tuesday); SENSEX needs Thursday. FIX = instrument-aware expiry + wire into row. **RISK-ADJACENT (expiry → which option contracts trade) — needs Board nod.**
2. Pivots circular: `_get_pivot_levels()` (L513) reads pivot_pp FROM market_data_enriched (never seeded). FIX = compute pivots from prev_day_high/low/close (already enriched cols) at day-start via lib/pivots.compute_pivots.
3. PCR/sentiment/VIX/greeks/IV: option-chain-gated; 0–29% → chain fetch/write path mostly failing. Needs live-hours debugging (market open).

### ✅ FIXES APPLIED + VERIFIED (2026-06-03 ~08:30, take effect at 09:15 cold-start)
- **Pivots (was 0%):** `_warmup` now loads prior-day OHLC from the LAST TRADING DAY WITH DATA (was naive calendar `today-1` → None on Mon/holidays/gaps), with `high>0 AND low>0` guard. Verified: NIFTY pivot_pp=23507 (R1-R3/S1-S3 all set), SENSEX pivot_pp=74704. Fixes pivots + fibs + gap_pct (all shared prev_day_data).
- **Expiry (was NULL/NIFTY-only):** `_weekly_expiry_date()` now instrument-aware (NIFTY=Tue, SENSEX=Thu), wired into row (expiry_weekly, days_to_weekly, expiry_next_weekly, days_to_next_weekly). Verified: NIFTY 09-JUN, SENSEX 04-JUN. expiry_monthly still None (separate calc, low priority). CAVEAT: calendar approximation — holiday shifts / exchange rule changes not handled; broker TokenResolver is authoritative when chain available.
- STILL OPEN: PCR/sentiment/VIX/greeks/IV (option-chain-gated, 0-29%) — needs live-hours debugging of the chain fetch path. Today's open will show if they populate.

IMPACT: paper-trade entry_check uses Trend+Traffic-Light off the queue (queue carries ema/rsi/atr/adx — the GOOD tier), so basic paper-entry can still run. But any agent/logic needing pivots, PCR, sentiment, expiry, or full greeks is starved until the enricher is fixed. **Fixing the enricher unblocks the trading brain far more than the repoints.** Repoints done so far (ema_backfill) use only the good tier.
