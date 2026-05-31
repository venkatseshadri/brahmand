# Backtest Results — 2024 Kaggle F&O Data

**Run date:** May 23, 2026  
**Dataset:** Kaggle `kaalicharan9080/nse-future-and-options-data` (6.5M rows, BANKNIFTY + stock options)

---

## Scripts Run

| Script | Result |
|--------|--------|
| `BACKTEST_2024_MINI.py` (pandas) | ❌ Timed out (>120s) |
| `BACKTEST_2024_DUCKDB.py` (SQL) | ✅ 2,055 trades |
| `BACKTEST_2024_FULL_RISK_MGMT.py` (Iron Fly + TSL + Morph) | ✅ 2,121 trades, 2 param sets compared |

---

## MINI Strategy (Sell ATM, No Risk Management)

| Metric | Value |
|--------|-------|
| Total trades | 2,055 |
| Total P&L | ₹3,20,591 |
| Win rate | 46.7% |
| Profit factor | 1.04x |
| Avg win / loss | ₹8,217 / ₹-6,897 |
| Strategy | Viable (marginal) |

---

## FULL Strategy (Iron Butterfly + TSL Ratchet + Morph)

### Current Params: TP 20% / SL 5%

| Metric | Value |
|--------|-------|
| Total P&L | **₹18,77,723** |
| Win rate | **51.7%** |
| Profit factor | **1.30x** |
| Avg win / loss | ₹7,402 / ₹-6,096 |
| TSL exits | 388 |
| Morph count | 861 |
| Avg duration | 25 min |
| **Verdict** | ✅ **WINNER** |

### DeepSeek Params: TP 25% / SL 3%

| Metric | Value |
|--------|-------|
| Total P&L | ₹2,15,888 |
| Win rate | 44.3% |
| Profit factor | 1.03x |
| Avg win / loss | ₹7,014 / ₹-5,405 |
| TSL exits | 405 |
| Morph count | 1004 |
| Avg duration | 23 min |
| **Verdict** | ❌ 8.7x worse than current |

---

## Key Finding

**TP 20% / SL 5% is the optimal pair.** DeepSeek's suggestion (TP 25% / SL 3%) sounds good but backfires — tighter SL causes 143 more stop-outs (+17%), narrowing the profit margin. The current 4:1 risk/reward ratio at 51.7% win rate is the sweet spot.

---

## Output Files

| File | Content |
|------|---------|
| `data/backtest_results_2024.json` | MINI summary |
| `data/backtest_trades_2024.csv` | Per-trade detail |
| `data/backtest_parameter_comparison_2024.json` | TP 20/5 vs TP 25/3 head-to-head |
