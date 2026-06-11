#!/usr/bin/env python3
"""SHERPA Phase 2b — parameter sweep over the recorded decision trace.

Grid: confidence threshold × sl_pct × tp_pct × max trades/day × entry window.
Train on 2024-H1; any config with positive net expectancy is validated
out-of-sample on 2024-H2 and 2025. Strategy logic untouched — thresholds are
applied as trace filters (supersets of the canonical internal gate) and
sl/tp via the decision dict the simulator consumes.

Usage: python3 -m backtest.sherpa.sweep
"""

import itertools
import json
import sys
from pathlib import Path

BRAHMAND = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BRAHMAND))

from backtest.sherpa import data_loader, trade_sim

CAPITAL = 200_000.0
EOD_HHMM = "15:25"

GRID = {
    "conf": [35, 50, 60, 70],
    "sl_pct": [0.25, 0.40, 0.60],
    "tp_pct": [0.30, 0.50, 0.70],
    "max_per_day": [1, 2, 3],
    "window": [("09:30", "11:30"), ("09:30", "14:30")],
}

PERIODS = {
    "H1_train": ("2024-01-01", "2024-06-30"),
    "H2_val": ("2024-07-01", "2024-12-31"),
    "Y2025_val": ("2025-01-01", "2025-12-31"),
}


def load_trace(path: Path) -> list[dict]:
    return json.loads(path.read_text())["points"]


def in_period(ts: str, period: tuple[str, str]) -> bool:
    return period[0] <= ts[:10] <= period[1]


def simulate(points: list[dict], bars_by_day, vix_series, cfg) -> dict:
    """Fast re-simulation: trades from trace GO points, minute-managed exits."""
    conf, sl, tp, max_day, window = cfg
    trades = []
    open_until = None  # ts string until which we're busy (position open)
    day_count = {}

    for p in points:
        ts = p["ts"]
        d, hhmm = ts[:10], ts[11:16]
        if not (window[0] <= hhmm <= window[1]):
            continue
        if day_count.get(d, 0) >= max_day:
            continue
        if open_until and ts <= open_until:
            continue
        if not p["go"] or p["confidence"] < conf or p["vix"] is None:
            continue

        decision = {
            "strategy": {
                "strategy_type": p["strategy_type"],
                "wing_width": p["wing"],
                "sl_pct": sl,
                "tp_pct": tp,
            }
        }
        import datetime as _dtm

        entry_ts = _dtm.datetime.fromisoformat(ts)
        probe = trade_sim.open_trade(decision, p["spot"], entry_ts, p["vix"], lots=1)
        if probe is None:
            continue
        lots = trade_sim.max_lots(CAPITAL, p["wing"], probe.net_credit)
        if lots < 1:
            continue
        trade = trade_sim.open_trade(decision, p["spot"], entry_ts, p["vix"], lots=lots)

        # minute-by-minute management on the day's bars
        bars = bars_by_day.get(d)
        if bars is None:
            continue
        after = bars[bars.index > ts]
        closed = False
        for bts, row in after.iterrows():
            v = data_loader.vix_at(vix_series, bts) or p["vix"]
            sell_px, buy_px = trade_sim.mark(trade, float(row["close"]),
                                             bts.to_pydatetime(), v)
            reason = trade_sim.check_exit(trade, sell_px, bts.strftime("%H:%M"), EOD_HHMM)
            if reason:
                trade_sim.close_trade(trade, sell_px, buy_px, bts.to_pydatetime(), reason)
                closed = True
                break
        if not closed:
            bts = after.index[-1] if len(after) else entry_ts
            row_close = float(after["close"].iloc[-1]) if len(after) else p["spot"]
            v = data_loader.vix_at(vix_series, bts) or p["vix"]
            sell_px, buy_px = trade_sim.mark(trade, row_close, bts.to_pydatetime(), v)
            trade_sim.close_trade(trade, sell_px, buy_px, bts.to_pydatetime(), "EOD")
        trades.append(trade)
        day_count[d] = day_count.get(d, 0) + 1
        open_until = str(trade.exit_ts)

    wins = [t for t in trades if t.pnl > 0]
    total = sum(t.pnl for t in trades)
    months = max(1, len({t.entry_ts.strftime("%Y-%m") for t in trades})) if trades else 1
    eq, peak, dd = CAPITAL, CAPITAL, 0.0
    for t in trades:
        eq += t.pnl
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {
        "trades": len(trades),
        "win_rate": round(100 * len(wins) / len(trades), 1) if trades else 0,
        "net_pnl": round(total, 0),
        "expectancy": round(total / len(trades), 0) if trades else 0,
        "pct_per_month_on_capital": round(100 * total / CAPITAL / months, 2),
        "max_dd": round(dd, 0),
    }


def main():
    trace24 = load_trace(BRAHMAND / "backtest/sherpa/trace_2024-01-01_2024-12-31.json")
    trace25 = load_trace(BRAHMAND / "backtest/sherpa/trace_2025-01-01_2025-12-31.json")

    nifty = data_loader.load_nifty("2024-01-01", "2025-12-31")
    vix = data_loader.load_vix("2024-01-01", "2025-12-31")
    bars_by_day = {str(d): data_loader.day_bars(nifty, d)
                   for d in data_loader.trading_days(nifty)}

    pts = {
        "H1_train": [p for p in trace24 if in_period(p["ts"], PERIODS["H1_train"])],
        "H2_val": [p for p in trace24 if in_period(p["ts"], PERIODS["H2_val"])],
        "Y2025_val": trace25,
    }

    rows = []
    combos = list(itertools.product(GRID["conf"], GRID["sl_pct"], GRID["tp_pct"],
                                    GRID["max_per_day"], GRID["window"]))
    for i, cfg in enumerate(combos):
        res = simulate(pts["H1_train"], bars_by_day, vix, cfg)
        rows.append({"cfg": {
            "conf": cfg[0], "sl": cfg[1], "tp": cfg[2],
            "per_day": cfg[3], "window": f"{cfg[4][0]}-{cfg[4][1]}",
        }, "H1_train": res})
        if (i + 1) % 24 == 0:
            print(f"  swept {i + 1}/{len(combos)}")

    rows.sort(key=lambda r: r["H1_train"]["net_pnl"], reverse=True)
    positive = [r for r in rows if r["H1_train"]["net_pnl"] > 0
                and r["H1_train"]["trades"] >= 20]

    print(f"\nH1-train: {len(positive)}/{len(rows)} configs positive (≥20 trades)")
    for r in positive[:10]:
        cfg = tuple([r["cfg"]["conf"], r["cfg"]["sl"], r["cfg"]["tp"], r["cfg"]["per_day"],
                     tuple(r["cfg"]["window"].split("-"))])
        r["H2_val"] = simulate(pts["H2_val"], bars_by_day, vix, cfg)
        r["Y2025_val"] = simulate(pts["Y2025_val"], bars_by_day, vix, cfg)

    out = BRAHMAND / "backtest/sherpa/sweep_results.json"
    out.write_text(json.dumps({"grid": {k: str(v) for k, v in GRID.items()},
                               "results": rows[:40],
                               "validated_top10": positive[:10]}, indent=1))

    print(f"\n{'cfg':52s} {'H1 pnl':>9s} {'H2 pnl':>9s} {'2025 pnl':>9s}")
    for r in positive[:10]:
        c = r["cfg"]
        label = f"conf≥{c['conf']} sl{c['sl']} tp{c['tp']} {c['per_day']}/d {c['window']}"
        print(f"{label:52s} {r['H1_train']['net_pnl']:>9.0f} "
              f"{r.get('H2_val', {}).get('net_pnl', float('nan')):>9.0f} "
              f"{r.get('Y2025_val', {}).get('net_pnl', float('nan')):>9.0f}")
    print(f"\nfull results → {out}")


if __name__ == "__main__":
    main()
