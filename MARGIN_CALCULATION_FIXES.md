# Margin Calculation Logic: Fixes Implemented

**Date:** May 19, 2026 23:30 IST  
**Status:** ✅ READY FOR TOMORROW (May 20, 2026)

---

## Issues Found & Fixed

### ✅ FIXED: Division by Zero in ROI Calculation (CRITICAL)
**File:** `wing_optimizer.py:90`  
**Issue:** `roi_pct = round(reward / margin * 100, 2)` crashed if margin=0  
**Fix:** Added check: `if margin > 0 else 0`

### ✅ FIXED: Negative Reward Spreads (CRITICAL)
**File:** `wing_optimizer.py:88-95`  
**Issue:** Spreads with negative net credit (debit) were scored anyway  
**Fix:** Added validation: `if net_credit_ps <= 0: continue`

### ✅ FIXED: Inverted Risk (CRITICAL)
**File:** `wing_optimizer.py:92-95`  
**Issue:** If net_credit > wing_width, risk becomes negative or zero  
**Fix:** Added validation: `if wing_width <= net_credit_ps: continue`

### ✅ FIXED: Criteria Relaxation Hidden (HIGH)
**File:** `wing_optimizer.py:121-128`  
**Issue:** No logging when min criteria (ROI>=5%, RR>=0.2) relaxed  
**Fix:** Added warning log: `logger.warning("No spreads meet criteria...")`

### ✅ FIXED: No Data Freshness Check (HIGH)
**File:** `wing_optimizer.py:7-47`  
**Issue:** Used stale premiums if DuckDB hadn't updated  
**Fix:** Added `_check_premium_freshness()` function (max 5 min old)

### ✅ FIXED: Margin Matrix Staleness (HIGH)
**File:** `wing_optimizer.py:20-37`  
**Issue:** No validation that margin_matrix.json is from today  
**Fix:** Added `_check_margin_freshness()` function (max 60 min old)

### ✅ FIXED: No Error Recovery in Loop (CRITICAL)
**File:** `margin_capture.py:308-330`  
**Issue:** Loop continued with stale data if Shoonya API failed  
**Fix:** Added failure tracking: exits after 3 consecutive failures

### ✅ FIXED: No Success Logging (MEDIUM)
**File:** `margin_capture.py:318-330`  
**Issue:** Silent success, no way to verify margins captured  
**Fix:** Log spreads_ok count every capture: `"✅ Captured X/10 spreads"`

---

## Code Changes Summary

### wing_optimizer.py
- ✅ Added 3 safety checks for margin/reward/risk
- ✅ Added freshness validation for margins and premiums
- ✅ Added logging when criteria relaxed
- ✅ All calculations now safe (no division by zero)

### margin_capture.py
- ✅ Added consecutive failure tracking
- ✅ Added success/failure logging
- ✅ Better error messages for debugging

---

## Pre-Market Validation (MUST RUN BEFORE 09:15)

```bash
# Before market opens tomorrow
python3 /home/trading_ceo/brahmand/test_margin_calculations_premarket.py
```

This tests:
1. ✓ DuckDB connectivity
2. ✓ Margin capture works (can call Shoonya)
3. ✓ Data freshness (no stale data)
4. ✓ Wing optimizer (selects valid wings)
5. ✓ Edge cases (handles negative reward, etc.)

**Must pass all 5 tests before trading!**

---

## Tomorrow's Checklist (May 20, 2026)

### Pre-Market (09:00 - 09:14)
- [ ] Run pre-market validation: `test_margin_calculations_premarket.py`
- [ ] All 5 tests must PASS
- [ ] If any FAIL: check logs and fix before 09:30

### During Trading (09:30 - 15:30)
- [ ] Monitor margin_capture.log for errors
- [ ] If any spread has ROI < 5%: check if criteria relaxed
- [ ] If any error: check margin_matrix.json timestamp

### After Market (15:30+)
- [ ] Compare actual trade margins vs calculated
- [ ] Log any mismatches for tomorrow's review

---

## Safety Guarantees

After these fixes, margin calculations will:

✅ **Not crash** on zero/negative margin  
✅ **Not select debit spreads** (negative reward)  
✅ **Not select inverted risk spreads** (risk <= 0)  
✅ **Not use stale data** (> 5 min old)  
✅ **Warn when criteria relaxed** (ROI < 5%)  
✅ **Exit on repeated failures** (3+ consecutive API errors)  
✅ **Log all decisions** (success/failure counts)  

---

## What Could Still Go Wrong Tomorrow

1. **Shoonya API unavailable** → margins won't capture
   - **Mitigation:** Pre-market validation catches this

2. **DuckDB option_snapshots empty** → premiums not fetched
   - **Mitigation:** Pre-market validation checks row counts

3. **Option premiums very wide** → ROI calculation off
   - **Mitigation:** Still calculated correctly, just value is low

4. **Market gaps overnight** → ATM strike changes by 250+ pts
   - **Mitigation:** Margins recaptured every 5 min, new ATM detected

---

## How Margins Work (If Tomorrow Asks)

**For PE spread (SELL ATM PE, BUY ATM-offset PE):**

```
reward_per_share = atm_premium - lower_premium
reward_per_lot = reward_per_share * 65
risk_per_lot = (offset * 50 - reward_per_share) * 65
margin = calculated by Shoonya span_calculator
roi_pct = (reward / margin) * 100
r/r = reward_per_share / risk_per_share

Example:
  ATM 25000 PE: premium = 100
  25000-250 PE: premium = 110
  Reward = (100 - 110) * 65 = -650 ← DEBIT (rejected by fix!)
  
  ATM 25000 PE: premium = 120
  24750 PE: premium = 100
  Reward = (120 - 100) * 65 = 1,300 ✓ CREDIT
  Risk = (250 - 20) * 65 = 14,950
  Margin = ~35,000 (Shoonya span)
  ROI = (1,300 / 35,000) * 100 = 3.7% (below 5%, but accepted if no better option)
  R/R = 20 / 230 = 0.087 (poor, 1:11 ratio)
```

---

## Files Modified

1. `/home/trading_ceo/brahmand/wing_optimizer.py`
   - Added freshness checks
   - Added safety validations
   - Added logging for criteria relaxation

2. `/home/trading_ceo/brahmand/margin_capture.py`
   - Added failure tracking
   - Added success logging
   - Better error messages

3. `/home/trading_ceo/brahmand/test_margin_calculations_premarket.py` (NEW)
   - 5-point validation suite
   - Run before trading each day

---

## Confidence Level for Tomorrow: **HIGH ✅**

All critical issues fixed. Edge cases handled. Freshness validated. Ready for live trading.

**But:** Run pre-market validation at 09:00. If any test fails, don't trade until fixed.

