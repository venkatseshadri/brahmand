#!/usr/bin/env python3
"""SHERPA Phase 2 — Black-Scholes premium model, IV anchored to INDIA VIX.

Approximations (documented for the Board report):
  - flat IV = VIX/100 across strikes (no smile); near-expiry weeklies usually
    trade slightly above VIX → premiums here are mildly conservative on credit
  - European exercise, r = 6.5%, no dividends (index options are European)
  - Tier-B calibration against the 13 real option-chain days is a follow-up
"""

from datetime import datetime, timedelta
from math import erf, exp, log, sqrt

RISK_FREE = 0.065
MINUTES_PER_YEAR = 365.0 * 24 * 60


def _N(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def bs_price(spot: float, strike: float, t_years: float, iv: float, opt_type: str) -> float:
    """European option price; floors at intrinsic when t or iv degenerate."""
    intrinsic = max(0.0, spot - strike) if opt_type == "CE" else max(0.0, strike - spot)
    if t_years <= 0 or iv <= 0:
        return round(intrinsic, 2)
    sq = iv * sqrt(t_years)
    d1 = (log(spot / strike) + (RISK_FREE + iv * iv / 2.0) * t_years) / sq
    d2 = d1 - sq
    if opt_type == "CE":
        px = spot * _N(d1) - strike * exp(-RISK_FREE * t_years) * _N(d2)
    else:
        px = strike * exp(-RISK_FREE * t_years) * _N(-d2) - spot * _N(-d1)
    return round(max(px, intrinsic), 2)


def next_weekly_expiry(ts: datetime) -> datetime:
    """Next Tuesday 15:30 (current NIFTY weekly regime — structural backtest
    applies today's contract spec to historical price dynamics)."""
    days_ahead = (1 - ts.weekday()) % 7  # Tuesday = 1
    expiry_day = (ts + timedelta(days=days_ahead)).date()
    expiry = datetime.combine(expiry_day, datetime.min.time()).replace(hour=15, minute=30)
    if expiry <= ts:  # Tuesday after the close → next week
        expiry += timedelta(days=7)
    return expiry


def t_to_expiry_years(ts: datetime, expiry: datetime) -> float:
    return max(0.0, (expiry - ts).total_seconds() / 60.0 / MINUTES_PER_YEAR)


def price_leg(spot: float, strike: float, opt_type: str, ts: datetime, vix: float) -> float:
    expiry = next_weekly_expiry(ts)
    return bs_price(spot, strike, t_to_expiry_years(ts, expiry), vix / 100.0, opt_type)
