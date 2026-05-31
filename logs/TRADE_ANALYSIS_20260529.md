# Trade Analysis — TRD-20260529091640 (29 May 2026)

**Trade:** IRON_BUTTERFLY | **Entered:** 09:16 IST | **Status:** OPEN  
**Spot at entry:** 23,971 | **ATM:** 23,950 | **Wings:** 150 pts | **Net credit:** ₹125.30

---

## 1. Market at Entry

```
NIFTY opened gap-down:
  Open:   23,902     Prev Close: 23,907     Gap: -5 pts (-0.021%)
  VIX:    14.9       ADX: 12.77             Spot at 09:16:  23,971
```

The gap-down was marginal (-0.02%) — barely a gap. The immediate bounce took NIFTY
from 23,902 to 23,972 within the first minute (+70 pts), creating the conflict
between trend direction and price action that drove this trade.

---

## 2. Decision Chain (agent-by-agent from logs)

### STEP 1 + 2: Trend & Traffic Light — CONFLICT

```
Trend scoring (entry_check.py, 09:16):
  Price below all 5 EMAs (5, 20, 50, 100, 200)
  → BEARISH, confidence=90%, score=-1.25
  Source: 60min EMA files (⌛ gap-down not yet reflected)

Traffic Light (entry_check.py, 09:16):
  All 6 timeframes GREEN
  1440m: GREEN  (yesterday close 23907 > open 23880)
  240m:  GREEN  (yesterday's last 4H candle)
  60m:   GREEN  (yesterday's last hour)
  30m:   GREEN  (yesterday's last 30m)
  15m:   GREEN  (yesterday's last 15m)
  5m:    GREEN  (yesterday's last 5m)
  
  → Pattern: MOMENTUM_PEAK (all 6 TFs green, bullish chaos pattern)
  → Signal: BULLISH, confidence=85%, score=+6.3

Why all green with only 1 minute of today's data?
  At 09:16, the market had been open for 60 seconds. Only 1 bar (09:15)
  existed in today's data. ALL multi-TF candles (5m, 15m, 30m, 60m,
  240m, 1440m) were built from YESTERDAY's bars (May 28).
  
  May 28 daily: open=23880, close=23907 (+27 pts, GREEN)
  The close was near the session high → all lower TFs also GREEN.
  
  The gap (open < prev close, RED) was captured separately and applied
  as a gap boost (+0.3 score, +10 confidence) but does not change the
  TF candle colors. TF candles are built by aggregating 1-min bars —
  a candle "completes" only when enough bars exist for that timeframe.
  At 09:16, no new candles had completed, so ALL 6 colors came from
  yesterday's completed candles.
  
  This is a "morning cold start" problem:
  → 5m  candle updates at 09:20 (needs 5 bars)
  → 15m candle updates at 09:30
  → 30m candle updates at 09:45
  → 60m candle updates at 10:15
  → 240m, 1440m take hours/days
```

### STEP 3: combine_entry_scores — deterministic conflict

```
Trend: BEARISH (90%)  vs  TL: BULLISH (85%)

→ CONFLICT → signal=NEUTRAL, go=NO-GO, multiplier=0.3x
→ Reason: "CONFLICT: Trend BEARISH vs TL BULLISH"

Normal flow: no trade enters. System waits for consensus.
```

### STEP 4: Research Override (ChromaDB) — OVERRIDES the gate

```
Research patterns loaded from ChromaDB (5 patterns):
  ADX Momentum Spike, PCR Mean Reversion Signal,
  VIX Spike Alert, Normal VIX Range Pattern, RSI Mean Reversion

Direction consensus:
  BULLISH=0   BEARISH=0   NEUTRAL=5
  → Neutral patterns ≥ 50% → consensus = NEUTRAL

Override logic (e2e_chain.py:590-607):
  "trend=BEARISH, TL=BULLISH → conflict → sideways market
   → force BOTH gates to GO → take IRON_BUTTERFLY at 40% confidence"

  NOT_UP  → overridden from NO-GO to GO (confidence: 40%)
  NOT_DOWN → overridden from NO-GO to GO (confidence: 40%)

Log entry:
  "Research Override: Research NEUTRAL → sideways market
   (trend=BEARISH, TL=BULLISH, conflict) → IRON_BUTTERFLY"
```

This is the critical decision: historical gap-opening patterns say "when trend
and TL conflict, the market is actually range-bound, not trending. Trade the
range, not the direction."

### STEP 5: Regime Agent

```
VIX=14.9 (< 18, no caution needed)
ADX=12.77 (< 25, sideways regime confirmed)
→ recommendation: "enter"
→ regime: "sideways"
```

ADX at 12.77 confirms the market has no trend. This validates the Research
Override's decision: in a trendless market, Iron Butterfly is the right play.

### STEP 6: Strategy Agent — picks IRON_BUTTERFLY

```
Both NOT_UP and NOT_DOWN are GO → IRON_BUTTERFLY

Parameter optimization from regime data:
  VIX=14.9 < 15  → wing_width = 150   (narrow wings — low vol)
  VIX < 18       → sl_pct     = 0.25  (standard SL, no urgency)
  ADX=12.77 < 20 → tp_pct     = 0.55  (let premium decay fully in chop)

Agent output:
  {"strategy_type": "IRON_BUTTERFLY",
   "wing_width": 150, "sl_pct": 0.25, "tp_pct": 0.55}

Agent reasoning (from log):
  "Both NOT_UP and NOT_DOWN triggered (overridden).
   VIX 14.9 < 15 → narrow wings (150).
   ADX 12.77 < 20 → sideways regime, let premium decay fully (tp 0.55).
   VIX < 18 → default SL (0.25)."
```

### STEP 7: Contract Agent

```
ATM strike: 23950

Resolved contracts from DuckDB option_snapshots:
  SELL  23950CE  tsym=NIFTY02JUN26C23950  LTP=170.10
  SELL  23950PE  tsym=NIFTY02JUN26P23950  LTP=118.85
  BUY   23800PE  tsym=NIFTY02JUN26P23800  LTP=65.80   (wing below: 23950-150)
  BUY   24100CE  tsym=NIFTY02JUN26C24100  LTP=97.85   (wing above: 23950+150)
```

### STEP 8: Execution Agent

```
Premium calculation:
  SELL premiums: 170.10 + 118.85 = 288.95
  BUY  premiums:  65.80 +  97.85 = 163.65
  NET CREDIT:    288.95 - 163.65 = 125.30  ✓ (positive)

SL/TP on SELL legs (calculated as fill_price × (1±pct)):
  CE (170.10):  SL=212.62 (+25%)   TP=76.54 (-55%)
  PE (118.85):  SL=148.56 (+25%)   TP=53.48 (-55%)

Max risk per leg: wing_width - net_credit = 150 - 125.30 = ₹24.70
Max total risk: ₹24.70 × 65 (lot size) = ₹1,605.50

Orders placed (PAPER, SIM):
  ORD-20260529-0033  SELL 23950CE @170.10
  ORD-20260529-0034  SELL 23950PE @118.85
  ORD-20260529-0035  BUY  23800PE @65.80
  ORD-20260529-0036  BUY  24100CE @97.85
  All 4 FILLED | Mode: PAPER
```

---

## 3. Traffic Light Cold Start Problem — Explained

**Why all 6 TFs were GREEN with only 1 minute of today's data:**

At 09:16 IST, the market had been open for exactly 60 seconds. The Redis queue had:

```
526 total bars:
  → 1 bar from today      (09:15)
  → 525 bars from yesterday (May 28, 15:07-15:10)
```

The `get_live_candles()` function builds timeframe candles by bucketing 1-min bars:

| TF | Required bars | Bars from today | Source of color |
|----|--------------|----------------|-----------------|
| 5m | 5 | 1 incomplete | Yesterday's last completed 5m candle |
| 15m | 15 | 1 incomplete | Yesterday's last completed 15m candle |
| 30m | 30 | 1 incomplete | Yesterday's last completed 30m candle |
| 60m | 60 | 1 incomplete | Yesterday's last completed 60m candle |
| 240m | 240 | 1 incomplete | Yesterday's last completed 240m candle |
| 1440m | 375 | 1 incomplete | Yesterday's full daily candle |

Yesterday (May 28) daily: open=23880, close=23907 → **GREEN** (+27 pts, near high)

Since the close was near the session high with positive momentum, ALL lower TFs
(240m, 60m, 30m, 15m, 5m) were also GREEN. The system doesn't mix yesterday's
candles with today's incomplete bars — it uses the most recent completed candle
for each TF.

The gap direction (RED, -0.021%) was captured separately and applied as a
gap adjustment (+0.3 score, +10 confidence) but doesn't change TF colors.

**When do TFs start reflecting today's reality?**

```
09:20 → 5m candle completes (from 09:15-09:19 bars)
09:30 → 15m candle completes
09:45 → 30m candle completes
10:15 → 60m candle completes
13:15 → 240m candle completes (from 09:15 bars onward)
Next day → 1440m candle completes
```

This is why at 09:45 the pattern shifted from MOMENTUM_PEAK → DEAD_CAT_BOUNCE,
and by 10:15 settled into STRONG_BEAR_CONTINUATION. The TFs gradually "woke up"
as new candles completed with today's gap-down reality.

---

## 4. Assessment

### What the system got right
- Recognised the trend/TL conflict as a range-bound signal
- ADX=12.77 confirmed no trend → Iron Butterfly appropriate
- Tight wings (150) appropriate for low VIX
- Delay on TP (55%) correct for chop: let time decay work

### What was riskly
- Confidence=40% is low conviction — borderline trade
- Entered at 09:16 (first minute of the session) — opening volatility
- Traffic light was blind: all TF colors from yesterday, not today
- NIFTY continued ~200 pts below entry (23800PE wing at risk)

### Post-entry: system response
- Only 1 trade today (iron_butterfly_only mode: 1 active trade max)
- Position manager has been monitoring since 09:16
- No TSL adjustments, morph actions, or MTM checks triggered
- NIFTY at ~15:00 = 23,765 → 206 pts below entry → wing breach zone approaching
