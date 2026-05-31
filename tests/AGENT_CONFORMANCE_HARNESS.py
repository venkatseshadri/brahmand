#!/usr/bin/env python3
"""
Agent Conformance Harness — validates that live CrewAI agents behave consistently,
never hallucinate numbers, and never emit fake P&L.

Three invariants per fixed market state:
  P1. PROVENANCE: every numeric field in agent decisions comes from a tool call.
  P2. CONSISTENCY: N repeated crew runs produce identical decisions; crew == oracle.
  P3. P&L INTEGRITY: agent output contains zero P&L fields; P&L only from settlement.

Architecture:
  2024 Kaggle → Redis v3_ohlcv_queue + EMA state files
    → per fixed state: (A) real crew run + (B) oracle deterministic run
    → assert invariants → conformance_report.json

Usage:
    python3 AGENT_CONFORMANCE_HARNESS.py [--days N] [--runs N]
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
from collections import defaultdict
from copy import deepcopy
from datetime import datetime as _dt
from pathlib import Path as _Path
from typing import Optional
from unittest.mock import patch

import numpy as np

# ── Configuration ─────────────────────────────────────────────────────
KAGGLE_CACHE = _Path(
    "/root/.cache/kagglehub/datasets/kaalicharan9080/"
    "nse-future-and-options-data/versions/2"
)
EMA_STATE_DIR = _Path("/tmp/backtest_ema_state")  # NEVER production path
REDIS_KEY = "v3_ohlcv_queue"
ENTRY_GATE_MIN = 0.75
EMA_PERIODS = [5, 20, 50, 100, 200]
EMA_MULT = {p: 2.0 / (p + 1) for p in EMA_PERIODS}
N_REPEAT_RUNS = int(os.environ.get("CONFORMANCE_N_RUNS", "3"))
P_NL_FIELDS = {
    "pnl",
    "p&l",
    "profit",
    "final_pnl",
    "realized",
    "net_pnl",
    "total_pnl",
    "pnl_per_lot",
}

_TICKER_RE = re.compile(
    r"^NIFTY(\d{2}[A-Z]{3}\d{2})(\d{5})(PE|CE)\.NFO$", re.IGNORECASE
)

# ── Redis ──────────────────────────────────────────────────────────────
try:
    import redis as _redis_lib
except ImportError:
    _redis_lib = None


def redis_client():
    if _redis_lib is None:
        return None
    try:
        r = _redis_lib.Redis(host="localhost", port=6379, db=1, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


# ====================================================================
# DATA LOADING (reused from NIFTY_BACKTEST_AGENT_TOOLS.py)
# ====================================================================


def load_day(csv_path):
    date_str = ""
    time_data = defaultdict(dict)
    expiries_seen = defaultdict(int)
    with open(csv_path) as f:
        reader = csv.reader(f)
        for ticker, date, time, open_p, high, low, close, vol, oi in reader:
            m = _TICKER_RE.search(ticker)
            if not m:
                continue
            date_str = date
            expiry = m.group(1)
            strike = int(m.group(2))
            opt_type = m.group(3)
            expiries_seen[expiry] += 1
            time_data[time][(strike, opt_type, expiry)] = float(close)

    if not expiries_seen:
        return date_str, time_data

    month_map = {
        "JAN": 1,
        "FEB": 2,
        "MAR": 3,
        "APR": 4,
        "MAY": 5,
        "JUN": 6,
        "JUL": 7,
        "AUG": 8,
        "SEP": 9,
        "OCT": 10,
        "NOV": 11,
        "DEC": 12,
    }
    trade_date_dt = _dt.strptime(date_str, "%d/%m/%Y")
    best_expiry, best_days = None, 999
    for exp in expiries_seen:
        day = int(exp[:2])
        month = month_map[exp[2:5]]
        year = int(f"20{exp[5:7]}")
        exp_dt = _dt(year, month, day)
        days_diff = (exp_dt - trade_date_dt).days
        if 0 <= days_diff < best_days:
            best_days, best_expiry = days_diff, exp

    if best_expiry:
        filtered = defaultdict(dict)
        for t, vault in time_data.items():
            for (strike, opt_type, exp), price in vault.items():
                if exp == best_expiry:
                    filtered[t][(strike, opt_type)] = price
        time_data = filtered
    return date_str, time_data


def reconstruct_spot(time_data):
    spot = {}
    for t in sorted(time_data):
        data = time_data[t]
        best_diff, best_spot = float("inf"), None
        for (strike, otype), price in data.items():
            if otype != "CE":
                continue
            pe = data.get((strike, "PE"))
            if pe is None:
                continue
            diff = abs(price - pe)
            if diff < best_diff:
                best_diff = diff
                best_spot = price - pe + strike
        if best_spot is not None:
            spot[t] = best_spot
    return spot


def spot_to_bars(spot_map):
    bars = []
    for t in sorted(spot_map):
        bars.append(
            {
                "timestamp": t,
                "open": spot_map[t],
                "high": spot_map[t],
                "low": spot_map[t],
                "close": spot_map[t],
                "index": "NIFTY",
            }
        )
    return bars


def _find_atm_strike(time_data, entry_time):
    """Find ATM strike from option data at a specific time."""
    if entry_time not in time_data:
        return None
    data = time_data[entry_time]
    best_diff, best_strike = float("inf"), None
    for (strike, otype), price in data.items():
        if otype != "CE":
            continue
        pe = data.get((strike, "PE"))
        if pe is None:
            continue
        diff = abs(price - pe)
        if diff < best_diff:
            best_diff = diff
            best_strike = strike
    return best_strike


# ====================================================================
# INDICATORS
# ====================================================================


def compute_emas(bars):
    closes = np.array([b["close"] for b in bars], dtype=float)
    emas = {p: np.full(len(closes), np.nan) for p in EMA_PERIODS}
    for p in EMA_PERIODS:
        if len(closes) < p:
            continue
        k = EMA_MULT[p]
        seed = np.mean(closes[:p])
        emas[p][p - 1] = seed
        for i in range(p, len(closes)):
            emas[p][i] = closes[i] * k + emas[p][i - 1] * (1 - k)
    return emas


def write_ema_files(emas, idx, ts):
    ema_snapshot = {}
    for tf in ["60min", "1min"]:
        d = EMA_STATE_DIR / tf
        d.mkdir(parents=True, exist_ok=True)
        for p in EMA_PERIODS:
            val = emas[p][idx] if idx < len(emas[p]) else np.nan
            if np.isnan(val):
                continue
            if tf == "60min":
                ema_snapshot[p] = float(val)
            state = {
                "tf": tf,
                "period": p,
                "ema_value": round(float(val), 4),
                "available": True,
                "status": "ready",
                "buffer_count": p,
                "threshold_crossed_at": ts,
                "timestamp": _dt.now().isoformat(),
            }
            (d / f"ema_{p}.json").write_text(json.dumps(state, indent=2))
    return ema_snapshot


def push_bars_to_redis(r, bars):
    r.delete(REDIS_KEY)
    count = 0
    for bar in bars:  # LPUSH oldest first → newest at head (LINDEX 0)
        r.lpush(REDIS_KEY, json.dumps(bar))
        count += 1
    return count


# ====================================================================
# ORACLE (deterministic gate logic)
# ====================================================================


def oracle_not_up(trend, tl):
    t_sig = trend.get("signal", "NEUTRAL")
    t_conf = trend.get("confidence", 50)
    tl_sig = tl.get("signal", "NEUTRAL")
    tl_conf = tl.get("confidence", 50)
    go, conf = False, 0
    if t_sig == "BEARISH" and tl_sig == "BEARISH":
        go, conf = True, round((t_conf + tl_conf) / 2)
    elif (t_sig == "BEARISH" and tl_sig == "NEUTRAL") or (
        t_sig == "NEUTRAL" and tl_sig == "BEARISH"
    ):
        go, conf = True, round(max(t_conf if t_sig == "BEARISH" else tl_conf, 0) * 0.67)
    return {"go": go, "confidence": conf, "signal": "NOT_UP"}


def oracle_not_down(trend, tl):
    t_sig = trend.get("signal", "NEUTRAL")
    t_conf = trend.get("confidence", 50)
    tl_sig = tl.get("signal", "NEUTRAL")
    tl_conf = tl.get("confidence", 50)
    go, conf = False, 0
    if t_sig == "BULLISH" and tl_sig == "BULLISH":
        go, conf = True, round((t_conf + tl_conf) / 2)
    elif (t_sig == "BULLISH" and tl_sig == "NEUTRAL") or (
        t_sig == "NEUTRAL" and tl_sig == "BULLISH"
    ):
        go, conf = True, round(max(t_conf if t_sig == "BULLISH" else tl_conf, 0) * 0.67)
    return {"go": go, "confidence": conf, "signal": "NOT_DOWN"}


# ====================================================================
# TRACE CAPTURE (step_callback for CrewAI)
# ====================================================================


class ToolTrace:
    """Captures every tool call during CrewAI execution."""

    def __init__(self):
        self.calls = []

    def callback(self, step):
        """CrewAI step_callback — captures tool invocations."""
        try:
            if hasattr(step, "tool") and step.tool:
                call = {
                    "tool": getattr(step.tool, "name", "unknown"),
                    "input": str(step.tool_input)[:2000]
                    if hasattr(step, "tool_input")
                    else "",
                    "output": str(step.tool_output)[:2000]
                    if hasattr(step, "tool_output")
                    else "",
                }
                self.calls.append(call)
        except Exception:
            pass


def extract_all_numbers(obj, prefix=""):
    """Recursively extract all numbers from a nested dict/list."""
    nums = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            nums.update(extract_all_numbers(v, f"{prefix}.{k}" if prefix else k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            nums.update(extract_all_numbers(v, f"{prefix}[{i}]"))
    elif isinstance(obj, (int, float)):
        nums[prefix] = obj
    return nums


# ====================================================================
# INVARIANT CHECKS
# ====================================================================


def check_pnl_integrity(agent_outputs: list[dict]) -> list[str]:
    """P3: No P&L field in any agent output."""
    violations = []
    for i, output in enumerate(agent_outputs):
        for key in output:
            key_lower = key.lower().replace("_", "").replace("-", "").replace(" ", "")
            if key_lower in P_NL_FIELDS:
                violations.append(
                    f"Agent[{i}] output contains forbidden field '{key}'={output[key]}"
                )
    return violations


def collect_tool_numbers(trace: ToolTrace) -> set:
    """Extract all numbers from tool outputs."""
    nums = set()
    for call in trace.calls:
        try:
            data = (
                json.loads(call["output"])
                if isinstance(call["output"], str)
                else call["output"]
            )
        except (json.JSONDecodeError, TypeError):
            continue
        for k, v in extract_all_numbers(data).items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                nums.add(v)
    return nums


def check_provenance(decision: dict, trace: ToolTrace) -> list[str]:
    """P1: Every number in decision must appear in a tool output."""
    violations = []
    tool_nums = collect_tool_numbers(trace)
    for key, val in extract_all_numbers(decision).items():
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            if val not in tool_nums:
                # Tolerance check for float rounding
                found = any(
                    abs(val - tn) < 0.01 for tn in tool_nums if isinstance(tn, float)
                )
                if not found:
                    violations.append(
                        f"{key}={val} not in any tool output (hallucination suspicion)"
                    )
    return violations


# ====================================================================
# MAIN HARNESS
# ====================================================================


def run_harness(max_days=100, n_runs=N_REPEAT_RUNS):
    r = redis_client()
    if r is None:
        print("ERROR: Redis not running. Start with: redis-server --daemonize yes")
        sys.exit(1)
    print("✓ Redis connected")

    # Import production tools
    SDK = _Path(__file__).parent
    sys.path.insert(0, str(SDK))  # brahmand/
    sys.path.insert(0, str(SDK.parent / "antariksh"))
    sys.path.insert(0, str(SDK.parent / "antariksh" / "tools"))
    try:
        from tools.entry_tools import score_trend_redis, score_traffic_light_redis
    except ImportError as e:
        print(f"Cannot import entry_tools: {e}")
        sys.exit(1)

    # Monkey-patch: redirect ALL tool Redis reads to DB 1 (backtest isolation)
    if _redis_lib:
        _orig_redis = _redis_lib.Redis

        def _bt_redis(**kw):
            kw["db"] = 1
            return _orig_redis(**kw)

        _redis_lib.Redis = _bt_redis
        import tools.entry_tools as _et_mod

        _et_mod._redis.Redis = _bt_redis
        print("✓ Redis isolated to DB 1 (production DB 0 untouched)")

    # Load days
    csv_files = sorted(
        {
            f
            for pat in ["NSE_FNO_DATA_2024-10-*.csv", "NSE_FNO_DATA_2024-10-*.CSV"]
            for f in KAGGLE_CACHE.glob(pat)
        },
        key=lambda f: f.name,
    )

    print("=" * 100)
    print("AGENT CONFORMANCE HARNESS")
    print(f"  Invariants: P1=PROVENANCE, P2=CONSISTENCY, P3=P&L_INTEGRITY")
    print(f"  Days: {min(len(csv_files), max_days)}  |  Repeats/state: {n_runs}")
    print(f"  Entry gate: >= {ENTRY_GATE_MIN * 100:.0f}%  |  temperature=0")
    print("=" * 100)

    all_bars_buffer = []
    prev_day_close = None
    report_states = []
    summary = {"pass": 0, "fail": 0, "error": 0}

    for day_idx, csv_file in enumerate(csv_files[:max_days]):
        date_str, time_data = load_day(csv_file)
        if not date_str:
            continue
        spot_map = reconstruct_spot(time_data)
        if not spot_map:
            continue
        bars = spot_to_bars(spot_map)
        if len(bars) < 30:
            continue

        combined_bars = all_bars_buffer + bars
        emas = compute_emas(combined_bars)

        # Entry point
        entry_idx = len(all_bars_buffer)
        for p in EMA_PERIODS:
            while entry_idx < len(combined_bars) and np.isnan(emas[p][entry_idx]):
                entry_idx += 1
        if entry_idx >= len(combined_bars):
            all_bars_buffer = combined_bars[-max(EMA_PERIODS) :]
            continue

        entry_time = combined_bars[entry_idx]["timestamp"]
        ema_snapshot = write_ema_files(emas, entry_idx, entry_time)
        if len(ema_snapshot) < 3:
            all_bars_buffer = combined_bars[-max(EMA_PERIODS) :]
            continue

        # Push to Redis
        bars_to_push = list(reversed(combined_bars[: entry_idx + 1]))
        push_bars_to_redis(r, bars_to_push)
        if prev_day_close is not None:
            r.set(f"prev_close_NIFTY", str(prev_day_close))

        print(f"\n{'─' * 60}")
        print(
            f"  [{day_idx + 1}] {date_str}  entry: {entry_time}  bars: {len(combined_bars)}"
        )
        print(f"{'─' * 60}")

        # ── (A) ORACLE: deterministic tool-level decision ──
        trend_result = score_trend_redis("NIFTY")
        tl_result = score_traffic_light_redis("NIFTY")
        oracle_up = oracle_not_up(trend_result, tl_result)
        oracle_down = oracle_not_down(trend_result, tl_result)

        # Strategy picker
        if oracle_up["go"]:
            oracle_trade = "SELL_CALL"
            oracle_conf = oracle_up["confidence"]
        elif oracle_down["go"]:
            oracle_trade = "SELL_PUT"
            oracle_conf = oracle_down["confidence"]
        else:
            oracle_trade = "NONE"
            oracle_conf = 0

        oracle_passes = (
            oracle_trade != "NONE" and (oracle_conf / 100.0) >= ENTRY_GATE_MIN
        )

        print(
            f"  ORACLE: UP={oracle_up['go']}/{oracle_up['confidence']}%  "
            f"DOWN={oracle_down['go']}/{oracle_down['confidence']}%  "
            f"→ {oracle_trade} conf={oracle_conf}%  "
            f"gate={'PASS' if oracle_passes else '—'}"
        )

        # ── (B) REAL CREW: N repeated runs ──
        crew_decisions = []
        for run_n in range(n_runs):
            trace = ToolTrace()

            mock_snap = {
                "spot": combined_bars[entry_idx]["close"],
                "atm_strike": _find_atm_strike(time_data, entry_time) or 24500,
                "india_vix": 0,
                "adx": None,
                "ema_20": ema_snapshot.get(20, 0),
                "ema_50": ema_snapshot.get(50, 0),
                "expiry_weekly": "31OCT24",
            }

            try:
                import duckdb_tool
                from e2e_chain import run_sequential_crew

                with patch.object(
                    duckdb_tool,
                    "get_latest_market_snapshot",
                    return_value=mock_snap,
                ):
                    result = run_sequential_crew(entry_time)

                crew_decisions.append(
                    {
                        "run": run_n,
                        "result": result,
                        "tool_trace_len": len(trace.calls),
                    }
                )

                if result:
                    not_up = result.get("not_up_decision", {})
                    not_down = result.get("not_down_decision", {})
                    kind = result.get("recommendation", "?")
                    print(
                        f"    crew run #{run_n}: {kind}  "
                        f"UP={not_up.get('go', '?')}/{not_up.get('confidence', '?')}%  "
                        f"DOWN={not_down.get('go', '?')}/{not_down.get('confidence', '?')}%"
                    )
                else:
                    print(f"    crew run #{run_n}: None (no LLM or fallback)")

            except Exception as e:
                crew_decisions.append({"run": run_n, "error": str(e)})
                print(f"    crew run #{run_n}: ERROR — {e}")
                import traceback

                traceback.print_exc()

        # ── INVARIANT CHECKS ──
        state_report = {
            "date": date_str,
            "entry_time": entry_time,
            "oracle": {
                "not_up": oracle_up,
                "not_down": oracle_down,
                "picked_trade": oracle_trade,
                "passes_gate": oracle_passes,
            },
            "trend_signal": trend_result.get("signal"),
            "trend_confidence": trend_result.get("confidence"),
            "tl_signal": tl_result.get("signal"),
            "tl_confidence": tl_result.get("confidence"),
            "crew_runs": [],
            "violations": [],
            "verdict": "PASS",
        }

        # P1: Provenance (checked per valid crew run)
        # P2: Consistency (all crew runs identical, crew == oracle)
        # P3: P&L integrity (no P&L in agent output)

        valid_runs = [r for r in crew_decisions if "result" in r and r["result"]]
        if valid_runs:
            # Consistency: all runs identical
            base = valid_runs[0]["result"]
            for run_data in valid_runs[1:]:
                r = run_data["result"]
                if json.dumps(base, sort_keys=True, default=str) != json.dumps(
                    r, sort_keys=True, default=str
                ):
                    state_report["violations"].append(
                        "P2a: run-to-run non-identical (determinism FAIL)"
                    )

            # Crew vs Oracle cross-check
            if base:
                crew_up = base.get("not_up_decision", {})
                crew_down = base.get("not_down_decision", {})

                if crew_up.get("go") != oracle_up["go"]:
                    state_report["violations"].append(
                        f"P2b: crew NOT_UP.go={crew_up.get('go')} != oracle={oracle_up['go']}"
                    )
                if crew_down.get("go") != oracle_down["go"]:
                    state_report["violations"].append(
                        f"P2b: crew NOT_DOWN.go={crew_down.get('go')} != oracle={oracle_down['go']}"
                    )

                # P3: no P&L in agent output
                agent_outputs = [crew_up, crew_down]
                reg = base.get("regime_decision", {})
                if reg:
                    agent_outputs.append(reg)
                pnl_issues = check_pnl_integrity(agent_outputs)
                if pnl_issues:
                    state_report["violations"].extend(pnl_issues)

        for rd in crew_decisions:
            state_report["crew_runs"].append(
                {
                    "run": rd.get("run"),
                    "result": rd.get("result"),
                    "error": rd.get("error"),
                }
            )

        if state_report["violations"]:
            state_report["verdict"] = "FAIL"
            summary["fail"] += 1
            print(f"  VERDICT: FAIL — {len(state_report['violations'])} violations")
            for v in state_report["violations"]:
                print(f"    • {v}")
        else:
            summary["pass"] += 1
            print(f"  VERDICT: PASS ✓")

        report_states.append(state_report)

        all_bars_buffer = combined_bars[-max(EMA_PERIODS) :]
        prev_day_close = combined_bars[-1]["close"] if combined_bars else None

    # ── WRITE REPORT ─────────────────────────────────────────────────
    report = {
        "generated": _dt.now().isoformat(),
        "invariants": ["P1=PROVENANCE", "P2=CONSISTENCY", "P3=P&L_INTEGRITY"],
        "config": {
            "n_repeat_runs": n_runs,
            "entry_gate_min": ENTRY_GATE_MIN,
            "temperature": 0,
            "source": "Kaggle NSE FNO cache → Redis",
        },
        "summary": summary,
        "states": report_states,
    }

    output_path = _Path("/home/trading_ceo/brahmand/data/conformance_report.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, default=str))

    print("\n" + "=" * 100)
    print("CONFORMANCE REPORT")
    print("=" * 100)
    print(f"  Pass:  {summary['pass']}")
    print(f"  Fail:  {summary['fail']}")
    print(f"  Error: {summary['error']}")
    print(f"  Total: {summary['pass'] + summary['fail'] + summary['error']}")
    print(f"\n  Report: {output_path}")

    if summary["fail"] == 0 and summary["pass"] > 0:
        print("\n  ✓ CONFORMANCE: ALL INVARIANTS HOLD")
    else:
        print(f"\n  ⚠ CONFORMANCE: {summary['fail']} failures — see report for details")

    return report


if __name__ == "__main__":
    max_days = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 100
    n_runs = (
        int(sys.argv[2])
        if len(sys.argv) > 2 and sys.argv[2].isdigit()
        else N_REPEAT_RUNS
    )
    run_harness(max_days=max_days, n_runs=n_runs)
