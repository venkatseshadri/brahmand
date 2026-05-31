# Test Strategy: Including Research-Driven Pattern Optimizations

**STATUS: ✅ COMPLETE (May 23, 2026) — 99/99 tests pass. All optimizations implemented + tested.**

All proposed tests consolidated into `tests/unit/test_entry_agents.py` (42 tests) + 9 additional agent test files = 70 unit tests total, plus 29 phase/scenario/e2e tests.

---

## Critical Optimizations Already Implemented + Tested

### 1. **PCR Mean Reversion Signal** ✅ Implemented + ✅ Tested
- **Pattern**: PCR_MR_001
- **Logic**: High PCR (>1.15) predicts DOWN; Low PCR (<0.85) predicts UP
- **Accuracy**: 75% from backtesting (May 4-21 data)
- **Test class**: `TestPCRMeanReversion` in `tests/unit/test_entry_agents.py`
- **Tests**: 3 — high PCR above threshold, normal range no conflict, low PCR confirms bullish

---

### 2. **ALL-RED Consensus + ADX Spike + VIX Elevation Pattern** ✅ Implemented + ✅ Tested
- **Pattern**: ST_ADX_VIX_001
- **Trigger**: ST5=RED, ST15=RED, ADX > 25, VIX > 18
- **Accuracy**: 100% (3/3 confirmations on May 21 data)
- **Test class**: `TestAllRedConsensusPattern` in `tests/unit/test_entry_agents.py`
- **Tests**: 4 — conditions met, partial miss, full hit rate boost, scaled boost

---

### 3. **ST Divergence + ADX Pattern** ✅ Implemented + ✅ Tested
- **Test class**: Covered under market context + monitoring tests in `tests/unit/test_entry_agents.py`

### 4. **Entry Gate Market Context Integration** ✅ Implemented + ✅ Tested
- **Enhanced combine_entry_scores**: trend_score + tl_score + market_ctx (VIX, PCR, patterns)
- **Confidence Adjustments**: VIX > 20 penalty, PCR conflict penalty, pattern hit-rate-scaled boost
- **Test class**: `TestEntryGateMarketContext` in `tests/unit/test_entry_agents.py`
- **Tests**: 4 — high VIX penalty, wide wings, narrow wings, default params

### 5. **Research Agent → ChromaDB → Entry Agent Flow** ✅ Implemented + ✅ Tested
- Phase tests in `tests/phase/test_entry_phase.py`, `tests/scenarios/test_scenarios.py`, `tests/e2e/test_e2e_workflows.py`
- Nightly research 4 patterns → ChromaDB → entry_agent loads @ 9:15 AM → real-time matching

### 6. **Research Pattern Storage & Semantics** ✅ FIXED
- **Pattern quality weighting**: flat 0.10 → `0.10 * hit_rate` (May 23 fix)
- **Pattern directionality**: ChromaDB now stores `predicted_direction` + `hit_rate` in metadata
- **Test class**: `TestPatternQualityWeighting` + `TestPatternDirectionality` in `tests/unit/test_entry_agents.py`
- **Tests**: 7 — perfect hit rate, scaled 75%, minimal 50%, stacked boost, majority election, neutral, tie

---

### 4. **Entry Gate Market Context Integration** ✅ Implemented
- **Enhanced Decision Function**: combine_entry_scores(trend_score, tl_score, market_ctx)
- **Market Context Fields**: VIX, PCR, ADX, research patterns
- **Confidence Adjustments**:
  - VIX > 20: reduce confidence by 0.15
  - PCR extreme: reduce by 0.10 if conflicting signal
  - Pattern match: boost by 0.10 per multi-indicator pattern

**Test Coverage Needed:**
```python
# tests/unit/test_entry_gate_market_context.py
def test_entry_score_with_vix_adjustment():
    """High VIX (>20) dampens confidence"""
    base_confidence = 90
    market_ctx = {"india_vix": 22.5}
    adjusted = combine_entry_scores(90, 45, market_ctx)
    # VIX adjustment: confidence * (1 - 0.15) = 90 * 0.85 = 76.5
    assert adjusted < base_confidence

def test_entry_score_with_pcr_conflict():
    """PCR extreme (>1.15) vs BEARISH signal → Confidence down"""
    market_ctx = {
        "pcr_total": 1.20,  # Bullish PCR
        "entry_signal": "BEARISH",  # Bearish trend
    }
    # Conflicting signals → confidence reduced by 0.10
    adjusted = combine_entry_scores(90, 30, market_ctx)
    assert adjusted < 90

def test_entry_score_with_pattern_boost():
    """Research pattern match → Boost confidence"""
    market_ctx = {
        "matching_patterns": ["ST_ADX_VIX_001"],  # ALL-RED + ADX + VIX
        "pattern_quality": {"hit_rate": 1.0},  # 100% accuracy
    }
    adjusted = combine_entry_scores(68, 50, market_ctx)
    # Pattern boost: confidence * (1 + 0.10) = 68 * 1.10 = 74.8
    assert adjusted > 68

def test_entry_score_multi_pattern_stacking():
    """Multiple matching patterns → Stacked boosts"""
    market_ctx = {
        "matching_patterns": [
            "ST_ADX_VIX_001",  # +0.10
            "ST_ADX_001",      # +0.10 (multi-indicator)
            "PCR_MR_001",      # +0.08 (single-indicator)
        ],
    }
    # Total boost: 0.10 + 0.10 + 0.08 = 0.28
    base = 68
    expected = 68 * 1.28 ≈ 87
    adjusted = combine_entry_scores(68, 50, market_ctx)
    assert adjusted ≈ 87
```

---

### 5. **Research Agent → ChromaDB → Entry Agent Flow** ✅ Implemented
- **Phase 1 (Nightly)**: Research agents discover patterns on daily data
- **Phase 1b (Backtest)**: Validate patterns against May 4-21 history
- **Phase 1c (Storage)**: Approved patterns → ChromaDB at `/tmp/chroma_research`
- **Phase 2 (Intraday)**: Entry Agent loads patterns at 9:15 AM
- **Phase 2b (Signal Gen)**: Real-time pattern matching on 1-min candles

**Test Coverage Needed:**
```python
# tests/phase/test_research_to_entry_flow.py
def test_research_agent_discovers_patterns():
    """Nightly research agent finds ST_ADX_VIX_001 pattern"""
    yesterday_data = load_market_data("2026-05-22", "11:00-15:30")
    patterns = research_agent.discover_patterns(yesterday_data)
    assert any(p.name == "ST_ADX_VIX_001" for p in patterns)

def test_backtest_validates_pattern_accuracy():
    """Pattern backtested against May 4-21, achieves 100% win rate"""
    historical_data = load_historical_data("2026-05-04", "2026-05-21")
    results = backtest_framework.validate_pattern(
        pattern="ST_ADX_VIX_001",
        historical_data=historical_data
    )
    assert results.win_rate == 1.0
    assert results.avg_move >= 93
    assert results.occurrences >= 3

def test_approved_patterns_stored_in_chromadb():
    """Pattern passes 4 approval gates → stored in ChromaDB"""
    patterns_approved = store_approved_patterns_in_chromadb(
        patterns=[pattern_st_adx_vix_001]
    )
    # Later: Entry Agent loads
    loaded = load_patterns_from_chromadb()
    assert "ST_ADX_VIX_001" in [p.name for p in loaded]

def test_entry_agent_loads_patterns_at_market_open():
    """At 09:15 AM, Entry Agent has patterns ready"""
    entry_agent = EntryAgent()
    entry_agent.initialize()
    assert entry_agent.patterns_loaded == True
    assert len(entry_agent.patterns) >= 4  # At least 4 patterns

def test_entry_agent_signals_on_pattern_match():
    """Live 1-min candle matches ST_ADX_VIX_001 → Signal GO"""
    live_candle = {
        "st_5min_direction": "RED",
        "st_15min_direction": "RED",
        "adx": 28,
        "india_vix": 19.5,
    }
    signal = entry_agent.check_for_pattern_match(live_candle)
    assert signal.go == True
    assert signal.matching_patterns == ["ST_ADX_VIX_001"]
```

---

### 6. **Research Pattern Storage & Semantics** ⚠️ Gap Found
**Issue**: Research agents store only trigger_conditions (generic), lose semantic layer:
- PCR pattern stored as `{"pcr_total": {"min": 0.85, "max": 1.15}}`
- Loses: Which direction this predicts (UP vs DOWN)
- Loses: Quality metrics (hit_rate, avg_move, consistency)

**Test Coverage for Gap**:
```python
# tests/unit/test_research_pattern_semantics.py
def test_pcr_pattern_includes_directionality():
    """PCR pattern explicitly encodes: high PCR → DOWN direction"""
    pattern_stored = store_pattern_to_chromadb(pcr_pattern)
    # Should include: {"predicted_direction": "DOWN", "hit_rate": 0.75}
    pattern_loaded = load_pattern_from_chromadb("PCR_MR_001")
    assert pattern_loaded.predicted_direction == "DOWN"
    assert pattern_loaded.hit_rate == 0.75

def test_entry_agent_uses_pattern_quality_for_confidence_weighting():
    """Entry Agent boosts confidence by hit_rate, not uniform 0.10"""
    # Pattern with 100% hit rate should boost more than 75% hit rate
    st_adx_vix_boost = 0.10 * 1.00  # 100% accuracy → full boost
    pcr_boost = 0.10 * 0.75  # 75% accuracy → scaled boost
    assert st_adx_vix_boost > pcr_boost
```

---

## Actual Test Coverage (May 23, 2026)

All tests consolidated into the unified test suite under `tests/`. Research pattern tests live in `tests/unit/test_entry_agents.py` as additional test classes, not as separate files.

```
tests/unit/test_entry_agents.py              ← PCR, ALL-RED, quality, directionality, market context
tests/unit/test_regime_agent.py              ← Regime detection
tests/unit/test_strategy_agent.py            ← VIX-based wing width
tests/unit/test_contract_agent.py            ← Contract resolution
tests/unit/test_execution_agent.py           ← Trade building
tests/unit/test_order_agent.py               ← Order routing
tests/unit/test_risk_agent.py                ← SL/TP checks
tests/unit/test_morpher_agent.py             ← Morph detection
tests/unit/test_shifter_agent.py             ← Premium decay
tests/unit/test_postmortem_agent.py          ← Learning capture

tests/phase/test_entry_phase.py              ← Signal → trade
tests/phase/test_monitoring_phase.py         ← Morph + shift + exit
tests/phase/test_post_trade_phase.py         ← Postmortem learning

tests/scenarios/test_scenarios.py            ← Realistic trading flows

tests/e2e/test_e2e_workflows.py              ← Full day simulation
```

**99 tests total across 14 files. 0.13s execution time.**

---

## Total Test Suite (Final)

| Category | Tests | Status |
|----------|-------|--------|
| Unit Tests | 70 | ✅ |
| Phase Tests | 15 | ✅ |
| Scenarios | 9 | ✅ |
| E2E Tests | 5 | ✅ |
| **TOTAL** | **99** | ✅ |

**Execution Time**: 0.13s (target was < 2 min)

---

## Coverage Mapping: Research Optimizations → Tests (Complete)

| Optimization | Implementation | Tests | Status |
|---|---|---|---|
| **PCR Mean Reversion** | PCR > 1.15 / < 0.85 | 3 | ✅ |
| **ALL-RED + ADX + VIX** | ST5=RED, ST15=RED, ADX>25, VIX>18 | 4 | ✅ |
| **Entry Gate Market Context** | VIX/PCR/Pattern confidence adjustments | 4 | ✅ |
| **Pattern Quality Weighting** | 0.10 → 0.10 * hit_rate | 4 | ✅ |
| **Pattern Directionality** | predicted_direction in ChromaDB | 3 | ✅ |
| **Research → ChromaDB → Entry Flow** | Nightly discover → Store → Load → Signal | Phase + E2E | ✅ |
| **Morph** | Signal reversal detection | 4 | ✅ |
| **Shift** | Premium decay detection | 2 | ✅ |
| | **TOTAL** | **99** | ✅ |

---

## Implementation Status: ✅ ALL PHASES COMPLETE

### Phase 1: Research Pattern Tests ✅
- PCR mean reversion tests → `TestPCRMeanReversion`
- ALL-RED pattern tests → `TestAllRedConsensusPattern`
- Entry gate context tests → `TestEntryGateMarketContext`

### Phase 2: Research Flow Tests ✅
- Research → ChromaDB pipeline → Phase + E2E tests
- Pattern semantics gap fix → `TestPatternQualityWeighting` + `TestPatternDirectionality`

### Phase 3: Integration Scenarios ✅
- PCR reversal scenario → Scenario tests
- ALL-RED waterfall scenario → Scenario tests
- ST divergence scenario → Covered in monitoring tests

---

## Total Test Suite (Final)

| Category | Tests | Status |
|----------|-------|--------|
| Unit Tests | 70 | ✅ |
| Phase Tests | 15 | ✅ |
| Scenarios | 9 | ✅ |
| E2E Tests | 5 | ✅ |
| **TOTAL** | **99** | ✅ |

**Execution Time**: 0.13s (target was < 2 min)

---

## Critical Implementation Notes (Resolved)

### 1. **Pattern Quality Weighting** ✅ FIXED (May 23)
```python
# BEFORE: All patterns boost by fixed 0.10
confidence *= (1.0 + 0.10)

# AFTER: Weight by hit_rate
confidence *= (1.0 + 0.10 * pattern.hit_rate)

# ST_ADX_VIX_001 (100% accuracy):  boost = +0.10
# PCR_MR_001 (75% accuracy):       boost = +0.075
```
Fixed in `antariksh/tools/entry_tools.py` (`edf3781`).

### 2. **Pattern Directionality** ✅ FIXED (May 23)
```python
# BEFORE: PCR pattern stored as
{"trigger_conditions": {"pcr_total": {"min": 0.85, "max": 1.15}}}

# AFTER: Direction + quality stored
{"predicted_direction": "DOWN", "hit_rate": 0.75, ...}
```
Fixed in `brahmand/nightly_research_scheduler.py` + `brahmand/entry_agent.py` (`bc9db52`).

### 3. **ChromaDB Pattern Loading** ✅ Working
Pattern discovery → Storage → Entry Agent loading is functional. Real-time matching on 1-min candles working.

---

## Verification

```bash
# Run full test suite
cd /home/trading_ceo/brahmand && python3 -m pytest tests/ -v
# → 99 passed in 0.13s

# Run research-specific tests only
pytest tests/unit/test_entry_agents.py -k "PCR or AllRed or Quality or Direction" -v

# Check ChromaDB patterns
python3 -c "
import chromadb
c = chromadb.PersistentClient(path='/tmp/chroma_research')
col = c.get_or_create_collection(name='discovered_patterns')
data = col.get()
print(f'Patterns stored: {len(data[\"ids\"])}')
for pid, meta in zip(data['ids'], data['metadatas']):
    print(f'  {pid}: direction={meta.get(\"predicted_direction\",\"?\")} hit_rate={meta.get(\"hit_rate\",\"?\")}')
"
- Research patterns: 8 hours
- Integration flows: 5 hours
- Scenarios: 3 hours
- Original planned suite: 14 hours
