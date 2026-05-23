# Brahmand Test Suite

Comprehensive testing framework for all agents and end-to-end workflows.

## Test Categories

### 1. **Unit Tests** (`tests/unit/`)
Individual agent tests in isolation. Fast, deterministic, no external dependencies.

**Agents tested:**
- `test_entry_agents.py` — NOT_UP, NOT_DOWN entry signal evaluation
- `test_regime_agent.py` — Market regime classification + VIX/ADX checks
- `test_strategy_agent.py` — Strategy selection + parameter optimization
- `test_contract_agent.py` — Option contract resolution
- `test_execution_agent.py` — Trade building + order routing
- `test_order_agent.py` — Order hub (PAPER/LIVE mode)
- `test_risk_agent.py` — SL/TP placement
- `test_morpher_agent.py` — Signal reversal detection
- `test_shifter_agent.py` — Premium decay shifts
- `test_postmortem_agent.py` — Post-trade analysis + learning

**Run:**
```bash
pytest tests/unit/ -v
```

---

### 2. **Phase Integration Tests** (`tests/phase/`)
Multi-agent workflows for each trading phase.

**Phases tested:**
- `test_entry_phase.py` — Entry signal → Execution → Risk (full entry workflow)
- `test_monitoring_phase.py` — Morph/shift scenarios during monitoring
- `test_postmortem_phase.py` — Learning + analysis

**Run:**
```bash
pytest tests/phase/ -v
```

---

### 3. **Scenario Tests** (`tests/scenarios/`)
Realistic trading day scenarios with multiple agents + monitoring.

**Scenarios:**
- `test_scenario_iron_fly.py` — Full iron butterfly (2 entries)
- `test_scenario_call_spread.py` — CALL_SPREAD entry + monitoring + exit
- `test_scenario_put_spread.py` — PUT_SPREAD entry + monitoring + exit
- `test_scenario_morph.py` — Signal reversal morph
- `test_scenario_hedge_shift.py` — 50% decay shift
- `test_scenario_sell_shift.py` — 60% decay shift
- `test_scenario_tsl_adjustment.py` — TSL activation + ratcheting
- `test_scenario_tp_hit.py` — TP exit
- `test_scenario_sl_hit.py` — SL exit
- `test_scenario_time_exit.py` — Expiry exit

**Run:**
```bash
pytest tests/scenarios/ -v
```

---

### 4. **E2E Tests** (`tests/e2e/`)
Complete end-to-end workflows from market open to close.

**Flows:**
- `test_e2e_market_open_entry.py` — Cron trigger → Entry execution
- `test_e2e_monitoring_cycle.py` — Entry → 5-min monitoring loop
- `test_e2e_tp_hit_exit.py` — Entry → Monitoring → TP exit
- `test_e2e_morph_and_exit.py` — Entry → Morph → Exit
- `test_e2e_full_trading_day.py` — Complete 9:15-15:30 trading day

**Run:**
```bash
pytest tests/e2e/ -v
```

---

## Test Fixtures

Located in `conftest.py`. Provides:

### Market Snapshots
- `market_snapshot_bearish` — Market rejecting upside (good for CALL_SPREAD)
- `market_snapshot_bullish` — Market rejecting downside (good for PUT_SPREAD)
- `market_snapshot_neutral` — Sideways market (good for IRON_BUTTERFLY)
- `market_snapshot_high_vix` — High volatility (VIX > 20)
- `market_snapshot_low_vix` — Low volatility (VIX < 15)

### Sample Trades
- `sample_trade_call_spread` — CALL_SPREAD with 4 legs
- `sample_trade_put_spread` — PUT_SPREAD with 4 legs
- `sample_trade_with_morph` — Trade after signal reversal
- `sample_trade_with_shift` — Trade after premium decay shift

### Entry/Strategy Decisions
- `entry_decision_bearish` — NOT_UP signal (go=true)
- `entry_decision_bullish` — NOT_DOWN signal (go=true)
- `strategy_decision_default` — Default parameters
- `strategy_decision_high_vix` — High VIX optimization
- `strategy_decision_low_vix` — Low VIX optimization

### Contracts
- `contracts_call_spread` — Resolved CALL_SPREAD symbols
- `contracts_put_spread` — Resolved PUT_SPREAD symbols

### Monitoring Events
- `monitoring_event_morph` — Signal reversal
- `monitoring_event_shift` — Premium decay shift
- `monitoring_event_no_action` — No action needed

### Exit Events
- `exit_event_tp_hit` — Trade exited at TP
- `exit_event_sl_hit` — Trade exited at SL
- `exit_event_time` — Trade exited at market close

### Postmortem Analysis
- `postmortem_analysis_success` — Trade analyzed successfully
- `postmortem_analysis_loss` — Trade resulted in loss

---

## Running Tests

### Run all tests
```bash
pytest tests/ -v
```

### Run by category
```bash
pytest tests/unit/          # Unit tests only
pytest tests/phase/         # Phase tests only
pytest tests/scenarios/     # Scenario tests only
pytest tests/e2e/           # E2E tests only
```

### Run with markers
```bash
pytest tests/ -m "unit"     # All unit tests
pytest tests/ -m "slow"     # Only slow tests
pytest tests/ -m "not slow" # Skip slow tests
```

### Run specific test
```bash
pytest tests/unit/test_entry_agents.py::TestNotUpEntryAgent::test_not_up_both_bearish_high_confidence -v
```

### Run with coverage
```bash
pytest tests/ --cov=brahmand --cov-report=html --cov-report=term
```

### Run with output capture disabled (see print statements)
```bash
pytest tests/ -s
```

---

## Test Performance Targets

| Category | Target | Current |
|----------|--------|---------|
| Unit tests | < 100ms each | — |
| Phase tests | < 500ms each | — |
| Scenario tests | < 2s each | — |
| E2E tests | < 10s each | — |
| **Full suite** | **< 2 minutes** | — |

---

## Implementation Progress

### ✅ Completed
- [x] TEST_STRATEGY.md (comprehensive plan)
- [x] conftest.py (all fixtures)
- [x] tests/unit/test_entry_agents.py (2 agents × 5 tests = 10 tests)

### 🚧 In Progress
- [ ] Remaining unit tests (8 agents × 5 tests = 40 tests)
- [ ] Phase integration tests (15 tests)
- [ ] Scenario tests (10 tests)
- [ ] E2E tests (5 tests)

### 📋 TODO
- [ ] CI/CD integration (GitHub Actions)
- [ ] Coverage dashboard
- [ ] Performance benchmarking
- [ ] Multi-asset test suite (Phase 2)

---

## Example Test: Entry Agents

```python
@pytest.mark.unit
class TestNotUpEntryAgent:
    """NOT_UP Agent: Evaluate if market rejects upside (BEARISH)"""

    def test_not_up_both_bearish_high_confidence(self, entry_decision_bearish):
        """Both Trend + Traffic Light BEARISH → GO with high confidence"""
        decision = entry_decision_bearish

        assert decision["go"] is True
        assert decision["signal"] == "NOT_UP"
        assert decision["confidence"] >= 80
        assert decision["trend_signal"] == "BEARISH"
```

**Run:**
```bash
pytest tests/unit/test_entry_agents.py::TestNotUpEntryAgent::test_not_up_both_bearish_high_confidence -v
```

---

## Key Files

| File | Purpose |
|------|---------|
| `conftest.py` | Pytest configuration + fixtures |
| `unit/` | Individual agent tests |
| `phase/` | Phase-based integration tests |
| `scenarios/` | Realistic trading scenarios |
| `e2e/` | End-to-end full workflows |
| `TEST_STRATEGY.md` | Complete test plan (this repo) |

---

## Contributing New Tests

1. **Unit test template:**
   ```python
   @pytest.mark.unit
   class TestYourAgent:
       """Agent: What it does"""

       def test_happy_path(self, relevant_fixture):
           """Describe what should happen"""
           # Arrange
           input_data = relevant_fixture

           # Act
           result = agent_function(input_data)

           # Assert
           assert result.is_expected()
   ```

2. **Use fixtures from conftest.py** — Don't duplicate test data
3. **Use markers** — `@pytest.mark.unit`, `@pytest.mark.slow`, etc.
4. **Clear test names** — Should describe what + expected result
5. **Isolated tests** — No shared state between tests

---

## Debugging Failed Tests

```bash
# Run with detailed output
pytest tests/unit/test_entry_agents.py -vv

# Stop on first failure
pytest tests/ -x

# Show local variables on failure
pytest tests/ -l

# Drop into debugger on failure
pytest tests/ --pdb

# Run only failed tests (from last run)
pytest tests/ --lf
```

---

## Notes

- **Deterministic:** All tests use fixed fixtures, no randomness
- **Isolated:** Each test is independent, no setup/teardown dependencies
- **Fast:** Unit tests run in < 100ms, full suite in < 2 minutes
- **Realistic:** Scenario tests simulate actual trading days
- **Maintainable:** Clear structure, easy to add new tests

See `TEST_STRATEGY.md` for complete test plan details.
