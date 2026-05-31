# REPLAY_KAGGLE_TO_REDIS.py — Validation Review

**Validator:** Claude (validator role; Deepseek built the file)
**Date:** 2026-05-24
**File under review:** `brahmand/REPLAY_KAGGLE_TO_REDIS.py` (607 lines)
**Method:** Full read of the file; traced data contract against production (`antariksh/tools/entry_tools.py`, `python-trader/varaha/data_capture_v3.1_duckdb.py`, `brahmand/ema_integration_hook.py`); inspected live Redis + ema_state state (read-only). **Did not execute the script** — see Critical #1.

---

## CRITICAL #1 — It writes to LIVE production state, and it already has

- `EMA_STATE_DIR = data/ema_state` (line 35) is the **exact path production reads** (`entry_tools.py:982`).
- `REDIS_KEY = "v3_ohlcv_queue"` (line 36) on `localhost:6379 db=0` (line 56) is the **live production queue**.
- `push_bars_to_redis` does `r.delete(REDIS_KEY)` then LPUSHes (lines 185-189).

**It was already run** (`data/REPLAY_KAGGLE_TO_REDIS_LOG.json` exists, mtime 18:57) and the live queue is **polluted right now**:
```
LLEN v3_ohlcv_queue = 201
newest (LINDEX 0):  {"timestamp":"09:15:59","open":24413.5,"high":24413.5,"low":24413.5,"close":24413.5,"index":"NIFTY"}
oldest (LINDEX -1): {"timestamp":"12:11:59", ... "close":24295.5 ...}
```
O=H=L=C single-point bars at ~24,400 = 2024 replay data, not live ticks.

---

## Is tomorrow safe? NO — two confirmed problems

### Problem A — Redis queue: 201 stale 2024 bars persist into tomorrow
The live capture **never flushes**; it only appends:
```python
# data_capture_v3.1_duckdb.py:1203-1204
redis_client.lpush("v3_ohlcv_queue", json.dumps(ohlcv_bar))
redis_client.expire("v3_ohlcv_queue", 604800)   # 7-day TTL
```
- No `delete`/`ltrim` on startup → tomorrow's live bars LPUSH **on top of** the 201 stale 2024 bars.
- `get_live_candles` reads `lrange(0, 359)` (lookback 360). Until ~360 fresh live bars accumulate (~most of the trading day), that window still contains the 2024 bars → **corrupted multi-TF candle colors → corrupted traffic-light signal → corrupted entry decisions for the morning session.**
- 7-day TTL means the junk self-clears ~May 31, not before tomorrow.

### Problem B — 60min EMA state overwritten with replay values; live hook only maintains 1min
- 60min ema files were rewritten today (mtime `May 24 19:05`).
- `ema_integration_hook.on_new_bar` only calls `update_ema(close, tf="1min")` (line 58) — it does **not** write `60min`.
- `score_trend_redis` reads **primary from `60min/`** (`entry_tools.py:983`). So the 60min trend EMAs are stale replay values unless a separate aggregator refreshes them.
- Partial mitigation (unverified): the 30-min staleness check (`entry_tools.py:1017-1027`) falls back to `1min`, which the live hook *does* update — so trend scoring *may* self-heal if the hook runs live. Fragile; must be confirmed, not assumed.

### Remediation before tomorrow's run
1. Flush the queue so live capture starts clean: `redis-cli DEL v3_ohlcv_queue` (loses nothing — it holds only 2024 garbage now).
2. Refresh/clear `data/ema_state/60min/*.json` (and confirm what production service repopulates the 60min slot).
3. Cleanest: restart the data-capture + EMA services so they rebuild state from scratch.

---

## Data-mashup fidelity (the part asked to check)

### Bug — the "60min" EMA is actually a 1-minute EMA
- `compute_emas` (lines 203-214) computes EMAs on the **1-minute** close series.
- `write_ema_state_files` (lines 222-241) writes that **same 1-min value into both `60min/` and `1min/`** dirs → the two timeframes are byte-identical, which is impossible for genuine 60min vs 1min EMAs.
- Production trend scoring expects true hourly-candle EMAs in `60min/`. Result: the replay's trend signal ≠ production's.
- Fix: aggregate 1-min → 60-min candles, compute EMA on those, write to `60min/`.

### Queue ordering is inverted vs production convention
- `push_bars_to_redis` lpushes `reversed(bars)`, leaving **head = oldest** bar. `get_live_candles` assumes "newest is at head (LPUSH)" (`entry_tools.py:906`). So the replay's notion of "latest bar" is the earliest minute. Verify against production LPUSH order.

### Single-point bars
- O=H=L=C=spot from put-call parity (lines 162-175). TF candle colors survive aggregation, but there is no real intrabar high/low. Medium-fidelity at best.

---

## Architecture — "invoke the tools"

- ✅ `score_trend_redis` / `score_traffic_light_redis` are called **natively via real Redis** (lines 436-437), no monkey-patch — a genuine improvement over `NIFTY_BACKTEST_AGENT_TOOLS.py`.
- ❌ `evaluate_not_up` / `evaluate_not_down` (lines 250-331) are **reimplemented locally**, not imported from `brahmand/tools/entry_gate_tools.py`. Tiers match production today but can drift — still "copy, not invoke."
- ❌ `combine_entry_scores` is imported (line 360) but **never called**. Production entry uses it; the replay substitutes local gates + a picker (lines 442-450) → decision path differs from production.

---

## The conformance invariants are NOT implemented
The `--e2e-chain` path (lines 466-507) runs the crew **once**, patches `get_latest_market_snapshot` with `india_vix=0, adx=None` (skews regime/strategy), and prints the result. None of the three invariants from `AGENT_CONFORMANCE_HARNESS_SPEC.md` are present:
- Pillar 1 (provenance / anti-hallucination): no tool-call capture, no number matching.
- Pillar 2a (determinism): no N-run identity check; LLM `temperature` still unset.
- Pillar 3 (P&L integrity): no settlement check.

So this is a **replay + single crew run + a diff**, not the conformance harness.

---

## Minor
- Line 71: corrupted dead string `"NSE_FNO_DATA_2024-10-*.CSV Rejected as irrelevant file path."` in an unused `patterns` list — copy/paste artifact; delete.
- Glob (lines 74-76) covers only Oct `.csv`/`.CSV`; misses the Nov-3 weekly file the tool-level backtest included → coverage differs from the log it diffs against.
- End-diff (lines 578-593) compares `not_up_go`/`not_down_go`/`suggested_trade` against `NIFTY_BACKTEST_AGENT_TOOLS_LOG.json`, whose `daily_log` schema may not contain `not_up_go`/`not_down_go` (older runs used `combined_signal`/`go`). `t.get(...)` then returns `None`, making the diff misleading. Verify both logs share the keys before trusting "ZERO diffs."

---

## Verdict
Right direction — native Redis replay beats monkey-patching. But:
1. **Unsafe to run on the live box** — it clobbers production Redis + ema_state, and has already left 201 stale 2024 bars in the live queue. **Must flush before tomorrow.**
2. **Data-mashup fidelity bug** — 1-min EMA mislabeled as 60-min; trend signal diverges from production.
3. **Still reimplements gates and skips `combine_entry_scores`** — decision path ≠ production.
4. **Does not enforce the three invariants** the harness exists to guarantee.

**Required fixes:** isolated Redis db/key + temp EMA dir (never touch live paths); real 60-min candle EMAs; import the actual gate tools and call `combine_entry_scores`; implement provenance + determinism + P&L invariants. Re-validate after.
