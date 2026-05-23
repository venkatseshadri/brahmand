# Backtest: MINI Strategy on 2024 Kaggle F&O Data

**Script:** `brahmand/BACKTEST_2024_MINI.py` (204 lines)  
**Run attempt:** May 23, 2026 — timed out (>120s)  
**Status:** ⚠️ Needs optimization (pandas too slow, recommended: DuckDB)

---

## Strategy

| Parameter | Value |
|-----------|-------|
| Entry | Sell ATM CE/PE at market open |
| Take Profit | 20% profit (price drops to 0.8 × entry) |
| Stop Loss | 5% loss (price rises to 1.05 × entry) |
| Lot size | 75 (MINI) |
| Instrument | NIFTY options (not BANKNIFTY) |

---

## Dataset

| Detail | Value |
|--------|-------|
| Source | Kaggle: `kaalicharan9080/nse-future-and-options-data` |
| Files | 9 CSVs (Oct–Nov 2024 + 2020) |
| Path | `/root/.cache/kagglehub/datasets/.../versions/2/` |
| Filter | NIFTY options only (PE + CE), excludes BANKNIFTY |
| Ticker format parsed | `NIFTY26NOV24C23800` → expiry, strike, type |

---

## How It Works

```
1. Load all CSVs → concat into single DataFrame (millions of rows)
2. Filter: NIFTY + PE/CE only
3. Parse tickers: extract expiry, strike, type
4. For each trading day:
   → Snapshot ATM strike at market open
   → Walk through intraday prices for that strike/type
   → Exit on first TP (≤ 0.8 × entry) or SL (≥ 1.05 × entry)
   → Calculate P&L = (entry - exit) × 75
5. Report: total P&L, win rate, avg win/loss, profit factor,
   trade duration, TP vs SL breakdown
```

## Why It Timed Out

- 9 CSVs with millions of option tick rows
- Pandas `groupby` + nested loop per day per strike
- No chunking, no DuckDB, no parallelization
- Estimated runtime: 5–10 minutes on full dataset

## Optimization Needed

```python
# Replace pandas groupby with DuckDB:
conn.execute("""
    SELECT date, strike, type, MIN(timestamp) as open_ts
    FROM options_data
    WHERE ticker LIKE '%NIFTY%'
    GROUP BY date, strike, type
""")
```

---

## Output Files

| File | Content |
|------|---------|
| `data/backtest_results_2024.json` | Summary: total P&L, win rate, avg win/loss, recommendation |
| `data/backtest_trades_2024.csv` | Per-trade: date, strike, type, entry, exit, signal, P&L, duration |
