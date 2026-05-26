# Time-Machine Replay System

**Built:** 2026-05-26 | **Author:** trading_ceo | **Status:** Operational

Replay a full trading day minute-by-minute in an isolated sandbox. The system
clones production data, pre-computes EMAs, and runs entry signals + kickoff
agents against historical bars — without touching live state.

---

## Architecture

```
┌─ Production ─────────────┐       ┌─ Sandbox ──────────────────────────┐
│ varaha_data.duckdb       │ copy  │ varaha_data.duckdb                  │
│ market_data_multitf_*.db │ copy  │ market_data_multitf_nifty.duckdb    │
│ ema_state/ (30 files)    │       │ data/ema_state/ (pre-computed)     │
│ trade_execution.duckdb   │       │ state/trade_execution.duckdb (empty)│
│ brahmand_kickoff.json    │       │ state/brahmand_kickoff.json (empty) │
│ order_ledger.json        │       │ state/order_ledger.json (empty)     │
│ Redis db=0               │       │ Redis db=1 (isolated)              │
└──────────────────────────┘       │ trace/trace_YYYY-MM-DD.jsonl       │
                                   └────────────────────────────────────┘

Isolation mechanism: BRAHMAND_SANDBOX env var.
All stateful modules check it at import time → redirect to sandbox.
```

## Commands

### Setup (run once per date/index)

```bash
cd /home/trading_ceo/brahmand
python3 tools/replay_setup.py 2026-05-22 --index NIFTY
```

What it does:
1. Creates sandbox dir: `data/replays/YYYY-MM-DD_INDEX/`
2. Copies `varaha_data*.duckdb` from production
3. Creates empty `market_data_multitf_*.duckdb` with schema
4. Creates empty `state/trade_execution.duckdb` with schema
5. Inits fresh `state/brahmand_kickoff.json` + `state/order_ledger.json`
6. **Pre-computes EMAs**: feeds up to 5000 historical bars through `ema_aggregator.update_ema()` for all timeframes (1min/5min/15min/60min/1D) × 6 periods (5/9/20/50/100/200)
7. Writes `manifest.json` with bar count

### Replay

```bash
# Fast mode: inline entry signals, no LLM calls (30s for full day)
python3 tools/replay_session.py data/replays/2026-05-22_NIFTY --fast

# Step mode: one bar at a time, interactive
python3 tools/replay_session.py data/replays/2026-05-22_NIFTY

# REAL mode: runs actual kickoff agents with CrewAI + LLM at each 5-min mark
python3 tools/replay_session.py data/replays/2026-05-22_NIFTY --fast --real

# Partial replay
python3 tools/replay_session.py data/replays/2026-05-22_NIFTY --fast --max 30
```

### Step mode controls

| Key | Action |
|-----|--------|
| `ENTER` | Advance one bar |
| `s 10` | Skip 10 bars |
| `d` | Dump current state (EMAs, diffs, signals, trades) |
| `t 10:30` | Jump to timestamp HH:MM |
| `q` | Quit (saves trace) |

## Per-Minute Pipeline

Each bar goes through 6 phases:

| Phase | What Runs | Sandbox Output |
|-------|-----------|---------------|
| **1. Indicators** | `_IndicatorBuffer.compute_indicators()` — EMA/RSI/ADX/ATR/SuperTrend via TA-Lib | Diffed against stored DuckDB values |
| **2. Redis push** | `LPUSH v3_ohlcv_queue_{INDEX}` (db=1) + `SET prev_close_{INDEX}` | Sandbox Redis queue |
| **3. EMA update** | `ema_aggregator.update_ema(close, tf)` for 1min/5min/15min/60min/1D | Sandbox EMA state files |
| **4. Risk check** | Reads sandbox `brahmand_kickoff.json` for active trades | PnL, morph stage, alerts |
| **5. Entry signal** | Computes BULLISH/BEARISH + confidence from Redis data (EMA crossover + ST + RSI + ADX) | Entry signal per bar |
| **6. Kickoff** | Every 5 min: either inline logic or REAL `kickoff.main()` with CrewAI 5-agent chain | Trade decisions in sandbox `trade_execution.duckdb` |

## Per-Bar Output Format

```
[030/447] 09:40:00 | ₹23756 | BUL:40% | K:entry_attempt | DIFF:ema_5,ema_20,em
   │        │          │          │            │               │
   │        │          │          │            │               └─ Indicator discrepancies
   │        │          │          │            └─ Kickoff action
   │        │          │          └─ Entry signal + confidence %
   │        │          └─ Spot price
   │        └─ Timestamp
   └─ Progress (bar / total)
```

### Signal confidence calculation

| Factor | BULLISH | BEARISH |
|--------|---------|---------|
| EMA5 > EMA20 | +25 | — |
| EMA5 < EMA20 | — | -25 |
| SuperTrend bullish | +15 | — |
| SuperTrend bearish | — | -15 |
| RSI > 60 | +10 | — |
| RSI < 40 | — | -10 |
| ADX > 25 | +10 | +10 |

Signal is BULLISH if net positive, BEARISH if net negative, NEUTRAL if 0.

Kickoff triggers `entry_attempt` when: no active trade AND signal is BULLISH AND confidence ≥ 30%.

### Indicator diff explained

The `DIFF:ema_5,ema_20,em` column shows which indicators don't match the stored
DuckDB values. This is **expected and informative** — it means:
- The replay buffer (warmup from OHLCV log) differs from production buffer
- EMA/RSI/ADX are path-dependent on preceding bars
- Large diffs (>200 pts for EMA, >30 for RSI) indicate buffer initialization gaps
- The trace file (`trace.jsonl`) has exact computed vs stored values with diffs

## Trace File

Location: `data/replays/YYYY-MM-DD_INDEX/trace/trace_YYYY-MM-DD.jsonl`

Each line is a JSON object with the complete state for one bar. Query with:

```bash
# Show all entry signals
cat trace_2026-05-22.jsonl | jq 'select(.entry.signal != "NEUTRAL") | {ts: ._ts, signal: .entry.signal, conf: .entry.confidence}'

# Show all kickoff runs
cat trace_2026-05-22.jsonl | jq 'select(.kickoff) | {ts: ._ts, action: .kickoff.action, reason: .kickoff.reason}'

# Show indicator diffs
cat trace_2026-05-22.jsonl | jq 'select(.indicator_diff | length > 0) | {ts: ._ts, diffs: .indicator_diff}'

# Count entry_attempt vs no_entry
cat trace_2026-05-22.jsonl | jq -r 'select(.kickoff) | .kickoff.action' | sort | uniq -c
```

## Sandbox Isolation Details

### Env var overrides

Setting `BRAHMAND_SANDBOX=/path/to/sandbox` before importing these modules
redirects all their state paths:

| Module | Affected Paths |
|--------|---------------|
| `ema_aggregator.py` | `EMA_BASE_DIR` → `$SANDBOX/data/ema_state/` |
| `kickoff.py` | `STATE_DIR` → `$SANDBOX/state/`, `is_market_hours()` returns True |
| `trade_execution_db.py` | `DB_PATH` → `$SANDBOX/state/trade_execution.duckdb` |
| `duckdb_tool.py` | `VARAH_DATA` → `$SANDBOX/varaha_data.duckdb` |
| `order_agent.py` | `LEDGER_FILE` → `$SANDBOX/state/order_ledger.json` |
| `entry_tools.py` | `_v4_db_path()`, `_v31_db_path()` → sandbox DuckDB files |
| `toolkit.py` | All `_V4_*_DB`, `_V31_*_DB` paths → sandbox files |
| `entry_tools.py` (Redis) | `BRAHMAND_REPLAY_REDIS_DB` → switches db index |

### What's NOT isolated (by design)

- **CrewAI/LLM API calls**: still use production `DEEPSEEK_API_KEY`. No way to mock without a mock API server.
- **Broker connections**: the replay doesn't call broker APIs. Trade execution is paper-mode only.
- **Pattern enricher**: not wired into the replay loop yet. Traffic light patterns are not recomputed during replay.
- **Margin capture**: skipped. Margins are market-dependent and can't be replayed from historical data.
- **Log files**: `logs/` directory under sandbox is created but kickoff agents still log to `stdout` (which the replay captures in trace).

## Workflow: Debugging a Session

Typical workflow to debug why the system did or didn't act on a specific day:

```bash
# 1. Setup (one-time)
python3 tools/replay_setup.py 2026-05-22 --index NIFTY

# 2. Fast-forward to pre-market state (skip first 5 bars)
python3 tools/replay_session.py data/replays/2026-05-22_NIFTY --step --max 5

# 3. At the prompt, use 't 10:15' to jump to the interesting time
> t 10:15
# Jumped to bar 60

# 4. Step through minute by minute, inspecting state
> (ENTER)  ← advance one bar
> d        ← dump state: EMAs, active trades, signals
```

To compare "what the system WOULD have done" vs "what it DID in production":

```bash
# Replay the day with --real (runs actual kickoff agents)
python3 tools/replay_session.py data/replays/2026-05-22_NIFTY --fast --real

# Then compare sandbox trade_execution.duckdb vs production
python3 -c "
import duckdb
prod = duckdb.connect('/home/trading_ceo/brahmand/data/trade_execution.duckdb', read_only=True)
replay = duckdb.connect('data/replays/2026-05-22_NIFTY/state/trade_execution.duckdb', read_only=True)
print('Production trades:', prod.execute('SELECT COUNT(*) FROM active_trades').fetchone()[0])
print('Replay trades:', replay.execute('SELECT COUNT(*) FROM active_trades').fetchone()[0])
"
```

## Known Limitations

1. **Indicator diffs**: EMA/RSI/ADX values differ from stored DuckDB because the replay buffer warmup uses OHLCV log data (only spot price, no open/high/low/close distinction). The diff itself is the diagnostic — if values converge after ~50 bars, the system is working. If they stay divergent, there's a real computation bug.

2. **Duplicate timestamps**: Some bars have sub-minute duplicate timestamps (e.g., 09:20:00 and 09:20:06). This is from the production capture's polling behavior. The replay handles these fine.

3. **`--real` mode is slow**: Each kickoff call runs the full CrewAI 5-agent chain with LLM API calls. For 78 kickoff cycles (390 bars / 5min), expect 10-30 minutes. Use `--max` to limit.

4. **Multi-TF DB may be empty**: The sandbox doesn't have multi-TF data unless the production `market_data_multitf_*.duckdb` files exist. The replay engine uses Redis-based entry signals, which work without multi-TF DB.

5. **Pattern enricher not wired**: Traffic light patterns are not recomputed during replay. This is the next feature to add.

## Adding New Replay Support

To make a new module replay-aware, add at the top:

```python
import os
_SANDBOX = os.environ.get("BRAHMAND_SANDBOX", "")
```

Then conditionally set paths:

```python
if _SANDBOX:
    DATA_DIR = Path(_SANDBOX) / "data"
    STATE_FILE = Path(_SANDBOX) / "state" / "file.json"
else:
    DATA_DIR = Path("/home/trading_ceo/brahmand/data")
    STATE_FILE = Path("/home/trading_ceo/brahmand/data/file.json")
```

## Files

| Path | Purpose |
|------|---------|
| `brahmand/tools/replay_env.py` | Shared sandbox env helpers |
| `brahmand/tools/replay_setup.py` | Sandbox creation + EMA pre-computation |
| `brahmand/tools/replay_session.py` | Master replay engine |
| `brahmand/tools/redis_tap.py` | Redis queue tap for ad-hoc testing |
| `antariksh/config/db_paths.py` | Per-index DuckDB path functions |
| `antariksh/cron/check_market_open.sh` | Holiday/weekend gate for systemd timers |
| `antariksh/tools/log_cleanup.py` | Daily log truncation (7-day retention, 10K lines) |

### Modified files (sandbox env var support)

| File | Change |
|------|--------|
| `ema_aggregator.py:28` | `BRAHMAND_SANDBOX` redirects `EMA_BASE_DIR` |
| `kickoff.py:30-40` | `BRAHMAND_SANDBOX` redirects `STATE_DIR`; `is_market_hours()` returns True |
| `trade_execution_db.py:22-24` | `BRAHMAND_SANDBOX` redirects `DB_PATH` |
| `duckdb_tool.py:24-26` | `BRAHMAND_SANDBOX` redirects `VARAH_DATA` |
| `order_agent.py:24-26` | `BRAHMAND_SANDBOX` redirects `LEDGER_FILE` + added `import os` |
| `entry_tools.py:48-67` | `BRAHMAND_SANDBOX` redirects `_v4_db_path()`, `_v31_db_path()` |
| `entry_tools.py:844-851` | `BRAHMAND_REPLAY_REDIS_DB` switches Redis db index |
| `entry_tools.py:854-860` | Added `_redis_queue_key()` supporting `REPLAY` env var |
| `toolkit.py:19-44` | `BRAHMAND_SANDBOX` redirects all `_V4_*_DB`, `_V31_*_DB` paths |
| `data_health.py:22-24` | Split into `V4_NIFTY_DB` / `V4_SENSEX_DB` |
| `pattern_enricher.py:32` | Changed `V4_DB` to `_v4_db_path(index)` function |
| `pattern_analyzer.py:30` | Changed `V4_DB` to `_v4_db_path("NIFTY")` |
| `entry_research_agent.py:128` | DB path parameterized by `index` |
| `backfill_v4_from_v3.py:17` | Changed to `_v4_db_path(index_name)` |
| `pa_tools.py:1318` | DB path parameterized by `index_name` |
| `research_agents.py:44` | Default changed to `market_data_multitf_nifty.duckdb` |
| `cleanup_zombies.sh:39` | Added new per-index multi-TF DB paths |
| `log-analyzer.service` | Added `MemoryHigh=350M` `MemoryMax=400M` |
| `data-capture-nifty.service` | New systemd service + timer |
| `data-capture-sensex.service` | New systemd service + timer |

### System changes

| Change | Details |
|--------|---------|
| Swap | Increased from 2GB → 4GB |
| Data capture | New `data_capture_combined.py` replaces v3.1 + v4 (one process per index) |
| Systemd timers | `data-capture-{nifty,sensex}.timer` replacing cron watchdog |
| Log analyzer | Memory limits active (`MemoryMax=400M`) — prevents OOM kill recurrence |
| Redis queue | Per-index keys (`v3_ohlcv_queue_NIFTY` / `_SENSEX`) replacing shared key |
| Multi-TF DBs | Split to `market_data_multitf_nifty.duckdb` + `market_data_multitf_sensex.duckdb` |
