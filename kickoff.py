#!/usr/bin/env python3
"""
Brahmand Kickoff — Scheduler entry point for autonomous 5-agent chain.

Runs every 5 minutes during market hours (9:30-15:30).
Lock-protected: won't overlap with a previous run.
First run of the day: enters a random trade. All runs: monitors open trades.

Usage:
    python kickoff.py                 # manual
    */5 9-15 * * 1-5  python3 kickoff.py >> logs/kickoff_$(date +\\%Y\\%m\\%d).log 2>&1

State tracked in /tmp/brahmand_kickoff.json:
    - pid, last_run, active_trade, trades_today
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

LOCK_FILE = Path("/tmp/brahmand_kickoff.lock")
STATE_FILE = Path("/tmp/brahmand_kickoff.json")


def _log(msg: str):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line)
    sys.stdout.flush()


def acquire_lock() -> bool:
    if LOCK_FILE.exists():
        pid = LOCK_FILE.read_text().strip()
        try:
            os.kill(int(pid), 0)
            _log(f"Already running (PID {pid}) — skipping")
            return False
        except (OSError, ValueError):
            pass
    LOCK_FILE.write_text(str(os.getpid()))
    return True


def release_lock():
    LOCK_FILE.unlink(missing_ok=True)


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    today = datetime.now().strftime("%Y%m%d")
    return {
        "date": today,
        "trades_today": 0,
        "active_trade": None,
        "all_trades": [],
        "post_mortem_done": False,
    }


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


def now_str():
    return datetime.now().strftime("%H:%M")


def is_market_hours() -> bool:
    t = datetime.now()
    return (
        datetime.strptime("09:30", "%H:%M").time()
        <= t.time()
        <= datetime.strptime("15:30", "%H:%M").time()
    )


def should_enter(state: dict) -> bool:
    """Gate entry: no active trade, below max, cooldown. Regime check next."""
    if state["active_trade"] is not None:
        return False
    max_trades = int(os.environ.get("BRAHMAND_MAX_TRADES", 4))
    if state["trades_today"] >= max_trades:
        return False
    if state["all_trades"]:
        last = state["all_trades"][-1].get("entry_time", "00:00")
        cooldown = int(os.environ.get("BRAHMAND_COOLDOWN_MIN", 15))
        mins = (
            datetime.strptime(now_str(), "%H:%M") - datetime.strptime(last, "%H:%M")
        ).total_seconds() / 60
        if mins < cooldown:
            return False
    return True


def enter_trade(state: dict):
    """Run 5-agent E2E chain. Regime Agent decides entry."""
    from e2e_chain import run_full_chain

    try:
        trade = run_full_chain(now_str())
    except Exception as e:
        _log(f"Chain failed: {e} — skipping this cycle")
        return state
    if trade is None:
        _log("Regime: SKIP — no trade entered")
        return state
    if isinstance(trade, dict) and trade.get("recommendation") == "skip":
        _log(f"Regime: SKIP — {trade.get('regime', 'unknown')}")
        return state

    trade["monitored_since"] = now_str()
    state["active_trade"] = trade
    state["trades_today"] += 1
    _log(
        f"ENTERED: {trade['strategy_type']} ({trade['leg_count']} legs) | Net ₹{trade['net_credit']}"
    )
    return state


def monitor_trade(state: dict):
    """Monitor active trade — check SL/TP via DuckDB every run."""
    trade = state["active_trade"]
    if not trade:
        return state

    from duckdb_tool import _connect

    expiry = trade.get("expiry", "")
    con = _connect()
    try:
        for leg in trade["legs"]:
            if leg["action"] != "SELL":
                continue
            t = leg["type"].lower()
            row = con.execute(
                "SELECT ltp FROM option_snapshots "
                "WHERE expiry_date = ? AND strike = ? AND option_type = ? "
                "AND tsym IS NOT NULL ORDER BY timestamp DESC LIMIT 1",
                (expiry, leg["strike"], leg["type"]),
            ).fetchone()
            ltp = float(row[0] or 0) if row else 0

            # Sanity: option LTP must be < 5000 (spot values are 23000+)
            if ltp > 5000:
                continue

            if ltp > 0 and trade["sl"].get(t) and ltp >= trade["sl"][t]:
                _log(f"SL HIT — {leg['tsym']}: LTP={ltp} >= {trade['sl'][t]}")
                exit_trade(state, "SL_HIT")
                return state
            elif ltp > 0 and trade["tp"].get(t) and ltp <= trade["tp"][t]:
                _log(f"TP HIT — {leg['tsym']}: LTP={ltp} <= {trade['tp'][t]}")
                exit_trade(state, "TP_HIT")
                return state
    finally:
        con.close()

    # Auto-exit after 45 min if no SL/TP
    mins_open = (
        datetime.strptime(now_str(), "%H:%M")
        - datetime.strptime(
            trade.get("monitored_since", trade.get("entry_time", "09:30")), "%H:%M"
        )
    ).total_seconds() / 60
    if mins_open > 45:
        _log(f"Auto-exit after {int(mins_open)} min")
        exit_trade(state, "TIME_EXIT")

    return state


def exit_trade(state: dict, reason: str):
    """Close active trade, calculate P&L, store."""
    trade = state["active_trade"]
    if not trade:
        return

    from duckdb_tool import _connect

    con = _connect()
    expiry = trade.get("expiry", "")
    total_pnl = 0.0
    sell_types = set()

    try:
        for leg in trade["legs"]:
            row = con.execute(
                "SELECT ltp FROM option_snapshots "
                "WHERE expiry_date = ? AND strike = ? AND option_type = ? "
                "AND tsym IS NOT NULL ORDER BY timestamp DESC LIMIT 1",
                (expiry, leg["strike"], leg["type"]),
            ).fetchone()
            ltp = float(row[0] or 0) if row else leg["fill_price"]

            if leg["action"] == "SELL":
                total_pnl += leg["fill_price"] - ltp
                sell_types.add(leg["type"])
            elif leg["action"] == "BUY" and leg["type"] in sell_types:
                total_pnl += ltp - leg["fill_price"]
    finally:
        con.close()

    trade["exit_time"] = now_str()
    trade["exit_reason"] = reason
    trade["pnl"] = round(total_pnl, 2)
    trade["status"] = "CLOSED"

    _log(f"EXIT ({reason}): P&L ₹{trade['pnl']}")
    state["all_trades"].append(trade)
    state["active_trade"] = None

    # Trigger Post-Mortem if market closing
    if not is_market_hours() and not state["post_mortem_done"]:
        run_pm(state)


def run_pm(state: dict):
    """Run Post-Mortem after market close."""
    _log("\n=== POST-MORTEM ===")
    state["post_mortem_done"] = True
    try:
        from chromadb_tool import QueryChromaDBTool, StoreResearchNoteTool
        from duckdb_tool import MarketDataQueryTool, OptionSnapshotQueryTool
        from factory import AgentFactory, LLM
        from crewai import Task, Crew, Process
        from persistence import get_today_date_int

        af = AgentFactory()
        pm = af.create_agent(
            "postmortem_agent",
            {
                "today_date_int": get_today_date_int(),
                "chroma_collection": "brahmand_notes",
            },
            tools=[
                QueryChromaDBTool(),
                StoreResearchNoteTool(),
                MarketDataQueryTool(),
                OptionSnapshotQueryTool(),
            ],
        )
        if "DEEPSEEK_API_KEY" in os.environ:
            pm.llm = LLM(
                model="deepseek/deepseek-chat",
                base_url=os.environ.get(
                    "DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"
                ),
                api_key=os.environ["DEEPSEEK_API_KEY"],
            )

        task = Task(
            description=f"Post-Mortem for today. {len(state['all_trades'])} trades: {json.dumps(state['all_trades'], default=str)[:2000]}. Analyze and write to ChromaDB.",
            expected_output="ResearchNotes JSON",
            agent=pm,
        )
        crew = Crew(
            agents=[pm], tasks=[task], process=Process.sequential, verbose=False
        )
        crew.kickoff()
        _log("Post-Mortem complete — ChromaDB updated")
    except Exception as e:
        _log(f"Post-Mortem failed: {e}")


def main():
    if not acquire_lock():
        sys.exit(0)

    try:
        if not is_market_hours():
            if state["active_trade"] and not state["post_mortem_done"]:
                _log("Market closed — force-closing active trade")
                exit_trade(state, "MARKET_CLOSE")
            _log("Market closed — exiting")
            return

        state = load_state()
        today = datetime.now().strftime("%Y%m%d")
        if state["date"] != today:
            state = load_state()  # Reset for new day
            state["date"] = today

        max_t = int(os.environ.get("BRAHMAND_MAX_TRADES", 4))
        _log(
            f"Scheduled run | Active: {state['active_trade'] is not None} | Today: {state['trades_today']}/{max_t}"
        )

        if state["active_trade"]:
            # Trade open — just monitor, no agent evaluation
            monitor_trade(state)
        elif should_enter(state):
            # No trade, gates passed — run full 5-agent chain
            enter_trade(state)
        # else: cooldown or max trades reached — skip

        save_state(state)
    finally:
        release_lock()


if __name__ == "__main__":
    main()
