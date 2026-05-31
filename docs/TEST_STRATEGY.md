# Brahmand Test Strategy: Comprehensive Test Suite

## Test Pyramid Structure

```
                          E2E Tests (5)
                        ╱              ╲
                    Integration      Integration
                    Tests (20)        Tests (20)
                   ╱          ╲      ╱          ╲
              Unit Tests (40) — Phase Tests (15)
```

---

## Test Organization

```
tests/
├── conftest.py                    # Fixtures, mocks, setup
├── fixtures/
│   ├── market_data.py             # Mock market snapshots
│   ├── trade_fixtures.py          # Sample trades, orders
│   └── mock_tools.py              # Mock tool implementations
│
├── unit/                          # Individual agent tests
│   ├── test_entry_agents.py       # NOT_UP, NOT_DOWN agents
│   ├── test_regime_agent.py       # Regime classification
│   ├── test_strategy_agent.py     # Strategy selection
│   ├── test_contract_agent.py     # Contract resolution
│   ├── test_execution_agent.py    # Trade building
│   ├── test_order_agent.py        # Order routing
│   ├── test_risk_agent.py         # SL/TP management
│   ├── test_morpher_agent.py      # Signal reversal detection
│   ├── test_shifter_agent.py      # Premium decay shifts
│   └── test_postmortem_agent.py   # Post-trade analysis
│
├── phase/                         # Phase-based integration tests
│   ├── test_entry_phase.py        # Full entry → execution → risk flow
│   ├── test_monitoring_phase.py   # Morph/shift scenarios
│   └── test_postmortem_phase.py   # Learning + analysis
│
├── scenarios/                     # Specific trade scenarios
│   ├── test_scenario_iron_fly.py          # Full iron butterfly
│   ├── test_scenario_call_spread.py       # CALL_SPREAD entry + monitoring
│   ├── test_scenario_put_spread.py        # PUT_SPREAD entry + monitoring
│   ├── test_scenario_morph.py             # Signal reversal morph
│   ├── test_scenario_hedge_shift.py       # 50% decay HEDGE_SHIFT
│   ├── test_scenario_sell_shift.py        # 60% decay SELL_SHIFT
│   ├── test_scenario_tsl_adjustment.py    # TSL threshold + ratcheting
│   ├── test_scenario_tp_hit.py            # TP hit exit
│   ├── test_scenario_sl_hit.py            # SL hit exit
│   └── test_scenario_time_exit.py         # Expiry exit
│
├── e2e/                          # End-to-end full flows
│   ├── test_e2e_market_open_entry.py      # Cron trigger → entry execution
│   ├── test_e2e_monitoring_cycle.py       # Entry → monitoring loop (5 min interval)
│   ├── test_e2e_tp_hit_exit.py            # Entry → monitoring → TP exit
│   ├── test_e2e_morph_and_exit.py         # Entry → morph → monitoring → exit
│   └── test_e2e_full_trading_day.py       # Complete day 9:15-15:30
│
└── data/
    ├── market_snapshots.json      # Real market data snapshots
    ├── sample_trades.json         # Pre-built trades for testing
    └── expected_outcomes.json     # Expected results per scenario
```

---

## Test Coverage Goals

### Unit Tests (40 total)

#### Entry Phase Agents (8 tests)
```python
# test_entry_agents.py
test_not_up_market_rejects_upside()      # Both BEARISH → go=true
test_not_up_single_bearish()             # One BEARISH + NEUTRAL → go=true  
test_not_up_market_accepts_upside()      # BULLISH or both NEUTRAL → go=false
test_not_up_prevents_double_entry()      # Existing CE_SPREAD → go=false

test_not_down_market_rejects_downside()  # Both BULLISH → go=true
test_not_down_single_bullish()           # One BULLISH + NEUTRAL → go=true
test_not_down_market_accepts_downside()  # BEARISH or both NEUTRAL → go=false
test_not_down_prevents_double_entry()    # Existing PE_SPREAD → go=false
```

#### Regime Agent (3 tests)
```python
# test_regime_agent.py
test_regime_trending_high_vix()    # ADX > 25, VIX > 18 → trending, caution
test_regime_sideways_low_vix()     # ADX < 25, VIX < 15 → sideways, safe
test_regime_signal_downgrade()     # Conflicting DuckDB data → confidence↓
```

#### Strategy Agent (4 tests)
```python
# test_strategy_agent.py
test_strategy_not_up_to_call_spread()        # NOT_UP → CALL_SPREAD
test_strategy_not_down_to_put_spread()       # NOT_DOWN → PUT_SPREAD
test_strategy_vix_parameter_optimization()   # VIX > 18 → sl_pct=0.35, etc
test_strategy_adx_parameter_optimization()   # ADX < 20 → tp_pct=0.55, etc
```

#### Contract Agent (2 tests)
```python
# test_contract_agent.py
test_contract_resolve_call_spread()    # CALL_SPREAD → 2 legs (sell CE, buy CE)
test_contract_resolve_put_spread()     # PUT_SPREAD → 2 legs (sell PE, buy PE)
```

#### Execution Agent (3 tests)
```python
# test_execution_agent.py
test_execution_builds_trade_dict()           # execute_paper_trade returns correct structure
test_execution_calculates_net_credit()       # net_credit = sum(SELL) - sum(BUY)
test_execution_routes_via_order_agent()      # Calls place_entry_orders
```

#### Order Agent (4 tests)
```python
# test_order_agent.py
test_order_paper_mode_saves_ledger()         # PAPER mode → order_ledger.json
test_order_live_mode_would_call_broker()     # LIVE mode → would call Shoonya
test_order_generates_unique_trade_id()       # Each trade gets TRD-YYYYMMDDHHMMSS
test_order_atomic_dual_write()               # Both order_ledger + duckdb written
```

#### Risk Agent (4 tests)
```python
# test_risk_agent.py
test_risk_places_sl_for_sell_legs()          # SELL legs get SL order
test_risk_places_tp_for_sell_legs()          # SELL legs get TP order
test_risk_skips_hedges()                     # BUY legs get NO orders
test_risk_calculates_sl_tp_levels()          # SL = premium × (1 + sl_pct), etc
```

#### Monitoring Phase Agents (6 tests)
```python
# test_morpher_agent.py
test_morpher_detects_bullish_to_bearish()   # BULLISH → BEARISH reversal
test_morpher_detects_bearish_to_bullish()   # BEARISH → BULLISH reversal
test_morpher_detects_to_neutral()           # BULLISH/BEARISH → NEUTRAL
test_morpher_respects_max_3_morphs()        # 3rd morph OK, 4th blocked

# test_shifter_agent.py
test_shifter_detects_50_percent_decay()     # Premium decay >= 50% → HEDGE_SHIFT
test_shifter_detects_60_percent_decay()     # Premium decay >= 60% → SELL_SHIFT
```

#### Post-Trade Agent (2 tests)
```python
# test_postmortem_agent.py
test_postmortem_analyzes_signal_accuracy()   # Was entry signal correct?
test_postmortem_stores_learning_chromadb()   # Writes research notes
```

---

### Phase Integration Tests (15 total)

#### Entry Phase (5 tests)
```python
# test_entry_phase.py
test_entry_phase_happy_path()                # Signal → Strategy → Contract → Execution → Risk
test_entry_phase_no_go_blocks_entry()        # Both entry agents = NO → no trade
test_entry_phase_regime_caution()            # Regime says caution → still proceed (logged)
test_entry_phase_contract_synthetic()        # Some contracts synthetic (no DuckDB) → proceed
test_entry_phase_order_routing()             # Orders reach ledger + duckdb
```

#### Monitoring Phase (6 tests)
```python
# test_monitoring_phase.py
test_monitoring_morph_to_bullish()           # Entry BEARISH → Signal becomes BULLISH → morph position
test_monitoring_morph_cancels_old_orders()   # Old CE/PE SL/TP cancelled
test_monitoring_morph_places_new_orders()    # New opposite leg SL/TP placed
test_monitoring_shift_hedge_leg()            # 50% decay → new hedge, cancel old
test_monitoring_shift_sell_leg()             # 60% decay → new sell, cancel old, book P&L
test_monitoring_tsl_adjustment()             # P&L reaches threshold → TSL ratchets
```

#### Post-Trade Phase (4 tests)
```python
# test_postmortem_phase.py
test_postmortem_tp_hit_analysis()            # Trade closed at TP → success case
test_postmortem_sl_hit_analysis()            # Trade closed at SL → loss case
test_postmortem_morph_success()              # Morph improved outcome → learn conditions
test_postmortem_chromadb_storage()           # Research notes stored correctly
```

---

### Scenario Tests (10 total)

Each scenario simulates a realistic trading day:

```python
# test_scenario_iron_fly.py
def test_iron_fly_full_cycle():
    """
    Day flow:
    1. Market open 09:15
    2. Entry Agent 1: NOT_UP decision (BEARISH) → CALL_SPREAD entry
    3. Monitoring: 2 morphs, 1 shift
    4. Market close 15:30
    5. Postmortem: Analyze outcomes
    """
    market_state = open_market_snapshot()
    entry_signal = not_up_agent.decide(market_state)  # CALL_SPREAD
    trade = execute_trade(entry_signal)
    
    # Monitoring: morph at 10:00, shift at 12:30
    morph1 = monitor_loop_morph(trade, timestamp=10_00)
    shift1 = monitor_loop_shift(trade, timestamp=12_30)
    
    # Exit
    exit_reason, pnl = close_trade(trade)
    postmortem = analyze(trade, exit_reason, pnl)
    
    assert postmortem.signal_accuracy == True
    assert postmortem.morphs == 1
    assert postmortem.shifts == 1

# test_scenario_morph.py
def test_morph_signal_reversal():
    """
    Entry: BEARISH (CALL_SPREAD)
    At 10:30: Signal becomes BULLISH → Morph to PUT_SPREAD
    """

# test_scenario_tsl_adjustment.py
def test_tsl_activation_and_ratcheting():
    """
    Entry: net_credit = 100
    P&L reaches 50 (50% of max) → TSL activates
    Market continues → P&L = 80 → SL ratchets up
    """

# test_scenario_tp_hit.py
def test_tp_hit_exit():
    """
    Entry: TP = 50 (50% of entry premium)
    Market decays to TP → Trade exits with profit
    """

# test_scenario_sl_hit.py
def test_sl_hit_exit():
    """
    Entry: SL = 125 (125% of entry premium)
    Market moves against → SL triggered, loss booked
    """
```

---

### E2E Tests (5 total)

```python
# test_e2e_market_open_entry.py
def test_cron_trigger_to_entry_execution():
    """
    Full flow from market open:
    1. Cron triggers at 09:15
    2. Fetch market data
    3. Run Entry Crew (NOT_UP, NOT_DOWN, Regime)
    4. Run full_crew (Strategy, Contract, Execution, Risk)
    5. Verify orders in ledger + duckdb
    """

# test_e2e_monitoring_cycle.py
def test_monitoring_loop_5min_interval():
    """
    After entry, monitoring runs every 5 minutes:
    1. Check for morph (09:20, 09:25, 09:30, ...)
    2. Check for shift (09:20, 09:25, 09:30, ...)
    3. Verify orders updated
    4. Continue until market close
    """

# test_e2e_full_trading_day.py
def test_complete_trading_day_9_15_to_15_30():
    """
    Simulate a complete trading day:
    1. Market open 09:15: Entry decision
    2. Entry execution + Risk setup
    3. Monitoring 09:20-15:25 (5-min cycles)
    4. Market close 15:30: Exit + Postmortem
    
    Verify:
    - Entry signal correct
    - Morphs detected at right times
    - Shifts executed when thresholds hit
    - TSL ratchets on favorable moves
    - Exit at TP/SL/time with P&L calculated
    - Learning stored in ChromaDB
    """
```

---

## Test Data Management

### Fixtures (conftest.py)

```python
@pytest.fixture
def market_snapshot_bullish():
    """Market rejects downside (BULLISH)"""
    return {
        "spot": 23750,
        "atm_strike": 23700,
        "india_vix": 16.5,
        "adx": 22,
        "ema_20": 23600,
        "ema_50": 23500,
        "supertrend_direction": "bullish",
        "trend_signal": "BULLISH",
        "traffic_light_signal": "BULLISH",
    }

@pytest.fixture
def sample_trade_call_spread():
    """CALL_SPREAD with 4 legs"""
    return {
        "trade_id": "TRD-20260523093000",
        "strategy_type": "CALL_SPREAD",
        "entry_time": "09:30:00",
        "legs": [
            {"tsym": "NIFTY26MAY26C23650", "action": "SELL", "type": "CE", "qty": 65, "price": 75.50, "sl": 113.25, "tp": 37.75},
            {"tsym": "NIFTY26MAY26C23850", "action": "BUY", "type": "CE", "qty": 65, "price": 25.50, "sl": 0, "tp": 0},
        ],
        "net_credit": 50,
        "margin": 20000,
    }

@pytest.fixture
def mock_duckdb(monkeypatch):
    """Mock DuckDB queries"""
    def mock_query(sql, params=None):
        if "option_snapshots" in sql:
            return [{"tsym": "NIFTY26MAY26C23650", "ltp": 75.50, "bid": 74, "ask": 77}]
    monkeypatch.setattr("duckdb_tool.query", mock_query)
```

---

## Running Tests

```bash
# Run all tests
pytest tests/

# Run by category
pytest tests/unit/                    # Unit tests only
pytest tests/phase/                   # Phase tests only
pytest tests/scenarios/               # Scenario tests only
pytest tests/e2e/                     # E2E tests only

# Run specific test
pytest tests/unit/test_execution_agent.py::test_execution_builds_trade_dict

# Run with coverage
pytest tests/ --cov=brahmand --cov-report=html

# Run with verbose output
pytest tests/ -v

# Run specific scenario
pytest tests/scenarios/test_scenario_morph.py -v
```

---

## Success Criteria

### Coverage Goals
- ✅ 100% line coverage for agent logic
- ✅ 90%+ branch coverage (conditional paths)
- ✅ All agent combinations tested (both entry signals)
- ✅ All monitoring actions tested (morph, shift, TSL)
- ✅ All exit reasons tested (TP, SL, time, morph)

### Speed Goals
- ✅ Unit tests: < 100ms each
- ✅ Phase tests: < 500ms each
- ✅ Scenario tests: < 2s each
- ✅ E2E tests: < 10s each
- ✅ Full suite: < 2 minutes

### Quality Goals
- ✅ No flaky tests (deterministic)
- ✅ Clear test names (describe what + expected result)
- ✅ Isolated tests (no shared state)
- ✅ Well-documented scenarios (why this test matters)

---

## Implementation Roadmap

| Phase | Work | Effort |
|-------|------|--------|
| **Phase 1** | conftest + fixtures | 2 hours |
| **Phase 2** | Unit tests (40) | 4 hours |
| **Phase 3** | Phase tests (15) | 3 hours |
| **Phase 4** | Scenario tests (10) | 4 hours |
| **Phase 5** | E2E tests (5) | 3 hours |
| **Total** | Complete test suite | 16 hours |

---

## Multi-Asset Phase 2 Testing

When adding Asset Selector Agent and multi-asset support:

```python
# test_asset_selector_agent.py
def test_asset_selector_picks_best_win_rate():
    """Asset Selector queries ChromaDB, picks NIFTY (70% WR) over Reliance (52%)"""

def test_asset_selector_respects_liquidity():
    """Reliance has insufficient liquidity for 100 lots → pick NIFTY instead"""

def test_asset_selector_considers_margin():
    """Limited capital → pick smaller-margin asset (BTC perp vs NIFTY)"""

# test_scenario_multi_asset.py
def test_entry_decision_routes_to_best_asset():
    """NOT_UP signal → Asset Selector picks asset → Contract resolves for that asset"""
```
