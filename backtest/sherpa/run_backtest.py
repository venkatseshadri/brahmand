#!/usr/bin/env python3
"""SHERPA Phase 2 — backtest orchestrator.

Drives the REAL canonical_strategy.decide_entry over historical NIFTY minute
bars via the production I/O seams (no strategy reimplementation), simulates
the decided spreads with BS premiums + honest costs, and emits the 3 Board
numbers.

Usage (from brahmand/):
    python3 -m backtest.sherpa.run_backtest --start 2024-01-01 --end 2024-12-31
"""

import argparse
import dataclasses
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

BRAHMAND = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BRAHMAND))

from backtest.sherpa import data_loader, trade_sim
from backtest.sherpa.replay_io import ReplayIO

ENTRY_START = "09:30"
ENTRY_END = "14:30"
DECISION_EVERY_MIN = 5
EOD_HHMM = "15:25"
CAPITAL = 200_000.0
MAX_TRADES_PER_DAY = 3  # live iron-fly discipline: initial entry + 2 re-entries
ATR_TF_MIN = 15
ATR_PERIOD = 14
ATR_MEDIAN_LOOKBACK_BARS = 130  # ~5 trading days of 15-min bars


def _atr_ratio_series(nifty: pd.DataFrame) -> pd.Series:
    """15-min ATR(14) / its own trailing ~5-day median, forward-filled onto the
    1-min index. >1 = currently more volatile than its own recent norm."""
    g = nifty.resample(f"{ATR_TF_MIN}min", origin="start_day", offset="15min")
    tf = pd.DataFrame({
        "high": g["high"].max(), "low": g["low"].min(), "close": g["close"].last(),
    }).dropna()
    tr = pd.concat([
        tf["high"] - tf["low"],
        (tf["high"] - tf["close"].shift()).abs(),
        (tf["low"] - tf["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / ATR_PERIOD, adjust=False).mean()
    median_atr = atr.rolling(ATR_MEDIAN_LOOKBACK_BARS, min_periods=20).median()
    ratio = (atr / median_atr).shift(1)  # shift 1: only use last COMPLETED bar's ATR
    return ratio.reindex(nifty.index, method="ffill")


def run(start: str, end: str, capital: float, out_path: Path, signal_exit_log: list = None,
        atr_sl_multiplier: float = None) -> dict:
    """signal_exit_log: if given, appends a shadow-exit record each time the live
    NOT_UP/NOT_DOWN entry signal flips against an open trade (mirror of decide_entry,
    re-run during the trade instead of at entry). Does not alter real exits/PnL —
    default None reproduces the original SHERPA numbers unchanged.

    atr_sl_multiplier: if given, replaces the fixed sl_pct with
    base_sl_pct * clip(current_ATR/trailing_median_ATR, 0.5, 2.0) * multiplier
    at entry time — SL widens on high-vol days, tightens on quiet ones. TP/EOD
    untouched, isolating the effect to the SL leg. Default None = fixed sl_pct,
    original SHERPA behavior."""
    import canonical_strategy

    warmup_start = (datetime.fromisoformat(start) - timedelta(days=45)).date().isoformat()
    nifty = data_loader.load_nifty(warmup_start, end)
    vix = data_loader.load_vix(warmup_start, end)
    days = [d for d in data_loader.trading_days(nifty) if str(d) >= start]
    if not days:
        raise SystemExit(f"no trading days in [{start}, {end}]")

    atr_ratio = _atr_ratio_series(nifty) if atr_sl_multiplier is not None else None

    sandbox = BRAHMAND / "backtest" / "sherpa" / "sandbox"
    io = ReplayIO(sandbox)

    # EMA warmup from pre-start history
    hist = nifty.loc[: str(days[0])]
    hist = hist[hist.index.date < days[0]]
    closes_60m = data_loader.resample_60m(hist)["close"].tolist()
    io.seed_emas(closes_60m)
    io.write_ema_files()

    trades: list[trade_sim.Trade] = []
    decisions = {"go": 0, "no_go": 0, "refused_pricing": 0}
    equity = capital
    equity_curve = []
    prev_day_bars = hist[hist.index.date == data_loader.trading_days(hist)[-1]]

    for d in days:
        bars = data_loader.day_bars(nifty, d)
        if len(bars) < 30:
            continue
        # yesterday tail (newest-last chronological) for 1440m/gap logic
        ytail = [
            {
                "index": "NIFTY",
                "timestamp": str(ts),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
            }
            for ts, r in prev_day_bars.tail(60).iterrows()
        ]
        prev_close = float(prev_day_bars["close"].iloc[-1]) if len(prev_day_bars) else None
        io.start_day(ytail, prev_close)

        open_trade: trade_sim.Trade | None = None
        day_trades = 0
        last_60m_mark = None
        flip_logged = False
        pending_signal = None

        for ts, row in bars.iterrows():
            hhmm = ts.strftime("%H:%M")
            io.push_minute_bar(
                str(ts), float(row["open"]), float(row["high"]),
                float(row["low"]), float(row["close"]),
            )
            # completed 60-min bar → EMA update (09:15 grid: 10:15, 11:15, …)
            slot = (ts.hour * 60 + ts.minute - (9 * 60 + 15)) // 60
            if last_60m_mark is None:
                last_60m_mark = slot
            elif slot > last_60m_mark:
                done = bars[(bars.index <= ts)]
                seg = done[done.index.map(
                    lambda x: (x.hour * 60 + x.minute - (9 * 60 + 15)) // 60
                ) == last_60m_mark]
                if len(seg):
                    io.push_60m_close(float(seg["close"].iloc[-1]))
                    io.write_ema_files()
                last_60m_mark = slot

            spot = float(row["close"])
            v = data_loader.vix_at(vix, ts)

            # manage the open position every minute
            if open_trade is not None:
                sell_px, buy_px = trade_sim.mark(open_trade, spot, ts.to_pydatetime(), v or 15.0)
                reason = trade_sim.check_exit(open_trade, sell_px, hhmm, EOD_HHMM)
                if reason:
                    trade_sim.close_trade(open_trade, sell_px, buy_px, ts.to_pydatetime(), reason)
                    equity += open_trade.pnl
                    trades.append(open_trade)
                    if pending_signal is not None:
                        pending_signal.update(
                            actual_exit_ts=str(ts), actual_exit_reason=reason,
                            actual_pnl=open_trade.pnl,
                        )
                        signal_exit_log.append(pending_signal)
                        pending_signal = None
                    open_trade = None
                    continue
                if signal_exit_log is not None and not flip_logged and ts.minute % DECISION_EVERY_MIN == 0:
                    io.set_as_of(str(ts))
                    live = canonical_strategy.decide_entry(vix=v, adx=None, session="mid")
                    opposite = "NOT_DOWN" if open_trade.strategy == "CALL_SPREAD" else "NOT_UP"
                    if live["go"] and live["signal"] == opposite:
                        shadow = dataclasses.replace(open_trade)
                        trade_sim.close_trade(shadow, sell_px, buy_px, ts.to_pydatetime(), "SIGNAL_FLIP")
                        pending_signal = {
                            "entry_ts": str(open_trade.entry_ts),
                            "strategy": open_trade.strategy,
                            "flip_ts": str(ts),
                            "signal_pnl": shadow.pnl,
                            "minutes_since_entry": round(
                                (ts.to_pydatetime() - open_trade.entry_ts).total_seconds() / 60, 1
                            ),
                        }
                        flip_logged = True
                continue

            # decision points: every 5 min inside the entry window, flat only,
            # capped at the live re-entry discipline
            if day_trades >= MAX_TRADES_PER_DAY:
                continue
            if not (ENTRY_START <= hhmm <= ENTRY_END) or ts.minute % DECISION_EVERY_MIN:
                continue
            io.set_as_of(str(ts))
            decision = canonical_strategy.decide_entry(vix=v, adx=None, session="mid")
            if not decision["go"]:
                decisions["no_go"] += 1
                continue
            decisions["go"] += 1
            wing = decision["strategy"]["wing_width"]
            probe = trade_sim.open_trade(decision, spot, ts.to_pydatetime(), v, lots=1)
            if probe is None:
                decisions["refused_pricing"] += 1
                continue
            lots = trade_sim.max_lots(capital, wing, probe.net_credit)
            if lots < 1:
                decisions["refused_pricing"] += 1
                continue
            open_trade = trade_sim.open_trade(decision, spot, ts.to_pydatetime(), v, lots=lots)
            if atr_sl_multiplier is not None and open_trade is not None:
                ratio = atr_ratio.get(ts, None)
                if ratio is not None and not pd.isna(ratio):
                    ratio = min(max(ratio, 0.5), 2.0)
                    open_trade.sl_pct = open_trade.sl_pct * ratio * atr_sl_multiplier
            flip_logged = False
            pending_signal = None
            day_trades += 1

        # day end: force-close anything still open at the last bar
        if open_trade is not None:
            ts = bars.index[-1]
            v = data_loader.vix_at(vix, ts) or 15.0
            sell_px, buy_px = trade_sim.mark(open_trade, float(bars["close"].iloc[-1]),
                                             ts.to_pydatetime(), v)
            trade_sim.close_trade(open_trade, sell_px, buy_px, ts.to_pydatetime(), "EOD")
            equity += open_trade.pnl
            trades.append(open_trade)
            if pending_signal is not None:
                pending_signal.update(
                    actual_exit_ts=str(ts), actual_exit_reason="EOD",
                    actual_pnl=open_trade.pnl,
                )
                signal_exit_log.append(pending_signal)
                pending_signal = None
            open_trade = None

        equity_curve.append({"date": str(d), "equity": round(equity, 2)})
        prev_day_bars = bars

    io.close()
    report = _report(trades, decisions, equity_curve, capital, start, end)
    out_path.write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report["board_numbers"], indent=2))
    print(f"\nfull report → {out_path}")
    return report


def _report(trades, decisions, equity_curve, capital, start, end) -> dict:
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    total_pnl = sum(t.pnl for t in trades)
    total_costs = sum(t.costs for t in trades)

    peak, max_dd = capital, 0.0
    for pt in equity_curve:
        peak = max(peak, pt["equity"])
        max_dd = max(max_dd, peak - pt["equity"])

    months = max(1, len({pt["date"][:7] for pt in equity_curve}))
    avg_margin = (
        sum(t.max_loss_per_lot * 1.15 * t.lots for t in trades) / len(trades)
        if trades else 0
    )
    sample = trades[len(trades) // 2] if trades else None

    return {
        "meta": {
            "period": f"{start}..{end}",
            "engine": "REAL canonical_strategy.decide_entry via production I/O seams",
            "premiums": "Black-Scholes, IV=VIX (flat smile) — Tier-B calibration pending",
            "contract_spec": "today's regime: Tue weekly expiry, lot 65, wing/SL/TP from canonical params",
            "capital": capital,
        },
        "decisions": decisions,
        "trades": {
            "count": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate_pct": round(100 * len(wins) / len(trades), 1) if trades else 0,
            "total_pnl_net": round(total_pnl, 2),
            "total_costs": round(total_costs, 2),
            "by_exit": {
                r: len([t for t in trades if t.exit_reason == r])
                for r in {t.exit_reason for t in trades}
            },
        },
        "board_numbers": {
            "1_return_on_capital_pct_per_month": round(100 * total_pnl / capital / months, 2),
            "1b_return_on_avg_margin_pct_per_month": (
                round(100 * total_pnl / avg_margin / months, 2) if avg_margin else None
            ),
            "2_avg_win": round(sum(t.pnl for t in wins) / len(wins), 0) if wins else 0,
            "2_avg_loss": round(sum(t.pnl for t in losses) / len(losses), 0) if losses else 0,
            "2_win_rate_pct": round(100 * len(wins) / len(trades), 1) if trades else 0,
            "3_max_lots_on_capital": sample.lots if sample else None,
            "3_margin_per_lot": round(sample.max_loss_per_lot * 1.15, 0) if sample else None,
            "max_drawdown": round(max_dd, 2),
            "months": months,
        },
        "equity_curve": equity_curve,
        "trade_log": [
            {
                "entry": str(t.entry_ts), "exit": str(t.exit_ts), "strategy": t.strategy,
                "sell_k": t.sell_strike, "buy_k": t.buy_strike, "lots": t.lots,
                "credit": round(t.net_credit, 2), "reason": t.exit_reason,
                "sell_entry": t.sell_entry, "sell_exit": t.sell_exit,
                "buy_entry": t.buy_entry, "buy_exit": t.buy_exit,
                "pnl": t.pnl, "costs": t.costs,
            }
            for t in trades
        ],
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--capital", type=float, default=CAPITAL)
    p.add_argument("--out", default=None)
    a = p.parse_args()
    out = Path(a.out) if a.out else BRAHMAND / "backtest" / "sherpa" / f"report_{a.start}_{a.end}.json"
    run(a.start, a.end, a.capital, out)


if __name__ == "__main__":
    main()
