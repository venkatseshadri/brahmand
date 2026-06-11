#!/usr/bin/env python3
"""SHERPA Phase 2c — iron-fly (original Varaha thesis) backtest + grid.

Tests the thesis the system was DESIGNED around but never executed:
sell ATM CE+PE, buy ±wing hedges, on sideways/calendar entries, with the
documented rules: single position, SL closes the fly (close+recenter),
max re-entries, EOD square-off. Honest costs, NSE margin floor.

Entry modes:
  calendar_all     — first decision point every day (pure theta thesis)
  calendar_exp     — Tuesday (expiry day) only
  calendar_mon_tue — Mon+Tue (closest to the documented NIFTY calendar)
  sideways50       — first point of day with canonical conf<50 or no-go
                     (low directional conviction = sideways signal)

Usage: python3 -m backtest.sherpa.fly_sweep
"""

import itertools
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

BRAHMAND = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BRAHMAND))

from backtest.sherpa import bs_pricer, data_loader

CAPITAL = 200_000.0
LOT_SIZE = 65
EOD_HHMM = "15:25"
REENTRY_CUTOFF = "14:00"
BROKERAGE_PER_ORDER = 20.0
TICK = 0.05
SLIPPAGE_PCT = 0.0025
STAT_CHARGES_PCT = 0.0007
MARGIN_FLOOR_PER_LOT = 35_000.0  # 4-leg fly: short-straddle SPAN after hedge benefit

GRID = {
    "entry_mode": ["calendar_all", "calendar_exp", "calendar_mon_tue", "sideways50"],
    "wing": [100, 200, 300],
    "sl_pct": [0.25, 0.40, 0.60],   # on each sold leg
    "tp_pct": [0.30, 0.50],          # net-premium decay capture
    "reentries": [0, 2],
}

PERIODS = {
    "H1_train": ("2024-01-01", "2024-06-30"),
    "H2_val": ("2024-07-01", "2024-12-31"),
    "Y2025_val": ("2025-01-01", "2025-12-31"),
}


@dataclass
class Fly:
    entry_ts: datetime
    atm: int
    wing: int
    legs: dict          # {"ce_s","pe_s","ce_b","pe_b"} entry fills
    lots: int
    exit_ts: datetime = None
    reason: str = ""
    pnl: float = 0.0
    costs: float = 0.0

    @property
    def credit(self) -> float:
        return self.legs["ce_s"] + self.legs["pe_s"] - self.legs["ce_b"] - self.legs["pe_b"]


def _legs_px(spot, atm, wing, ts, vix):
    return {
        "ce_s": bs_pricer.price_leg(spot, atm, "CE", ts, vix),
        "pe_s": bs_pricer.price_leg(spot, atm, "PE", ts, vix),
        "ce_b": bs_pricer.price_leg(spot, atm + wing, "CE", ts, vix),
        "pe_b": bs_pricer.price_leg(spot, atm - wing, "PE", ts, vix),
    }


def open_fly(spot, ts, vix, wing, capital) -> Fly | None:
    atm = int(round(spot / 50) * 50)
    px = _legs_px(spot, atm, wing, ts, vix)
    fills = {
        "ce_s": px["ce_s"] - (TICK + px["ce_s"] * SLIPPAGE_PCT),
        "pe_s": px["pe_s"] - (TICK + px["pe_s"] * SLIPPAGE_PCT),
        "ce_b": px["ce_b"] + (TICK + px["ce_b"] * SLIPPAGE_PCT),
        "pe_b": px["pe_b"] + (TICK + px["pe_b"] * SLIPPAGE_PCT),
    }
    credit = fills["ce_s"] + fills["pe_s"] - fills["ce_b"] - fills["pe_b"]
    if credit <= 5.0:
        return None
    margin = max((wing - credit) * LOT_SIZE * 1.15, MARGIN_FLOOR_PER_LOT)
    lots = int((capital * 0.95) // margin)
    if lots < 1:
        return None
    return Fly(entry_ts=ts, atm=atm, wing=wing, legs=fills, lots=lots)


def close_fly(fly: Fly, spot, ts, vix, reason):
    px = _legs_px(spot, fly.atm, fly.wing, ts, vix)
    exit_cost = {
        "ce_s": px["ce_s"] + (TICK + px["ce_s"] * SLIPPAGE_PCT),
        "pe_s": px["pe_s"] + (TICK + px["pe_s"] * SLIPPAGE_PCT),
        "ce_b": max(0.0, px["ce_b"] - (TICK + px["ce_b"] * SLIPPAGE_PCT)),
        "pe_b": max(0.0, px["pe_b"] - (TICK + px["pe_b"] * SLIPPAGE_PCT)),
    }
    qty = fly.lots * LOT_SIZE
    gross = (
        (fly.legs["ce_s"] - exit_cost["ce_s"])
        + (fly.legs["pe_s"] - exit_cost["pe_s"])
        + (exit_cost["ce_b"] - fly.legs["ce_b"])
        + (exit_cost["pe_b"] - fly.legs["pe_b"])
    ) * qty
    turnover = sum(fly.legs.values()) * qty + sum(exit_cost.values()) * qty
    fly.costs = round(8 * BROKERAGE_PER_ORDER + turnover * STAT_CHARGES_PCT, 2)
    fly.pnl = round(gross - fly.costs, 2)
    fly.exit_ts = ts
    fly.reason = reason


def fly_exit_check(fly: Fly, spot, ts, vix, sl_pct, tp_pct, hhmm) -> str:
    px = _legs_px(spot, fly.atm, fly.wing, ts, vix)
    if px["ce_s"] >= fly.legs["ce_s"] * (1 + sl_pct):
        return "SL_CE"
    if px["pe_s"] >= fly.legs["pe_s"] * (1 + sl_pct):
        return "SL_PE"
    cur_val = px["ce_s"] + px["pe_s"] - px["ce_b"] - px["pe_b"]
    if cur_val <= fly.credit * (1 - tp_pct):
        return "TP"
    if hhmm >= EOD_HHMM:
        return "EOD"
    return ""


def entry_days_filter(mode: str, d: str) -> bool:
    wd = datetime.fromisoformat(d).weekday()
    if mode == "calendar_exp":
        return wd == 1          # Tuesday expiry
    if mode == "calendar_mon_tue":
        return wd in (0, 1)
    return True                  # calendar_all, sideways50


def first_entry_point(mode: str, day_points: list[dict]) -> dict | None:
    if mode == "sideways50":
        for p in day_points:
            if (not p["go"]) or p["confidence"] < 50:
                return p
        return None
    return day_points[0] if day_points else None


def simulate(points_by_day, bars_by_day, vix_series, cfg) -> dict:
    mode, wing, sl, tp, max_re = cfg
    trades = []
    for d, day_points in points_by_day.items():
        if not entry_days_filter(mode, d):
            continue
        bars = bars_by_day.get(d)
        if bars is None or not day_points:
            continue
        p = first_entry_point(mode, day_points)
        if p is None or p["vix"] is None:
            continue
        entries_left = 1 + max_re
        entry_ts = datetime.fromisoformat(p["ts"])
        spot0, vix0 = p["spot"], p["vix"]

        while entries_left > 0:
            entries_left -= 1
            fly = open_fly(spot0, entry_ts, vix0, wing, CAPITAL)
            if fly is None:
                break
            after = bars[bars.index > str(entry_ts)]
            closed = False
            for bts, row in after.iterrows():
                v = data_loader.vix_at(vix_series, bts) or vix0
                reason = fly_exit_check(fly, float(row["close"]), bts.to_pydatetime(),
                                        v, sl, tp, bts.strftime("%H:%M"))
                if reason:
                    close_fly(fly, float(row["close"]), bts.to_pydatetime(), v, reason)
                    trades.append(fly)
                    closed = True
                    # close+recenter rule: re-enter only on SL, before cutoff
                    if reason.startswith("SL") and entries_left > 0 \
                            and bts.strftime("%H:%M") < REENTRY_CUTOFF:
                        entry_ts = bts.to_pydatetime()
                        spot0 = float(row["close"])
                        vix0 = v
                    else:
                        entries_left = 0
                    break
            if not closed:
                bts = after.index[-1] if len(after) else None
                if bts is not None:
                    v = data_loader.vix_at(vix_series, bts) or vix0
                    close_fly(fly, float(after["close"].iloc[-1]),
                              bts.to_pydatetime(), v, "EOD")
                    trades.append(fly)
                entries_left = 0

    wins = [t for t in trades if t.pnl > 0]
    total = sum(t.pnl for t in trades)
    months = max(1, len({t.entry_ts.strftime("%Y-%m") for t in trades})) if trades else 1
    eq, peak, dd = CAPITAL, CAPITAL, 0.0
    for t in trades:
        eq += t.pnl
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    by_exit = {}
    for t in trades:
        by_exit[t.reason] = by_exit.get(t.reason, 0) + 1
    return {
        "trades": len(trades),
        "win_rate": round(100 * len(wins) / len(trades), 1) if trades else 0,
        "net_pnl": round(total, 0),
        "expectancy": round(total / len(trades), 0) if trades else 0,
        "pct_per_month_on_capital": round(100 * total / CAPITAL / months, 2),
        "max_dd": round(dd, 0),
        "by_exit": by_exit,
    }


def main():
    trace24 = json.loads(
        (BRAHMAND / "backtest/sherpa/trace_2024-01-01_2024-12-31.json").read_text()
    )["points"]
    trace25 = json.loads(
        (BRAHMAND / "backtest/sherpa/trace_2025-01-01_2025-12-31.json").read_text()
    )["points"]

    nifty = data_loader.load_nifty("2024-01-01", "2025-12-31")
    vix = data_loader.load_vix("2024-01-01", "2025-12-31")
    bars_by_day = {str(d): data_loader.day_bars(nifty, d)
                   for d in data_loader.trading_days(nifty)}

    def by_day(points, period):
        out = {}
        for p in points:
            d = p["ts"][:10]
            if period[0] <= d <= period[1]:
                out.setdefault(d, []).append(p)
        return out

    pts = {
        "H1_train": by_day(trace24, PERIODS["H1_train"]),
        "H2_val": by_day(trace24, PERIODS["H2_val"]),
        "Y2025_val": by_day(trace25, PERIODS["Y2025_val"]),
    }

    combos = list(itertools.product(GRID["entry_mode"], GRID["wing"], GRID["sl_pct"],
                                    GRID["tp_pct"], GRID["reentries"]))
    rows = []
    for i, cfg in enumerate(combos):
        res = simulate(pts["H1_train"], bars_by_day, vix, cfg)
        rows.append({"cfg": dict(zip(["mode", "wing", "sl", "tp", "re"], cfg)),
                     "H1_train": res})
        if (i + 1) % 24 == 0:
            print(f"  swept {i + 1}/{len(combos)}")

    rows.sort(key=lambda r: r["H1_train"]["net_pnl"], reverse=True)
    positive = [r for r in rows if r["H1_train"]["net_pnl"] > 0
                and r["H1_train"]["trades"] >= 15]
    print(f"\nH1-train: {len(positive)}/{len(rows)} configs positive (≥15 trades)")

    for r in positive[:12]:
        c = r["cfg"]
        cfg = (c["mode"], c["wing"], c["sl"], c["tp"], c["re"])
        r["H2_val"] = simulate(pts["H2_val"], bars_by_day, vix, cfg)
        r["Y2025_val"] = simulate(pts["Y2025_val"], bars_by_day, vix, cfg)

    out = BRAHMAND / "backtest/sherpa/fly_sweep_results.json"
    out.write_text(json.dumps({"results": rows[:50], "validated_top": positive[:12]},
                              indent=1))

    print(f"\n{'cfg':46s} {'H1 pnl':>9s} {'H2 pnl':>9s} {'2025 pnl':>9s}")
    for r in positive[:12]:
        c = r["cfg"]
        label = f"{c['mode']} w{c['wing']} sl{c['sl']} tp{c['tp']} re{c['re']}"
        print(f"{label:46s} {r['H1_train']['net_pnl']:>9.0f} "
              f"{r.get('H2_val', {}).get('net_pnl', float('nan')):>9.0f} "
              f"{r.get('Y2025_val', {}).get('net_pnl', float('nan')):>9.0f}")
    print(f"\nfull results → {out}")


if __name__ == "__main__":
    main()
