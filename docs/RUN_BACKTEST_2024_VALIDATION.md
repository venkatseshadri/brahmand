# Backtest Validation Task for Deepseek

**Objective:** Independently run and validate the 2024 NIFTY backtest WITH risk management (TSL + morphing + re-entry) to confirm strategy profitability before Monday (2026-05-24) market open.

## Steps

### PART A: Basic Backtest (mechanical TP/SL only)
```bash
cd /home/trading_ceo
python3 brahmand/BACKTEST_2024_DUCKDB.py
```

### PART B: Full Risk Management Backtest (TSL 33% + Leg Shifting + Morphing + Parameter Comparison)
```bash
cd /home/trading_ceo
python3 brahmand/BACKTEST_2024_FULL_RISK_MGMT.py
```

**Features:**
- TSL at 33% activation with trailing exits
- Leg shifting: CE and PE close independently on TP/SL (each leg is its own trade)
- Morphing: Tracks when losing legs close and can be re-entered
- Parameter comparison: Tests both parameter sets and shows which is better
  - **Current:** TP 20% / SL 5%
  - **Deepseek suggestion:** TP 25% / SL 3%

**Output files:**
- `data/backtest_parameter_comparison_2024.json` — Shows which params give better P&L

2. Capture and report:
   - Total P&L (should be ~₹287k)
   - Win rate (should be ~46%)
   - Profit factor (should be ~1.04x)
   - Number of trades (should be ~2,055)
   - Any errors or warnings

3. Verify output files created:
   - `data/backtest_results_2024.json` — exists and contains results
   - `data/backtest_trades_2024.csv` — exists with trade details

## Expected Results

| Metric | Expected |
|--------|----------|
| Total P&L | ₹287,347.50 |
| Trades | 2,055 |
| Win Rate | 46.4% |
| Profit Factor | 1.04x |
| Avg Win | ₹8,189.81 |
| Avg Loss | ₹-6,835.36 |

## Files Modified (May 23, 2026)

- `BACKTEST_2024_DUCKDB.py` line 50-59: Changed filter from BANKNIFTY → NIFTY
- `BACKTEST_2024_DUCKDB.py` line 90: Fixed DuckDB REGEXP_EXTRACT syntax (added capture group index)
- `BACKTEST_2024_DUCKDB.py` line 159: Updated lot size from 65 → 75 (2024 pricing)

## Validation Checklist

- [ ] Script runs without errors
- [ ] Results match expected P&L (±10%)
- [ ] Win rate is 46%–47%
- [ ] Output files are created
- [ ] Ready to confirm deployment Monday
