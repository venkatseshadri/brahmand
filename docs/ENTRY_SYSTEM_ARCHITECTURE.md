# Entry Check System — Complete Architecture

## 1. System Overview

The entry gate has **3 checkpoints** that vote on direction, and **2 modifiers** that scale conviction:

```
            ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
            │   TREND      │  │ TRAFFIC LIGHT│  │   FEEDBACK   │
            │  (EMA files) │  │  (Redis OHLC)│  │  (ChromaDB)  │
            └──────┬───────┘  └──────┬───────┘  └──────┬───────┘
                   │                 │                  │
                   ▼                 ▼                  ▼
            ┌────────────────────────────────────────────────┐
            │          combine_entry_scores()               │
            │  Direction = weighted vote(Trend, TL)         │
            │  Conviction = (T+TL) × Feedback(confirm/warn) │
            │             × PriceLocation(multiplier)       │
            └─────────────────────┬──────────────────────────┘
                                  │
                                  ▼
                    GO(BEARISH/BULLISH/NEUTRAL)
                            or NO-GO
```

### Data flow at runtime (every 5 minutes)

```
cron → entry_check_daemon.py
        │
        ├─ score_trend_redis()          → filesystem EMA files
        ├─ score_traffic_light_redis()  → Redis OHLCV queue
        ├─ EntrySignalBroker.get_full_context()
        │   ├─ DuckDB latest candle     → vix, pcr_total, adx, spot
        │   └─ EntryAgent.entry_check() → ChromaDB pattern matching
        │       └─ trigger_conditions (ADX, PCR, VIX, RSI)
        └─ combine_entry_scores()       → GO/NO-GO + confidence
```

---

## 2. Checkpoint 1: Trend (EMA)

**Source:** Filesystem — `brahmand/data/ema_state/{60min,1min}/ema_*.json`

| Component | Description |
|-----------|-------------|
| **Indicators** | EMA(5), EMA(20), EMA(50), EMA(100), EMA(200) |
| **Logic** | Weighted slope + alignment score. Price relative to EMA bands. |
| **Output** | `{signal: BULLISH/BEARISH/NEUTRAL, confidence: 0-100, score: float}` |
| **Primary frame** | 60-minute (falls back to 1-min if stale) |
| **Weights (configurable)** | ema5=0.60, ema20=0.30, ema50=0.25, ema100=0.00, ema200=0.00 |

**What it detects:**
- Trend direction (EMA slope, price position relative to EMAs)
- Trend strength (alignment across multiple EMAs)
- Trend changes (crossover signals)

---

## 3. Checkpoint 2: Traffic Light (Candlestick)

**Source:** Redis — `v3_ohlcv_queue_NIFTY`, `prev_close_NIFTY`

| Component | Description |
|-----------|-------------|
| **Indicators** | OHLC, gap direction, wick ratios, candle color sequences |
| **Logic** | Last 5 candles classified as G/R. Pattern matching against known sequences (GGGRRR, etc.) |
| **Output** | `{signal: BULLISH/BEARISH/NEUTRAL, confidence: 0-100, score: float, pattern: string}` |
| **Pattern library** | Gap-open reversal, STRONG_BEAR_CONTINUATION, STRONG_BULL_CONTINUATION, etc. |

**What it detects:**
- Gap direction (previous close vs current open)
- Momentum from last 5 candles (e.g., 4 red → bearish)
- Wick ratios (long upper wick = selling pressure)
- Candle size (large red = conviction)

---

## 4. Checkpoint 3: Feedback (Research Patterns)

### 4.1 Nightly Research Pipeline

```
23:00 cron → nightly_research_scheduler.py
              │
              ├─ Phase 1: 5 Research Agents discover patterns
              │   ├─ SuperTrend agent (adx, st_5min_dir, st_15min_dir)
              │   ├─ PCR agent (pcr_total)
              │   ├─ EMA agent (rsi, ema_5, ema_20) ← weight=0 (excluded)
              │   ├─ Volatility agent (india_vix)
              │   └─ Volume agent (vwap, open_range, oi_concentration, intraday_range)
              │
              ├─ Phase 2: Backtest against historical data (May 4-21)
              │   └─ Win rate, avg move, consistency → approve/reject
              │
              ├─ Phase 3: Store approved patterns in ChromaDB
              │   └─ /tmp/chroma_research/discovered_patterns
              │
              └─ Phase 4: Telegram summary
```

### 4.2 Active Patterns in ChromaDB

| Pattern ID | Name | Family | Trigger | Predicts | Weight |
|------------|------|--------|---------|----------|--------|
| ST_ADX_002 | ADX Momentum Spike | supertrend | ADX ≥ 30 | BEARISH | 0.87 |
| PCR_MR_001 | PCR Mean Reversion | pcr | PCR < 0.85 or > 1.15 | BEARISH | 0.72 |
| VOL_VIX_001 | VIX Spike Alert | volatility | VIX ≥ 18.0 | BEARISH | 0.68 |
| VOL_VIX_002 | Normal VIX Range | volatility | VIX 17.0-19.0 | NEUTRAL | 0.68 |
| EMA_RSI_002 | RSI Mean Reversion | ema | RSI < 30 or > 70 | NEUTRAL | **0.0** (excluded) |

**Why EMA is excluded:** The EMA family double-counts with the Trend checkpoint, which already uses EMA(5/20/50/100/200). Weight set to 0.0, RSI Mean Reversion never contributes to matching patterns.

### 4.3 Feedback Logic (Option A: Bearish Confirmation Gate)

- All active patterns detect **market stress/pressure** (ADX spike, PCR extreme, VIX elevated)
- Patterns are matched via `trigger_conditions` from ChromaDB against current candle data
- Result is a **pattern count** (0-4), not a weighted confidence score

| Pattern Count | BEARISH signal | BULLISH signal | NEUTRAL signal |
|:---:|---|---|---|
| 0-1 | No adjustment | No adjustment | No adjustment |
| 2 | **+16%** (confirm) | **-24%** (warn) | No adjustment |
| 3 | **+24%** (confirm) | **-35%** (warn) | -10% (lean bearish) |
| 4 | **+32%** (confirm) | **-35%** (warn, capped) | -10% (lean bearish) |

---

## 5. Modifier 1: VIX + Raw PCR

Same source as Feedback (`market_ctx`), but these are **raw market state** adjustments, not pattern-driven:

| Condition | Effect |
|-----------|--------|
| VIX > 20 | Confidence reduced by up to 15% (scales 20→30) |
| PCR ≥ 1.15 AND BULLISH | -10% (high puts = bearish conviction conflict) |
| PCR ≤ 0.85 AND BEARISH | -10% (low puts = low bearish conviction conflict) |

---

## 6. Modifier 2: Price Location Score (PLANNED)

Uses DuckDB columns for SMC, Pivots, Fibs, IV Rank, Greeks, Max Pain.

| Direction | Favorable | Unfavorable |
|-----------|-----------|-------------|
| BEARISH | Near resistance (pivot_r1, cluster_res, OB, fib_618+) | Near support or mid-air |
| BULLISH | Near support (pivot_s1, cluster_sup, OB, fib_382-) | Near resistance or mid-air |

**Score formula:**
```
LocationMultiplier = distance_score × zone_quality × iv_context
  0.95-1.05 at zone, 0.85 near zone, 0.60 far from zone
```

---

## 7. Full Signal Families Map

### 7.1 Families used by at least one checkpoint

| Family | Trend | Traffic Light | Feedback | Location (planned) |
|--------|:---:|:---:|:---:|:---:|
| **EMA** (5/20/50/100/200) | ✓ | | | |
| **OHLCV** (open/high/low/close/prev_close) | close | ✓ all | spot | |
| **SuperTrend** (st_5min, st_15min) | | | ✓ | |
| **ADX** | | | ✓ | |
| **PCR** (pcr_total) | | | ✓ (pattern + raw) | |
| **VIX** (india_vix) | | | ✓ (pattern + raw) | |
| **SMC** (ob_zone, fvg, swing, structure, liquidity) | | | | ✓ |
| **Pivots** (pp, r1-r3, s1-s3) | | | | ✓ |
| **Pivot Clusters** (cluster_support/resistance) | | | | ✓ |
| **Fibonacci** (fib_382, fib_50, fib_618) | | | | ✓ |
| **IV Analysis** (iv_current, iv_rank, iv_regime) | | | | ✓ |
| **Greeks** (agg_delta, agg_gamma) | | | | ✓ |
| **Max Pain** (max_pain_strike) | | | | ✓ |

### 7.2 Families NOT used yet (available for future research)

| Family | Columns Available | Potential Value |
|--------|------------------|-----------------|
| MACD (v4) | macd, signal, histogram | Momentum divergence |
| CCI (v4) | cci | Overbought/oversold cycles |
| Bollinger Bands | bb_pct_b, bb_width, bb_upper/lower | Squeeze → expansion |
| OBV/CMF (v4) | obv, cmf | Volume confirmation |
| ATR | atr | Normalize targets |
| DI+/DI- (v4) | di_plus, di_minus | Directional bias |
| SMAs (v4) | sma20, sma50, sma200 | Long-term trend |
| Historical Vol | hv_20, hv_60 | HV/IV spread |
| OI skew | oi_skew | Option sentiment |
| Expiry data | days_to_weekly, expiry dates | Time decay pressure |
| Session metrics | session_phase, open_to_current_pct | Time-of-day bias |
| Call/Put OI conc | call_oi_concentration, put_oi_concentration | Resistance/support zones from options |

---

## 8. Exit Condition Mapping → Risk Agent

### 8.1 Indicators that signal "BOOK PROFITS"

| Signal | Source | Action | Confidence |
|--------|--------|--------|------------|
| **Price at resistance zone** (bearish entry) | SMC, Pivots, Fibs, Clusters | Exit 50%, move SL to entry | HIGH |
| **Price at support zone** (bullish entry) | SMC, Pivots, Fibs, Clusters | Exit 50%, move SL to entry | HIGH |
| **MACD bearish divergence on BEARISH trade** | v4 DuckDB (macd_histogram) | Momentum fading — book 100% | MEDIUM |
| **Structure break** (SMC structure_type flips) | DuckDB SMC (structure_confirmed) | Trade thesis broken — exit 100% | HIGH |
| **PCR reversal** (PCR crosses back inside 0.85-1.15) | DuckDB (pcr_total) | Sentiment neutralizing — book 50% | MEDIUM |
| **IV rank drops below 20** | DuckDB (iv_rank) | No premium left — close day before expiry | MEDIUM |
| **Leg 1 at 50% profit** (spread) | P&L tracker | Move SL to entry — free trade | HIGH |
| **Liquidity swept at target zone** | DuckDB (liquidity_swept) | Smart money took liquidity — reversal likely | HIGH |

### 8.2 Indicators that signal "TIGHTEN STOP LOSS"

| Signal | Source | Action | Confidence |
|--------|--------|--------|------------|
| **Approaching resistance** (bearish) | Pivots, Fibs, Clusters | SL to 20pts above next zone | HIGH |
| **Approaching support** (bullish) | Pivots, Fibs, Clusters | SL to 20pts below next zone | HIGH |
| **Gamma spike** (agg_gamma > threshold) | DuckDB (agg_gamma) | Pin risk — tight SL or exit | MEDIUM |
| **VIX spike > 25** on bearish trade | DuckDB (india_vix) | High vol supports trend — SL wider, don't tighten | LOW (opposite action) |
| **ADX weakening** (ADX < 25) | DuckDB (adx) | Trend losing strength — tighten SL | MEDIUM |
| **Volume divergence** (OBV vs price) | v4 DuckDB (obv, cmf) | Smart money exiting — tighten | MEDIUM |

### 8.3 Indicators that signal "ADD TO TRADE"

| Signal | Source | Action | Confidence |
|--------|--------|--------|------------|
| **Pullback to support** (bullish) + green candle | SMC + TL + Trend | Add 0.5x position | MEDIUM |
| **Pullback to resistance** (bearish) + red candle | SMC + TL + Trend | Add 0.5x position | MEDIUM |
| **Feedback patterns increase** (2→4 matching) | EntryAgent | Trend strengthening — add | LOW (needs research) |
| **IV rank rises while in trade** | DuckDB (iv_rank) | Better premium for selling — add 0.5x | MEDIUM |

### 8.4 Indicators that signal "EXIT IMMEDIATELY"

| Signal | Source | Action | Confidence |
|--------|--------|--------|------------|
| **Trend flips opposite** (BEARISH → BULLISH on short) | score_trend_redis | Exit 100% | HIGH |
| **Traffic Light flips opposite** + gap | score_traffic_light_redis | Exit 100% | HIGH |
| **SMC structure confirmed break** | DuckDB (structure_confirmed) | Exit 100% — trend broken | HIGH |
| **PCR extreme reversal** (>1.25 → <0.85 or vice versa) | DuckDB (pcr_total) | Exit 100% — sentiment flipped | MEDIUM |
| **FVG fill** (price fills a fair value gap) | DuckDB (fvg_high, fvg_low) | Reversal zone — exit or tight SL | MEDIUM |
| **L1 invariant violated** (max drawdown, position size) | CFO Auditor | Exit 100% — hard risk limit | HIGH |

---

## 9. Risk Agent Architecture (Proposed)

```
             ┌─────────────────┐
             │   ENTRY GATE    │
             │  GO: SELL_CALL  │
             │  SL: 100 pts    │
             │  Target: 80 pts │
             └───────┬─────────┘
                     │
                     ▼
     ┌──────────────────────────────────┐
     │         RISK AGENT               │
     │  (runs every 1-min during trade) │
     │                                  │
     │  Inputs:                         │
     │   • DuckDB live candle           │
     │   • Trade state (entry price, SL,│
     │     target, current P&L)         │
     │   • SMC zones, IV, Greeks, PCR   │
     │                                  │
     │  Outputs (3 actions):            │
     │   📈 BOOK_PROFITS (partial/close)│
     │   📉 TIGHTEN_SL (new SL price)   │
     │   🚫 EXIT (market close)        │
     └──────────────────────────────────┘
```

### Risk Agent Triggers (priority-ordered)

| Priority | Trigger | Action | Threshold |
|----------|---------|--------|-----------|
| **1** | Trend flips opposite | EXIT | signal != entry_direction |
| **2** | SMC structure break | EXIT | structure_confirmed flip |
| **3** | PCR extreme reversal | EXIT | cross 0.85 or 1.15 boundary |
| **4** | Price at resistance (bearish) | BOOK 50%, SL→entry | within 15pts of strongest zone |
| **5** | Price at support (bullish) | BOOK 50%, SL→entry | within 15pts of strongest zone |
| **6** | 50% profit on spread | TIGHTEN SL→entry | P&L ≥ 50% of max |
| **7** | IV rank drops < 20 | TIGHTEN SL | iv_rank < 20 |
| **8** | ADX weakening | TIGHTEN SL | ADX < 25 from > 30 |
| **9** | Max pain magnet | TIGHTEN SL | price within 30pts of max_pain |

---

## 10. Integration Points

### 10.1 Price Location Score → Entry Check

Add to `EntrySignalBroker.get_full_context()`:
```python
location_score = score_price_location(spot, predicted_direction, candle)
market_ctx["location_score"] = location_score
```

Apply in `combine_entry_scores()`:
```python
if market_ctx and "location_score" in market_ctx:
    confidence = int(confidence * market_ctx["location_score"])
```

### 10.2 Risk Agent → Running Trade Management

New agent: `brahmand/risk_agent.py`
- Called by `kickoff.py` or `position_manager.py` on a 1-minute cadence
- Reads active trade state from `antariksh/logs/entry_check_latest.json`
- Queries DuckDB for current candle + SMC/Greeks/IV data
- Emits: EXIT, BOOK_PARTIAL, TIGHTEN_SL, HOLD
- Sends Telegram alerts on action

### 10.3 Missing Patterns for Research Agents

| New Agent | Indicators | Expected Patterns |
|-----------|-----------|-------------------|
| **SMC Research Agent** | ob_zone, fvg, swing_high/low, liquidity_swept, structure_type | Sweep-reversal, FVG-fill, OB-rejection |
| **Greeks Research Agent** | agg_delta, agg_gamma, max_pain_strike | Gamma pin, delta divergence, max-pain magnet |
| **IV Research Agent** | iv_current, iv_rank, iv_regime, iv_52w_high/low, hv_20 | IV rank regime shift, HV/IV spread convergence |
