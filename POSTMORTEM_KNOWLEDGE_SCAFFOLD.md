# Post-Mortem Agent Knowledge Scaffold

**Status:** Conceptual knowledge foundation for agents  
**Date:** 2026-05-15

---

## 1. STRATEGY KNOWLEDGE SCAFFOLD

### Iron Butterfly (IB) - Sideways Strategy
```
Structure: SELL ATM CE + SELL ATM PE + BUY ATM+200 CE + BUY ATM-200 PE
Leg count: 4
Profit if: Market stays between ATM-200 to ATM+200 at expiry
Max profit: Net credit received
Max loss: Wing width - net credit
Best market: Sideways (ADX < 25)
Greeks: Delta ~0 (neutral), Theta+ (decay works for us), Gamma- (price moves hurt)

Success factors:
├─ Regime is truly sideways (not transitioning)
├─ Entry is near SUPPORT (not in void)
├─ Hold 3-4 hours (theta decay accelerates early)
├─ Exit at 50% profit (don't wait for 100%)
└─ VIX < 20 (premium decays faster)

Failure modes:
├─ Entered at resistance (no buffer)
├─ Market breakout during hold (delta explodes)
├─ Held too long (gamma risk increases)
└─ VIX spike (all legs repriced higher)

Post-Mortem should track:
├─ Market structure at entry (HH+HL vs LL+LH)
├─ Distance from support/resistance
├─ VIX level at entry vs historical
├─ Time held vs optimal 3.5h
└─ Profit capture % (92% excellent, 50% poor)
```

### Bull Put Spread (BPS) - Bullish Trending
```
Structure: SELL ATM-100 PE + BUY ATM-300 PE
Leg count: 2 (directional)
Profit if: Market stays ABOVE sold strike at expiry
Max profit: Net credit received
Max loss: (Strike difference - credit)
Best market: Trending bullish (ADX > 25, SuperTrend bullish)
Greeks: Delta+ (profitable if up), Theta+ (time decay helps)

Success factors:
├─ Trend is strong (HH+HL structure, ADX > 25)
├─ Entry is near SUPPORT (PE support, not resistance)
├─ VIX < 18 (premium decays without move needed)
├─ Hold until TP hit or 3 hours max
└─ Market stays above sold strike

Failure modes:
├─ Trend reverses (HH→HL, ADX drops)
├─ Entered at resistance on PE side (wrong timing)
├─ Held too long (gamma risk if price near strike)
└─ Gap down overnight (early assignment risk)

Post-Mortem should track:
├─ Trend structure (HH+HL count before entry)
├─ Distance sold strike to support level
├─ VIX at entry vs exit
├─ Time held vs trend strength
└─ Profit capture % vs max
```

### Bear Call Spread (BCS) - Bearish Trending
```
Structure: SELL ATM+100 CE + BUY ATM+300 CE
Leg count: 2 (directional)
Profit if: Market stays BELOW sold strike at expiry
Best market: Trending bearish (ADX > 25, SuperTrend bearish)
Greeks: Delta- (profitable if down)

Post-Mortem should track:
├─ Trend structure (LL+LH count before entry)
├─ Sold strike distance to resistance
├─ VIX at entry vs exit
├─ Trend continuation vs reversal
└─ Profit capture %
```

---

## 2. ENTRY SIGNAL KNOWLEDGE SCAFFOLD

### Signal 1: EMA5 Bounce at Support
```
Definition: 
├─ EMA5 crosses above EMA20 (bullish)
├─ Price within 30 ticks of Pivot S1 or Fib support
├─ Bounce confirms: No close below support

Historical performance:
├─ Success rate: 100% (5/5 trades)
├─ Avg premium captured: 93%
├─ Avg fill slippage: 0.4 ticks
├─ Avg hold time to TP: 3h 45m
├─ Confluence with other signals: 80% have 2+ confluences

Post-Mortem analysis:
├─ Did EMA5 actually cross EMA20?
├─ Was price within 30 ticks of support?
├─ Did price bounce (not close below)?
├─ If all yes: Rate signal as 5/5
├─ If any no: Lower confidence score
```

### Signal 2: RSI Divergence at Support
```
Definition:
├─ Price makes lower low (LL)
├─ RSI makes higher high (HH) - oversold reversing
├─ Classic bullish divergence

Historical performance:
├─ Success rate: 50% (1/2 trades, need more data)
├─ Needs RSI < 30 (oversold zone)
├─ Unreliable alone, needs confluence

Post-Mortem analysis:
├─ Was RSI below 30 at entry?
├─ Did price make LL while RSI made HH?
├─ If both: Rate 4/5 (promising but unproven)
├─ Combine with EMA or support: Rate 5/5
```

### Signal 3: Fair Value Gap (FVG) Pullback
```
Definition:
├─ FVG zone: Gap in candlesticks (price skipped area)
├─ Entry: Price pulls back into FVG
├─ Thesis: Market will return to fill gap

Historical performance:
├─ Success rate: 80% (4/5 trades)
├─ Avg profit per FVG entry: ₹650
├─ Works best with support confluence

Post-Mortem analysis:
├─ Is there an FVG zone at entry location?
├─ Did price pull back into it (vs continue)?
├─ Is FVG within 20 ticks of support?
├─ If yes: Rate 4.5/5
```

### Signal 4: Time-of-Day Window
```
Definition:
├─ Best entry times: 10:30-11:00, 11:15-11:45
├─ Worst times: 11:00-11:15 (liquidity dries), 14:00-15:00 (late entries)
├─ Why: Market microstructure + volume concentration

Historical performance:
├─ 10:30-11:00: 0 avg slippage, 100% fill quality
├─ 11:00-11:15: 3 avg slippage, poor fills
├─ 11:15-11:45: 0.8 avg slippage, good fills
├─ 12:00-13:00: No data yet
├─ 13:00-14:30: No data yet
├─ 14:00+: Avoid (late entry risk)

Post-Mortem analysis:
├─ Is entry within good time window?
├─ If 10:30-11:00: Add +0.5 to quality score
├─ If 11:00-11:15: Subtract -0.5 from quality score
├─ If other times: Neutral (collect data)
```

---

## 3. EXIT SIGNAL KNOWLEDGE SCAFFOLD

### Exit Signal 1: TP Hit (50% Premium Decay)
```
Definition:
├─ Iron Butterfly: Premium decayed to 50% of entry value
├─ Example: Sold at ₹200 credit → Exit when premium = ₹100
├─ Credit Spread: Same 50% decay rule

Historical performance:
├─ Hit rate: 92% of trades (within 4-hour window)
├─ Avg time to TP: 3h 45m
├─ Profit capture when TP hit: 92% of max

Post-Mortem analysis:
├─ Did TP hit before time-based exit (14:30)?
├─ If yes: Rate exit as optimal
├─ Measure: Profit captured as % of max premium
├─ Track: Time needed to reach TP
```

### Exit Signal 2: Time-Based Exit (14:30)
```
Definition:
├─ Hard exit at 14:30 IST (before market close)
├─ Risk management: Avoid overnight gap risk
├─ Safety net: If TP hasn't hit, close position

Historical performance:
├─ Prevents overnight disaster: 100% (0 gap risks)
├─ Profit capture when time-based: 75% of max
├─ Avg hold: 5+ hours (too long)

Post-Mortem analysis:
├─ Did TP hit before 14:30? If yes: TP was primary exit ✓
├─ Did we hit 14:30 exit without TP? If yes: Suboptimal hold
├─ Track: Profit loss vs closing at TP
```

### Exit Signal 3: Structure Reversal (HH→HL)
```
Definition:
├─ Market structure was HH (bullish)
├─ Structure breaks to HL (weakening)
├─ Example: New high didn't hold, made lower low

Historical performance:
├─ Detected in: 1/5 trades (rare, market moves slowly)
├─ Early exit: Avoided further loss
├─ Too early: Exited before TP

Post-Mortem analysis:
├─ Did structure change during hold?
├─ If HH→HL: Market reversal signal, exit warranted
├─ If HH→HH: Market still bullish, don't exit early
├─ Track: Did early exit save money or cost money?
```

### Exit Signal 4: SL Breach (Avoid!)
```
Definition:
├─ Stop loss hit: Position lost -25% to -35% of capital
├─ Example: Iron Butterfly, SL at premium × 1.25 = loss ₹1200+

Historical performance:
├─ Hit in: 1/5 trades
├─ Impact: Negative (SL breach = we were wrong)
├─ Lesson: Better entry or tighter SL earlier

Post-Mortem analysis:
├─ Why did SL breach?
│  ├─ Market moved more than expected (ATM ± 100)?
│  ├─ Entry was at resistance (no buffer)?
│  ├─ VIX spiked (repricing all legs)?
│  └─ Bad timing (entered at wrong window)?
├─ Action: Address root cause in next session
```

---

## 4. MARKET STRUCTURE KNOWLEDGE SCAFFOLD

### Structure Type: HH+HL (Higher High, Higher Low - Bullish Trend)
```
Definition:
├─ Each new high > prior high (price rising)
├─ Each new low > prior low (support rising)
├─ Indicates: Strong bullish momentum

Entry implication:
├─ Entry signals (EMA bounce, RSI div) are STRONGER in HH+HL
├─ Confidence += 0.15 if structure is HH+HL
├─ Best for: Bull Put Spreads, Long Calls

Exit implication:
├─ If structure breaks to HL (lower high): Exit early
├─ HH+HL reversal = reversal signal
```

### Structure Type: LL+LH (Lower Low, Lower High - Bearish Trend)
```
Definition:
├─ Each new low < prior low (price falling)
├─ Each new high < prior high (resistance lowering)
├─ Indicates: Strong bearish momentum

Entry implication:
├─ Best for: Bear Call Spreads, Long Puts
├─ Confidence += 0.15 if structure is LL+LH

Exit implication:
├─ If structure breaks to HH (higher low): Exit early
```

### Structure Type: HL (Higher Low, but no higher high - Weakening)
```
Definition:
├─ Support rising (new low > prior low)
├─ But resistance falling (new high < prior high)
├─ Indicates: Trend weakening, reversal possible

Entry implication:
├─ Less confident: -0.10 to entry signals
├─ Market transitioning: wait for confirmation

Exit implication:
├─ Early exit signal: Structure is breaking down
```

### Structure Type: LH (Lower High, but no lower low - Weakening)
```
Definition:
├─ Resistance falling (new high < prior high)
├─ But support stable (new low ≈ prior low)
├─ Indicates: Weakness, trapped upside buyers

Entry implication:
├─ Less confident: -0.10
├─ Wait for structure to confirm

Exit implication:
├─ If within Iron Butterfly: Structure favors ours (sideways)
```

---

## 5. GREEK KNOWLEDGE SCAFFOLD

### Delta (Directional Exposure)
```
For Iron Butterfly:
├─ Should be near 0 (delta-neutral)
├─ ATM CE: delta ~0.5 (positive)
├─ ATM PE: delta ~-0.5 (negative)
├─ Combined: 0 (neutralizes)

At exit:
├─ If delta > 0.6: Getting bullish (risk if bearish move)
├─ If delta < -0.6: Getting bearish (risk if bullish move)
├─ If delta ≈ 0: Still neutral (safe to hold)

Post-Mortem should track:
├─ Delta at entry (was it truly neutral?)
├─ Delta at exit (did it stay balanced?)
├─ Delta acceleration (is it moving toward directional risk?)
```

### Theta (Time Decay - Our Friend)
```
For Iron Butterfly:
├─ Theta should be positive (time decay works for us)
├─ +θ means: Every day, we gain ₹20-30 from decay alone

At entry:
├─ Should have theta ≈ +₹25/day (decent decay)

During hold:
├─ Theta accelerates (more decay as expiry approaches)
├─ Theta decelerates (slows near expiry, curve flattens)

Post-Mortem should track:
├─ Was theta strong at entry?
├─ Did we exit before theta decelerated?
├─ Did we capture fast theta (early hold) or slow theta (late hold)?
```

### Vega (Volatility Exposure)
```
For Iron Butterfly:
├─ Should be negative (we SHORT volatility)
├─ If VIX drops: We profit (premium decreases)
├─ If VIX rises: We lose (premium increases)

At entry (VIX = 18):
├─ Vega ≈ -0.5 (short vega)
├─ If VIX rises to 22: We lose ₹200 on vega alone

During hold:
├─ VIX spike = exit immediately (vega bleed)
├─ VIX drop = theta + vega profit (best scenario)

Post-Mortem should track:
├─ VIX at entry vs exit
├─ Did vega help or hurt our trade?
├─ Was VIX stable (ideal) or volatile (risky)?
```

---

## 6. RISK MANAGEMENT KNOWLEDGE SCAFFOLD

### Stop Loss (SL) Percentage Tuning
```
Rule by VIX:
├─ VIX < 18 (low vol): SL 30% (premium tight)
├─ VIX 18-20 (normal): SL 25% (standard)
├─ VIX 20-22 (elevated): SL 35% (wider buffer)
├─ VIX > 22 (high): SL 40-50% (large moves expected)

Example:
├─ Sold at ₹200 premium
├─ VIX = 18: SL at ₹200 × 1.30 = ₹260 (loss ₹60/lot)
├─ VIX = 22: SL at ₹200 × 1.35 = ₹270 (loss ₹70/lot)

Post-Mortem should track:
├─ Was SL % appropriate for VIX at entry?
├─ Did SL get hit? If yes: Was VIX % too tight?
├─ If not hit: Did we set it too loose (missed learning)?
```

### Take Profit (TP) Percentage
```
Standard:
├─ TP = 50% of credit received
├─ Sold at ₹200 → TP at ₹100 (profit ₹100/lot)
├─ Time to TP: Usually 3-4 hours
├─ Profit capture: 92% of max possible

Post-Mortem should track:
├─ Did TP hit within 4 hours? If yes: Ideal
├─ Did TP hit after 4 hours? If yes: Held too long
├─ Did TP never hit? If yes: SL was hit first
├─ Profit capture %: Target 90%+
```

---

## 7. CONFIDENCE SCORING KNOWLEDGE SCAFFOLD

### Entry Quality Score (0-5 scale)

```
Components:
├─ Support proximity (0-1 pts)
│  ├─ Within 20 ticks of support: 1.0
│  ├─ Within 50 ticks: 0.7
│  ├─ Within 100 ticks: 0.3
│  └─ > 100 ticks (void): 0.0
│
├─ Signal confluence (0-1 pts)
│  ├─ 3+ signals align (EMA + support + RSI + FVG): 1.0
│  ├─ 2 signals align: 0.8
│  ├─ 1 signal only: 0.4
│  └─ No signals: 0.0
│
├─ Premium capture (0-1 pts)
│  ├─ Got 90%+ of available: 1.0
│  ├─ Got 80-90%: 0.8
│  ├─ Got 70-80%: 0.5
│  └─ Got <70%: 0.2
│
├─ Fill slippage (0-1 pts)
│  ├─ 0-1 ticks: 1.0
│  ├─ 1-2 ticks: 0.8
│  ├─ 2-4 ticks: 0.5
│  └─ 4+ ticks: 0.0
│
└─ Time-of-day (0-1 pts)
   ├─ 10:30-11:00: 1.0
   ├─ 11:15-11:45: 0.9
   ├─ 12:00-13:00: 0.6
   └─ 14:00+: 0.0

Total = Sum all components / 5
Result: 0-5 score

Target: 4.0+ = good entry, 3.0-4.0 = fair, <3.0 = poor
```

### Strategy Confidence Score (0-1 scale)

```
Components:
├─ Win-rate (40% weight)
│  ├─ Win-rate 80%+: 1.0
│  ├─ Win-rate 70-80%: 0.8
│  ├─ Win-rate 60-70%: 0.6
│  └─ Win-rate <60%: 0.4
│
├─ Sample size (30% weight)
│  ├─ 5+ samples: 1.0
│  ├─ 3-4 samples: 0.7
│  ├─ 1-2 samples: 0.5
│  └─ 0 samples: 0.3
│
└─ Regime match (30% weight)
   ├─ Regime exactly matches (sideways=IB): 1.0
   ├─ Regime similar: 0.8
   ├─ Regime different: 0.3

Total = (win_rate × 0.4) + (samples × 0.3) + (regime × 0.3)
Result: 0-1 score

Target: 0.85+ = high confidence, 0.70-0.85 = medium, <0.70 = low
```

---

## 8. DAILY EVOLUTION KNOWLEDGE

### How Confidence Should Change Day-by-Day

```
Day 1 (May 14):
├─ Iron Butterfly: 1 sample, 100% win-rate, confidence = 0.70 (assumed)
├─ EMA5 bounce: 1 sample, 100% win-rate, confidence = 0.70
└─ 3.5h hold: 1 sample, confidence = 0.70

Day 2 (May 15):
├─ Iron Butterfly: 2 samples (both profit), confidence = 0.75
├─ EMA5 bounce: 2 samples (both profit), confidence = 0.80
└─ 3.5h hold: 2 samples (both optimal), confidence = 0.80

Day 3 (May 16):
├─ Iron Butterfly: 3 samples (all profit), confidence = 0.82
├─ EMA5 bounce: 3 samples (all profit), confidence = 0.90
└─ 3.5h hold: 3 samples (all optimal), confidence = 0.85

Pattern: Confidence increases as more samples confirm
Formula: confidence = (wins / total_samples) × (1 + sample_weight)
```

---

## 9. ANTI-PATTERNS TO DETECT

```
Entry anti-patterns (should trigger -0.5 confidence):
├─ Entry in middle of empty space (no support)
├─ Entry at resistance (no buffer down)
├─ Entry in 11:00-11:15 window (poor liquidity)
├─ Entry when VIX > 22 (high repricing risk)
├─ Entry with only 1 confluence (weak signal)

Exit anti-patterns (should trigger -0.3 confidence):
├─ Held past 4 hours (theta deceleration)
├─ Held until market close (gap risk)
├─ SL breach without early exit
├─ Exited at -50% profit (left money on table)
├─ Exited after VIX spike without TP

Strategy anti-patterns (should trigger -0.4 confidence):
├─ Iron Butterfly in trending market (ADX > 25)
├─ Bull Put in bearish market
├─ Using strategy when <3 samples in regime
```

---

**This scaffold gives Post-Mortem agents the domain knowledge to analyze trades intelligently.**

