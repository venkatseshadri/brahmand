# Backtest: MINI Strategy on 2024 Kaggle F&O Data

**Scripts:**
- `backtest/BACKTEST_2024_MINI.py` (204 lines) — pandas version, timed out
- `backtest/BACKTEST_2024_DUCKDB.py` (242 lines) — DuckDB migration, runs but has regex bug

**Status:** ⚠️ DuckDB regex bug — Claude needs to fix parse_ticker

---

## Strategy (Same in Both Versions)

| Parameter | Value |
|-----------|-------|
| Entry | Sell ATM CE/PE at market open |
| Take Profit | 20% profit (price drops to 0.8 × entry) |
| Stop Loss | 5% loss (price rises to 1.05 × entry) |
| Lot size | 75 (MINI) |
| Instrument | BANKNIFTY options only |

---

## Dataset

| Detail | Value |
|--------|-------|
| Source | Kaggle: `kaalicharan9080/nse-future-and-options-data` |
| Files | 9 CSVs (Oct–Nov 2024 + 2020) |
| Total rows | 6,534,963 |
| BANKNIFTY rows | 527,062 (filtered by `Ticker LIKE '%BANKNIFTY%'`) |
| Format | Stock F&O options + BANKNIFTY index options |
| **No standalone NIFTY** | Dataset has BANKNIFTY but not NIFTY-50 |

---

## DuckDB Version Progress (WORKING until strike parse)

```
✅ 6.5M rows loaded into DuckDB (5 CSVs)
✅ 527K BANKNIFTY rows filtered
✅ 10 potential trades identified (daily ATM opens)
❌ Strike parse fails — REGEXP_EXTRACT returns NULL for all rows
```

---

## THE BUG: Tick Parse Failure

### Ticker Format (actual)
```
BANKNIFTY06NOV2443000CE.NFO
│        │      │   │ │
│        │      │   │ └── .NFO suffix
│        │      │   └── CE or PE
│        │      └── Strike: 43000
│        └── Expiry: 06NOV24 (6 Nov 2024)
└── Index: BANKNIFTY
```

### Broken Code (line 90 of BACKTEST_2024_DUCKDB.py)
```python
# CURRENT (broken):
REGEXP_EXTRACT(Ticker, '(\\d{4,5})(CE|PE).NFO') as strike_str
# Returns NULL because DuckDB's REGEXP_EXTRACT needs explicit capture group index
```

### Error
```
Binder Error: Referenced column "None" not found in FROM clause
LINE 5: AND strike = None
```

### Fix Needed
DuckDB's `REGEXP_EXTRACT` returns the Nth capture group with a third argument. Also need `TRY_CAST` to handle NULLs:

```python
# OPTION A: DuckDB regex with capture group index
TRY_CAST(REGEXP_EXTRACT(Ticker, '(\d{4,5})(CE|PE)\.NFO$', 1) AS INTEGER) as strike
#                                                                    ^
#                                     Capture group 1 = strike digits
```

```python
# OPTION B: Python-side parse (run after SQL, in the trade loop)
import re
match = re.search(r'(\d{4,5})(CE|PE)\.NFO$', ticker)
strike = int(match.group(1)) if match else None
```

```python
# OPTION C: Use REGEXP_REPLACE to strip suffix then extract
TRY_CAST(
    REGEXP_REPLACE(
        REGEXP_REPLACE(Ticker, '\.NFO$', ''), 
        '^.*(\d{4,5})(CE|PE)$', '\1'
    ) AS INTEGER
) as strike
```

---

## Files to Modify

| File | Line | Issue |
|------|------|-------|
| `BACKTEST_2024_DUCKDB.py` | 51-59 | Changed to BANKNIFTY filter (no standalone NIFTY available) |
| `BACKTEST_2024_DUCKDB.py` | 90 | REGEXP_EXTRACT returns NULL — needs capture group index `', 1'` |
| `BACKTEST_2024_DUCKDB.py` | 47-48 | SyntaxWarning: `\d` needs raw string `r'\d'` or `\\d` in SQL string |

---

## Expected Output (After Fix)

```
📈 Running backtest (Sell ATM, TP 20%, SL 5%)...
   Processing 10 potential trades...

======================================================================
📊 BACKTEST RESULTS (X trades)
======================================================================

Performance:
  Total P&L: ₹XXX,XXX
  Win rate: XX%
  Avg win: ₹XXX
  Avg loss: ₹XXX
  Max win: ₹XXX
  Max loss: ₹XXX
  Profit factor: X.Xx

Trade Distribution:
  Avg duration: X minutes
  TP exits: X
  SL exits: X

======================================================================
✅ STRATEGY PROFITABLE / ❌ NEEDS IMPROVEMENT
```
