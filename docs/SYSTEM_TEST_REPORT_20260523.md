# System Test Report — May 23, 2026

**Timestamp:** 2026-05-23T20:24:21 IST  
**Status:** ✅ READY FOR DEPLOYMENT  
**Next Session:** Monday, May 24, 2026 — 9:30 AM IST

---

## Test Summary

| # | Component | Result | Detail |
|---|-----------|--------|--------|
| 1 | Test trade entry | ✅ | SELL 11750 PE @ ₹2.35 |
| 2 | Price data | ✅ | 1,203 rows available |
| 3 | Monitoring (SL hit) | ✅ | Exit ₹4.35, P&L ₹-150.00 |
| 4 | Order placement | ✅ | ORD-20260523-0012, fill ₹250.00 |
| 5 | DuckDB access | ✅ | 0 active trades, DB writable |

---

## Full Cycle Simulation

| Metric | Value |
|--------|-------|
| Entry price | ₹2.35 |
| Exit price | ₹4.35 |
| Exit reason | SL_HIT |
| P&L | ₹-150.00 |
| Test passed | True |

---

## System State at Test Time

| Component | Status |
|-----------|--------|
| Redis v3_ohlcv_queue | Live (15 indicators, 0 NULLs) |
| DuckDB varaha_data | Accessible (5,429 rows) |
| DuckDB market_data_multitf | Accessible (2,489 rows) |
| ChromaDB research patterns | 4 patterns stored |
| Entry gate | Wired (VIX/PCR/patterns) |
| Risk agent crew | Deployed (Morpher → Shifter → Risk) |
| Position manager bridge | Active (1-min cron via flock) |
| All guard scripts | Flock-protected, zero leaks |
| Test suite | 99/99 pass (0.13s) |

---

## Deployed Cron (Ready for Monday)

```
# Entry gate signal
*/5 9-15 1-5  entry_check_daemon.py

# Kickoff entry (5-min)
*/5 9-15 1-5  kickoff.py

# Position manager bridge (1-min LLM risk)
*/1 9-15 1-5  run_position_manager.sh

# Margin capture (5-min)
*/5 9-15 1-5  run_margin_capture.sh

# Pattern enricher (5-min)
*/5 9-15 1-5  run_pattern_enricher.sh

# Data health monitor (5-min)
*/5 9-15 1-5  data_health.py --alert

# Nightly research
0 23 1-5     nightly_research_scheduler.py
```

---

## Recent Fixes Deployed

| Fix | Commit | Repo |
|-----|--------|------|
| Pattern quality weighting (0.10 → 0.10*hit_rate) | `edf3781` | antariksh |
| Pattern directionality (predicted_direction in ChromaDB) | `bc9db52` | brahmand |
| Regime detection fix (close_price → spot) | `be12ac7` | brahmand |
| All guard scripts with flock (zero process leaks) | `7cecd13` | brahmand |
| Risk agent crew (Morpher + Shifter + Risk) | `fb16ba8` | brahmand |
| Redis TTL 7-day expire | `8c1ab63` | python-trader |
| NOT_UP/NOT_DOWN split agents | `dda850a` | brahmand |
| 99/99 test suite | `85d1e2e` | brahmand |
