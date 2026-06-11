# Reader Migration Map — `varaha_data.duckdb` (dead) → Penguin sources

**Date:** 2026-06-03 · **Status:** for Board review · **Owner:** Claude (validation), Board (approval)

Companion to memory [[capture_canonical_penguin_only]]. The legacy `varaha_data.duckdb` /
`varaha_data_sensex.duckdb` are **stale since 2026-05-29** — nothing in Penguin writes them.
Every reader below currently points (wholly or partly) at that dead path. This document maps
each reader to its correct live Penguin source so the Board can approve edits before touching
trading-brain code.

> **Do not bulk-edit.** Tiers A→D are ordered by live-trading risk. Migrate Tier A first,
> one file at a time, each verified against the running pipeline.

---

## 1. Source-of-truth: where the data lives now

| Legacy (DEAD) | Live Penguin replacement | Engine | Freshness verified 06-03 |
|---|---|---|---|
| `varaha_data.duckdb` :: `market_data` (104 cols) | `capture_{index}.sqlite` :: `market_data` + `market_data_enriched` (joined) | **SQLite** (was DuckDB) | rows @ 09:34 ✅ |
| `varaha_data.duckdb` :: `market_data_aggregated` (28 cols) | `market_data_multitf_{index}.duckdb` :: `market_data_multitf` (26 cols) | DuckDB | bar @ 09:31 ✅ |
| `varaha_data.duckdb` :: `option_snapshots` (13 cols) | `capture_{index}.sqlite` :: `option_prices` (5 cols) | SQLite | row @ 09:35 ✅ |

`{index}` ∈ {`nifty`, `sensex`, `mcx`}. SENSEX legacy was `varaha_data_sensex.duckdb`.

---

## 2. Universal column-translation cheatsheet

### 2a. `market_data` → `capture_{index}.sqlite` (`market_data` ⋈ `market_data_enriched`)
**Reference implementation already exists:** `brahmand/duckdb_tool.py:69-115` builds the exact
compatibility VIEW via `sqlite_scanner`. Copy that pattern. Key renames:

| Old `market_data` col | Penguin source |
|---|---|
| `index_name` | `instrument` |
| `spot` | `market_data.close` |
| `open_price` | `market_data.open` |
| `intraday_high` / `intraday_low` | `market_data.high` / `.low` |
| `date`, `time` | derive: `substr(timestamp,1,10)`, `substr(timestamp,12,8)` |
| all indicators / IV / greeks / pivots / SMC / PCR (~85 cols) | `market_data_enriched.*` (join on `timestamp` + `instrument`) |
| `id`, `trading_day`, `buffer_bars` | **dropped** (not in Penguin; derive if needed) |

Engine change: `duckdb.connect(path)` → in-memory DuckDB + `INSTALL/LOAD sqlite_scanner` +
`sqlite_scan('capture_*.sqlite','market_data_enriched')`. SQLite is WAL-mode, so reads are
concurrent with the live writer (no lock-retry loop needed, unlike the old DuckDB path).

### 2b. `market_data_aggregated` → `market_data_multitf_{index}.duckdb`
Same DuckDB engine — just repoint path + table name + filter `timeframe_min`. Renames:
`open_price`→`open`. **Columns NOT present in multitf:** `spot`, `futures`, `india_vix`,
`agg_delta/gamma/vega/theta`. multitf is pure OHLCV + technicals (adds sma/macd/di/bb/obv/cmf/cci).
If a reader needs spot/VIX/greeks at a timeframe, source those from `market_data_enriched` instead.

### 2c. `option_snapshots` → `capture_{index}.sqlite` :: `option_prices`
**Available:** `tsym, strike, option_type, ltp, timestamp`.
**LOST (no Penguin equivalent yet):** `oi`, `iv`, `volume`, `expiry_label`, `expiry_date`, `strike_offset`.
→ Live-LTP consumers migrate cleanly. **OI/IV consumers are blocked** — see Gap §4.

---

## 3. Per-reader migration table

### TIER A — Production live-trading path (migrate first, verify each)

| File | Reads | Target | Action / gotcha |
|---|---|---|---|
| `duckdb_tool.py` | market_data, option_snapshots | capture sqlite | **✅ market_data ALREADY migrated** (`_connect_sqlite_intraday`, warehouse, legacy fallback). Remaining: `option_snapshots` queries still assume legacy schema — repoint to `option_prices` and handle lost oi/iv. |
| `entry_signal_broker.py` | market_data (latest candle) | capture sqlite | `MarketDataFeed.__init__` hardcodes DuckDB path; `get_latest_candle/get_candle_at_time` do `SELECT * ... WHERE index_name=`. Apply §2a VIEW; `index_name`→`instrument`. **Highest live impact.** |
| `tools/risk_tools.py` | market_data (agg greeks), option_snapshots (live ltp) | capture sqlite | `monitor_pnl_greeks` ATTACHes DuckDB + `SELECT strike,option_type,ltp FROM option_snapshots` at MAX(timestamp). ltp **available** in `option_prices` ✅. Switch ATTACH→sqlite_scanner. agg_greeks come from `market_data_enriched`. |
| `entry_research_agent.py` | market_data, market_data_multitf | capture sqlite + multitf | Already dual-source; multitf leg is live. Repoint the `market_data` (v31) leg per §2a. **Partial — read file before editing.** |
| `antariksh/trading_desk.py` | market_data (latest row, line ~384) | capture sqlite | Production desk. Apply §2a. Docstring lines 290-296 still describe v3.1 path — update. |
| `margin_capture.py` | market_data (spot/atm) | capture sqlite | This is also a *writer* (margin loop). Only its read of spot/atm_strike needs repointing per §2a. Confirm read vs write paths before editing. |

### TIER B — Research / nightly (migrate after A)

| File | Reads | Target | Action / gotcha |
|---|---|---|---|
| `research_agents.py` | market_data, market_data_multitf | capture sqlite + multitf | `db_path_v31` + `db_path_v4` ctor args. Repoint v31→capture sqlite VIEW; v4 already live. |
| `research_agents_full_db.py` | market_data | capture sqlite | "full db" historical research — confirm it wants live vs history. |
| `nightly_research_scheduler.py` | market_data | research warehouse | Runs EOD → prefer `/home/trading_ceo/research/{date}/{index}.duckdb` (Penguin EOD ETL) over live sqlite. |
| `wing_optimizer.py` | option_snapshots (ltp by strike) | option_prices | Needs only `ltp` ✅. Repoint to `option_prices` (sqlite). |
| `pattern_analyzer.py` | market_data, market_data_multitf | multitf (primary) | Already multitf-centric; check whether market_data leg is actually used. |
| `pattern_enricher.py` | market_data, market_data_multitf | multitf (primary) | Same as above. |

### TIER C — Monitoring / utility / backfill (low risk)

| File | Reads | Action |
|---|---|---|
| `data_health.py` | all 4 DBs | Already multi-DB aware; **stop alerting green on stale `varaha_data.duckdb`** — drop it from checks or mark legacy. |
| `ema_backfill.py` | market_data | Docstring already says it writes multitf, not varaha_data; the `DUCKDB_PATH` const is unused — delete const (mention only, don't refactor). |
| `antariksh/rebuild_ema_from_v3.py` | market_data | **Leave** — intentionally reads old DB as historical source. |
| `antariksh/backfill_v4_from_v3.py` | market_data → multitf | **Leave** — one-time backfill *from* v3 history into v4. |

### TIER D — Tests / backtest / replay (fixtures or history; lowest)

| File | Action |
|---|---|
| `research_backtest_framework.py` | Historical backtest — old DB holds the history; leave or point at EOD warehouse. |
| `backtest/REPLAY_REDIS_DRYRUN.py` | Replay harness — uses recorded data. |
| `tools/replay_session.py`, `tools/replay_setup.py` | Sandbox replay; already reference multitf. |
| `tests/autonomous_dryrun.py`, `tests/test_margin_calculations_premarket.py` | Tests — repoint to fixtures or capture sqlite; not live-critical. |
| `antariksh/validate_data_capture_complete.py` | Validator — already references all schemas; keep as the cross-check. |

---

## 4. OPEN GAP — option OI / IV / volume has no Penguin source

`option_snapshots` carried per-strike **`oi`, `iv`, `volume`, `expiry_label`**. Original
assumption (that the Redis `feed:{index}:options:*` hashes already held OI/IV) was **wrong** —
on inspection that hash carries only `{tsym, strike, option_type, ltp, timestamp}`. The data
never enters the pipeline because `feed.py`'s WS callback read only `lp`. So this was a
**feed-level** gap, not a writer gap.

**RESOLVED 2026-06-03 — OI + volume now captured end-to-end:**
- `feed.py` `on_tick` now reads `msg['oi']` / `msg['v']` (Shoonya sends both for F&O,
  incrementally — only updated when present) and `_publish_option_tick` writes them to the hash.
- `instrument_consumer.py` persists `oi`/`volume` into `option_prices`.
- `config/sqlite_schema.py` adds nullable `oi`/`volume` columns + an additive `ALTER` migration
  for existing DBs (runs on next consumer startup — no live-DB mutation required).
- `penguin_compat.option_snapshots` view passes `oi`/`volume` through when present, NULL when not
  (column-aware, so it's correct both pre- and post-migration).
- Verified on a copy of `capture_nifty.sqlite`: migration non-destructive (22 rows preserved),
  view surfaces real `oi`/`volume`. **Takes effect live at next feed restart / market open** —
  must verify `oi` actually populates then (LTPs were 0 at edit time, market closed).

**STILL OPEN — IV:** Shoonya does **not** transmit per-strike IV; it must be **computed**
(Black-Scholes inversion from spot/strike/time-to-expiry/rate/LTP). That is a separate, scoped
piece of work (an IV solver, best placed in the enricher alongside the existing index-level
`iv_*` fields) and needs live-market validation before trust — deliberately NOT faked.
`option_snapshots.iv` stays NULL until then; readers degrade gracefully.

---

## 5. Recommended sequence

1. **Board approves** target mapping (§1–2) and the OI/IV gap decision (§4).
2. Migrate Tier A one file at a time using the `duckdb_tool.py` VIEW template; after each,
   verify against live pipeline (latest row matches `capture_{index}.sqlite` @ current minute).
3. `data_health.py`: stop treating `varaha_data.duckdb` as a live source (§Tier C).
4. Tier B, then sweep tests (Tier D).
5. When zero live readers reference `varaha_data.duckdb`, retire the file.
