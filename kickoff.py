#!/usr/bin/env python3
"""
Brahmand Kickoff — Scheduler entry point for autonomous 5-agent chain.

Runs every 5 minutes during market hours (9:30-15:30).
Lock-protected: won't overlap with a previous run.
First run of the day: enters a random trade. All runs: monitors open trades.

Usage:
    python kickoff.py                 # manual
    */5 9-15 * * 1-5  python3 kickoff.py >> logs/kickoff_$(date +\\%Y\\%m\\%d).log 2>&1

State tracked in data/brahmand_kickoff.json:
    - pid, last_run, active_trade, trades_today
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
load_dotenv()

from trade_execution_db import add_active_trade

STATE_DIR = Path(__file__).parent / "data"
STATE_DIR.mkdir(parents=True, exist_ok=True)
LOCK_FILE = STATE_DIR / "brahmand_kickoff.lock"
STATE_FILE = STATE_DIR / "brahmand_kickoff.json"


from logger import get_logger, agent_log, chain_summary, log_exception

_log = get_logger("kickoff").info
_err = get_logger("kickoff").error


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
    today = datetime.now().strftime("%Y%m%d")
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text())
        if state.get("date") == today:
            return state
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


def _apply_tsl(trade: dict, leg_type: str, entry_price: float, ltp: float) -> None:
    """Ratchet SL downward as option decays (favorable for SELL).

    TSL activates when current profit >= 25% of max TP profit.
    Then locks portion of every favorable tick past the threshold (lock_ratio from pattern or default 0.5).
    Only ratchets SL DOWN (never up) — locks in gains.
    """
    t = leg_type.lower()
    sl = trade["sl"].get(t)
    if not sl:
        return

    tp = trade["tp"].get(t, entry_price * 0.50)
    max_profit = entry_price - tp  # full TP profit per share
    current_profit = entry_price - ltp  # current profit per share

    # TSL not yet active
    if current_profit < max_profit * 0.25:
        return

    # Lock ratio can be overridden by pattern adaptation (from risk agent)
    lock_ratio = trade.get("tsl_lock_ratio", 0.5)

    # Lock portion of every favorable move past the 25% threshold
    threshold_profit = max_profit * 0.25
    excess = current_profit - threshold_profit
    locked_profit = threshold_profit + (excess * lock_ratio)
    new_sl = round(entry_price - locked_profit, 2)

    # Only ratchet SL DOWN (more favorable = lower price for shorts to trigger)
    if new_sl < sl:
        old_sl = trade["sl"][t]
        trade["sl"][t] = new_sl
        shift_pct = round((old_sl - new_sl) / old_sl * 100, 1)

        # Capture TSL history for RL analysis
        if "tsl_history" not in trade:
            trade["tsl_history"] = []
        trade["tsl_history"].append(
            {
                "timestamp": datetime.now().isoformat(),
                "leg": leg_type,
                "old_sl": old_sl,
                "new_sl": new_sl,
                "shift_pct": shift_pct,
                "lock_ratio": lock_ratio,
                "current_profit": round(current_profit, 2),
                "threshold_profit": round(threshold_profit, 2),
            }
        )

        _log(
            f"TSL: {leg_type} SL ratcheted {old_sl:.2f} → {new_sl:.2f} (lock_ratio={lock_ratio})"
        )


def is_market_hours() -> bool:
    t = datetime.now()
    return (
        datetime.strptime("09:15", "%H:%M").time()
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
    """Run Entry → Regime → Strategy → Contract → Execution → Risk chain.
    Entry Agent is the first gate — called inline, not from a stale file."""
    from e2e_chain import run_full_chain

    entry_time = now_str()
    try:
        trade = run_full_chain(entry_time)
    except Exception as e:
        _log(f"Chain failed: {e}")
        return state
    if trade is None:
        _log("  SKIP: Gate rejected")
        return state
    if isinstance(trade, dict) and trade.get("recommendation") == "skip":
        _log(f"  SKIP: {trade.get('regime', 'unknown')}")
        return state
    if isinstance(trade, dict) and trade.get("recommendation") == "no_go":
        _log("  SKIP: Entry Agent NO-GO")
        return state

    # Normalize strategy_type: map one-sided strategies to "credit_spread"
    strategy_normalized = trade.get("strategy_type", "IRON_BUTTERFLY")
    if "SPREAD" in strategy_normalized or "CREDIT" in strategy_normalized.upper():
        strategy_display = "credit_spread"
    elif "BUTTERFLY" in strategy_normalized:
        strategy_display = "iron_butterfly"
    else:
        strategy_display = strategy_normalized.lower()

    # Store entry_scores on trade for pattern logging on exit
    trade["entry_gate_signal"] = trade.get(
        "entry_gate_signal", trade.get("entry_scores", {}).get("signal", "UNKNOWN")
    )
    trade["monitored_since"] = entry_time

    # Initialize monitoring phase tracking for postmortem analysis
    trade["monitoring_events"] = {
        "tsl_adjustments": [],      # TSL ratchet history
        "morph_actions": [],        # Signal reversal actions
        "shift_actions": [],        # Premium decay shifts
        "mtm_checks": [],           # P&L snapshots during monitoring
    }

    state["active_trade"] = trade
    state["trades_today"] += 1

    # ALSO write to DuckDB for Risk Monitor (1-min monitoring)
    try:
        trade_id = (
            trade.get("trade_id")
            or f"TRADE-{datetime.now().strftime('%Y%m%d')}-{state['trades_today']:03d}"
        )
        trade["trade_id"] = trade_id
        add_active_trade(
            trade_id=trade_id,
            entry_time=entry_time,
            strategy=strategy_display,
            entry_gate_signal=trade.get("entry_gate_signal", "UNKNOWN"),
            legs=trade.get("legs", []),
            sl=trade.get("sl", {}),
            tp=trade.get("tp", {}),
        )
        _log(f"  ✅ Wrote to DuckDB: {trade_id}")
    except Exception as e:
        _log(f"  ⚠️  DuckDB write failed: {e}")

    _log(
        f"ENTERED: {strategy_display} ({trade['leg_count']} legs) @ ₹{trade['net_credit']} [{entry_time}]"
    )
    return state


def monitor_trade(state: dict):
    """Monitor active trade — check SL/TP, adjust TSL, detect MORPH."""
    trade = state["active_trade"]
    if not trade:
        return state

    # ── Log monitoring cycle ──
    entry_time = trade.get("entry_time", "09:30")
    monitored_since = trade.get("monitored_since", entry_time)
    mins_open = (
        datetime.strptime(now_str(), "%H:%M")
        - datetime.strptime(monitored_since, "%H:%M")
    ).total_seconds() / 60
    _log(
        f"  MONITOR: {trade.get('strategy_type', '?')} | {int(mins_open)}min | Gate: {trade.get('entry_gate_signal', '?')}"
    )

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

            # Apply TSL adjustment before SL/TP check
            fill = leg.get("fill_price", ltp)
            if ltp > 0:
                _apply_tsl(trade, leg["type"], fill, ltp)

            # Check SL/TP triggers
            if ltp > 0 and trade["sl"].get(t) and ltp >= trade["sl"][t]:
                _log(
                    f"  SL HIT — {leg['tsym']}: LTP={ltp} >= {trade['sl'][t]} [{now_str()}]"
                )
                exit_trade(state, "SL_HIT")
                return state
            elif ltp > 0 and trade["tp"].get(t) and ltp <= trade["tp"][t]:
                _log(
                    f"  TP HIT — {leg['tsym']}: LTP={ltp} <= {trade['tp'][t]} [{now_str()}]"
                )
                exit_trade(state, "TP_HIT")
                return state
    finally:
        con.close()

    # ── Monitoring Crew: Morpher → Shifter ──────────────────────────────
    if _get_llm_monitor():
        try:
            state = _run_monitoring_crew(state)
        except Exception as e:
            _log(f"  Monitoring crew failed: {e} — falling back to Python checks")
            state = _monitor_fallback(state, trade)

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


def _get_llm_monitor():
    """Return DeepSeek LLM for monitoring crew or None if unavailable."""
    try:
        from crewai import LLM

        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            return None
        return LLM(
            model="deepseek/deepseek-chat",
            base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
            api_key=api_key,
        )
    except Exception:
        return None


def _run_monitoring_crew(state: dict):
    """Run Morpher → Shifter monitoring Crew."""
    import json as _json

    trade = state["active_trade"]
    llm = _get_llm_monitor()

    from factory import AgentFactory
    from tools.monitor_tools import MorphCheckTool, ShiftCheckTool
    from tools.risk_tools import PlaceSLOrderTool, PlaceTPOrderTool, CancelOrderTool

    af = AgentFactory()
    morph_tool = MorphCheckTool()
    shift_tool = ShiftCheckTool()
    sl_tool = PlaceSLOrderTool()
    tp_tool = PlaceTPOrderTool()
    cancel_tool = CancelOrderTool()

    morpher = af.create_agent(
        "morpher_agent", {}, tools=[morph_tool, sl_tool, tp_tool, cancel_tool]
    )
    morpher.llm = llm
    shifter = af.create_agent(
        "shifter_agent", {}, tools=[shift_tool, sl_tool, tp_tool, cancel_tool]
    )
    shifter.llm = llm

    trade_json = _json.dumps(trade, default=str)

    from crewai import Task, Crew, Process

    morph_task = Task(
        description=(
            "Check if the position needs to MORPH.\n\n"
            f"Trade JSON: {trade_json}\n\n"
            "Call check_for_morph with the trade_json. If morph actions are proposed, "
            "execute them using place_sl_order/place_tp_order for NEW legs and "
            "cancel_order for OLD legs. Report what happened."
        ),
        expected_output="Morph report with actions executed or 'no action'",
        agent=morpher,
    )

    shift_task = Task(
        description=(
            "Check if any SELL leg's premium has decayed enough to shift wings.\n\n"
            f"Trade JSON: {trade_json}\n\n"
            "Call check_for_shift with the trade_json. If shift proposals are returned, "
            "execute them: for HEDGE_SHIFT, use place_sl_order/place_tp_order for new hedge "
            "and cancel_order for old hedge. For SELL_SHIFT, cancel old sell SL/TP and "
            "place new sell SL/TP. Report what happened."
        ),
        expected_output="Shift report with actions executed or 'no action'",
        agent=shifter,
        context=[morph_task],
    )

    crew = Crew(
        agents=[morpher, shifter],
        tasks=[morph_task, shift_task],
        process=Process.sequential,
        verbose=True,
    )
    result = crew.kickoff()

    # ── Log each agent's output ────────────────────────────────────────
    agent_names = ["Morpher", "Shifter"]
    if hasattr(result, "tasks_output"):
        for i, name in enumerate(agent_names):
            if i < len(result.tasks_output):
                raw = str(result.tasks_output[i])
                try:
                    parsed = (
                        json.loads(raw[raw.find("{") : raw.rfind("}") + 1])
                        if "{" in raw
                        else {}
                    )
                    _log(f"  {name}: {json.dumps(parsed)[:300]}")
                except Exception:
                    _log(f"  {name} (raw): {raw[:300]}")
    else:
        _log(f"  Monitoring Crew result: {str(result)[:400]}")

    return state


def _monitor_fallback(state, trade):
    """Fallback: Python-based morph + shift check when LLM is down."""
    try:
        from position_manager import run as pm_run

        actions = pm_run(trade)
        if actions:
            for action in actions:
                if action["type"] == "MORPH":
                    _log(
                        f"  MORPH: {action['from_type']} → {action['to_type']} ({action['reason']})"
                    )
                    from position_manager import execute_action

                    trade = execute_action(action, trade)
                    state["active_trade"] = trade
    except Exception as e:
        _log(f"  Morph fallback failed: {e}")

    try:
        from leg_shifter import run_leg_shifter, execute_hedge_shift, execute_sell_shift

        available_margin = trade.get("available_margin", 100000)
        proposals = run_leg_shifter(trade, available_margin)
        if proposals.get("hedge_shift"):
            result = execute_hedge_shift(trade, proposals["hedge_shift"])
            if result.get("status") == "SUCCESS":
                state["active_trade"] = trade
        if proposals.get("sell_shift"):
            shift = proposals["sell_shift"]
            if shift.get("status") != "REJECTED":
                result = execute_sell_shift(trade, shift)
                if result.get("status") == "SUCCESS":
                    state["active_trade"] = trade
    except Exception as e:
        _log(f"  Shift fallback failed: {e}")

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

    # Log trade→pattern correlation for EOD analysis
    try:
        from pattern_enricher import log_trade_pattern

        log_trade_pattern(trade)
    except Exception:
        pass

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
        from factory import AgentFactory
        from crewai import Task, Crew, Process, LLM
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

        trades_summary = json.dumps(state['all_trades'], default=str)[:3000]
        task = Task(
            description=(
                f"POST-MORTEM ANALYSIS for {len(state['all_trades'])} trades today.\n\n"
                "COMPLETE trade data (all agent outputs) included:\n"
                f"{trades_summary}\n\n"
                "ANALYZE EACH TRADE:\n"
                "1. Entry Agent Analysis:\n"
                "   - Was entry_gate_signal accurate? (compare signal vs actual market direction at exit)\n"
                "   - Was confidence level predictive of outcome?\n"
                "   - Trend vs Traffic Light accuracy?\n\n"
                "2. Regime Analysis:\n"
                "   - Did regime_analysis.recommendation match outcome?\n"
                "   - Was VIX level factored correctly?\n"
                "   - ADX trend bias accurate?\n\n"
                "3. Strategy Analysis:\n"
                "   - Were strategy_analysis parameters (wing_width, sl_pct, tp_pct) optimal?\n"
                "   - Did actual premium decay match expectations?\n\n"
                "4. Execution Analysis:\n"
                "   - Net credit sufficient for drawdown? (margin = wing_width - net_credit)\n"
                "   - SL/TP levels appropriate?\n\n"
                "5. Risk Analysis:\n"
                "   - Risk_confirmation: were all orders placed? Any failures?\n"
                "   - Order_ids tracked correctly in order_ledger?\n\n"
                "6. Exit Analysis:\n"
                "   - Exit reason (SL_HIT, TP_HIT, MORPH, TSL, TIME_EXIT)?\n"
                "   - Was the exit reason predictable from earlier analysis?\n"
                "   - PnL: was it within expected range given wing_width and net_credit?\n\n"
                "WRITE ResearchNotes to ChromaDB with:\n"
                "- key insights\n"
                "- what worked (pattern, VIX level, regime match)\n"
                "- what failed (wrong signal, bad timing, parameter miscalibration)\n"
                "- recommendations for tomorrow (parameter adjustments, market regime filters)"
            ),
            expected_output="ResearchNotes JSON with trade analysis summary",
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
        state = load_state()
        today = datetime.now().strftime("%Y%m%d")
        if state["date"] != today:
            state = load_state()  # Reset for new day
            state["date"] = today

        if not is_market_hours():
            if state["active_trade"] and not state["post_mortem_done"]:
                _log("Market closed — force-closing active trade")
                exit_trade(state, "MARKET_CLOSE")
            _log("Market closed — exiting")
            return

        max_t = int(os.environ.get("BRAHMAND_MAX_TRADES", 4))

        # SIMPLE CHECK: Look at in-memory state first (fast)
        # Risk Monitor keeps DuckDB in sync, so this is sufficient
        has_active = state["active_trade"] is not None

        _log(
            f"Scheduled run | Active: {has_active} | Today: {state['trades_today']}/{max_t}"
        )

        if has_active:
            # Trade open — Risk Monitor has it (1-min cadence), scheduler skips
            _log("  ✓ Position exists → Risk Monitor monitoring → skipping entry crew")
        elif should_enter(state):
            # No trade, gates passed — run full 5-agent chain
            enter_trade(state)
        # else: cooldown or max trades reached — skip

        save_state(state)
    finally:
        release_lock()


if __name__ == "__main__":
    main()
