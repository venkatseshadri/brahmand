# Session Findings — May 25, 2026

Generated: 21:45 IST Monday

---

## 1. Trade Activity Today

**1 trade executed:** `TRD-20260525102654 — CALL_SPREAD`

| Field | Value |
|-------|-------|
| Entry time | 10:26 AM |
| Exit time | 15:31 (MARKET_CLOSE) |
| Strategy | CALL_SPREAD (23950CE SELL + 24150CE BUY) |
| Net credit | ₹82.0 |
| **Notional P&L** | **~₹4,650** (estimated from spot close at 23970) |
| System P&L | ₹0.0 (bug — `exit_trade` fell back to `fill_price` because `option_snapshots` had no data after 09:20) |

**Entry signal:** Trend=BULLISH, TL=BEARISH (genuine conflict). Research override was too aggressive — forced both gates to GO at 40% despite conflict. This was a bug. The override should only fire when both trend+TL are NEUTRAL, never on conflict.

---

## 2. Data Capture Failure

**v3.1 NIFTY captured only 6 bars (09:15–09:20) then died.**

Root cause: DuckDB lock conflict. The original process (PID 1401886) crashed but never released its file lock on `varaha_data.duckdb`. The master wrapper's built-in watchdog tried restarting every 30 seconds from 09:20 to 15:30 — all failed with `Conflicting lock is held in PID 1401886`.

The external watchdog cron also failed — ran at 09:00/05/10 (market closed), then nothing until 15:35. Likely crashed at 09:15 with stale lock.

**Impact:**
- `market_data`: only 6 rows today
- `option_snapshots`: 257 rows, all before 09:20
- Redis `v3_ohlcv_queue`: 6 bars max
- Entry chain had minimal data all day
- Exit P&L calculation couldn't find closing option prices

**Fix:** Killed zombie PID 1401886. DuckDB now writable. Lock files cleaned.

---

## 3. Code Fixes Applied Today

### Production Chain

| Fix | File | What |
|-----|------|------|
| `temperature=0` | 9 files | All LLM instantiations pinned to deterministic output |
| Provenance guard | `e2e_chain.py` | `_verify_provenance()` + `_recompute_gate()` clamp hallucinated go/confidence |
| Research override — remove conflict | `e2e_chain.py` | Only fires when trend+TL are BOTH NEUTRAL, never on BULLISH vs BEARISH conflict |
| Research override — crew context | `e2e_chain.py` | Injects `entry_decision` into strategy task description so downstream agents see overridden values |
| IRON_BUTTERFLY support | `e2e_chain.py` | Strategy agent + downstream code now handle `strategy_to_execute: IRON_BUTTERFLY` when both gates fire |
| EMA staleness → 24h | `antariksh/tools/entry_tools.py` | Changed from 30min to 86400s (24h). Charting-standard behavior — carries Friday EMA to Monday |
| EMA files regenerated | `ema_backfill.py` | Restored 60min and 1min EMA files from DuckDB + yfinance after pollution cleanup |

### Risk & Monitoring

| Fix | File | What |
|-----|------|------|
| Morph/shift persistence | `position_manager.py` | `run_bridge()` now calls `update_active_trade()` + `log_monitor_action()` after every action |
| TP/SL exit archiving | `kickoff.py` | `exit_trade()` now calls `trade_execution_db.close_trade()` |
| Parent trade linking | `kickoff.py` | `enter_trade()` adds `parent_trade_id`, `parent_exit_reason`, `re_entry_count` |
| JSONL monitoring events | `kickoff.py` | File path now resolved per-write (was frozen at import time) |

### Research System

| Fix | File | What |
|-----|------|------|
| 5th research family | `research_agents.py` | VolumeResearchAgent — VWAP, OI, open range patterns |
| Direction mapping fix | `nightly_research_scheduler.py` | `_derive_direction` now returns BULLISH/BEARISH/NEUTRAL (was DOWN/SIDEWAYS/NONE) |
| TL pattern cross-ref | `research_agents.py` | `evaluate_pattern_performance()` queries v4 `market_data_patterns` for real TL data + forward returns |
| TL trend reconstruction | `research_agents.py` | `compute_trend_signal()` + `compute_tl_approximation()` from DuckDB |
| Partial candle fix | `pattern_enricher.py` | `get_latest_bar_per_tf()` now computes partial candles from 1-min bars instead of writing "-" |
| `--force` flag | `pattern_enricher.py` | Recomputes existing rows. 734 patterns now have all 6 TF colors populated |
| Volume query type | `duckdb_tool.py` | `query_type="volume"` returns VWAP, OI, open range, intraday high/low |
| Volume agent blueprint | `agents_registry.yaml` | Full CrewAI agent with role/goal/backstory/tools documenting the 4-gate entry system |

### Backtest Tooling

| File | Purpose |
|------|---------|
| `NIFTY_BACKTEST_AGENT_TOOLS.py` | Monkey-patched Redis → production tools on Kaggle 2024 data. 13 days, 11 trades |
| `REPLAY_KAGGLE_TO_REDIS.py` | Kaggle data → Redis DB 1 → native tool reads + `combine_entry_scores` |
| `AGENT_CONFORMANCE_HARNESS.py` | CrewAI + oracle + provenance/consistency/P&L invariance checks (partial) |
| `NIFTY_SPOT_2024_LOADER.py` | Loads NIFTY 50 minute OHLCV from Kaggle `debashis74017/nifty-50-minute-data` |
| `STEP1_LOAD_NIFTY_2024_DATA.py` | Fixed: glob, ATM detection, CE direction, memory logging |

---

## 4. State Ready for Tomorrow (May 26)

| Component | Status | Notes |
|-----------|--------|-------|
| DuckDB | ✅ | Lock released, writable, Friday data intact |
| Redis DB 0 | ✅ | Empty (v3.1 refills at 09:14) |
| Redis DB 1 | ✅ | Isolated for backtest |
| EMA 60min | ✅ | Regenerated from DuckDB + yfinance |
| EMA 1min | ✅ | v4 updates on each bar |
| LLM | ✅ | Temperature=0, provenance guard active |
| Entry gates | ✅ | NOT_UP/NOT_DOWN deterministic tiers |
| Research consensus | ✅ | Wired into e2e_chain override |
| Morph logging | ✅ | DuckDB `monitoring_log` + `active_trades` |
| TP/SL archiving | ✅ | DuckDB `trade_history` populated on exit |
| JSONL events | ✅ | Dynamic path resolution |
| Re-entry linking | ✅ | `parent_trade_id` chain |
| Pattern enricher | ✅ | Partial candle fix, `--force` flag |

---

## 5. Pre-market Checklist

- [ ] Verify crontab still has `14 9 * * 1-5 run_data_capture_with_v4.sh`
- [ ] Verify DuckDB is writable: `python3 -c "import duckdb; duckdb.connect('varaha_data.duckdb')"`
- [ ] Verify EMA files exist: `ls data/ema_state/60min/ema_20.json`
- [ ] Verify Redis is running: `redis-cli ping`
- [ ] Check 09:15 kickoff log for trade entries
- [ ] After market close: run `python3 pattern_enricher.py --force --all` for proper EOD forward returns

---

## 6. Open Gaps

| Gap | Severity | Detail |
|-----|----------|--------|
| Data capture stability | 🔴 Critical | v3.1 died at 09:20 today. DuckDB lock contention. Need lock-free design or retry logic |
| Exit P&L depends on live `option_snapshots` | 🔴 Critical | Today's P&L showed ₹0 because option data stopped at 09:20 |
| Research patterns hit_rate=100% | 🟡 Medium | In-sample overfitting. Need out-of-sample backtest validation |
| Fwd returns NULL during market hours | 🟡 Medium | Post-market `pattern_enricher --force` scheduled at 15:35 fills them |
| Conformance harness e2e_chain integration | 🟡 Medium | `duckdb_tool` import path issue prevents full crew run |
| Volume patterns not yet in ChromaDB | 🟡 Low | Tonight's 23:00 run will store them |

---

## 7. Root Cause: DuckDB Lock Conflict

**Zombie processes from previous days** held file locks on both DuckDB files. These piled up because the cleanup function only runs on normal exit — if a process crashes (segfault, OOM, or gets killed by the broker with a stale socket), the lock never releases.

Today's timeline:
```
09:14:07 v3.1 NIFTY starts (PID 1369998) — writes to varaha_data.duckdb
09:14:07 SENSEX starts (PID 1369997) — separate DB, no issues
09:15:06 v4 starts (PID 1370004) — writes to market_data_multitf.duckdb
09:16:33 v4 DIES (lock conflict from zombie PID 1368143 on market_data_multitf.duckdb)
09:16:34 v4 restart (PID 1370821) — acquires new lock ✓
09:20:00 v3.1 NIFTY captures its last bar
09:21:34 v3.1 NIFTY DIES (lock conflict from zombie PIDs 1369994 + 1401886 on varaha_data.duckdb)
09:21–15:30 v3.1 NIFTY unable to restart — ALL 52 restart attempts fail
15:31 Master wrapper shuts down pipeline
```

**Fix applied:** `run_data_capture_with_v4.sh` now runs a zombie cleanup at the start:
```bash
pkill -9 -f "data_capture_v3.1_duckdb" 
pkill -9 -f "data_capture_v4_queue_aggregator"
fuser -k varaha_data.duckdb
fuser -k market_data_multitf.duckdb
rm -f /home/trading_ceo/projects/antariksh/locks/*.lock
```

This prevents zombie accumulation across days. Tomorrow's 09:14 startup will run clean.

---

## 8. Commands to Run Tonight

```bash
# Kill any residual zombie data capture processes
kill $(ps aux | grep "data_capture_v3\|aggregator" | grep -v grep | awk '{print $2}') 2>/dev/null

# Clean stale lock files
find /home/trading_ceo -name "*.lock" -path "*/locks/*" -delete 2>/dev/null

# Verify DuckDB healthy
python3 -c "import duckdb; duckdb.connect('/home/trading_ceo/projects/varaha/data/varaha_data.duckdb').close(); print('DuckDB OK')"

# Re-run pattern enrichment for EOD forward returns
python3 /home/trading_ceo/projects/brahmand/pattern_enricher.py --force --all
```
