# ENTRY RESEARCH AGENT — Complete Tools & Database Reference

**Last Updated:** 2026-05-21  
**Databases Accessible:** Varaha v3.1 + v4  
**Total Data Points:** 90+ columns across both databases

---

## TOOLS AVAILABLE

### TOOL 1: `query_1min_candles_v31` — Varaha v3.1 Complete Database

**Database Path:** `/home/trading_ceo/projects/varaha/data/varaha_data.duckdb`

**Table:** `market_data` (primary trading data)

**Access:** Full unrestricted read-only access to ALL columns

**Function Signature:**
```python
query_1min_candles_v31(
    date: str,              # "2026-05-21"
    index: str = "NIFTY",   # "NIFTY" or "SENSEX"
    limit: int = None       # None = all rows for the day
) -> JSON
```

**Available Columns in market_data (v3.1):**

#### Identification & Time
- `timestamp` — Full timestamp (2026-05-21 09:16:00)
- `date` — Date (2026-05-21)
- `time` — Time (09:16)
- `index_name` — "NIFTY" or "SENSEX"

#### Price Data (OHLC)
- `open_price` — Opening price
- `high_price` — Intrabar high
- `low_price` — Intrabar low
- `close_price` — Closing price
- `spot` — **Current spot price (main analysis field)**

#### Gap & Prior Close
- `prev_close` — Previous day's close
- `gap_pct` — Gap percentage from prev close

#### SuperTrend Indicators (Two Timeframes)
- `st_15min` — 15-min SuperTrend ("GREEN" or "RED")
- `st_60min` — 60-min SuperTrend ("GREEN" or "RED")

#### Moving Averages (Calculated on 15-min basis)
- `ema_5_15min` — 5-period EMA (15-min bars)
- `ema_9_15min` — 9-period EMA (15-min bars)
- `ema_20_15min` — 20-period EMA (15-min bars)
- `sma_50_15min` — 50-period SMA (15-min bars)
- `sma_200_15min` — 200-period SMA (15-min bars)

#### Momentum & Trend Strength
- `adx` — Average Directional Index (0-100, >25 = strong)
- `rsi_14` — Relative Strength Index (0-100, >70 = overbought, <30 = oversold)
- `rsi_5` — Fast RSI (5-period)

#### Volatility & Sentiment
- `india_vix` — VIX index level (17.0-25.0 typical range)
- `pcr_total` — Total Put/Call Ratio (>1.0 = bearish, <0.95 = bullish)
- `pcr_oi` — OI-weighted Put/Call ratio
- `pcr_volume` — Volume-weighted Put/Call ratio

#### Traffic Light System (Pattern Recognition)
- `traffic_light_15min` — Pattern indicator: "G" (green), "R" (red)
- `traffic_light_pattern_15min` — Full pattern string ("GGGRRG")
- `traffic_light_signal_15min` — Signal name (BULLISH, BEARISH, CHOPPY)

#### Option Greeks & IV
- `iv_percentile` — IV Percentile (0-100)
- `iv_rank` — IV Rank (0-100, >80 = high IV)
- `call_iv` — Call option implied volatility
- `put_iv` — Put option implied volatility

#### Volume & OI Metrics
- `total_volume` — Total traded volume (1-min bar)
- `option_volume` — Total option volume
- `futures_oi` — Futures open interest
- `call_oi` — Call option open interest
- `put_oi` — Put option open interest

#### Additional Technical Indicators
- `bb_upper` — Bollinger Band upper (20, 2)
- `bb_lower` — Bollinger Band lower (20, 2)
- `bb_middle` — Bollinger Band middle (20-SMA)
- `atr_14` — Average True Range (volatility measure)
- `macd` — MACD line
- `macd_signal` — MACD signal line
- `macd_histogram` — MACD histogram
- `obv` — On-Balance Volume
- `cmf` — Chaikin Money Flow

#### Regime & Market Context
- `market_regime` — "BULLISH", "BEARISH", "SIDEWAYS"
- `session_phase` — "OPENING", "MIDDAY", "CLOSING"
- `volatility_regime` — "LOW", "NORMAL", "HIGH"

#### Data Quality Flags
- `data_quality` — "CLEAN", "PARTIAL", "GAP"
- `missing_fields` — Count of null fields in row
- `outlier_flag` — Boolean if price move is unusual

---

### TOOL 2: `query_1min_candles_v4` — Varaha v4 Multitimeframe Database

**Database Path:** `/home/trading_ceo/projects/varaha/data/market_data_multitf.duckdb`

**Tables:** `market_data_multitf` or `market_data` (depending on setup)

**Access:** Full unrestricted read-only access to ALL columns + cross-timeframe data

**Function Signature:**
```python
query_1min_candles_v4(
    date: str,              # "2026-05-21"
    index: str = "NIFTY",   # "NIFTY" or "SENSEX"
    limit: int = None       # None = all rows for the day
) -> JSON
```

**What Makes v4 Different:**
- **Multitimeframe aggregation:** Data aggregated from 1-min, 5-min, 15-min, 60-min candles
- **Cross-TF correlations:** Indicators calculated at multiple timeframes simultaneously
- **Enhanced reliability:** Aggregates across Varaha v3 and other data sources

**Expected Additional Columns in v4:**
- `tf_1min_*` — All 1-min indicators
- `tf_5min_*` — All 5-min indicators (ST5, EMA5, ADX5, etc.)
- `tf_15min_*` — All 15-min indicators (likely duplicates of v3.1)
- `tf_60min_*` — All 60-min indicators (ST60, ADX60, etc.)
- `tf_240min_*` — All 240-min (4-hour) indicators
- `cross_tf_alignment` — Multi-TF consensus (how many TFs agree on direction)
- `aggregate_signal` — Composite signal from all timeframes

---

### TOOL 3: `detect_significant_moves` — Move Detection Engine

**Purpose:** Find all price moves >= threshold in a dataset

**Function Signature:**
```python
detect_significant_moves(
    candles_json: str,           # Output from query_1min_candles_v31 or v4
    min_move_points: int = 50    # Threshold (50 for NIFTY, 100 for SENSEX)
) -> JSON
```

**Output Fields:**
```json
{
  "min_move_threshold": 50,
  "significant_moves_found": 8,
  "moves": [
    {
      "time": "2026-05-21 14:05:00",
      "prev_spot": 23625.0,
      "curr_spot": 23700.0,
      "move_points": 75.0,
      "direction": "UP",
      "magnitude_pct": 0.32
    }
  ]
}
```

---

### TOOL 4: `correlate_move_with_indicators` — Indicator State Analysis

**Purpose:** For each move, analyze what indicators aligned BEFORE it

**Function Signature:**
```python
correlate_move_with_indicators(
    candles_json: str,           # Full candle dataset
    move_time: str,              # "2026-05-21 14:05:00"
    lookback_minutes: int = 15   # How far back to examine
) -> JSON
```

**Output Analysis Fields:**
```json
{
  "move_time": "2026-05-21 14:05:00",
  "lookback_minutes": 15,
  "indicator_states": {
    "st15_aligned": "GREEN",          // From v3.1
    "st60_aligned": "GREEN",
    "traffic_light_pattern": ["G", "G", "R", "G", "R", "G"],
    "ema_alignment": "ABOVE_20EMA",
    "adx_trend_strength": "WEAK",
    "vix_level": 17.45,
    "pcr_sentiment": "BEARISH",
    "rsi_14": 65.2,
    "bb_position": "ABOVE_UPPER",
    "macd_signal": "BULLISH",
    "iv_percentile": 45
  }
}
```

---

## WORKFLOW: Using Both Databases

### Scenario: Comprehensive Analysis

```
STEP 1: Query both databases simultaneously
  ├─ query_1min_candles_v31("2026-05-21", "NIFTY")
  │  └─ Returns: 390 candles with 50+ technical indicators
  └─ query_1min_candles_v4("2026-05-21", "NIFTY")
     └─ Returns: 390 candles with cross-TF data + 80+ columns

STEP 2: Detect moves in v3.1 data (primary)
  └─ detect_significant_moves(v31_output, min_move=50)
     └─ Identifies: 8 moves >= 50 pts

STEP 3: Cross-check moves in v4 data (validation)
  └─ If v3.1 shows move at 14:05, verify in v4 data
     └─ Confirms data integrity, identifies any discrepancies

STEP 4: Analyze each move with indicator states
  ├─ For each of 8 moves:
  │  ├─ Extract v3.1 indicator state 15 min BEFORE move
  │  ├─ Extract v4 cross-TF indicator state
  │  └─ Compare (do v3.1 and v4 agree on signals?)
  └─ Return: Aligned + Divergent signals

STEP 5: Pattern discovery
  ├─ Group moves by preceding indicator states
  ├─ Calculate frequency: "ST15 GREEN + PCR BEARISH" preceded 3/8 moves
  ├─ Calculate effectiveness: "When this pattern appears, move happens 75% of the time"
  └─ Rank by confidence score

OUTPUT: JSON report with discovered patterns, cross-referenced across v3.1 + v4
```

---

## DATA QUALITY CHECKS

### Cross-Database Validation
```
For each timestamp:
  ├─ Compare spot prices between v3.1 and v4
  ├─ Verify indicators match (ST15, EMA, ADX, etc.)
  ├─ Flag if data diverges (possible staleness)
  └─ Use v3.1 as primary, v4 as secondary confirmation
```

### Missing Data Handling
```
If v3.1 row is NULL:
  └─ Check v4 for same timestamp
     ├─ If v4 has data: Use v4, flag as "secondary_source"
     ├─ If v4 also NULL: Skip row, note time gap
     └─ Log gap duration for context

If both have data but disagree:
  └─ Calculate percentage difference
     ├─ If <1%: Accept v3.1 (likely rounding)
     ├─ If 1-5%: Flag as "minor_discrepancy", use average
     └─ If >5%: Flag as "data_quality_issue", investigate
```

---

## EXAMPLE: Complete Column Inventory

### From v3.1 (Sample Row)
```json
{
  "timestamp": "2026-05-21 09:16:00",
  "date": "2026-05-21",
  "time": "09:16",
  "index_name": "NIFTY",
  "open_price": 23830.05,
  "high_price": 23850.00,
  "low_price": 23820.00,
  "close_price": 23835.50,
  "spot": 23835.50,
  "prev_close": 23659.00,
  "gap_pct": 0.75,
  "st_15min": "GREEN",
  "st_60min": "GREEN",
  "ema_5_15min": 23832.10,
  "ema_9_15min": 23829.50,
  "ema_20_15min": 23805.20,
  "sma_50_15min": 23810.00,
  "sma_200_15min": 23450.00,
  "adx": 18.50,
  "rsi_14": 62.30,
  "rsi_5": 58.50,
  "india_vix": 17.80,
  "pcr_total": 1.02,
  "pcr_oi": 1.05,
  "pcr_volume": 0.99,
  "traffic_light_15min": "G",
  "traffic_light_pattern_15min": "GGGGGG",
  "traffic_light_signal_15min": "BULLISH",
  "iv_percentile": 45,
  "iv_rank": 42,
  "call_iv": 18.50,
  "put_iv": 19.20,
  "total_volume": 125000,
  "option_volume": 85000,
  "futures_oi": 15000,
  "call_oi": 8500,
  "put_oi": 9200,
  "bb_upper": 23850.00,
  "bb_lower": 23700.00,
  "bb_middle": 23775.00,
  "atr_14": 120.50,
  "macd": 45.20,
  "macd_signal": 42.10,
  "macd_histogram": 3.10,
  "obv": 2500000,
  "cmf": 0.35,
  "market_regime": "SIDEWAYS",
  "session_phase": "OPENING",
  "volatility_regime": "NORMAL",
  "data_quality": "CLEAN",
  "missing_fields": 0,
  "outlier_flag": false
}
```

### From v4 (Additional Cross-TF Data)
```json
{
  // All of v3.1 data PLUS:
  "tf_5min_st": "GREEN",
  "tf_5min_ema_20": 23808.00,
  "tf_5min_adx": 22.10,
  "tf_15min_st": "GREEN",
  "tf_15min_ema_20": 23805.20,
  "tf_15min_adx": 18.50,
  "tf_60min_st": "GREEN",
  "tf_60min_ema_20": 23750.00,
  "tf_60min_adx": 16.80,
  "tf_240min_st": "GREEN",
  "tf_240min_ema_20": 23600.00,
  "tf_240min_adx": 12.30,
  "cross_tf_alignment": {
    "all_tf_green": true,
    "aligned_count": 4,
    "consensus": "STRONG_BULLISH"
  },
  "aggregate_signal": "STRONG_BULLISH",
  "multitf_confidence": 0.92
}
```

---

## Usage Examples

### Example 1: Load Everything from v3.1
```bash
python entry_research_agent.py --date 2026-05-21 --index NIFTY --min-move 50
# Agent will query query_1min_candles_v31 to get all 90+ columns
```

### Example 2: Cross-Check Both Databases
```python
from entry_research_agent import *

# Get v3.1 data
v31_data = query_1min_candles_v31("2026-05-21", "NIFTY")

# Get v4 data for comparison
v4_data = query_1min_candles_v4("2026-05-21", "NIFTY")

# Detect moves (using primary v3.1)
moves = detect_significant_moves(v31_data, min_move=50)

# For each move, analyze with full indicator state
for move in moves:
    indicators = correlate_move_with_indicators(v31_data, move["time"])
    # Cross-check with v4 if needed
    indicators_v4 = correlate_move_with_indicators(v4_data, move["time"])
```

### Example 3: Specific Column Investigation
```python
# Need to check cross-TF alignment?
# Use v4:
v4 = query_1min_candles_v4("2026-05-21", "NIFTY")
for candle in v4["candles"]:
    if candle["cross_tf_alignment"]["all_tf_green"]:
        print(f"At {candle['timestamp']}: All timeframes bullish")
```

---

## Performance Notes

| Metric | v3.1 | v4 |
|--------|------|-----|
| **Database Size** | ~500MB | ~1GB+ |
| **Query Time (1 day)** | 100-500ms | 200-1000ms |
| **Rows per Day** | 390-400 | 390-400 |
| **Columns** | 50+ | 80+ (with cross-TF) |
| **Data Staleness** | Current (updated live) | Refreshed every 5 min |

---

## Troubleshooting

### Q: Getting null values for indicators?
**A:** Check `data_quality` field. If "PARTIAL" or "GAP", some indicators not calculated. Cross-check with other database.

### Q: v3.1 and v4 disagree on ST15?
**A:** Possible timing lag (v4 aggregates from multiple sources). Use v3.1 as primary.

### Q: Query returns 0 rows?
**A:** Verify:
1. Date format is YYYY-MM-DD
2. Index name is exactly "NIFTY" or "SENSEX" (case-sensitive)
3. Both databases are live (check file timestamps)

### Q: Need ALL columns including Greeks?
**A:** Use v3.1 with no limit:
```python
query_1min_candles_v31("2026-05-21", "NIFTY", limit=None)
```

---

## Summary

**Entry Research Agent has unrestricted access to:**
- ✅ **Varaha v3.1:** 50+ technical indicators, complete OHLC, Greeks, IV
- ✅ **Varaha v4:** Cross-timeframe correlations, multi-TF aggregator data
- ✅ **Both databases:** Full row-level data (no sampling)
- ✅ **All columns:** No filtering—agent can explore entire schema

This enables comprehensive pattern discovery by testing indicators across granular historical data.
