# SESSION CONTEXT — Updated 2026-05-21 (May 20 EOD)

Project: Brahmand — E2E Chain execution layer (5-agent sequential pipeline)  
Branch: `master` | Live data: DuckDB reads verified, paper trading active

## Locations

```
/home/trading_ceo/brahmand/           ← Brahmand (execution engine)
/home/trading_ceo/antariksh/          ← Antariksh (orchestration + signals)
/home/trading_ceo/python-trader/      ← Data capture + utilities
/root/.claude/projects/-home-trading-ceo/memory/  ← Persistent memory
```

GitHub: `github.com/venkatseshadri/antariskh` (submodule)

## Last Built (May 20-21)

✅ Complete E2E Chain operational with Kickoff scheduler running every 5 minutes.  
✅ State persistence (JSON + SQLite) confirmed working.  
✅ 5-agent pipeline (Entry→Regime→Strategy→Contract→Execution→Risk) tested and verified.

**Critical Blocker:** EMA wiring to v4 aggregator (see Priority Queue #1)

## Priority Queue (Next)

### ⭐ #1 BLOCKING: Wire EMA to v4 Aggregator (15 min)

**File:** `/home/trading_ceo/antariksh/data_capture_v4_queue_aggregator.py`

**What's Missing:**
- EMA backfill exists ✅
- EMA aggregator exists ✅
- v4 aggregator writes to DuckDB ✅
- **v4 aggregator never calls `update_ema()` on closed candles** ❌

**Impact:** Entry signals cannot be scored without fresh EMA data.

**Fix:**
```python
# At top of data_capture_v4_queue_aggregator.py:
from brahmand.ema_aggregator import update_ema

# In run_all_timeframes(), after each closed candle:
update_ema(timestamp)
```

**Verification:**
```bash
# After fix, this should show fresh EMA:
python3 -c "from brahmand.ema_aggregator import load_ema; print(load_ema('NIFTY', 1))"
```

**Due:** Before 9:15 AM on May 21

---

### #2 Verify Kickoff Cron Executing (5 min)

**Cron Entry:** `*/5 9-15 * * 1-5 python3 kickoff.py >> logs/kickoff_$(date +\%Y\%m\%d).log 2>&1`

**Check:**
```bash
cd /home/trading_ceo/brahmand
tail -20 logs/kickoff_$(date +%Y%m%d).log
# Should see entries every 5 min starting 9:15 AM
```

---

### #3 Test Full Flow (20 min)

```bash
cd /home/trading_ceo/brahmand

# Mock test (no real data)
python3 e2e_chain.py --mock

# Trial run (live DuckDB, paper trading)
python3 kickoff.py --once

# Full session
python3 kickoff.py  # Runs once; scheduled every 5 min
```

---

## Key Files (May 20 Build)

### Core Engine
- `kickoff.py` — Scheduler entry point, lock protection, state management
- `e2e_chain.py` — Sequential CrewAI pipeline (Entry→Regime→Strategy)
- `crewai_chain.py` — CrewAI agent/task definitions
- `duckdb_tool.py` — Market data query layer (DuckDB)
- `factory.py` — Agent factory helper

### Risk & Monitoring
- `position_manager.py` — Morphing detection (when to shift legs)
- `ema_aggregator.py` — EMA calculation & persistence
- `ema_backfill.py` — Historical EMA recovery
- `pattern_analyzer.py` — Trade pattern recognition
- `pattern_enricher.py` — Pattern analysis enrichment
- `data_health.py` — Data quality checks

### Integration & Persistence
- `trade_execution_db.py` — Execution logging to SQLite
- `margin_capture.py` — Margin snapshot collection
- `order_agent.py` — Order hub (legacy, reference only)
- `broker_manager.py` — Dual broker interface (Shoonya/Flattrade)

### State & Configuration
- `state.db` (SQLite) — Trade history, orders, monitoring
- `data/brahmand_kickoff.json` — Daily state, active trades
- `config/` — Agent definitions, risk parameters

---

## System State (May 21)

### Data Flow
```
┌─ DuckDB (varaha_data.duckdb)
│  ├─ market_data (1-min OHLCV + Greeks)
│  └─ option_snapshots (per-strike LTP)
│
├─ Entry Signals (from Antariksh entry_check.py)
│  └─ /antariksh/entry_signals/entry_check_latest.json
│
├─ EMA State Files (Antariksh)
│  └─ /antariksh/ema_state/NIFTY_{1,5,15,60}.pkl
│
└─ Brahmand Kickoff (5-min polling)
   ├─ run_sequential_crew() → E2E Chain
   ├─ _monitor_active_trade() → TSL, exits
   └─ Save to state.db + JSON
```

### Crontab Active

```
# Data capture v3.1 + v4 (Antariksh)
09:14  data_capture_with_v4.sh

# Entry signal generation (Antariksh) [NEEDS EMA FIX]
09:15-15:25  */5 entry_check.py

# Trading orchestration (Brahmand)
09:15-15:30  */5 kickoff.py

# Risk monitoring (1-min cadence)
09:15-15:30  * risk_monitor.py
```

### Open Issues

| Issue | Status | Impact | Due |
|-------|--------|--------|-----|
| EMA wiring to v4 aggregator | 🔴 BLOCKING | Entry signals can't be scored | Before 9:15 AM May 21 |
| Gap detection parameter | ⚠️ STUCK | Traffic light incomplete | Investigate May 21 |
| Kickoff cron execution | ⏳ VERIFY | Need to confirm May 21 morning | May 21 09:20 AM |

---

## Verify State (May 21 Morning)

```bash
cd /home/trading_ceo/brahmand

# 1. Check DuckDB data flowing
python3 -c "from duckdb_tool import get_latest_market_snapshot; import json; print(json.dumps(get_latest_market_snapshot(), default=str, indent=2))"

# 2. Check EMA files exist (after wire fix)
ls -lah /home/trading_ceo/antariksh/ema_state/

# 3. Check entry signal (from Antariksh)
cat /home/trading_ceo/antariksh/entry_signals/entry_check_latest.json | jq .

# 4. Check state.db schema
sqlite3 state.db ".tables"
sqlite3 state.db "SELECT name FROM sqlite_master WHERE type='table';"

# 5. Dry-run kickoff
python3 kickoff.py --dry-run

# 6. Check logs
tail -50f logs/kickoff_$(date +%Y%m%d).log
```

---

## Operational Checklist

### Before 9:15 AM
- [ ] Wire EMA to v4 aggregator
- [ ] Verify DuckDB is populating
- [ ] Verify entry_check.py can access EMA files
- [ ] Kickoff scheduler is in crontab
- [ ] Risk monitor is armed

### During 9:15-15:30
- [ ] Monitor logs every 5 minutes
- [ ] Check active_trade in state JSON
- [ ] Verify P&L calculations are correct
- [ ] Watch for data quality issues

### After 15:30
- [ ] Generate post-mortem
- [ ] Archive logs
- [ ] Update session context
- [ ] Plan next day fixes

---

## Recent Commits

```
2a7f12a chore: bump submodules — antariksh, brahmand, python-trader (May 20 22:28)
da5e799 docs: comprehensive agents and systems architecture documentation (May 20 09:10)
3575415 fix: simplify scheduler check + add 1-min risk monitor cron (May 20 21:47)
8e1770e feat: separate risk monitoring with 1-min cadence via DuckDB (May 20 20:56)
64ceec2 fix: correct Varaha class import in token_refresh_dual.py (May 19 22:14)
```

**Next Commits (May 21):**
```
→ fix: wire EMA to v4 aggregator (BLOCKING)
→ feat: verify kickoff scheduler execution May 21
→ docs: update session context post-market
```

---

## Testing Commands

### Unit Tests
```bash
python3 -m pytest tests/test_duckdb_tool.py -v
python3 -m pytest tests/test_ema_aggregator.py -v
python3 -m pytest tests/test_position_manager.py -v
```

### Integration Tests
```bash
# Single kickoff with live data
python3 kickoff.py --once

# Full pipeline test
python3 e2e_chain.py --trial

# Risk monitor test
python3 risk_monitor.py --test-one-cycle
```

### Manual Smoke Tests
```bash
# 1. DuckDB query
python3 duckdb_tool.py --query "market_data"

# 2. EMA loading
python3 -c "from ema_aggregator import load_ema; print(load_ema('NIFTY', 1))"

# 3. Contract resolution
python3 e2e_chain.py --test-contracts

# 4. State persistence
sqlite3 state.db "SELECT COUNT(*) as trade_count FROM trades;"
```

---

## Dependencies & Configuration

### Python Packages
- crewai (>=0.30)
- duckdb (>=0.9)
- pandas (>=2.0)
- numpy (>=1.24)

### Environment Variables
```
DEEPSEEK_API_KEY      (for CrewAI agents, optional)
DEEPSEEK_BASE_URL     (default: https://api.deepseek.com/v1)
BRAHMAND_MODE         (PAPER | LIVE, default: PAPER)
```

### Broker Configuration
- Shoonya API (primary)
- Flattrade API (fallback)
- Credentials: `/opt/hayagreeva/cred.yml`

---

## Quick Start

```bash
cd /home/trading_ceo/brahmand

# 1. Check system ready
python3 -c "print('DuckDB:', end=' '); from duckdb_tool import get_latest_market_snapshot; print('✅' if get_latest_market_snapshot() else '❌')"

# 2. Run once (paper trading with live data)
python3 kickoff.py --once

# 3. Watch logs
tail -f logs/kickoff_$(date +%Y%m%d).log

# 4. Check state
cat data/brahmand_kickoff.json | jq '.active_trade'

# 5. Full day (cron runs every 5 min 9:15-15:30)
# No manual action needed — scheduler handles it
```

---

## Contact & Escalation

**System Owner:** trading_ceo  
**Status Reporting:** Telegram bot  
**Critical Issues:** Immediate escalation to Chairman  
**Post-Market Review:** 15:35 IST

---

**Context Updated:** 2026-05-21 09:00 IST  
**Next Update:** 2026-05-21 15:30 IST (post-market)
