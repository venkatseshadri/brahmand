#!/usr/bin/env python3
"""SHERPA Phase 2b — record the canonical decision trace once per period.

Runs the REAL canonical_strategy.decide_entry at EVERY 5-min decision point
(no trading), recording {ts, go, confidence, signal, strategy, spot, vix}.
The sweep then re-simulates trades over this trace with different
sl/tp/cadence/window/threshold configs without re-running the replay.

Valid because the grid's confidence thresholds (>=35) are supersets of the
canonical internal go-threshold: filtering the trace at a higher threshold
equals re-running with that threshold.

Usage: python3 -m backtest.sherpa.trace_decisions --start 2024-01-01 --end 2024-12-31
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

BRAHMAND = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BRAHMAND))

from backtest.sherpa import data_loader
from backtest.sherpa.replay_io import ReplayIO

WINDOW_START = "09:30"
WINDOW_END = "14:30"
EVERY_MIN = 5


def trace(start: str, end: str, out_path: Path) -> dict:
    import canonical_strategy

    warmup_start = (datetime.fromisoformat(start) - timedelta(days=45)).date().isoformat()
    nifty = data_loader.load_nifty(warmup_start, end)
    vix = data_loader.load_vix(warmup_start, end)
    days = [d for d in data_loader.trading_days(nifty) if str(d) >= start]

    sandbox = BRAHMAND / "backtest" / "sherpa" / "sandbox_trace"
    io = ReplayIO(sandbox)
    hist = nifty[nifty.index.date < days[0]]
    io.seed_emas(data_loader.resample_60m(hist)["close"].tolist())
    io.write_ema_files()

    prev_day_bars = hist[hist.index.date == data_loader.trading_days(hist)[-1]]
    points = []

    for d in days:
        bars = data_loader.day_bars(nifty, d)
        if len(bars) < 30:
            continue
        ytail = [
            {
                "index": "NIFTY", "timestamp": str(ts),
                "open": float(r["open"]), "high": float(r["high"]),
                "low": float(r["low"]), "close": float(r["close"]),
            }
            for ts, r in prev_day_bars.tail(60).iterrows()
        ]
        prev_close = float(prev_day_bars["close"].iloc[-1]) if len(prev_day_bars) else None
        io.start_day(ytail, prev_close)
        last_60m_mark = None

        for ts, row in bars.iterrows():
            hhmm = ts.strftime("%H:%M")
            io.push_minute_bar(str(ts), float(row["open"]), float(row["high"]),
                               float(row["low"]), float(row["close"]))
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

            if not (WINDOW_START <= hhmm <= WINDOW_END) or ts.minute % EVERY_MIN:
                continue
            v = data_loader.vix_at(vix, ts)
            io.set_as_of(str(ts))
            dec = canonical_strategy.decide_entry(vix=v, adx=None, session="mid")
            points.append({
                "ts": str(ts),
                "go": dec["go"],
                "confidence": dec["confidence"],
                "signal": dec["signal"],
                "strategy_type": dec["strategy"]["strategy_type"],
                "wing": dec["strategy"]["wing_width"],
                "spot": float(row["close"]),
                "vix": v,
            })
        prev_day_bars = bars

    io.close()
    out = {"period": f"{start}..{end}", "points": points}
    out_path.write_text(json.dumps(out))
    gos = sum(1 for p in points if p["go"])
    print(f"trace: {len(points)} points, {gos} GO → {out_path}")
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    a = p.parse_args()
    out = BRAHMAND / "backtest" / "sherpa" / f"trace_{a.start}_{a.end}.json"
    trace(a.start, a.end, out)


if __name__ == "__main__":
    main()
