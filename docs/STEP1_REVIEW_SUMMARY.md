# STEP1 Review Summary & Decision Path

**Date:** 2026-05-24  
**Status:** ✅ REVIEWED BY DEEPSEEK  
**File Reviewed:** `brahmand/STEP1_LOAD_NIFTY_2024_DATA.py`

---

## Deepseek Review Results

### What Works ✅
- **Regex parsing**: Clean extraction of strikes and PE/CE types
- **Put-call parity**: Spot price derived from ATM option prices (self-contained)
- **Class design**: Clean `NIFTY2024DataLoader` with good separation of concerns
- **Output structure**: Includes entry_spread, tp_target (80%), sl_target (105%), lot_size (75)
- **Observability**: Per-date summary printed during execution
- **CSV handling**: Sorted iteration ensures predictable processing order

### Critical Issues 🔴

#### 1. File Glob Misses Files (High)
**Problem**: Pattern `NSE_FNO_DATA_2024-10-*.csv` misses:
- `NSE_FNO_2024-11-03.csv` (different prefix)
- Oct 21-22 and Oct 29-30 use uppercase `.CSV` (case-sensitive fail)

**Impact**: Missing 4 files = incomplete dataset

**Fix**: Use pattern `NSE_FNO*2024-1[01]-*.{csv,CSV}` or list explicitly

---

#### 2. Single Timepoint Per Day (High) ⚠️ CRITICAL
**Problem**: `time_filter="market_open"` gets ONE price per day at 09:15  
**Impact**: Production agents need intraday data:
- `score_trend_redis()` needs rolling EMAs from 1-min candles
- `score_traffic_light_redis()` needs multi-TF candle colors (5m, 15m, 30m, 60m, 240m, 1440m)
- Entry gate needs intraday volatility/confidence evolution
- Cannot detect SL/TP hits without intraday price movement

**This blocks STEP 2-5**

---

#### 3. Hardcoded PE Direction (High)
**Problem**: Always builds PUT_SPREAD (SELL ATM PE, BUY OTM PE)  
**Impact**: No CALL_SPREAD support; ignores NOT_UP agent signal

**Fix**: Derive direction from agent signal or parameterize

---

#### 4. Hardcoded ATM Range (Medium)
**Problem**: Searches only 23000-24500; NIFTY could trade outside  
**Impact**: Silent skip if no valid ATM found; data loss

**Fix**: Find most-liquid strike pair dynamically using volume/OI

---

#### 5. Non-Deterministic Time (Medium)
**Problem**: `first_time` uses `dict.values()` iteration (order depends on insertion)  
**Impact**: Time labels could be arbitrary/inconsistent

**Fix**: Use `min(time)` across all records instead

---

#### 6. Memory Budget Not Warned (Medium)
**Problem**: Kaggle cache = 1.4GB; full load into nested dict could overflow  
**Impact**: Potential OOM on smaller machines

**Fix**: Log memory usage before/after load

---

#### 7. OI Not Used (Low)
**Problem**: Open Interest parsed but never used in snapshot construction  
**Impact**: Missing liquidity signal for strike selection

**Fix**: Weight ATM strike selection by combined CE+PE volume/OI

---

#### 8. Type Hints Missing (Low)
**Problem**: `derive_spot_from_atm()` returns `None` but no Optional type hint  
**Impact**: Callers could miss null check

**Fix**: Add `-> Optional[float]` type hints

---

## Architecture Gap: Daily → Intraday

**Core mismatch**: Step 1 produces 7 daily snapshots (one per day).

**But agents need intraday data** to compute:
1. **EMAs** for trend strength (requires 1-min OHLCV bars)
2. **Traffic light patterns** for multi-TF candle sequences
3. **Intraday volatility** for confidence thresholds
4. **Option premium movement** to detect SL/TP hits during the day

**Current output**: Insufficient for full production E2E backtest

---

## Two Paths Forward

### Path A: Add Step 1.5 (Intraday Bar Loader) ✅ RECOMMENDED

```
STEP1: STEP1_LOAD_NIFTY_2024_DATA.py
       ↓ (fixes glob, time, direction issues)
       Output: Daily snapshots + fixed data structure

STEP1.5: STEP1_5_LOAD_INTRADAY_BARS.py  [NEW]
       Load per-day Pandas DataFrames with full 1-min OHLCV
       For each date:
         - Load all strikes' 1-min bars
         - Calculate rolling EMAs (5, 20, 50, 100, 200)
         - Aggregate to multi-TF candles (5m, 15m, 30m, 60m, 240m, 1440m)
         - Extract traffic light patterns
       Output: date → {1-min bars, EMAs, TF candles}

STEP2: STEP2_RUN_ENTRY_AGENT_TOOLS.py
       For each date:
         - Call score_trend_redis() with 1-min EMA data
         - Call score_traffic_light_redis() with TF candle patterns
         - Call NOT_UP / NOT_DOWN agent logic
         - Apply entry gate (≥75% confidence)
         - Record entry decision with confidence/reasoning

STEP3: STEP3_SIMULATE_BUTTERFLY_TRADES.py
       For each entry decision:
         - Simulate butterfly entry (SELL ATM, BUY OTM 200pt)
         - Track intraday movement (SL/TP hits)
         - Simulate morphing (if SL hit)
         - Simulate leg shifting (if decay >50%)
         - Final P&L

STEP4: STEP4_COMPARE_WITH_ORDER_LEDGER.py
       Compare agent decisions vs real order_ledger.json trades
       Show: which real trades would have been triggered, false positives, false negatives

STEP5: STEP5_REGIME_VALIDATION.py
       Confirm regime agent supports entry decision
       CALL_SPREAD → BEARISH regime, PUT_SPREAD → BULLISH regime
```

**Pros:**
- Minimal changes to Step 1
- Clean separation (each step independent, testable)
- Transparent data flow
- Matches production architecture

**Cons:**
- Two-pass CSV loading (reads same files twice)
- Additional Step 1.5 script needed

---

### Path B: Rework Step 1 (Intraday-First)

Single loader reads CSVs once, builds both:
- Daily snapshots (for summary)
- Intraday DataFrames (for agent tools)

**Pros:**
- Single pass, memory efficient
- Fewer files

**Cons:**
- Larger refactor (~400+ lines)
- Tighter coupling
- Harder to debug

---

## Decision Matrix

| Aspect | Path A | Path B |
|--------|--------|--------|
| **Production alignment** | ✅ High | ✅ High |
| **Debuggability** | ✅ Easy (step by step) | ⚠️ Medium (interdependent) |
| **Development speed** | ⚠️ Medium | ⚠️ Medium |
| **Code clarity** | ✅ Clear (separation) | ⚠️ Complex (one file does all) |
| **Memory efficiency** | ⚠️ Two passes | ✅ One pass |
| **Testing** | ✅ Each step isolated | ⚠️ Full system test needed |

---

## Recommended Decision: ✅ Path A

**Why:**
1. **Validation transparency**: Each step produces intermediate outputs reviewable with Deepseek
2. **Incremental**: Build one step at a time, get sign-off before next
3. **Production-like**: Matches actual agent chain architecture (separate tools)
4. **Low risk**: If Step 1.5 or Step 2 has issues, we can debug without breaking Step 1

---

## Next Steps

### To Proceed with Path A:

1. **Fix STEP 1 issues**:
   - [ ] Fix file glob pattern to catch all CSV files
   - [ ] Use `min(time)` for deterministic time
   - [ ] Add optional CE direction support
   - [ ] Dynamic ATM detection via volume/OI
   - [ ] Log memory usage
   - [ ] Add type hints

2. **Build STEP 1.5**:
   - [ ] Load 1-min OHLCV for all strikes per date
   - [ ] Calculate rolling EMAs (5, 20, 50, 100, 200)
   - [ ] Aggregate to multi-TF candles
   - [ ] Save DataFrame per date as pickle/parquet

3. **Build STEP 2**:
   - [ ] Import score_trend_redis, score_traffic_light_redis from antariksh/tools/entry_tools.py
   - [ ] For each date, call agent tools with intraday EMA/TF data
   - [ ] Apply NOT_UP/NOT_DOWN logic
   - [ ] Apply entry gate filter (≥75%)
   - [ ] Log all signals and decisions

4. **Build STEP 3**:
   - [ ] Simulate butterfly entry
   - [ ] Track P&L with actual premium movement from CSV
   - [ ] Simulate morphing and leg shifting

5. **Build STEP 4**:
   - [ ] Load order_ledger.json
   - [ ] Compare agent decisions vs real trades

6. **Build STEP 5**:
   - [ ] Call regime agent for validation

---

## Approval Required From

- [ ] **Deepseek**: Agrees with Path A recommendation?
- [ ] **trading_ceo**: Approve Path A to proceed?

---

## Sign-Off

**Deepseek Review:** ✅ Complete (2026-05-24 18:23)  
**Recommendation:** Path A (Intraday Bar Loader)  
**Status:** Awaiting approval to fix STEP 1 + build STEP 1.5
