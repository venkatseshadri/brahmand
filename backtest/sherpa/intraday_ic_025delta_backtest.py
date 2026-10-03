#!/usr/bin/env python3
"""Intraday iron condor, 0.25-delta shorts — no directional entry logic at all.

Sidesteps SHERPA's proven-broken NOT_UP/NOT_DOWN direction call entirely
(see sherpa_signal_exit_finding / reverse_move_analysis memory) by selling
BOTH sides, same theta-harvesting idea as PROTON (weekly IC) but held
intraday with per-minute monitoring instead of PROTON's once-daily check.

Strikes are chosen by inverting Black-Scholes delta (not PROTON's RV-based
1SD move) — short call/put strikes where |delta|=0.25 given live VIX as
sigma and REAL time-to-next-weekly-expiry (so DTE varies 0-4 days by entry
weekday; true 0DTE happens when entering on expiry Tuesday itself).

Entry: every trading day, unconditional (no vol filter — testing the
"simple, no entry criteria" hypothesis directly). PT 60% credit captured /
SL 1.0x credit lost / EOD square-off — same params as PROTON for
comparability. Honest costs: 8 orders/round-trip + slippage + STT et al,
same model as weekly_ic_backtest_costed.py.

Usage (from brahmand/):
    python3 -m backtest.sherpa.intraday_ic_025delta_backtest --start 2024-01-01 --end 2024-12-31
"""

import argparse
import json
import math
import sys
from pathlib import Path
from statistics import NormalDist

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, "/home/trading_ceo/projects/antariksh")

from backtest.sherpa import data_loader
from backtester import black_scholes_call, black_scholes_put
from weekly_ic_backtest import next_tuesday_expiry

RISK_FREE_RATE = 0.06
STRIKE_GAP = 50
LOT_SIZE = 75
WING = 150
TARGET_DELTA = 0.25
PT_FRAC = 0.6
SL_MULT = 1.0
ENTRY_TIME = "09:30"
EOD_HHMM = "15:25"
MAX_TRADES_PER_DAY = 3  # same re-entry discipline as SHERPA/iron-fly rules

BROKERAGE_PER_ORDER = 20.0
SLIPPAGE_TICKS = 1
TICK = 0.05
SLIPPAGE_PCT = 0.0025
STAT_CHARGES_PCT = 0.0007

_N = NormalDist()


def delta_strike(S: float, T: float, sigma: float, option_type: str) -> int:
    if T <= 1e-6 or sigma <= 0:
        return round(S / STRIKE_GAP) * STRIKE_GAP
    d1 = _N.inv_cdf(TARGET_DELTA if option_type == "call" else 1 - TARGET_DELTA)
    k = S * math.exp((RISK_FREE_RATE + 0.5 * sigma ** 2) * T - d1 * sigma * math.sqrt(T))
    return round(k / STRIKE_GAP) * STRIKE_GAP


def leg_prices(S, sp, lp, sc, lc, T, sigma):
    return {
        "short_put": black_scholes_put(S, sp, T, RISK_FREE_RATE, sigma),
        "long_put": black_scholes_put(S, lp, T, RISK_FREE_RATE, sigma),
        "short_call": black_scholes_call(S, sc, T, RISK_FREE_RATE, sigma),
        "long_call": black_scholes_call(S, lc, T, RISK_FREE_RATE, sigma),
    }


def combo_value(legs: dict) -> float:
    return (legs["short_put"] - legs["long_put"]) + (legs["short_call"] - legs["long_call"])


def entry_fill(px, is_sell):
    slip = SLIPPAGE_TICKS * TICK + px * SLIPPAGE_PCT
    return max(0.0, px - slip) if is_sell else px + slip


def exit_fill(px, is_sell):
    slip = SLIPPAGE_TICKS * TICK + px * SLIPPAGE_PCT
    return px + slip if is_sell else max(0.0, px - slip)


def run(start: str, end: str, capital: float, trades_out: list = None) -> dict:
    warmup_start = (data_loader.pd.Timestamp(start) - data_loader.pd.Timedelta(days=10)).date().isoformat()
    nifty = data_loader.load_nifty(warmup_start, end)
    vix = data_loader.load_vix(warmup_start, end)
    days = [d for d in data_loader.trading_days(nifty) if str(d) >= start]
    date_set = set(nifty.index.date)

    trades = []
    for d in days:
        bars = data_loader.day_bars(nifty, d)
        if len(bars) < 30:
            continue
        expiry = next_tuesday_expiry(d, {ts for ts in date_set})
        cycle = None
        day_trades = 0
        for ts, row in bars.iterrows():
            hhmm = ts.strftime("%H:%M")
            spot = float(row["close"])
            v = data_loader.vix_at(vix, ts)
            sigma = (v or 15.0) / 100.0

            if cycle is None:
                if hhmm < ENTRY_TIME or day_trades >= MAX_TRADES_PER_DAY:
                    continue
                T = max((data_loader.pd.Timestamp(f"{expiry} 15:30") - ts).total_seconds() / (365 * 86400), 1e-6)
                sp = delta_strike(spot, T, sigma, "put")
                sc = delta_strike(spot, T, sigma, "call")
                lp, lc = sp - WING, sc + WING
                legs0 = leg_prices(spot, sp, lp, sc, lc, T, sigma)
                credit = combo_value(legs0)
                min_credit_to_cover_costs = (8 * BROKERAGE_PER_ORDER) / LOT_SIZE  # don't pay more in fees than credit
                if credit <= max(1.0, min_credit_to_cover_costs):
                    continue  # no real credit at this strike/vol combo — refuse
                entry_fills = {
                    "short_put": entry_fill(legs0["short_put"], True),
                    "long_put": entry_fill(legs0["long_put"], False),
                    "short_call": entry_fill(legs0["short_call"], True),
                    "long_call": entry_fill(legs0["long_call"], False),
                }
                cycle = {"entry_ts": ts, "entry_spot": spot, "sp": sp, "lp": lp, "sc": sc, "lc": lc,
                         "credit": credit, "entry_fills": entry_fills, "expiry": expiry, "T0": T}
                day_trades += 1
                continue

            T = max((data_loader.pd.Timestamp(f"{expiry} 15:30") - ts).total_seconds() / (365 * 86400), 1e-6)
            legs_now = leg_prices(spot, cycle["sp"], cycle["lp"], cycle["sc"], cycle["lc"], T, sigma)
            val = combo_value(legs_now)
            credit = cycle["credit"]
            reason = None
            if val <= credit * (1 - PT_FRAC):
                reason = "PT"
            elif val >= credit * (1 + SL_MULT):
                reason = "SL"
            elif hhmm >= EOD_HHMM:
                reason = "EOD"
            if reason:
                exit_fills = {
                    "short_put": exit_fill(legs_now["short_put"], True),
                    "long_put": exit_fill(legs_now["long_put"], False),
                    "short_call": exit_fill(legs_now["short_call"], True),
                    "long_call": exit_fill(legs_now["long_call"], False),
                }
                raw_pnl = (credit - val) * LOT_SIZE
                turnover = (sum(cycle["entry_fills"].values()) + sum(exit_fills.values())) * LOT_SIZE
                costs = 8 * BROKERAGE_PER_ORDER + turnover * STAT_CHARGES_PCT
                costed_pnl = raw_pnl - costs
                trades.append({
                    "entry_ts": str(cycle["entry_ts"]), "entry_spot": round(cycle["entry_spot"], 2),
                    "exit_ts": str(ts), "exit_spot": round(spot, 2), "reason": reason,
                    "sp": cycle["sp"], "sc": cycle["sc"], "wing": WING,
                    "entry_credit": round(credit, 2), "exit_value": round(val, 2),
                    "dte_at_entry": round(cycle["T0"] * 365, 2),
                    "raw_pnl": round(raw_pnl, 2), "costs": round(costs, 2), "pnl": round(costed_pnl, 2),
                })
                cycle = None
        if cycle is not None:
            # force EOD close on last bar if never triggered (shouldn't happen given EOD_HHMM check, safety net)
            ts = bars.index[-1]
            spot = float(bars["close"].iloc[-1])
            v = data_loader.vix_at(vix, ts) or 15.0
            sigma = v / 100.0
            T = max((data_loader.pd.Timestamp(f"{expiry} 15:30") - ts).total_seconds() / (365 * 86400), 1e-6)
            legs_now = leg_prices(spot, cycle["sp"], cycle["lp"], cycle["sc"], cycle["lc"], T, sigma)
            val = combo_value(legs_now)
            raw_pnl = (cycle["credit"] - val) * LOT_SIZE
            trades.append({"entry_ts": str(cycle["entry_ts"]), "exit_ts": str(ts), "reason": "EOD_FORCE",
                            "sp": cycle["sp"], "sc": cycle["sc"], "wing": WING, "credit": round(cycle["credit"], 2),
                            "dte_at_entry": round(cycle["T0"] * 365, 2),
                            "raw_pnl": round(raw_pnl, 2), "costs": 0, "pnl": round(raw_pnl, 2)})

    if trades_out is not None:
        trades_out.extend(trades)
    return summarize(trades, start, end, capital)


def summarize(trades, start, end, capital) -> dict:
    if not trades:
        return {"trades": 0}
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    months = max(1, len({t["entry_ts"][:7] for t in trades}))
    margin_floor = 30_000.0
    lots = int(capital * 0.95 // margin_floor)
    return {
        "period": f"{start}..{end}", "trades": len(trades),
        "win_rate_pct": round(100 * len(wins) / len(trades), 1),
        "avg_win_per_lot": round(sum(wins) / len(wins), 2) if wins else 0,
        "avg_loss_per_lot": round(sum(losses) / len(losses), 2) if losses else 0,
        "total_pnl_per_lot": round(sum(pnls), 2),
        "worst_per_lot": round(min(pnls), 2),
        "by_exit": {r: len([t for t in trades if t["reason"] == r]) for r in {t["reason"] for t in trades}},
        "months": months, "lots_at_capital": lots,
        "pct_return_per_month": round(100 * sum(pnls) * lots / capital / months, 2),
        "trade_log_sample": trades[:5],
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--capital", type=float, default=200_000.0)
    a = p.parse_args()
    report = run(a.start, a.end, a.capital)
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
