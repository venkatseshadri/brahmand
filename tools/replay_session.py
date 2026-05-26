#!/usr/bin/env python3
"""
Replay Session — time-machine replay of a full trading day, minute by minute.

Feeds historical 1-min bars through the indicator pipeline, entry check,
risk monitor, and kickoff — all in a sandbox. Shows every decision and
parameter so you can debug WHY the system did or didn't act.

Usage:
  python3 tools/replay_session.py data/replays/2026-05-25_NIFTY
  python3 tools/replay_session.py data/replays/2026-05-25_NIFTY --step   # interactive
  python3 tools/replay_session.py data/replays/2026-05-25_NIFTY --fast    # non-stop

Controls (step mode):
  ENTER  — next bar
  s N    — skip N bars
  q      — quit
  d      — dump current state
  t N    — jump to timestamp hh:mm
"""

import argparse
import json
import os
import sys
import time
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


# MUST set env vars before any imports of entry_tools / ema_aggregator
# These modules compute paths at import time — set them NOW.
def _prep_env(sandbox_dir: Path):
    os.environ["BRAHMAND_SANDBOX"] = str(sandbox_dir)
    os.environ["BRAHMAND_REPLAY_REDIS_DB"] = "1"


# Apply env vars from command line as early as possible
for i, arg in enumerate(sys.argv):
    if arg == "data/replays" or arg.startswith("data/replays") or arg.startswith("/"):
        candidate = Path(arg)
        if (candidate / "manifest.json").exists():
            _prep_env(candidate)
            break

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "antariksh"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "python-trader"))


def _trace(trace_file: Path, event_type: str, ts: str, data: dict):
    data["_type"] = event_type
    data["_ts"] = ts
    with open(trace_file, "a") as f:
        f.write(json.dumps(data, default=str) + "\n")


def _indicator_diff(computed: dict, stored: dict) -> dict:
    diffs = {}
    for key in ["ema_5", "ema_20", "ema_50", "rsi", "atr", "adx", "st_direction"]:
        cv = computed.get(key)
        sv = stored.get(key)
        if cv is None and sv is None:
            continue
        if cv is not None and sv is not None:
            diff = abs(float(cv) - float(sv))
            if diff > 0.01:
                diffs[key] = {"computed": cv, "stored": sv, "diff": round(diff, 4)}
        elif cv is not None and sv is None:
            diffs[key] = {"computed": cv, "stored": None, "diff": "computed_only"}
        elif cv is None and sv is not None:
            diffs[key] = {"computed": None, "stored": sv, "diff": "stored_only"}
    return diffs


class _IndicatorBuffer:
    def __init__(self, maxlen: int = 200):
        self.buf = deque(maxlen=maxlen)

    def append(self, o, h, l, c, v=0):
        self.buf.append({"open": o, "high": h, "low": l, "close": c, "volume": v})

    def warmup_from_log(self, path, max_bars=200):
        p = Path(path)
        if not p.exists():
            return
        try:
            for line in p.read_text().splitlines()[-max_bars:]:
                try:
                    bar = json.loads(line)
                    self.append(
                        bar.get("open", 0),
                        bar.get("high", 0),
                        bar.get("low", 0),
                        bar.get("close", 0),
                    )
                except Exception:
                    pass
        except Exception:
            pass

    def compute_indicators(self):
        result = {}
        if len(self.buf) < 5:
            return result
        try:
            import talib

            talib.set_compatibility(1)
            import numpy as np

            closes = np.array([b["close"] for b in self.buf], dtype=float)
            highs = np.array([b["high"] for b in self.buf], dtype=float)
            lows = np.array([b["low"] for b in self.buf], dtype=float)
            if len(closes) >= 5:
                result["ema_5"] = float(talib.EMA(closes, timeperiod=5)[-1])
            if len(closes) >= 20:
                result["ema_20"] = float(talib.EMA(closes, timeperiod=20)[-1])
            if len(closes) >= 50:
                result["ema_50"] = float(talib.EMA(closes, timeperiod=50)[-1])
            if len(closes) >= 14:
                result["rsi"] = float(talib.RSI(closes, timeperiod=14)[-1])
                result["atr"] = float(talib.ATR(highs, lows, closes, timeperiod=14)[-1])
                result["adx"] = float(talib.ADX(highs, lows, closes, timeperiod=14)[-1])
            if len(closes) >= 20:
                try:
                    from orbiter.filters.entry.f4_supertrend import calculate_st_values

                    st = calculate_st_values(
                        highs, lows, closes, period=10, multiplier=3
                    )
                    result["supertrend_direction"] = (
                        "bullish" if closes[-1] > st[-1] else "bearish"
                    )
                except Exception:
                    pass
            talib.set_compatibility(0)
        except Exception:
            pass
        return result


class ReplaySession:
    def __init__(
        self,
        sandbox_dir: Path,
        step_mode: bool = True,
        max_bars: int = None,
        real_kickoff: bool = False,
    ):
        self.sandbox = Path(sandbox_dir)
        self.step_mode = step_mode
        self.max_bars = max_bars
        self.real_kickoff = real_kickoff
        self.manifest = json.loads((self.sandbox / "manifest.json").read_text())
        self.date = self.manifest["date"]
        self.index = self.manifest["index"]
        self.trace_file = self.sandbox / "trace" / f"trace_{self.date}.jsonl"

        self._init_sandbox_state()

    def _init_sandbox_state(self):
        import duckdb, redis

        # DB paths
        suffix = "_sensex" if self.index == "SENSEX" else ""
        self.v31_db = self.sandbox / f"varaha_data{suffix}.duckdb"
        self.multitf_db = (
            self.sandbox / f"market_data_multitf_{self.index.lower()}.duckdb"
        )
        self.trade_exec_db = self.sandbox / "state" / "trade_execution.duckdb"

        # Redis — db=1 for replay isolation
        self.redis = redis.Redis(
            host="localhost", port=6379, db=1, decode_responses=True
        )
        self.redis.flushdb()
        self.redis_queue = f"v3_ohlcv_queue_{self.index}"

        # Load bars from v3.1 DB
        db = duckdb.connect(str(self.v31_db), read_only=True)
        rows = db.execute(f"""
            SELECT timestamp, spot, futures, open_price, prev_close,
                   ema_5, ema_20, ema_50, rsi, atr, adx,
                   supertrend_direction, vwap, bb_pct_b, india_vix,
                   expiry_weekly, atm_strike, data_source, buffer_bars
            FROM market_data
            WHERE date = '{self.date}' AND index_name = '{self.index}'
            ORDER BY timestamp ASC
        """).fetchall()
        db.close()

        self.bars = [
            dict(
                zip(
                    [
                        "timestamp",
                        "spot",
                        "futures",
                        "open_price",
                        "prev_close",
                        "ema_5",
                        "ema_20",
                        "ema_50",
                        "rsi",
                        "atr",
                        "adx",
                        "st_direction",
                        "vwap",
                        "bb_pct_b",
                        "vix",
                        "expiry",
                        "atm_strike",
                        "data_source",
                        "buffer_bars",
                    ],
                    row,
                )
            )
            for row in rows
        ]

        # Stats
        self.bar_idx = 0
        self.total_bars = len(self.bars)
        self.indicator_diffs = []
        self.entry_signals = []
        self.kickoff_results = []
        self.risk_events = []

        # EMA state — start fresh from pre-computed sandbox state
        from ema_aggregator import update_ema, get_ema

        self.update_ema = update_ema
        self.get_ema = get_ema

        # Indicator buffer for capture simulation
        self.buf = _IndicatorBuffer()
        if (
            Path("/home/trading_ceo/brahmand/logs") / f"v3_ohlcv_{self.index}.log"
        ).exists():
            self.buf.warmup_from_log(
                str(
                    Path("/home/trading_ceo/brahmand/logs")
                    / f"v3_ohlcv_{self.index}.log"
                ),
                max_bars=200,
            )

        # Consecutive diffs count for alerting
        self._consecutive_diffs = 0

    def _print_header(self):
        print(f"\n{'=' * 70}")
        print(f" REPLAY: {self.date} {self.index} | {self.total_bars} bars")
        print(f" Sandbox: {self.sandbox.name}")
        print(f" Trace:   {self.trace_file}")
        print(f"{'=' * 70}")
        print(f" ENTER=next | s N=skip N | q=quit | d=dump | t HH:MM=jump\n")

    def _dump_state(self):
        print(
            f"\n--- STATE @ {self.bars[self.bar_idx]['timestamp'] if self.bar_idx < self.total_bars else 'END'} ---"
        )
        print(f"  Bar:        {self.bar_idx}/{self.total_bars}")
        print(f"  Diffs:      {len(self.indicator_diffs)} indicator diffs found")
        if self.indicator_diffs:
            latest = self.indicator_diffs[-1]
            print(f"  Last diff:  {latest}")
        print(f"  Signals:    {len(self.entry_signals)} entry signals")
        if self.entry_signals:
            print(f"  Last signal: {self.entry_signals[-1]}")
        print(f"  Kickoffs:   {len(self.kickoff_results)} kickoff runs")
        if self.kickoff_results:
            for kr in self.kickoff_results[-3:]:
                print(f"  {kr}")
        print(f"  Risk events: {len(self.risk_events)}")
        print(f"  EMA 1min/20:  {self.get_ema('1min', 20)}")
        print(f"  EMA 60min/20: {self.get_ema('60min', 20)}")
        print(f"  Redis queue:  {self.redis.llen(self.redis_queue)} bars")
        print(f"  Buffer:       {len(self.buf.buf)} bars")
        print()

    def _run_one_minute(self) -> dict:
        bar = self.bars[self.bar_idx]
        ts_str = bar["timestamp"]
        dt = datetime.fromisoformat(ts_str) if isinstance(ts_str, str) else ts_str
        spot = float(bar["spot"]) if bar["spot"] else None
        if spot is None:
            return {"status": "skipped", "reason": "no_spot"}

        result = {"ts": ts_str, "spot": spot, "minute": dt.minute, "hour": dt.hour}

        # ── PHASE 1: Indicator computation ──
        self.buf.append(spot, spot, spot, spot, v=1.0)
        computed = self.buf.compute_indicators()

        # Diff against stored values
        stored = {
            k: bar[k]
            for k in ["ema_5", "ema_20", "ema_50", "rsi", "atr", "adx"]
            if bar.get(k)
        }
        stored["st_direction"] = bar.get("st_direction")
        diffs = _indicator_diff(computed, stored)
        if diffs:
            self.indicator_diffs.append({"ts": ts_str, "diffs": diffs})
            self._consecutive_diffs += 1
            result["indicator_diff"] = diffs
        else:
            self._consecutive_diffs = 0

        # ── PHASE 2: Push to Redis ──
        queue_data = {
            "timestamp": ts_str,
            "index": self.index,
            "open": spot,
            "high": spot,
            "low": spot,
            "close": spot,
            "volume": 1.0,
            "ema5": computed.get("ema_5"),
            "ema20": computed.get("ema_20"),
            "ema50": computed.get("ema_50"),
            "rsi": computed.get("rsi"),
            "atr": computed.get("atr"),
            "adx": computed.get("adx"),
            "st_direction": computed.get("supertrend_direction"),
            "bb_pct_b": computed.get("bb_pct_b"),
        }
        self.redis.lpush(self.redis_queue, json.dumps(queue_data))
        self.redis.set(f"prev_close_{self.index}", str(spot))

        # ── PHASE 3: EMA update ──
        self.update_ema(spot, tf="1min")
        if dt.minute % 5 == 0 and dt.minute > 0:
            self.update_ema(spot, tf="5min")
        if dt.minute % 15 == 0 and dt.minute > 0:
            self.update_ema(spot, tf="15min")
        if dt.minute % 60 == 0 and dt.minute > 0:
            self.update_ema(spot, tf="60min")
        if dt.hour == 15 and dt.minute == 30:
            self.update_ema(spot, tf="1D")

        # ── PHASE 4: Risk monitor (every minute) ──
        risk = {
            "ts": ts_str,
            "spot": spot,
            "active_trade": None,
            "alerts": [],
            "morph_stage": 0,
        }
        try:
            state = json.loads(
                (self.sandbox / "state" / "brahmand_kickoff.json").read_text()
            )
            at = state.get("active_trade")
            if at:
                risk["active_trade"] = at.get("trade_id")
                risk["pnl"] = at.get("current_pnl", 0)
                risk["morph_stage"] = at.get("morph_stage", 0)
        except Exception:
            pass
        self.risk_events.append(risk)
        result["risk"] = risk

        # ── PHASE 5: Entry check (based on Redis + EMA sandbox data) ──
        signal = "NEUTRAL"
        confidence = 0
        try:
            latest = json.loads(self.redis.lindex(self.redis_queue, 0) or "{}")
            ema5 = latest.get("ema5")
            ema20 = latest.get("ema20")
            rsi = latest.get("rsi")
            adx = latest.get("adx")
            st_dir = latest.get("st_direction")

            if ema5 and ema20 and ema5 > ema20:
                signal = "BULLISH"
                confidence += 25
            elif ema5 and ema20 and ema5 < ema20:
                signal = "BEARISH"
                confidence -= 25
            if st_dir == "bullish":
                confidence += 15
            elif st_dir == "bearish":
                confidence -= 15
            if rsi and rsi > 60:
                confidence += 10
            elif rsi and rsi < 40:
                confidence -= 10
            if adx and adx > 25:
                confidence += 10
            confidence = max(-50, min(50, confidence))
        except Exception as e:
            entry = {
                "ts": ts_str,
                "signal": "ERROR",
                "confidence": 0,
                "error": str(e)[:80],
            }

        entry = {
            "ts": ts_str,
            "signal": signal,
            "confidence": confidence,
            "ema5": ema5 if "ema5" in dir() else None,
            "ema20": ema20 if "ema20" in dir() else None,
            "rsi": rsi if "rsi" in dir() else None,
        }
        result["entry"] = entry
        self.entry_signals.append(entry)

        # ── PHASE 6: Kickoff (every 5 min) ──
        if dt.minute % 5 == 0 and dt.minute > 0:
            kickoff = {"ts": ts_str, "ran": True, "action": "none", "reason": ""}
            at = risk.get("active_trade")
            signal = result.get("entry", {}).get("signal", "NEUTRAL")
            confidence = result.get("entry", {}).get("confidence", 0)

            if self.real_kickoff:
                try:
                    from kickoff import (
                        main as kickoff_main,
                        release_lock as kl_release,
                        acquire_lock as kl_acquire,
                    )

                    lock_ok = kl_acquire()
                    if lock_ok:
                        kicked = kickoff_main()
                        kl_release()
                    from trade_execution_db import has_active_trades, get_active_trades

                    if has_active_trades():
                        trades = get_active_trades()
                        kickoff["action"] = "trade_active"
                        kickoff["reason"] = f"{len(trades)} active trade(s)"
                        kickoff["trade_ids"] = [t.get("trade_id") for t in trades]
                    else:
                        kickoff["action"] = "kicked"
                        kickoff["reason"] = "kickoff ran — no trade"
                except Exception as e:
                    kickoff["action"] = "error"
                    kickoff["reason"] = f"{type(e).__name__}: {str(e)[:120]}"
            else:
                if not at and signal == "BULLISH" and confidence >= 30:
                    kickoff["action"] = "entry_attempt"
                    kickoff["reason"] = f"signal={signal} confidence={confidence}%"
                elif not at and (signal == "NEUTRAL" or confidence < 30):
                    kickoff["action"] = "no_entry"
                    kickoff["reason"] = f"signal={signal} confidence={confidence}%"
                elif at:
                    kickoff["action"] = "monitor_active"
                    kickoff["reason"] = (
                        f"active_trade={at} morph_stage={risk.get('morph_stage', 0)}"
                    )

            self.kickoff_results.append(kickoff)
            result["kickoff"] = kickoff

        _trace(self.trace_file, "bar", ts_str, result)
        return result

    def _format_minute(self, result: dict) -> str:
        ts = str(result.get("ts", ""))[11:19]
        spot = result.get("spot", 0)
        entry = result.get("entry", {})
        kickoff = result.get("kickoff", {})
        risk = result.get("risk", {})
        diffs = result.get("indicator_diff", {})

        parts = [ts, f"₹{spot:.0f}"]
        if entry:
            parts.append(
                f"{entry.get('signal', '-')[:3]}:{entry.get('confidence', 0)}%"
            )
        if kickoff:
            act = kickoff.get("action", "-")
            if act == "error":
                parts.append(f"K:ERR")
            elif act in (
                "entry_attempt",
                "no_entry",
                "monitor_active",
                "kicked",
                "trade_active",
            ):
                parts.append(f"K:{act}")
        if diffs:
            parts.append(f"DIFF:{','.join(diffs.keys())[:15]}")
        if risk.get("alerts"):
            parts.append(f"RISK:{','.join(risk['alerts'])[:10]}")
        if hasattr(self, "real_kickoff") and self.real_kickoff:
            ki = kickoff or {}
            rid = ki.get("reason", "")[:20]
            if rid:
                parts.append(f"[{rid}]")

        return " | ".join(parts)

    def run(self):
        self._print_header()

        while self.bar_idx < self.total_bars:
            if self.max_bars and self.bar_idx >= self.max_bars:
                break

            result = self._run_one_minute()
            ts = result.get("ts", "")
            line = self._format_minute(result)
            print(f"[{self.bar_idx + 1:03d}/{self.total_bars}] {line}")

            self.bar_idx += 1

            if self.step_mode:
                cmd = input("> ").strip().lower()
                if cmd == "q":
                    print(f"Quit at bar {self.bar_idx}/{self.total_bars}")
                    break
                if cmd.startswith("s"):
                    try:
                        n = int(cmd.split()[1]) if len(cmd.split()) > 1 else 1
                        for _ in range(n):
                            if self.bar_idx >= self.total_bars:
                                break
                            result = self._run_one_minute()
                            print(
                                f"[{self.bar_idx + 1:03d}/{self.total_bars}] {self._format_minute(result)}"
                            )
                            self.bar_idx += 1
                        continue
                    except (IndexError, ValueError):
                        pass
                if cmd == "d":
                    self._dump_state()
                    continue
                if cmd.startswith("t"):
                    try:
                        target = cmd.split()[1]
                        h, m = target.split(":")
                        target_ts = f"{self.date}T{h}:{m}:00"
                        for i, b in enumerate(self.bars):
                            if b["timestamp"].startswith(target_ts):
                                self.bar_idx = i
                                print(f"Jumped to bar {i + 1}: {b['timestamp']}")
                                break
                    except (IndexError, ValueError):
                        print("Usage: t HH:MM (e.g., t 10:15)")
                    continue

        self._print_summary()

    def _print_summary(self):
        n_diffs = len(self.indicator_diffs)
        n_signals = len(self.entry_signals)
        n_kickoffs = len(self.kickoff_results)
        n_risk = len(self.risk_events)
        entries_attempted = [
            k for k in self.kickoff_results if k.get("action") == "entry_attempt"
        ]
        no_entries = [k for k in self.kickoff_results if k.get("action") == "no_entry"]
        bullish_signals = len(
            [s for s in self.entry_signals if s.get("signal") == "BULLISH"]
        )
        bearish_signals = len(
            [s for s in self.entry_signals if s.get("signal") == "BEARISH"]
        )

        print(f"\n{'=' * 60}")
        print(f" REPLAY SUMMARY — {self.date} {self.index}")
        print(f"{'=' * 60}")
        print(f" Bars replayed:       {self.bar_idx}")
        print(f" Indicator diffs:     {n_diffs}") if n_diffs else print(
            f" Indicator diffs:     ✅ 0 — all match"
        )
        print(
            f" Entry signals:       {n_signals} ({bullish_signals}BULL / {bearish_signals}BEAR)"
        )
        print(f" Kickoff runs:        {n_kickoffs}")
        print(f"  - Entry attempted:  {len(entries_attempted)}")
        print(f"  - Entry skipped:    {len(no_entries)}")
        print(f" Risk events:         {n_risk}")
        print(f"\n Trace saved:         {self.trace_file}")
        print(
            f" Redis db=1 flushed:  {self.redis_queue} ← {self.redis.llen(self.redis_queue)} bars remain"
        )
        print(f"{'=' * 60}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Replay Session — time-machine minute-by-minute"
    )
    parser.add_argument("sandbox", help="Path to sandbox directory from setup")
    parser.add_argument(
        "--step",
        action="store_true",
        default=True,
        help="Interactive step-through (default)",
    )
    parser.add_argument(
        "--fast", action="store_true", help="Run all bars without stopping"
    )
    parser.add_argument("--max", type=int, help="Stop after N bars")
    parser.add_argument(
        "--real", action="store_true", help="Run REAL kickoff agents with LLM calls"
    )
    args = parser.parse_args()

    sandbox = Path(args.sandbox)
    if not sandbox.exists():
        print(f"Sandbox not found: {sandbox}")
        print("Run setup first: python3 tools/replay_setup.py YYYY-MM-DD --index NIFTY")
        sys.exit(1)

    session = ReplaySession(
        sandbox, step_mode=not args.fast, max_bars=args.max, real_kickoff=args.real
    )
    session.run()


if __name__ == "__main__":
    main()
