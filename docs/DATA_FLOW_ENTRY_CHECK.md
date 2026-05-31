# Entry Check Data Flow & Frequency

## 1. Redis Messages — Updated Every 60 Seconds

**Source:** `data_capture_v3.1_duckdb.py` (runs continuously 09:15-15:30)

Every 60 seconds, v3.1 pushes a complete 1-minute bar to Redis:

```
Redis Queue: v3_ohlcv_queue
├─ Timestamp (ISO format)
├─ Index (NIFTY or SENSEX)
├─ OHLCV (Open, High, Low, Close, Volume)
└─ 15 Indicator Fields:
   ├─ ema5
   ├─ ema20
   ├─ ema50
   ├─ rsi (momentum)
   ├─ atr (volatility)
   ├─ adx (trend strength)
   ├─ st_direction (SuperTrend bullish/bearish)
   ├─ bb_pct_b (Bollinger Band position)
   └─ 7 others (composite indicators)
```

**Example push at 09:15:00:**
```json
{
  "timestamp": "2026-05-20T09:15:00.123456",
  "index": "NIFTY",
  "open": 23747.35,
  "high": 23750.00,
  "low": 23745.00,
  "close": 23748.50,
  "volume": 12500000,
  "ema5": 23741.25,
  "ema20": 23740.50,
  "ema50": 23735.80,
  "rsi": 52.30,
  "atr": 9.60,
  "adx": 14.20,
  "st_direction": "bullish",
  "bb_pct_b": 0.65
}
```

**Timeline:**
```
09:15:00 → v3.1 pushes bar #1 to Redis
09:16:00 → v3.1 pushes bar #2 to Redis
09:17:00 → v3.1 pushes bar #3 to Redis
...
15:30:00 → v3.1 pushes final bar to Redis
15:31:00 → v3.1 stops pushing
```

---

## 2. Entry Check Method — Location & Frequency

**Location:** `/home/trading_ceo/antariksh/agents/entry/entry_check.py`

**Method:** `check_entry(index: str = "NIFTY") -> dict`

**What it does:**
```python
def check_entry(index: str = "NIFTY"):
    # 1. Read from Redis (deterministic, no DB calls)
    trend = score_trend_redis(index)           # Uses EMA, ADX, SuperTrend
    tl = score_traffic_light_redis(index)      # Uses 6-TF candle colors
    
    # 2. Combine scores (deterministic fusion)
    decision = combine_entry_scores(trend, tl) # Weighted combination
    
    # 3. Add timestamp (when this decision was made)
    decision["timestamp"] = datetime.now().isoformat()
    
    # 4. Write to file (so kickoff.py can read it)
    Path("/tmp/entry_check_latest.json").write_text(json.dumps(decision))
    
    return decision
```

**Calling Frequency (May 20+):**
- **Every 5 minutes** (via v4 queue aggregator, after data aggregation completes)
- Times: 09:15, 09:20, 09:25, 09:30, ... 15:25, 15:30
- This REPLACES the stale once-per-day approach from May 19

---

## 3. Who Updates Entry Check Signals

### Data Flow Diagram (May 20+)

```
┌─────────────────────────────────────────────────────────────┐
│ V3.1 Data Capture (python-trader/varaha)                   │
│ • Continuously reads from Shoonya WebSocket                  │
│ • Computes 15 indicators every 60 seconds                    │
│ • PUSHES to Redis v3_ohlcv_queue                             │
│   Freq: Every minute (09:15-15:30)                           │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ├─→ DuckDB (varaha_data.duckdb)
                 └─→ Redis (v3_ohlcv_queue)
                         │
                         ↓
    ┌────────────────────────────────────────────────┐
    │ Entry Check (antariksh/agents/entry)           │
    │ • Reads Redis queue (last 500 bars)            │
    │ • Scores: Trend + Traffic Light                │
    │ • Combines scores deterministically            │
    │ • WRITES to /tmp/entry_check_latest.json       │
    │   Freq: Every 5 minutes (via v4)               │
    │   Times: 09:15, 09:20, 09:25, ...              │
    └────────────────┬───────────────────────────────┘
                     │
                     ↓
    /tmp/entry_check_latest.json
    {
      "signal": "BULLISH",
      "confidence": 75,
      "timestamp": "2026-05-20T09:20:15.456789"  ← Fresh!
    }
                     │
                     ↓
    ┌────────────────────────────────────────────────┐
    │ Kickoff Scheduler (brahmand/kickoff.py)        │
    │ • Runs every 5 minutes (same as entry_check)   │
    │ • Reads fresh /tmp/entry_check_latest.json     │
    │ • Passes entry_signal to Regime Agent          │
    │ • Executes trade with fresh gate signal        │
    └────────────────────────────────────────────────┘
```

---

## 4. Score Functions — What They Calculate

### `score_trend_redis()` 
Reads the last 500 1-min bars from Redis, computes:
- Multi-TF aggregation (5/15/30/60/240/1440-min)
- EMA alignment (price vs EMA20/50)
- ADX trend strength (>25 = trending, <20 = sideways)
- SuperTrend direction confirmation
- Applies tunable weights from `config/entry_weights.json`

**Output:**
```python
{
  "family": "Trend",
  "signal": "BULLISH" | "BEARISH" | "NEUTRAL",
  "score": 5.2,  # Weighted sum
  "confidence": 75,
  "reasoning": "EMA confluence + high ADX"
}
```

### `score_traffic_light_redis()`
Reads the last 1-min bar, computes:
- 6 timeframe candle colors (GREEN/RED/neutral)
- Pattern detection (MOMENTUM_PEAK, BULLISH_CONTINUATION, etc.)
- Daily + intraday alignment
- Applies pattern confidence weights

**Output:**
```python
{
  "family": "TrafficLight",
  "signal": "BULLISH" | "BEARISH" | "NEUTRAL",
  "score": 3.0,
  "confidence": 80,
  "pattern": "BULLISH_CONTINUATION",
  "colors": {"5m": "GREEN", "15m": "GREEN", ...}
}
```

### `combine_entry_scores(trend, tl)`
Fuses both scores deterministically (no LLM):
```python
if trend_score > 3.0 and tl_score > 2.0:
    signal = "BULLISH"
    confidence = (trend_confidence + tl_confidence) / 2
elif trend_score < -3.0 and tl_score < -2.0:
    signal = "BEARISH"
    confidence = (trend_confidence + tl_confidence) / 2
else:
    signal = "NEUTRAL"
    confidence = min(trend_confidence, tl_confidence)
```

---

## 5. Timeline for May 20 (Expected)

```
09:14:00  run_data_capture_with_v4.sh starts
          ├─ v3.1 NIFTY starts capturing (watchdog)
          ├─ v3.1 SENSEX starts capturing (watchdog)
          └─ v4 queue aggregator starts looping

09:15:00  First 1-min bar arrives
          ├─ v3.1 pushes bar #1 to Redis
          ├─ v4 reads from queue
          ├─ v4 aggregates to 5/15/30/60-min
          └─ v4 calls entry_check()
          
09:15:01  Entry Check Result
          ├─ score_trend_redis() reads Redis (500 bars, just 1 available)
          ├─ score_traffic_light_redis() reads Redis (just 1 bar)
          ├─ combine_entry_scores()
          └─ Writes /tmp/entry_check_latest.json with 09:15:01 timestamp

09:15:05  Kickoff runs
          ├─ Reads /tmp/entry_check_latest.json (timestamp 09:15:01 ✓ FRESH)
          ├─ Passes signal to Regime Agent
          └─ Might enter trade

09:16:00  v3.1 pushes bar #2
09:20:00  v4 calls entry_check() again (minute % 5 == 0)
09:20:01  Writes fresh /tmp/entry_check_latest.json (timestamp 09:20:01)
09:20:05  Kickoff runs, reads fresh signal

09:25:00  v4 calls entry_check() again
...
15:30:00  Final bar
15:31:00  Market closes, pipeline shuts down
```

---

## 6. Key Insight: Deterministic, Not LLM

Entry check is **100% deterministic**:
- No LLM calls at runtime
- No DuckDB calls (no lock contention)
- Just formula-based scoring
- Timing: ~100-200ms per call

This is why it's safe to call from v4 aggregator without blocking concerns.

---

## May 19 vs May 20 Comparison

| Aspect | May 19 | May 20+ |
|--------|--------|---------|
| **entry_check called** | Manually at 12:20 (1 time!) | Every 5 min by v4 |
| **Redis data freshness** | Last bar from 12:15 | Last bar from 09:15-15:30 |
| **entry_check_latest.json** | Stale (May 18 15:20) | Fresh (current time) |
| **kickoff reads** | Stale data from yesterday | Fresh data from this minute |
| **Trade record** | Confusion: old entry_scores | Clear: timestamp matches trading time |

---

**Summary:** Entry check is lightweight, deterministic, and Redis-native. V4 can safely call it every 5 minutes without DuckDB contention, ensuring kickoff.py always has fresh signals.
