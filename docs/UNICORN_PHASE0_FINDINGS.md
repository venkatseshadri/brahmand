# UNICORN Phase 0 Findings — Field Inventory & Verdict Audit

**Date:** 2026-06-03  
**Source:** `antariksh/tools/entry_tools.py::query_all_families("NIFTY")`  
**Frozen fixture:** `tests/unicorn/fixtures/raw_data_sample.json`

## Pre-requisite Bug Fix

`entry_tools.py` imported `json as _json` and `datetime as _dt` but used bare `json.` and `datetime.` in function bodies. Fixed: 14 `json.` → `_json.`, 9 `datetime.now()` → `_dt.now()`, 1 `json.JSONDecodeError` → `_json.JSONDecodeError`.

## Verdict: 7 core families are RAW, traffic_light is SCORED

The 7 design document families return **pure raw/indicator data** with zero verdict tokens. The 8th family (`traffic_light`) — not in the design doc — returns **scored verdicts** that MUST be stripped by `unicorn_raw_query`.

---

## Field Inventory

### 1. TREND (raw — no verdicts)
```
family, index, timestamp, timeframes
  timeframes/5m,15m,30m,60m,240m,1440m: [adx, candle, di_minus, di_plus, sma20, sma50, sma_position, st_consensus]
  timeframes/1m_v3.1: [adx, ema20, ema5, ema50, ema_position, spot, st_15m_direction, st_5m_direction, st_consensus, st_direction]
```
Note: `sma_position` is pre-computed (bullish/bearish/neutral) from sma20 vs sma50. Not a trading verdict — it's a positional indicator.

### 2. MOMENTUM (raw — no verdicts)
```
family, index, timestamp, timeframes
  timeframes/5m-1440m: [cci, macd, macd_histogram, rsi, rsi_zone]
  timeframes/1m_v3.1: [bb_pct_b, bb_width, rsi, rsi_zone]
```
`rsi_zone` is "oversold", "overbought", "neutral" — raw zone classification.

### 3. VOLATILITY (raw — no verdicts)
```
family, index, timestamp, timeframes
  timeframes/5m-1440m: [atr, atr_pct, bb_lower, bb_upper]
  timeframes/1m_v3.1: [atr, atr_pct, hv_20, hv_60, iv_current, iv_rank]
```

### 4. VOLUME (raw — no verdicts)
```
family, index, timestamp, indicators
  indicators/5m,15m,30m: [cmf, cmf_signal, obv, volume]
```
`cmf_signal` is "accumulation" / "distribution" / "neutral" — raw classification.

### 5. OPTIONS (raw — no verdicts)
```
family, index, timestamp, indicators: [
  call_oi_concentration, greeks (delta,gamma,vega,theta), iv_current, iv_percentile,
  iv_regime, max_pain_strike, oi_price_signal, oi_skew, pcr_atm, pcr_signal,
  pcr_total, put_oi_concentration, sentiment
]
```
- `oi_price_signal`: "bullish" / "bearish" — OI-price divergence classification
- `pcr_signal`, `sentiment`, `iv_regime`: directional classifications
- **NOT verdicts** — these are raw computed classifications an agent can interpret.

### 6. FLOW (raw — no verdicts)
```
family, index, timestamp, indicators: [
  fii_data_note, fii_fut_5d_change, pcr_change, pcr_total
]
```

### 7. MACRO (raw — no verdicts)
```
family, index, timestamp, indicators: [
  banknifty_nifty_ratio, banknifty_nifty_ratio_note, distance_to_pivot_pct,
  gap_pct, gift_premium, gift_premium_note, open_price, open_to_current_pct,
  pivot_pp, pivot_r1, pivot_s1, prev_close, prev_day_high, prev_day_low,
  prev_day_range, session_phase, spot, vix, vix_change, vix_level
]
```
`session_phase` is "preopen", "open_drive", "mid_session", "late", "closing" — time-based, not verdict.

---

## TRAFFIC_LIGHT (SCORED — MUST BE STRIPPED)

The 8th family returned by `query_all_families` is NOT in the 7-family design. It returns:
```
family, index, timestamp, candles, pattern, confidence, summary, exhaustion, reversal_signal
  candles/5m-1440m: [body_pct, color, lower_wick_pct, range_pct, upper_wick_pct]
  pattern: "DEAD_CAT_BOUNCE" (SCORED)
  confidence: 60 (SCORED)
  summary: {daily: RED, four_hour: RED, ... green_count: 4, red_count: 2, story: "..."} (SCORED)
  exhaustion: False (SCORED)
  reversal_signal: True (SCORED)
```

### Verdict fields to strip:
| Field | Type | Reason |
|-------|------|--------|
| `pattern` | string | Scored price action pattern |
| `confidence` | int | Scored confidence level |
| `summary` | dict | Color-coded TF verdicts (RED/GREEN) |
| `exhaustion` | bool | Scored exhaustion detection |
| `reversal_signal` | bool | Scored reversal detection |

### Fields to KEEP (raw):
| Field | Type | Reason |
|-------|------|--------|
| `candles` | dict | Per-TF candle structure (body_pct, color, wick_pct) — raw data |

---

## Action Items for unicorn_raw_query.py

1. **Call 7 families individually** (trend, momentum, volatility, volume, options, flow, macro) — NOT `query_all_families` since it includes `traffic_light`.
2. **Do NOT call `query_traffic_light`** — it returns scored verdicts.
3. **Include `candles` data from traffic_light** — the per-TF candle structure is raw and useful.
4. Return flat dict with 7 top-level keys matching the design doc schema.
5. 60-second cache (first call expensive, subsequent calls hit cache).
