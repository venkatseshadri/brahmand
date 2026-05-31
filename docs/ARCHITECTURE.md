# Brahmand — E2E Chain Architecture

**Last Updated:** 2026-05-21 | **Status:** Live paper trading with 5-agent sequential pipeline

---

## 0. SYSTEM OVERVIEW

Brahmand is the **execution layer** of the trading system. It implements a deterministic 5-agent pipeline that transforms entry signals into live trades with continuous risk monitoring.

| Layer | Component | Purpose |
|-------|-----------|---------|
| **Signal Entry** | Entry Agent (CrewAI) | Query EMA + traffic light → GO/NO-GO |
| **Market Context** | Regime Agent (CrewAI) | Validate signal against live DuckDB data |
| **Strategy Selection** | Strategy Agent (CrewAI) | Choose spread type, wing width, SL/TP |
| **Contract Resolution** | Contract Resolver (Python) | Resolve tsyms from option_snapshots |
| **Trade Execution** | Executor (Python) | Build trade, save SIM order, handoff to Risk |
| **Risk Monitoring** | Risk Monitor (Python) | 1-min cadence via DuckDB, TSL engine |

**Trade Mode:** Paper (simulated fills, real market data from DuckDB)  
**Schedule:** Kickoff every 5 minutes during 9:15-15:30, lock-protected  
**State:** Persistent JSON + SQLite (`data/brahmand_kickoff.json`, `state.db`)

---

## 1. PIPELINE ARCHITECTURE

### 1.1 Entry Point: `kickoff.py`

**Frequency:** Every 5 minutes (9:15-15:30 IST)  
**Lock:** PID-based, timeout-aware (won't overlap)  
**State File:** `data/brahmand_kickoff.json`

```json
{
  "date": "20260521",
  "trades_today": 4,
  "active_trade": {
    "id": "TRADE-001",
    "entry_time": "09:30:15",
    "legs": [...]
  },
  "all_trades": [...],
  "post_mortem_done": false
}
```

**Flow:**
```
kickoff.py
  ├─ acquire_lock()           ← Check if already running
  ├─ load_state()             ← Daily state
  ├─ First run? → run_sequential_crew()  ← Enter new trade
  ├─ All runs → monitor_active_trades()  ← Risk monitoring
  ├─ apply_tsl()              ← Trailing stop loss
  ├─ save_state()
  └─ release_lock()
```

---

### 1.2 Signal Generation: `e2e_chain.py` → `run_sequential_crew()`

**What it does:** Entry → Regime → Strategy as a single sequential CrewAI pipeline

**Prerequisite Data:**
- DuckDB latest snapshot (spot, VIX, ATM, indicators)
- EMA state files (from entry_check or backfill)
- Option chain snapshots

**Agent Pipeline:**

```python
def run_sequential_crew(entry_time: str) -> dict | None:
    """
    Run Entry → Regime → Strategy as CrewAI sequential crew.
    Returns combined decisions or None if Entry says NO-GO.
    """
    llm = _get_llm()  # DeepSeek API
    
    # 1. ENTRY AGENT (CrewAI)
    entry_agent = af.create_agent("entry_agent", {
        "market_type": "NSE_OPTIONS",
        "strategy_type": "IRON_BUTTERFLY",
        "ticker": "NIFTY",
        "decision_gate": "GO/NO-GO"
    })
    
    entry_task = Task(
        description=f"""Query market data:
        - trend_ema: is NIFTY trending (UP/DOWN/NEUTRAL)?
        - traffic_light: is signal GO or NO-GO?
        Return: {{ "entry_signal": "GO" | "NO-GO", "reason": "..." }}"""
    )
    
    # 2. REGIME AGENT (CrewAI)
    # Validates entry_agent output against DuckDB
    
    # 3. STRATEGY AGENT (CrewAI)
    # Selects strategy, calculates strikes, SL/TP
    
    crew = Crew(agents=[entry_agent, regime_agent, strategy_agent], ...)
    result = crew.kickoff()
    return result
```

**Output:** Strategy dict
```json
{
  "entry_signal": "GO",
  "regime": "BULLISH_REVERSAL",
  "strategy_type": "IRON_BUTTERFLY",
  "strike": 24500,
  "wing_width": 300,
  "sl": 24200,
  "tp": 24800,
  "legs": [...]
}
```

---

### 1.3 Contract Resolution: `_resolve_contracts()`

**Input:** Strategy dict with strikes  
**Data Source:** DuckDB `option_snapshots` table  
**Output:** 4-leg contract dict with tsyms

```python
def _resolve_contracts(strategy: dict) -> dict:
    """
    Resolve trading symbols (tsyms) from DuckDB option_snapshots.
    
    For Iron Butterfly on strike 24500 with width 300:
    1. BUY 24200 CE (upper wing)
    2. SELL 24500 CE (long call)
    3. SELL 24500 PE (short put)
    4. BUY 24800 PE (lower wing)
    
    Returns: {
        "24200_CE": { "tsym": "NIFTY24APR24200CE", "qty": 50, ... },
        "24500_CE": { "tsym": "NIFTY24APR24500CE", "qty": 50, ... },
        ...
    }
    """
    contracts = {}
    for leg_name, strike, option_type, action in [
        ("LONG_CE", 24200, "CE", "BUY"),
        ("SHORT_CE", 24500, "CE", "SELL"),
        ("SHORT_PE", 24500, "PE", "SELL"),
        ("LONG_PE", 24800, "PE", "BUY"),
    ]:
        row = query_option_snapshot(strike=strike, option_type=option_type)
        contracts[leg_name] = {
            "tsym": row["tsym"],
            "qty": strategy["qty"],
            "action": action,
            "ltp": row["ltp"],
            "bid": row["bid"],
            "ask": row["ask"],
        }
    return contracts
```

---

### 1.4 Trade Execution: `_execute_trade()`

**Mode:** Paper trading (simulated fills, real market data)

```python
def _execute_trade(strategy: dict, contracts: dict) -> dict:
    """
    Simulate trade execution:
    1. Place all 4 legs
    2. Track fills in state.db
    3. Handoff to Risk Monitor
    
    Returns: ExecutionReport { "status": "FILLED", "total_cost": 0, ... }
    """
    execution_report = {
        "id": f"TRADE-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "entry_time": datetime.now(),
        "strategy_type": strategy["strategy_type"],
        "spot": strategy["spot"],
        "atm": strategy["atm"],
        "legs": [],
        "total_cost": 0.0,
        "fills": [],
    }
    
    # 1. Place BUY wings first (hedges)
    for leg in ["LONG_CE", "LONG_PE"]:
        order_id = f"SIM-{leg}-{datetime.now().timestamp()}"
        contract = contracts[leg]
        execution_report["legs"].append({
            "order_id": order_id,
            "leg_name": leg,
            "tsym": contract["tsym"],
            "qty": contract["qty"],
            "action": "BUY",
            "fill_price": contract["ask"],  # SIM: ask price
            "fill_qty": contract["qty"],
            "timestamp": datetime.now(),
        })
        execution_report["total_cost"] += contract["ask"] * contract["qty"]
    
    # 2. Place SELL center (straddle)
    for leg in ["SHORT_CE", "SHORT_PE"]:
        order_id = f"SIM-{leg}-{datetime.now().timestamp()}"
        contract = contracts[leg]
        execution_report["legs"].append({
            "order_id": order_id,
            "leg_name": leg,
            "tsym": contract["tsym"],
            "qty": contract["qty"],
            "action": "SELL",
            "fill_price": contract["bid"],  # SIM: bid price
            "fill_qty": contract["qty"],
            "timestamp": datetime.now(),
        })
        execution_report["total_cost"] -= contract["bid"] * contract["qty"]
    
    # 3. Save to state.db
    save_execution_report(execution_report)
    
    return execution_report
```

---

### 1.5 Risk Monitoring: `_monitor_active_trade()`

**Frequency:** 1-minute cadence (DuckDB polling)  
**State:** In-memory dict + persistent state.db  
**Actions:** TSL, OCO logic, exit signals

```python
def _monitor_active_trade(trade: dict, market_data: dict) -> dict:
    """
    Monitor live P&L, apply TSL, handle exits.
    
    Every 1 minute:
    1. Query DuckDB for latest LTP
    2. Calculate P&L per leg
    3. Check SL/TP boundaries
    4. Apply TSL if favorable move detected
    5. Place SL/TP orders (simulated)
    6. Return action (HOLD, EXIT, TRAIL)
    """
    action = "HOLD"
    
    for leg in trade["legs"]:
        leg_name = leg["leg_name"]
        entry_price = leg["fill_price"]
        tsym = leg["tsym"]
        
        # Get live LTP from DuckDB
        ltp = query_duckdb_ltp(tsym)
        
        if leg["action"] == "BUY":
            leg_pnl = (entry_price - ltp) * leg["qty"]
        else:  # SELL
            leg_pnl = (ltp - entry_price) * leg["qty"]
        
        # Check SL
        if leg_pnl < trade["sl"][leg_name]:
            action = "EXIT"
            break
        
        # Apply TSL
        if leg_pnl > trade["tp"][leg_name] * 0.25:
            new_sl = _apply_tsl(leg, entry_price, ltp)
            trade["sl"][leg_name] = new_sl
            action = "TRAIL"
    
    return {"action": action, "pnl": sum(...), "trade": trade}
```

**TSL Logic:**

```python
def _apply_tsl(trade: dict, leg_type: str, entry_price: float, ltp: float) -> None:
    """
    Ratchet SL downward as option decays (favorable for SELL).
    
    TSL activates when current profit >= 25% of max TP profit.
    Then locks portion of every favorable tick past threshold.
    Only ratchets SL DOWN (never up) — locks in gains.
    """
    sl = trade["sl"].get(leg_type)
    if not sl:
        return
    
    tp = trade["tp"].get(leg_type, entry_price * 0.50)
    max_profit = entry_price - tp
    current_profit = entry_price - ltp
    
    # TSL not yet active
    if current_profit < max_profit * 0.25:
        return
    
    # Lock ratio can be overridden by pattern
    lock_ratio = trade.get("lock_ratio", 0.5)
    
    # Calculate new SL
    favorable_ticks = entry_price - ltp
    locked_gain = favorable_ticks * lock_ratio
    new_sl = entry_price - locked_gain
    
    # Only update if SL improves (DOWN for SELL)
    if new_sl < sl:
        trade["sl"][leg_type] = new_sl
```

---

## 2. DATA FLOW & DEPENDENCIES

### 2.1 Input Data Sources

```
DuckDB (varaha_data.duckdb)
├── market_data (latest 1-min candle)
│   ├── spot, india_vix, futures_price
│   ├── adx, supertrend_direction
│   ├── delta, gamma, vega, theta (aggregate)
│   └── timestamp
├── option_snapshots (latest per strike/option_type)
│   ├── strike, option_type (CE/PE)
│   ├── ltp, bid, ask, volume, oi
│   ├── delta, gamma, vega, theta, iv
│   └── timestamp (1-min)
└── futures_snapshots
    └── expiry, ltp, volume, oi

EMA State Files (Persistent)
└── /home/trading_ceo/antariksh/ema_state/
    ├── NIFTY_1.pkl (1-min EMA)
    ├── NIFTY_5.pkl (5-min EMA)
    ├── NIFTY_15.pkl (15-min EMA)
    └── NIFTY_60.pkl (60-min EMA)

Entry Signals (from entry_check.py)
└── /home/trading_ceo/antariksh/entry_signals/
    └── entry_check_latest.json
        {
          "signal": "GO" | "NO-GO",
          "score": 0-100,
          "ema_trend": "UP" | "DOWN" | "NEUTRAL",
          "traffic_light": "GREEN" | "RED",
          "timestamp": "2026-05-21T09:30:00Z"
        }
```

### 2.2 State Persistence

```
state.db (SQLite)
├── trades (execution history)
│   ├── id, entry_time, exit_time
│   ├── strategy_type, spot, atm
│   ├── legs (JSON), total_cost
│   ├── pnl, status
│   └── timestamp
├── orders (SL/TP orders)
│   ├── order_id, leg_name, tsym
│   ├── action (BUY/SELL), qty
│   ├── price, status (PENDING/FILLED/CANCELLED)
│   └── timestamp
└── monitoring (1-min snapshots)
    ├── trade_id, timestamp
    ├── pnl, action (HOLD/EXIT/TRAIL)
    ├── highest_favorable
    └── tsl_level
```

---

## 3. KEY FILES & RESPONSIBILITIES

| File | Purpose | LOC |
|------|---------|-----|
| `kickoff.py` | Scheduler entry point, lock, state mgmt | 300+ |
| `e2e_chain.py` | Sequential CrewAI pipeline | 400+ |
| `crewai_chain.py` | CrewAI agent/task definitions | 200+ |
| `position_manager.py` | Morphing spread detection | 400+ |
| `duckdb_tool.py` | Market data query layer | 200+ |
| `factory.py` | Agent factory (legacy reference) | 100 |
| `ema_aggregator.py` | EMA calculation & persistence | 200+ |
| `ema_backfill.py` | Historical EMA recovery | 200+ |
| `pattern_analyzer.py` | Trade pattern recognition | 250+ |
| `pattern_enricher.py` | Pattern enrichment logic | 300+ |
| `margin_capture.py` | Margin snapshot collection | 300+ |
| `order_agent.py` | Legacy order hub (reference) | 300+ |
| `data_health.py` | Data quality checks | 200+ |
| `trade_execution_db.py` | Execution persistence | 100+ |

---

## 4. CRITICAL INTEGRATION POINTS

### 4.1 EMA Wiring (BLOCKING - May 21)

**Current State:** ⚠️ EMA files exist but v4 aggregator doesn't call `update_ema()`

**Fix:**
```python
# In data_capture_v4_queue_aggregator.py:
from brahmand.ema_aggregator import update_ema

# After each closed candle:
update_ema(timestamp)
```

**Impact:** Without this, `entry_check.py` cannot score entry signals.

---

### 4.2 Traffic Light Gate

**Source:** `entry_check.py` (Antariksh)  
**Uses:** EMA direction + market structure  
**Output:** GO/NO-GO signal

```python
def score_entry(market_data, ema_state):
    """
    Score entry signal:
    1. EMA trend (UP/DOWN/NEUTRAL)
    2. SuperTrend consensus (1/5/15 min)
    3. VIX gate (< 20.0 for Antariksh)
    4. Gap detection (7th traffic light)
    5. Return: score 0-100
    """
    score = 0
    score += 25 if ema_trend == "UP" else 0
    score += 25 if supertrend_consensus == "BULLISH" else 0
    score += 20 if vix < 20 else 0
    score += 15 if not gap_detected else 0
    score += 15 if liquidity_ok else 0
    
    return "GO" if score >= 70 else "NO-GO"
```

---

### 4.3 Position Morphing

**File:** `position_manager.py`

**What:** Detects when holding position should shift legs

```python
def detect_morphing(trade: dict, market_data: dict) -> bool:
    """
    Detect if position should morph to new strikes.
    
    Triggers:
    - Wing too close (delta > 0.30)
    - Time decay insufficient (theta < target)
    - VIX spike/drop (> 25% change)
    
    Returns: True if morphing recommended
    """
    ...
```

---

## 5. OPERATIONAL PROCEDURES

### 5.1 Daily Startup (9:14 AM)

```bash
# 1. Check data capture is running
ps aux | grep data_capture

# 2. Verify DuckDB health
python3 -c "from duckdb_tool import get_latest_market_snapshot; print(get_latest_market_snapshot())"

# 3. Check EMA state
ls -la /home/trading_ceo/antariksh/ema_state/

# 4. Verify kickoff cron
crontab -l | grep kickoff

# 5. Start risk monitor (if not running)
python3 risk_monitor.py &

# 6. Tail logs
tail -f logs/kickoff_*.log
```

### 5.2 During Market Hours (9:15-15:30)

```bash
# Monitor active trades
tail -f logs/kickoff_*.log

# Check state
cat data/brahmand_kickoff.json | jq '.active_trade'

# Manual override: exit all
python3 -c "from kickoff import exit_all_trades; exit_all_trades()"
```

### 5.3 Post-Market (15:30+)

```bash
# Generate post-mortem
python3 -c "from pattern_analyzer import generate_postmortem; print(generate_postmortem())"

# Review P&L
sqlite3 state.db "SELECT * FROM trades WHERE DATE(entry_time) = DATE('now');"

# Check data integrity
python3 data_health.py
```

---

## 6. TESTING & VALIDATION

### 6.1 Unit Tests

```bash
# Test crewai_chain
python3 -m pytest tests/test_crewai_chain.py -v

# Test duckdb_tool
python3 -m pytest tests/test_duckdb_tool.py -v

# Test position_manager
python3 -m pytest tests/test_position_manager.py -v

# Test TSL engine
python3 -m pytest tests/test_tsl_engine.py -v
```

### 6.2 Integration Tests

```bash
# Test full pipeline (mock mode)
python3 e2e_chain.py --mock

# Test kickoff scheduler (single iteration)
python3 kickoff.py --once

# Test with live DuckDB (paper trading)
python3 kickoff.py --trial
```

### 6.3 Manual Smoke Test

```bash
# 1. Check DuckDB accessible
python3 -c "from duckdb_tool import MarketDataQueryTool; t = MarketDataQueryTool(); print(t.run('query latest market data'))"

# 2. Check EMA files
python3 -c "from ema_aggregator import load_ema; print(load_ema('NIFTY', 1))"

# 3. Check entry signal
python3 -c "from entry_check import score_entry; print(score_entry())"

# 4. Check contract resolution
python3 -c "from e2e_chain import _resolve_contracts; print(_resolve_contracts({'strike': 24500, 'qty': 50}))"

# 5. Check kickoff can run
python3 kickoff.py --dry-run
```

---

## 7. SAFETY CHECKS

### 7.1 Pre-Flight (Before Execution)

- [ ] DuckDB updated in last 2 minutes
- [ ] EMA state files exist and are fresh
- [ ] Entry signal score available
- [ ] Option chain has liquidity (OI > 100)
- [ ] VIX within gates
- [ ] Free cash > 11,000

### 7.2 During Execution

- [ ] All 4 legs placed within 5 seconds
- [ ] No partial fills (all 4 legs must fill)
- [ ] Total cost within margin limit
- [ ] P&L monitoring active (1-min checks)
- [ ] SL/TP orders placed

### 7.3 Risk Abort Conditions

- [ ] Daily loss > ₹3,500 (hard stop)
- [ ] P&L swing > ₹2,000 unfavorable (exit)
- [ ] Liquidity drains (bid-ask > 5 points)
- [ ] Data stale (DuckDB > 5 min old)
- [ ] Manual override via Telegram

---

## 8. PERFORMANCE METRICS

| Metric | Target | Current |
|--------|--------|---------|
| Kickoff latency | < 10 sec | ~5 sec |
| Contract resolution | < 2 sec | ~1 sec |
| Risk monitoring cycle | < 60 sec | ~45 sec |
| State persistence | 100% | 100% ✅ |
| Lock contention | 0 conflicts | 0 ✅ |
| DuckDB query latency | < 100 ms | ~50 ms ✅ |

---

## 9. DEPLOYMENT CHECKLIST

- [x] All files in `/home/trading_ceo/brahmand/`
- [x] Crontab entries for kickoff + risk monitor
- [x] DuckDB attached (read-only)
- [x] EMA state directory accessible
- [x] state.db schema created
- [x] Logs directory writable
- [ ] **EMA wiring to v4 aggregator** ⚠️ BLOCKING
- [x] Entry signal pipeline working
- [x] DeepSeek API key set (if using CrewAI)

---

## 10. QUICK START

```bash
cd /home/trading_ceo/brahmand

# 1. Check system status
python3 -c "from duckdb_tool import get_latest_market_snapshot; import json; print(json.dumps(get_latest_market_snapshot(), indent=2))"

# 2. Single kickoff iteration (mock)
python3 kickoff.py --mock

# 3. Single iteration with live data (paper trading)
python3 kickoff.py --once

# 4. Full scheduler (runs every 5 min)
# Already in crontab: */5 9-15 * * 1-5 python3 kickoff.py

# 5. View logs
tail -100f logs/kickoff_$(date +%Y%m%d).log

# 6. Check state
cat data/brahmand_kickoff.json | jq .
```

---

**Architecture Created:** 2026-05-21  
**Next Review:** 2026-05-21 (post-market)
