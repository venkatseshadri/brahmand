# Postmortem Agent — Complete Data Flow ✅

**Status:** All agents now provide complete information to postmortem analysis

## Data Flow Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│             E2E SEQUENTIAL CREW (Entry → Risk)                  │
│                                                                 │
│  1. Entry Agent     → entry_scores (signal, confidence)        │
│  2. Regime Agent    → regime_analysis (regime, VIX, ADX)       │
│  3. Strategy Agent  → strategy_analysis (parameters)           │
│  4. Contract Agent  → contracts_analysis (tsyms, ltps)         │
│  5. Execution Agent → execution_analysis (credit, SL/TP)       │
│  6. Risk Agent      → risk_confirmation (order_ids, status)    │
└─────────────────────────────────────────────────────────────────┘
                              ↓
                  Trade Dict (accumulated data)
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│          MONITORING PHASE (5-min cadence)                       │
│                                                                 │
│  - Risk Monitor         → SL/TP triggers, TSL adjustments      │
│  - Morpher Agent        → MORPH actions (signal reversal)      │
│  - Shifter Agent        → SHIFT actions (premium decay)        │
│  - MTM Snapshots        → P&L snapshots during monitoring      │
│                                                                 │
│  Data collected in: trade["monitoring_events"]                 │
└─────────────────────────────────────────────────────────────────┘
                              ↓
                     Trade CLOSED (exit)
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│               EXIT DATA                                         │
│                                                                 │
│  - exit_time: when trade closed                                │
│  - exit_reason: SL_HIT | TP_HIT | MORPH | SHIFT | TIME_EXIT   │
│  - final_pnl: realized profit/loss                             │
│  - status: CLOSED                                              │
└─────────────────────────────────────────────────────────────────┘
                              ↓
                      state["all_trades"]
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│             POSTMORTEM AGENT (after market close)               │
│                                                                 │
│  Receives: trade dict with ALL data from 6 agents +            │
│            monitoring events + exit data                       │
│                                                                 │
│  Analyzes: accuracy, pattern correlation, optimization         │
│                                                                 │
│  Outputs: ResearchNotes → ChromaDB + daily_config.json update  │
└─────────────────────────────────────────────────────────────────┘
```

## Complete Trade Data Structure (Postmortem POV)

```json
{
  "entry_time": "14:01",
  "trade_id": "TRD-20260521140100",
  
  "📊 ENTRY AGENT DATA": {
    "entry_scores": {
      "go": true,
      "signal": "BEARISH",
      "confidence": 58,
      "trend_signal": "BEARISH",
      "traffic_light_signal": "NEUTRAL",
      "trend_confidence": 90,
      "traffic_light_confidence": 20,
      "ema_source": "60min",
      "tl_pattern": "CHOPPY_INDECISION",
      "gap": "GREEN"
    },
    "entry_gate_signal": "BEARISH",
    "entry_confidence": 58
  },

  "📊 REGIME AGENT DATA": {
    "regime_analysis": {
      "regime": "sideways",
      "confidence": 0.6,
      "recommendation": "caution",
      "vix": 17.82,
      "adx": 22.5,
      "entry_signal": "BEARISH",
      "reason": "ADX < 25 indicates sideways movement"
    }
  },

  "📊 STRATEGY AGENT DATA": {
    "strategy_analysis": {
      "strategy_type": "CALL_SPREAD",
      "wing_width": 200,
      "sl_pct": 0.25,
      "tp_pct": 0.50,
      "reason": "VIX 17.82 < 20, use default wing_width"
    }
  },

  "📊 CONTRACT AGENT DATA": {
    "contracts_analysis": {
      "contracts": {
        "sell_ce": {
          "tsym": "NIFTY26MAY26C23650",
          "ltp": 164.65,
          "strike": 23650,
          "option_type": "CE",
          "action": "SELL"
        },
        "buy_ce": {
          "tsym": "NIFTY26MAY26C23850",
          "ltp": 84.1,
          "strike": 23850,
          "option_type": "CE",
          "action": "BUY"
        }
      },
      "count": 2,
      "note": "all live"
    }
  },

  "📊 EXECUTION AGENT DATA": {
    "legs": [
      {
        "action": "SELL",
        "strike": 23650,
        "type": "CE",
        "fill_price": 164.65,
        "tsym": "NIFTY26MAY26C23650"
      },
      {
        "action": "BUY",
        "strike": 23850,
        "type": "CE",
        "fill_price": 84.1,
        "tsym": "NIFTY26MAY26C23850"
      }
    ],
    "execution_analysis": {
      "leg_count": 2,
      "net_credit": 80.55,
      "premium_sell": 164.65,
      "premium_buy": 84.1
    },
    "sl": { "ce": 205.81 },
    "tp": { "ce": 74.09 },
    "spot_at_entry": 23659.05,
    "atm_strike": 23650,
    "vix": 17.82,
    "expiry": "26-MAY-2026",
    "wing_width": 200
  },

  "📊 RISK AGENT DATA": {
    "risk_confirmation": {
      "trade_id": "TRD-20260521140100",
      "sl_orders": [
        "ORD-20260521-0029"
      ],
      "tp_orders": [
        "ORD-20260521-0030"
      ],
      "status": "FILLED",
      "mode": "PAPER"
    }
  },

  "📊 MONITORING PHASE DATA": {
    "monitoring_events": {
      "tsl_adjustments": [
        {
          "timestamp": "14:05",
          "leg": "CE",
          "old_sl": 205.81,
          "new_sl": 195.0,
          "reason": "TSL ratchet"
        }
      ],
      "morph_actions": [
        {
          "timestamp": "14:10",
          "action": "NO_MORPH",
          "reason": "Signal still BEARISH"
        }
      ],
      "shift_actions": [],
      "mtm_checks": [
        {
          "timestamp": "14:05",
          "mtm_pnl": 1500.0,
          "status": "MONITORING"
        }
      ]
    }
  },

  "📊 EXIT DATA": {
    "exit_time": "14:15",
    "exit_reason": "TP_HIT",
    "pnl": 1200.50,
    "status": "CLOSED"
}
```

## Postmortem Analysis Checklist

### 1. Entry Agent Validation
- ✅ Check if signal (BEARISH) matched actual market direction at exit
- ✅ Was confidence 58% predictive of 60+ min profit?
- ✅ Trend vs TL score breakdown: 90% trend, 20% TL (conflicting)

### 2. Regime Agent Validation
- ✅ Regime "sideways" correct for ADX 22.5
- ✅ VIX 17.82: was "caution" recommendation appropriate?
- ✅ Entry signal BEARISH preserved correctly

### 3. Strategy Agent Validation
- ✅ CALL_SPREAD correct for BEARISH signal
- ✅ Wing width 200 suitable for VIX 17.82?
- ✅ SL 0.25 (SL at 205.81): was it hit too easily?

### 4. Contract Agent Validation
- ✅ NIFTY26MAY26C23650 SELL @ 164.65: current at exit?
- ✅ NIFTY26MAY26C23850 BUY @ 84.10: hedge effective?

### 5. Execution Agent Validation
- ✅ Net credit 80.55 sufficient for margin (wing 200)?
  - Max loss: (200 - 80.55) * 65 = ₹7,759
  - Actual loss if SL hit: premium * 1.25 = 205.81
- ✅ SL/TP levels placed correctly

### 6. Risk Agent Validation
- ✅ Orders filled? SL and TP created?
- ✅ Order IDs tracked in order_ledger?

### 7. Monitoring Phase Validation
- ✅ TSL ratcheted from 205.81 → 195.0 (locked in gains)
- ✅ No MORPH triggered (signal still BEARISH)
- ✅ P&L progression: 1500 → 1200 (TP hit, favorable)

### 8. Exit Analysis
- ✅ TP_HIT at 14:15 (14 min into trade)
- ✅ Final PnL ₹1,200: TP at 74.09, achieved at TP
- ✅ Exit reason matches strategy (TP = profit taking)

## Output: ResearchNotes

**What Worked:**
- Entry BEARISH signal correct
- TP hit quickly (14 min) = fast capital turnover
- TSL ratchet locked in extra gains (205.81 → 195.0)

**What Failed:**
- Confidence 58% despite 90% trend signal + 20% TL = conflicting signals
- Sideways regime but BEARISH trade = higher risk

**Recommendations for Tomorrow:**
- Increase minimum confidence threshold: 65% (not 58%)
- Require TL score > -2 before entry (not -6 CHOPPY pattern)
- If VIX < 18 AND sideways regime: skip trades (too conflicting)

---

**Status:** ✅ **POSTMORTEM NOW RECEIVES 100% OF AGENT DATA**

All 6 agents + monitoring phase + exit data = complete trade analysis capability
