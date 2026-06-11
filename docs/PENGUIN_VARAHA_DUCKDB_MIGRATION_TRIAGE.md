# varaha_data.duckdb → Penguin Migration Triage + Multi-TF Recommendation

**Date:** 2026-06-02 · **Author:** Claude (advisory) · **Status:** for Board review — NO edits made to readers yet

Context: Board decision = Penguin canonical, Varaha v3.1 retired. `varaha_data.duckdb` was written only by the retired v3.1 → now dead. This triages the 12 brahmand readers still pointed at it, and recommends collapsing the duplicate multi-TF layer.

## The storage split (answers "why SQLite 7-day?")

Per `trading-knowledge-base/PENGUIN_ARCHITECTURE.md` — this is the documented design, your intuition is correct:

| Store | Role | Horizon | Access pattern |
|---|---|---|---|
| **SQLite (WAL)** `capture_*.sqlite` | **Hot / operational** — consumer & enricher write every minute; read *directly during market hours* | rolling **7 days** (`cleanup_old_ticks --days 7`) | row-oriented, low-latency, single-writer (flock); cheap small writes |
| **DuckDB warehouse** `research/{date}/*.duckdb` | **Cold / analytical** — `eod_etl.py` ships SQLite→DuckDB at 15:40 | full history (dated files) | columnar, fast scans/aggregations over long history → backtests, deep research |

So: SQLite = hot recent (write-optimized, intraday). DuckDB = deep history (read/scan-optimized, research). `varaha_data.duckdb` was the *old* mash-up of both and is replaced by this split.

## Why not "just swap DuckDB → SQLite"?

Three reasons a blind swap silently feeds the trading brain wrong/empty data:
1. **Driver + SQL dialect** — readers use `duckdb.connect()` + DuckDB SQL (e.g. `ATTACH`, `sqlite_scan`, columnar funcs). SQLite needs `sqlite3` + portable SQL.
2. **Table may not exist** — `option_snapshots` (historical option chain) has **no Penguin equivalent**; live SQLite has `option_prices` = *current* LTP per strike only.
3. **Horizon** — SQLite keeps **7 days**. Anything needing more must read the EOD warehouse, not live SQLite.

So it's a per-reader routing decision, hence the triage below.

## Triage — 12 readers

### Bucket 1 — Already Penguin-aware (minimal change)
| File | Reads | Action |
|---|---|---|
| `duckdb_tool.py` | market_data, option_snapshots | Central layer; already has `_connect_sqlite()` + reads `research/{date}/`. Finish routing; **option_snapshots is the blocker** (see B4). |
| `nightly_research_scheduler.py` | market_data | Already warehouse-first (`research/{date}/nifty.duckdb`); just **drop the varaha_data.duckdb fallback**. |

### Bucket 2 — Recent data → repoint to `capture_*.sqlite` (≤7d) + dialect fix
| File | Reads | Penguin source |
|---|---|---|
| `data_health.py` | market_data, market_data_multitf | capture_*.sqlite (already reads v3_ohlcv_queue too) |
| `margin_capture.py` | market_data | capture_*.sqlite / v3_ohlcv_queue |
| `entry_signal_broker.py` | market_data | capture_*.sqlite / v3_ohlcv_queue |
| `risk_tools.py` | `ATTACH live.market_data` → spot, agg_delta (Greeks) | `market_data_enriched` in capture_*.sqlite (has agg_delta) |

### Bucket 3 — Needs >7d history → repoint to EOD warehouse `research/{date}/*.duckdb`
| File | Reads | Note |
|---|---|---|
| `research_agents_full_db.py` | market_data | full-history research → warehouse |
| `ema_backfill.py` | market_data | EMA backfill over history → warehouse |
| `entry_research_agent.py` | market_data (90+ cols) | warehouse (post-market) or `market_data_enriched` (recent) |

### Bucket 4 — BLOCKERS (no clean equivalent — need a decision)
| File | Reads | Problem |
|---|---|---|
| `wing_optimizer.py` | **option_snapshots** only | Penguin captures `option_prices` (current LTP), NOT historical chain snapshots. Needs either (a) add periodic option-snapshot persistence to Penguin (enricher already computes pcr/max_pain/oi + option_prices has per-strike LTP), or (b) accept degraded wing optimization. |
| `research_agents.py` | market_data, multitf, **market_data_patterns, trade_outcomes** | Last two are written by `pattern_enricher.py` → that writer must be migrated too (chained dependency, not a repoint). |

### Bucket 5 — Leave as-is
| File | Reason |
|---|---|
| `tools/replay_setup.py` | Backtest/replay tooling using sandbox copies — not the live path. |

### Also pulled in by the migration
- `pattern_enricher.py` — itself reads market_data from varaha_data.duckdb and writes market_data_patterns/trade_outcomes. Source for B4's research_agents. Must migrate its input to a Penguin source.

## Summary
- **6 of 12** are straightforward repoints (B1 drop-fallback ×2, B2 recent→SQLite ×4).
- **3** need warehouse routing (B3) — easy once warehouse is confirmed populating.
- **2 + pattern_enricher** are real blockers (B4): `option_snapshots` history + `market_data_patterns`/`trade_outcomes` writer chain.
- **1** leave as-is (replay).

The genuine work is the **2 blockers**, not the path swaps. The biggest is **historical option-chain snapshots** — a data-model gap Penguin doesn't fill today.

---

## Multi-TF layer recommendation

**Enricher and aggregator are NOT redundant with each other** — enricher = 1-min *indicators* (`market_data_enriched`), v4 aggregator = higher *timeframes* (5/15/30/60/240/1440). Both functions needed.

**The real duplication is one layer over:** multi-TF OHLCV is computed **twice** —
- `consumer` → `market_data_multitf` in `capture_*.sqlite` (hot, 7d, documented live read), and
- `v4 aggregator` → `market_data_multitf_{index}.duckdb` (rolling DuckDB, every 5 min from the queue).

Same aggregation, two producers, two stores.

**Recommended end-state (collapse to one producer):**
1. Keep the **consumer** as the single multi-TF producer (SQLite, hot path — consistent with the storage split).
2. Let **EOD ETL** ship multitf → DuckDB warehouse (it already copies SQLite→DuckDB).
3. **Retire the v4 aggregator** — removes the duplicate computation, the `queue → v4` path, and a 5-min cron daemon.

**Prerequisites / caveats (don't flip until done):**
- Repoint the 13 `market_data_multitf_*.duckdb` readers → SQLite multitf (live) or warehouse (historical). Same readers as the triage above — **bundle the two efforts**.
- The consumer's multitf has the **MCX cross-contract collision bug** (BarAggregator keys buckets by time only, not instrument). Must fix before it's the sole producer.
- Verify no agent needs *intraday* (sub-EOD) multitf from DuckDB; if so, point it at SQLite multitf instead.

Alternative (if v4's DuckDB multitf is considered the "trusted" research-grade copy): keep v4, drop the consumer's SQLite multitf, and have live readers use v4's DuckDB. Less aligned with the hot/warehouse split; noted for completeness.

## Proposed order of work
1. Verify the live chain at next 09:14 open (queue → multitf DuckDB → enriched SQLite populating).
2. Land B1+B2+B3 repoints (8 readers) — low risk.
3. Resolve B4 blockers: decide on option-snapshot persistence; migrate pattern_enricher chain.
4. Consolidate multi-TF (fix consumer MCX bug → retire v4) once multitf readers are repointed.
