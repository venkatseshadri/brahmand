# PROJECT UNICORN — TDD Implementation Plan
## Step-by-step with failing tests first, implementation second

---

## PHASE 1: RAW DATA TOOL (unicorn_raw_query.py)

### Step 1.1 — Failing test: tool returns all 7 families
**Test:** `tests/unicorn/test_raw_query.py::test_returns_seven_families`
```python
def test_returns_seven_families():
    tool = UnicornRawQuery()
    result = json.loads(tool._run("NIFTY"))
    assert set(result.keys()) == {"trend", "momentum", "volatility", "volume", "options", "flow", "macro"}
```
**Estimated time:** 15 min
**Status:** [ ] TODO

### Step 1.2 — Failing test: output contains NO verdicts
**Test:** `tests/unicorn/test_raw_query.py::test_no_verdicts_in_output`
```python
def test_no_verdicts_in_output():
    tool = UnicornRawQuery()
    result = json.loads(tool._run("NIFTY"))
    forbidden = {"go", "signal", "recommendation", "verdict", "enter", "skip", "BULLISH", "BEARISH", "NEUTRAL"}
    flat = json.dumps(result).upper()
    found = [f for f in forbidden if f in flat]
    assert not found, f"Verdicts found in raw output: {found}"
```
**Estimated time:** 10 min
**Status:** [ ] TODO

### Step 1.3 — Failing test: cache returns same data within 60s
**Test:** `tests/unicorn/test_raw_query.py::test_cache_ttl`
```python
def test_cache_ttl():
    tool = UnicornRawQuery()
    r1 = json.loads(tool._run("NIFTY"))
    time.sleep(2)
    r2 = json.loads(tool._run("NIFTY"))
    assert r1 == r2  # cached, identical
```
**Estimated time:** 10 min
**Status:** [ ] TODO

### Step 1.4 — Implement UnicornRawQuery tool
**File:** `brahmand/unicorn_raw_query.py`
- Class: UnicornRawQuery(BaseTool)
- Wraps `antariksh.tools.entry_tools.query_all_families("NIFTY")`
- Passes through raw data, strips any verdict fields
- Implements 60s TTL cache
**Estimated time:** 30 min
**Status:** [ ] TODO

**PHASE 1 CHECKPOINT:** 3 green tests → raw data flowing


## PHASE 2: BULL & BEAR AGENTS

### Step 2.1 — Failing test: Bull produces valid argument JSON
**Test:** `tests/unicorn/test_debate.py::test_bull_produces_valid_json`
```python
def test_bull_produces_valid_json():
    raw_data = load_fixture("raw_data_sample.json")
    agent = create_bull_agent()
    task = Task(description=f"Raw data:\n{json.dumps(raw_data)}\n\nArgue for entry.", ...)
    result = agent.execute_task(task)
    parsed = parse_json_output(str(result))
    assert parsed["recommendation"] == "ENTER"
    assert len(parsed["points"]) >= 3
    for p in parsed["points"]:
        assert "family" in p and "claim" in p and "evidence" in p
```
**Estimated time:** 20 min
**Status:** [ ] TODO

### Step 2.2 — Failing test: Bear produces valid argument JSON
**Test:** `tests/unicorn/test_debate.py::test_bear_produces_valid_json`
```python
def test_bear_produces_valid_json():
    raw_data = load_fixture("raw_data_sample.json")
    agent = create_bear_agent()
    task = Task(description=f"Raw data:\n{json.dumps(raw_data)}\n\nArgue against entry.", ...)
    result = agent.execute_task(task)
    parsed = parse_json_output(str(result))
    assert parsed["recommendation"] == "SKIP"
    assert len(parsed["points"]) >= 3
```
**Estimated time:** 20 min
**Status:** [ ] TODO

### Step 2.3 — Create Bull & Bear YAML blueprints
**File:** `brahmand/config/unicorn_agents.yaml`
- bull_entry_agent: role, goal, backstory (adversarial ENTER bias)
- bear_entry_agent: role, goal, backstory (adversarial SKIP bias)
- Both use `unicorn_raw_query` tool
**Estimated time:** 30 min
**Status:** [ ] TODO

### Step 2.4 — Create test fixture: raw_data_sample.json
**File:** `tests/unicorn/fixtures/raw_data_sample.json`
- Frozen snapshot of all 7 families with realistic values
- Bullish scenario: ADX=38, RSI=55, VIX=14, PCR=0.85 → should produce ENTER
- Bearish scenario: ADX=18, RSI=72, VIX=22, PCR=1.25 → should produce SKIP
**Estimated time:** 20 min
**Status:** [ ] TODO

**PHASE 2 CHECKPOINT:** 2 green tests → Bull/Bear producing structured arguments


## PHASE 3: JUDGE AGENT

### Step 3.1 — Failing test: Judge detects hallucination (fabricated value)
**Test:** `tests/unicorn/test_judge.py::test_judge_detects_fabrication`
```python
def test_judge_detects_fabrication():
    raw_data = load_fixture("raw_data_sample.json")
    # Bull fabricates: claims ADX=55 but actual is 38
    bull_arg = make_argument("ENTER", [{"family": "trend", "claim": "ADX=55", "evidence": {"adx": 55}}])
    bear_arg = make_argument("SKIP", [{"family": "volatility", "claim": "ATR=12", "evidence": {"atr": 12}}])
    
    result = judge_bull_bear(raw_data, bull_arg, bear_arg)
    assert "hallucinations" in result
    assert any("ADX" in h for h in result["hallucinations"])
    assert result["bull_score"] < result["bear_score"]  # lied → penalized
```
**Estimated time:** 25 min
**Status:** [ ] TODO

### Step 3.2 — Failing test: Judge verifies claims against raw data
**Test:** `tests/unicorn/test_judge.py::test_judge_verifies_claims`
```python
def test_judge_verifies_claims():
    raw_data = load_fixture("raw_data_sample.json")
    # Both truthful — sell weak trend, bear catches volatility
    bull_arg = make_argument("ENTER", [
        {"family": "trend", "claim": "ADX=38 strong trend", "evidence": {"adx": 38, "di_plus": 28}}
    ])
    bear_arg = make_argument("SKIP", [
        {"family": "macro", "claim": "VIX=14 low risk but ATR=18 wide", "evidence": {"vix": 14, "atr": 18}}
    ])
    
    result = judge_bull_bear(raw_data, bull_arg, bear_arg)
    assert result["hallucinations"] == [] or len(result["hallucinations"]) == 0
    # Truthful claims should score
    assert result["bull_score"] > 0
    assert result["bear_score"] > 0
```
**Estimated time:** 25 min
**Status:** [ ] TODO

### Step 3.3 — Failing test: Judge produces correct signal
**Test:** `tests/unicorn/test_judge.py::test_judge_produces_correct_signal`
```python
def test_judge_produces_correct_signal():
    # Bull scenario: convincing ENTER argument
    raw = load_fixture("raw_data_bullish.json")
    bull = make_argument("ENTER", [...strong bullish points...])
    bear = make_argument("SKIP", [...weak bearish points...])
    
    result = judge_bull_bear(raw, bull, bear)
    assert result["signal"] == "NOT_UP"
    assert 0.5 <= result["confidence"] <= 1.0
    
    # Bear scenario: convincing SKIP argument
    raw = load_fixture("raw_data_bearish.json")
    bull = make_argument("ENTER", [...weak bullish points...])
    bear = make_argument("SKIP", [...strong bearish points...])
    
    result = judge_bull_bear(raw, bull, bear)
    assert result["signal"] == "NONE"
```
**Estimated time:** 25 min
**Status:** [ ] TODO

### Step 3.4 — Implement Judge agent and scoring
**File:** `brahmand/unicorn_judge.py`
- Judge class with `verify_claims()`, `score_arguments()`, `synthesize()`
- Uses `unicorn_raw_query` tool
- Implements verified/unverifiable/contradicted scoring tiers
- Detects hallucinations, flags in output
**Estimated time:** 45 min
**Status:** [ ] TODO

### Step 3.5 — Create Judge YAML blueprint
**File:** `brahmand/config/unicorn_agents.yaml` (append)
- judge_agent: role, goal, backstory, scoring rules
**Estimated time:** 15 min
**Status:** [ ] TODO

**PHASE 3 CHECKPOINT:** 3 green tests → Judge scoring arbitration working


## PHASE 4: DEBATE ORCHESTRATOR

### Step 4.1 — Failing test: full debate produces valid result
**Test:** `tests/unicorn/test_debate.py::test_full_debate_e2e`
```python
def test_full_debate_e2e():
    raw_data = load_fixture("raw_data_sample.json")
    result = run_unicorn_debate(raw_data, gate_type="NOT_UP")
    
    assert result["signal"] in ("NOT_UP", "NOT_DOWN", "NONE")
    assert 0 <= result["confidence"] <= 1
    assert "bull_score" in result and "bear_score" in result
    assert isinstance(result.get("hallucinations"), list)
```
**Estimated time:** 20 min
**Status:** [ ] TODO

### Step 4.2 — Failing test: NOT_DOWN debate works symmetrically
**Test:** `tests/unicorn/test_debate.py::test_not_down_debate`
```python
def test_not_down_debate():
    raw_data = load_fixture("raw_data_sample.json")
    result = run_unicorn_debate(raw_data, gate_type="NOT_DOWN")
    assert result["signal"] in ("NOT_DOWN", "NOT_UP", "NONE")
```
**Estimated time:** 15 min
**Status:** [ ] TODO

### Step 4.3 — Implement debate orchestrator
**File:** `brahmand/unicorn_debate.py`
- `run_unicorn_debate(raw_data, gate_type="NOT_UP")`
- Sequence: query raw data → Bull task → Bear task → Judge task
- Context passing: raw_data → Bull → (raw+bull_arg) → Bear → (raw+bull_arg+bear_arg) → Judge
- Handles both NOT_UP and NOT_DOWN via gate_type parameter
**Estimated time:** 45 min
**Status:** [ ] TODO

**PHASE 4 CHECKPOINT:** 2 green tests → end-to-end debate working


## PHASE 5: INTEGRATION WITH E2E CHAIN

### Step 5.1 — Failing test: e2e_chain uses unicorn debate
**Test:** `tests/unicorn/test_integration.py::test_e2e_chain_with_unicorn`
```python
def test_e2e_chain_with_unicorn():
    # Mock raw data tool to return known fixture
    with patch('unicorn_raw_query.UnicornRawQuery._run') as mock_query:
        mock_query.return_value = json.dumps(load_fixture("raw_data_sample.json"))
        result = run_sequential_crew("09:30")  # Uses new unicorn gate
        assert result is not None
        # Either entry or skip — both valid
```
**Estimated time:** 25 min
**Status:** [ ] TODO

### Step 5.2 — Replace entry crew in e2e_chain.py
**File:** `brahmand/e2e_chain.py`
- Remove NOT_UP/NOT_DOWN agent creation and `entry_crew.kickoff()`
- Replace with `run_unicorn_debate(raw_data, gate_type)`
- Map judge output → entry_decision dict (same format as current)
- Deterministic execution pipeline UNCHANGED
**Estimated time:** 30 min
**Status:** [ ] TODO

### Step 5.3 — Failing test: execution pipeline unchanged
**Test:** `tests/e2e/test_e2e_workflows.py` (existing tests must still pass)
```python
# All existing e2e workflow tests must pass with unicorn gate
```
**Estimated time:** 15 min
**Status:** [ ] TODO

**PHASE 5 CHECKPOINT:** All existing tests green → seamless integration


## PHASE 6: HARDENING

### Step 6.1 — Failing test: scorecard anomaly checker
**Test:** `tests/unicorn/test_anomaly.py::test_anomaly_detector`
```python
def test_anomaly_detector():
    # Both scores 0 but recommends ENTER → anomaly
    bad = {"bull_score": 0, "bear_score": 0, "signal": "NOT_UP"}
    assert detect_anomaly(bad) is True
    
    # Normal
    good = {"bull_score": 3.2, "bear_score": 4.1, "signal": "NONE"}
    assert detect_anomaly(good) is False
```
**Estimated time:** 20 min
**Status:** [ ] TODO

### Step 6.2 — Failing test: fallback when raw query fails
**Test:** `tests/unicorn/test_debate.py::test_fallback_on_tool_failure`
```python
def test_fallback_on_tool_failure():
    with patch('unicorn_raw_query.UnicornRawQuery._run', side_effect=Exception("Redis down")):
        result = run_unicorn_debate(None, gate_type="NOT_UP")
        # Must not crash — fallback to deterministic
        assert result["source"] == "fallback"
```
**Estimated time:** 20 min
**Status:** [ ] TODO

### Step 6.3 — Implement anomaly checker and fallback
**File:** `brahmand/unicorn_anomaly.py`
- Scorecard validation rules
- Minimum family coverage check
- Fallback path: deterministic entry tools
**Estimated time:** 30 min
**Status:** [ ] TODO

**PHASE 6 CHECKPOINT:** Hardened — anomalies caught, graceful degradation


## ESTIMATED TOTALS

| Phase | Steps | Tests | Code | Total |
|-------|-------|-------|------|-------|
| 1. Raw Data Tool | 4 | 3 | 1 file | ~65 min |
| 2. Bull & Bear | 4 | 2 | 1 YAML | ~90 min |
| 3. Judge | 5 | 3 | 2 files | ~135 min |
| 4. Orchestrator | 3 | 2 | 1 file | ~80 min |
| 5. Integration | 3 | 3 | 1 edit | ~70 min |
| 6. Hardening | 3 | 3 | 1 file | ~70 min |
| **TOTAL** | **22** | **16** | **6 files** | **~8.5 hours** |

## NEW FILES (6)

```
brahmand/
  unicorn_raw_query.py       # UnicornRawQuery(BaseTool)
  unicorn_judge.py           # Judge scoring logic
  unicorn_debate.py          # Orchestrator: run_unicorn_debate()
  unicorn_anomaly.py         # Scorecard validation + fallback
  config/unicorn_agents.yaml # Bull, Bear, Judge blueprints
  tests/unicorn/
    __init__.py
    test_raw_query.py
    test_debate.py
    test_judge.py
    test_integration.py
    test_anomaly.py
    fixtures/
      raw_data_sample.json
      raw_data_bullish.json
      raw_data_bearish.json
```

## MODIFIED FILES (1)

```
brahmand/
  e2e_chain.py               # Replace entry crew with unicorn_debate.run_unicorn_debate()
```
