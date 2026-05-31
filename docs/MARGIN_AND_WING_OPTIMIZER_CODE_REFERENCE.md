# Margin Calculator + Wing Width Optimizer — Code Reference

Two systems compute ideal wing width. Both are in `brahmand/`. A third heuristic-only variant exists in `antariksh/tools/pm_tools.py` for the CrewAI PM agent.

---

## System 1: brahmand (Production — Shoonya Live API)

### File: `brahmand/margin_capture.py` (360 lines)

**Purpose:** Captures real Shoonya SPAN margins for PE and CE credit spreads at ATM ±5 strikes (50pt steps). Outputs JSON for the wing optimizer.

**Flow:**
```
Shoonya API (span_calculator) → margin_matrix.json → wing_optimizer.py
```

**Key config:**
| Constant | Value | Line |
|----------|-------|------|
| `STRIKE_COUNT` | 5 (ATM ±5 strikes) | 36 |
| `STRIKE_STEP` | 50 (NIFTY strike gap) | 37 |
| `LOT_SIZE` | 65 | 38 |
| `DEFAULT_QTY` | 65 (1 lot, per-leg) | 39 |

**How it works (lines 132–284):**

```python
def capture_margins() -> dict:
    # 1. Auth Shoonya via cred.yml
    api = NorenApiPy()
    api.injectOAuthHeader(cred["Access_token"], cred["UID"], cred["Account_ID"])

    # 2. Get ATM strike from DuckDB spot price
    atm = round(spot / 50) * 50

    # 3. For each wing width (50, 100, 150, 200, 250):
    for offset in range(1, 6):
        wing = atm - offset * 50  # PE (down)
        # Build 2-leg position: SELL ATM PE + BUY wing PE
        resp = api.span_calculator(actid, [position1, position2])
        margin = parse_margin(resp)

    # 4. Same for CE (atm + offset * 50)
    for offset in range(1, 6):
        wing = atm + offset * 50  # CE (up)
        resp = api.span_calculator(actid, [position1, position2])
        margin = parse_margin(resp)

    # 5. Save to brahmand/data/margin_matrix.json
```

**Spread built (per wing width):**
```
PE:  SELL ATM PE + BUY (ATM-N) PE   (N = 50, 100, 150, 200, 250)
CE:  SELL ATM CE + BUY (ATM+N) CE   (N = 50, 100, 150, 200, 250)
```
Total: 10 spreads captured per cycle.

**Output:** `brahmand/data/margin_matrix.json`
```json
{
  "atm": 23750,
  "expiry": "19-MAY-2026",
  "timestamp": "2026-05-19T09:15:00",
  "spreads": [
    {"type": "PE", "sell_strike": 23750, "buy_strike": 23700, "wing_width": 50,  "margin": 154000},
    {"type": "PE", "sell_strike": 23750, "buy_strike": 23650, "wing_width": 100, "margin": 158000},
    ...
    {"type": "CE", "sell_strike": 23750, "buy_strike": 23800, "wing_width": 50,  "margin": 140000},
    {"type": "CE", "sell_strike": 23750, "buy_strike": 23850, "wing_width": 100, "margin": 147000},
    ...
  ]
}
```

**Runtime modes (lines 313–356):**
```bash
python3 margin_capture.py              # Run once, capture + exit
python3 margin_capture.py --loop       # Every 5 min during market hours (09:15–15:30)
python3 margin_capture.py --once       # Single capture
```

**Safety (loop mode):** Alerts after 3 consecutive failures (lines 332–343).

---

### File: `brahmand/wing_optimizer.py` (277 lines)

**Purpose:** Reads `margin_matrix.json` + live option premiums from DuckDB. Scores each wing width. Returns optimal wing.

**Key config:**
| Constant | Value | Line |
|----------|-------|------|
| `MARGIN_FILE` | `brahmand/data/margin_matrix.json` | 28 |
| `DUCKDB_V31` | `varaha/data/varaha_data.duckdb` | 29 |
| Premium freshness | 5 min max age | 60 |
| Scoring | 70% ROI + 30% R/R | 184 |

**Main function: `get_optimal_wing()` (lines 107–203)**

```python
def get_optimal_wing(spread_type, atm, expiry,
                     min_roi_pct=5.0, min_rr=0.2) -> Optional[dict]:

    for each spread in margin_matrix:
        # 1. Get live premiums from DuckDB (max 5 min old)
        sell_premium = _check_premium_freshness(atm, spread_type, expiry, max_age_sec=300)
        buy_premium  = _check_premium_freshness(buy_strike, spread_type, expiry, max_age_sec=300)

        # 2. Calculate per-lot (NIFTY lot = 65)
        net_credit_ps = sell_premium - buy_premium          # premium per share

        # 3. Validation
        if net_credit_ps <= 0: continue                      # no debit spreads
        if margin <= 0: continue                             # skip bad margin
        if wing_width <= net_credit_ps: continue             # risk must be positive

        # 4. Risk/Reward
        reward = net_credit_ps * 65                          # max gain per lot
        risk = (wing_width - net_credit_ps) * 65             # max loss per lot
        roi_pct = round(reward / margin * 100, 2)            # return on margin
        rr = round(net_credit_ps / (wing_width - net_credit_ps), 3)  # risk-to-reward

        # 5. Score: 70% ROI + 30% R/R (normalized)
        score = round(roi_pct * 0.7 + rr * 100 * 0.3, 2)

    # 6. Filter by minimums, sort by score, return best
    valid = [c for c in candidates if c["roi_pct"] >= min_roi_pct and c["rr"] >= min_rr]
    return valid[0]  # highest score
```

**Helper: `compare_wings()` (lines 206–247)**
Returns all wing options with scores for analysis (not just best). Used for premarket testing.

**Margin freshness check: `_check_margin_freshness()` (lines 34–57)**
Two-layer check:
1. File modification time (stat mtime)
2. JSON `timestamp` field (millisecond-precise)

**Premium freshness check: `_check_premium_freshness()` (lines 60–86)**
- Queries DuckDB `option_snapshots` table
- Requires LTP ≤ 5 minutes old
- Returns `None` if stale (skips that wing)

---

## Data Flow: Margin → Wing

```
┌──────────────────────────────────────────────────────────────────────┐
│                     EVERY 5 MIN (09:15–15:30)                        │
│                                                                      │
│  ┌─────────────────────┐     ┌─────────────────────┐                │
│  │  margin_capture.py  │────→│ margin_matrix.json  │                │
│  │  Shoonya SPAN API   │     │ (10 spreads: 5 PE,  │                │
│  │  ATM ±5 strikes     │     │  5 CE, each with    │                │
│  │  (50pt steps)       │     │  real margin in ₹)  │                │
│  └─────────────────────┘     └─────────┬───────────┘                │
│                                        │                             │
│  ┌─────────────────────┐               │                             │
│  │ v3.1 DuckDB         │               │                             │
│  │ option_snapshots    │               │                             │
│  │ (live LTPs)         │               │                             │
│  └─────────┬───────────┘               │                             │
│            │                            │                             │
│            └────────────┬───────────────┘                            │
│                         │                                            │
│                ┌────────▼────────┐                                   │
│                │ wing_optimizer  │                                   │
│                │                 │                                   │
│                │ Per spread:     │                                   │
│                │  premium_sell   │  (from DuckDB, max 5min old)      │
│                │  premium_buy    │  (from DuckDB, max 5min old)      │
│                │  net_credit_ps  │  = sell - buy                     │
│                │  reward         │  = net_credit * 65                │
│                │  risk           │  = (wing_width - net_credit) * 65 │
│                │  roi_pct        │  = reward / margin * 100          │
│                │  rr             │  = net_credit / (wing - credit)   │
│                │  score          │  = roi*0.7 + rr*100*0.3           │
│                │                 │                                   │
│                │ Returns:        │                                   │
│                │  get_optimal_wing("PE", atm, expiry)                │
│                │  get_optimal_wing("CE", atm, expiry)                │
│                └────────┬────────┘                                   │
│                         │                                            │
│                         ▼                                            │
│                { "wing_width": 200,                                  │
│                  "margin": 154000,                                   │
│                  "roi_pct": 12.5,                                    │
│                  "rr": 0.42 }                                        │
└──────────────────────────────────────────────────────────────────────┘
```

---

## System 2: antariksh (Heuristic — CrewAI PM Agent Tool)

### File: `antariksh/tools/pm_tools.py` (685 lines)

**Purpose:** CrewAI tool for the PM agent. Calls Shoonya span calculator directly OR falls back to heuristics.

**`analyze_wing_margins()` — Lines 311–409**

```python
def analyze_wing_margins(nifty_spot, lots, expiry, lot_size=75,
                         dry_run=False) -> List[Dict]:
    # Builds 4-leg Iron Butterfly for each wing width (not 2-leg credit spread!)
    # wings: 50, 100, 150, 200, 250, 300, 350, 400, 450, 500
    for wing in 50..500 step 50:
        positions = [
            SELL ATM PE, BUY (ATM-wing) PE,
            SELL ATM CE, BUY (ATM+wing) CE
        ]
        if dry_run or api fails:
            # HEURISTIC: margin_per_lot = (wing * 75 * 1.8) + 5000
        else:
            resp = api.span_calculator(actid, positions)
```

**`recommend_optimal_wing()` — Lines 413–end**

```python
def recommend_optimal_wing(nifty_spot, vix, free_cash, lots, expiry,
                           dry_run=False) -> Dict:
    # Scoring (different from brahmand):
    #   efficiency (25%): lower margin → higher score
    #   safety (25%):     lower breach prob → higher score
    #   proximity (25%):  ≤250 wings get full score
    #   headroom (25%):   lower % of free_cash used
    #   hedge_factor:     wings >70% breach risk get 35–70% penalty
    # score = (eff + safety + prox + headroom) * 0.25 * hedge_factor
```

---

## Comparison: brahmand vs antariksh Wing Optimizers

| Aspect | brahmand (Production) | antariksh (CrewAI Tool) |
|--------|----------------------|------------------------|
| **File** | `wing_optimizer.py` | `pm_tools.py:413` |
| **Margin source** | `margin_matrix.json` (pre-captured, fresh) | Live SPAN call OR heuristic fallback |
| **Premium source** | DuckDB `option_snapshots` (freshness-checked) | None (uses wing_width only) |
| **Spread type** | 2-leg credit spread (PE or CE only) | 4-leg Iron Butterfly |
| **Wing range** | 50, 100, 150, 200, 250 (5 widths) | 50–500 step 50 (10 widths) |
| **Lot size** | 65 (NIFTY) | 75 (default, configurable) |
| **Scoring** | 70% ROI + 30% R/R | 4-factor equal weight + hedge penalty |
| **Criterion** | min_roi_pct=5%, min_rr=0.2 | Affordability vs free_cash |
| **LLM-dependent** | No (deterministic) | Yes (CrewAI tool, called by PM agent) |
| **Used by** | e2e_chain.py (signal-driven entry) | PM crew agent (LLM-orchestrated) |

---

## Integration Points

### Where wing width is used:

| Location | How |
|----------|-----|
| `brahmand/e2e_chain.py` | Strategy selection (BULLISH→PUT, BEARISH→CALL, NEUTRAL→IB) with wing_width |
| `brahmand/kickoff.py` | Entry execution: passes wing_width to e2e_chain |
| `brahmand/position_manager.py` | Morph execution: uses WING_BUTTERFLY=200, WING_SPREAD=200 constants |
| `antariksh/trading_desk.py` | Shifter: proposes new strike at `atm + 50`, wing_width=300 |
| `antariksh/tools/pm_tools.py` | PM tool: `recommend_optimal_wing()` called by CrewAI PM agent |
| `antariksh/crews/pm_crew.py:70` | Crew wrapper for `recommend_optimal_wing()` |

### Where ideal wing is NOT yet auto-selected:

The wing optimizer outputs exist but are **not wired into** `kickoff.py` or `e2e_chain.py`. The entry gate currently uses hardcoded/default wing widths. The wing optimizer's `get_optimal_wing()` is available for import but not called at trade entry time.

---

## Verification

```bash
# Capture live margins
python3 margin_capture.py --once

# Run wing optimizer standalone
python3 wing_optimizer.py

# Premarket test suite (capture + optimize + validate)
python3 test_margin_calculations_premarket.py
```
