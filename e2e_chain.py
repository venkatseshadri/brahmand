"""
Brahmand E2E Chain — Sequential Crew: Entry → Regime → Strategy → Contract → Execution → Risk

Chain:
  1. Entry Agent   (CrewAI) — query_trend_ema + query_traffic_light → GO/NO-GO
  2. Regime Agent  (CrewAI) — validates entry signal against DuckDB → regime
  3. Strategy Agent(CrewAI) — selects spread/butterfly, wing width, SL/TP
  4. Contract      (Python) — resolves tsyms from DuckDB option_snapshots
  5. Execution     (Python) — builds trade dict, saves SIM to state.db
  6. Risk          (Python) — saves SL/TP orders to state.db

Entry/Regime/Strategy run as a single sequential Crew with context passing.
Contract/Execution/Risk are pure Python (no LLM, no CrewAI overhead).
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
load_dotenv()


from logger import get_logger, agent_log, chain_summary, log_exception
from logger import _make_crew_step_callback, _make_crew_after_callback
from llm import get_llm
from parsing import extract_task_output
from fallback import deterministic_fallback
from verification import (
    verify_provenance,
    verify_regime_provenance,
    verify_strategy_provenance,
)

# ── UNICORN Integration ───────────────────────────────────────────────
# USE_UNICORN=True  → Entry gate runs adversarial debate pipeline
# USE_UNICORN=False → Entry gate runs legacy CrewAI deterministic tools


def _snapshot_regime(adx: float, snap: dict) -> str:
    """Derive a basic regime label from ADX + Supertrend when CrewAI agent output is empty."""
    if not adx or not snap:
        return "unknown"
    if adx > 25:
        st = (snap.get("supertrend_direction") or "").lower()
        if "up" in st:
            return "bullish"
        if "down" in st:
            return "bearish"
    st15 = (snap.get("st_15min_direction") or "").lower()
    if adx > 20:
        if "up" in st15:
            return "bullish"
        if "down" in st15:
            return "bearish"
    return "sideways"


def _dambuilder_trace(gate: str, entry_decision: dict, regime: dict, outcome: str, spot: float):
    try:
        from datetime import datetime, timezone, timedelta

        ist = datetime.now(timezone(timedelta(hours=5, minutes=30)))
        db_path = os.environ.get(
            "CAPTURE_SQLITE",
            "/home/trading_ceo/python-trader/varaha/data/capture_nifty.sqlite",
        )
        row = {
            "timestamp": ist.isoformat(),
            "index_name": "NIFTY",
            "decision_id": f"{ist.strftime('%Y%m%dT%H%M%S')}",
            "gate_type": gate,
            "decision_source": entry_decision.get("source", "unknown"),
            "signal": entry_decision.get("signal"),
            "go": entry_decision.get("go", False),
            "confidence": entry_decision.get("confidence"),
            "regime": regime.get("regime"),
            "regime_recommendation": regime.get("recommendation"),
            "vix": regime.get("vix"),
            "spot": spot,
        }
        home = str(Path(__file__).resolve().parent.parent)
        if home not in sys.path:
            sys.path.insert(0, home)
        from antariksh.research.outcome_tables import write_decision_trace

        write_decision_trace(db_path, row)
    except Exception as e:
        get_logger("chain").warning(f"decision_trace write failed: {e}")


USE_UNICORN = True
_UNICORN_RESEARCH_LOCK = Path(__file__).parent / "data" / ".unicorn_research.lock"

_log = get_logger("chain").info
_agent = get_logger("chain")
_err = lambda msg, exc=None: (
    log_exception(get_logger("chain"), exc, msg) if exc else get_logger("chain").error(msg)
)


def _trigger_unicorn_research(gate_type: str):
    """Spawn background research subprocess. Non-blocking. Lock-guarded.
    Called when cache is empty or expired to generate fresh LLM points
    for the next 5-min cycle. Does NOT block this cycle's execution."""
    import subprocess
    import fcntl

    lock = _UNICORN_RESEARCH_LOCK
    lock.parent.mkdir(parents=True, exist_ok=True)

    # Guard: if research is already running, skip
    try:
        lf = open(str(lock), "w")
        fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, BlockingIOError, PermissionError):
        return  # already running

    # Release lock before spawning (child will reacquire)
    fcntl.flock(lf, fcntl.LOCK_UN)
    lf.close()

    _log(f"  Spawning background UNICORN research for {gate_type}")
    subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).parent / "unicorn_research.py"),
            "--gate",
            gate_type,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env={**os.environ, "UNICORN_RESEARCH_LOCK": str(lock)},
    )


def run_sequential_crew(entry_time: str) -> dict | None:
    """
    Run Entry → Regime → Strategy as a single sequential CrewAI pipeline.
    Returns the combined agent decisions dict or None if Entry says NO-GO
    or if any agent fails.
    """
    llm = get_llm()

    from factory import AgentFactory, TaskFactory
    from market_data import MarketDataQueryTool, get_latest_market_snapshot

    af = AgentFactory()
    tf = TaskFactory()
    market_tool = MarketDataQueryTool()
    snap = get_latest_market_snapshot()
    if not snap or not snap.get("spot"):
        from duckdb_tool import get_latest_market_snapshot as ddb_snap

        snap = ddb_snap()

    spot = float(snap.get("spot", 0))
    atm = int(float(snap.get("atm_strike", 0)))
    vix = float(snap.get("india_vix", 0))
    adx_val = snap.get("adx")
    adx = float(adx_val) if adx_val and adx_val != "None" else 0.0

    if not spot or not atm:
        _log("  E2E Chain: ⚠ No market data — skipping")
        return None

    # Freshness + expiry-sanity guard. If the data capture didn't run today, the
    # latest market_data row is from a prior session — yesterday's prices and a
    # past expiry. On 2026-05-27 a stale 26-May snapshot caused the system to
    # trade the already-expired 26-MAY weekly. Refuse entry on stale or expired data.
    today = datetime.now().date()
    snap_date = (snap.get("date") or "")[:10]
    if snap_date != today.isoformat():
        _log(
            f"  E2E Chain: ⚠ STALE snapshot (date={snap_date!r} != today {today.isoformat()!r}) — skipping entry"
        )
        return None
    expiry_raw = snap.get("expiry_weekly", "")
    try:
        expiry_d = datetime.strptime(expiry_raw, "%d-%b-%Y").date()
    except ValueError:
        expiry_d = None
    if expiry_d is None or expiry_d < today:
        _log(
            f"  E2E Chain: ⚠ expiry {expiry_raw!r} missing or already expired (today={today.isoformat()}) — skipping entry"
        )
        return None

    snap_json = json.dumps(
        {
            k: snap.get(k, "")
            for k in [
                "spot",
                "india_vix",
                "adx",
                "ema_20",
                "ema_50",
                "supertrend_direction",
                "st_15min_direction",
                "iv_current",
                "iv_rank",
                "rsi",
                "pcr_total",
                "sentiment",
                "structure_type",
                "session_phase",
            ]
        }
    )

    if not llm:
        _log("  E2E Chain: ⚠ No LLM — using deterministic fallback")
        return deterministic_fallback(entry_time, spot, atm, vix, adx, snap)

    # ── Build tools ────────────────────────────────────────────────────
    from tools.entry_gate_tools import (
        QueryTrendEMA,
        QueryTrafficLight,
        CheckActiveSpreads,
        EvaluateNotUpRejection,
        EvaluateNotDownRejection,
    )
    from tools.chain_tools import (
        ResolveOptionContractsTool,
        BuildAndExecuteTradeTool,
        PlaceSLTPOrdersTool,
    )

    trend_tool = QueryTrendEMA()
    tl_tool = QueryTrafficLight()
    position_check_tool = CheckActiveSpreads()
    not_up_rejection_tool = EvaluateNotUpRejection()
    not_down_rejection_tool = EvaluateNotDownRejection()
    contract_tool = ResolveOptionContractsTool()
    execution_tool = BuildAndExecuteTradeTool()
    sl_tp_orders_tool = PlaceSLTPOrdersTool()

    # ── Build agents ───────────────────────────────────────────────────
    try:
        not_up_entry_agent = af.create_agent(
            "not_up_entry_agent", {}, tools=[position_check_tool, not_up_rejection_tool]
        )
        not_up_entry_agent.llm = llm

        not_down_entry_agent = af.create_agent(
            "not_down_entry_agent",
            {},
            tools=[position_check_tool, not_down_rejection_tool],
        )
        not_down_entry_agent.llm = llm

        regime_agent = af.create_agent("regime_agent", {}, tools=[market_tool])
        regime_agent.llm = llm

        strategy_agent = af.create_agent("strategy_agent", {}, tools=[market_tool])
        strategy_agent.llm = llm

        contract_agent = af.create_agent("contract_agent", {}, tools=[contract_tool])
        contract_agent.llm = llm

        execution_agent = af.create_agent(
            "execution_agent",
            variables={
                "market_type": "NIFTY",  # Phase 1: NIFTY/SENSEX (no selection). Phase 2+: receives asset from Asset Selector Agent
                "strategy_type": "deterministic",
                "ticker": "NIFTY",
                "mock_mode": "paper",
                "phase": "1",  # Phase 1 (NIFTY only), Phase 2+ (multi-asset, receives asset from upstream)
                "role": "dumb_executor",  # Does NOT make decisions. All decisions upstream.
            },
            tools=[execution_tool],
        )
        execution_agent.llm = llm

        risk_agent = af.create_agent(
            "risk_agent",
            variables={"market_type": "NIFTY", "ticker": "NIFTY", "mock_mode": "paper"},
            tools=[sl_tp_orders_tool],
        )
        risk_agent.llm = llm
    except KeyError as e:
        _log(f"  ⚠ Agent factory: {e}")
        return deterministic_fallback(entry_time, spot, atm, vix, adx, snap)

    expiry = snap.get("expiry_weekly", "")
    # Guard: if data capture didn't run today, expiry_weekly may be stale (yesterday's)
    # Never trade expired contracts — compute fresh expiry
    try:
        expiry_dt = datetime.strptime(expiry, "%d-%b-%Y").date()
        if expiry_dt < datetime.now().date():
            _log(f"  ⚠ expiry_weekly {expiry} is stale (past) — computing fresh")
            today_dt = datetime.now()
            days_to_tue = (1 - today_dt.weekday()) % 7
            if days_to_tue == 0 and today_dt.hour >= 15:
                days_to_tue = 7
            expiry_dt_computed = today_dt + timedelta(days=days_to_tue)
            if (expiry_dt_computed - today_dt).days < 2:
                expiry_dt_computed = expiry_dt_computed + timedelta(days=7)
            expiry = expiry_dt_computed.strftime("%d-%b-%Y").upper()
            _log(f"  ✓ corrected expiry: {expiry}")
    except ValueError:
        pass
    from crewai import Crew, Process

    # ── Task 1a: NOT_UP Entry Agent (CALL_SPREAD gate) ─────────────────
    not_up_entry_task = tf.create_task("not_up_entry_task", agent=not_up_entry_agent)

    # ── Task 1b: NOT_DOWN Entry Agent (PUT_SPREAD gate) ────────────────
    not_down_entry_task = tf.create_task("not_down_entry_task", agent=not_down_entry_agent)

    # ── Task 2: Regime Agent ───────────────────────────────────────────
    regime_task = tf.create_task("regime_task", agent=regime_agent)

    # ── Task 3: Strategy Agent (sequential execution - one spread per cycle) ────────────────────
    strategy_task = tf.create_task(
        "strategy_task",
        agent=strategy_agent,
        context=[not_up_entry_task, not_down_entry_task, regime_task],
    )

    # ── Task 4: Contract Agent ─────────────────────────────────────────
    contract_task = tf.create_task(
        "contract_task",
        variables={"atm": atm, "expiry": expiry},
        agent=contract_agent,
        context=[strategy_task],
    )

    # ── Task 5: Execution Agent ────────────────────────────────────────
    execution_task = tf.create_task(
        "execution_task",
        variables={"spot": spot, "atm": atm, "vix": vix, "expiry": expiry},
        agent=execution_agent,
        context=[strategy_task, contract_task],
    )

    # ── Task 6: Risk Agent ─────────────────────────────────────────────
    risk_task = tf.create_task(
        "risk_task",
        variables={"wing_width": 200},
        agent=risk_agent,
        context=[execution_task],
    )

    # ── ENTRY GATE ─────────────────────────────────────────────────────────
    # USE_UNICORN: Adversarial debate pipeline. Entry agents replaced;
    #   Regime agent still runs separately. Downstream processing unchanged.
    # !USE_UNICORN: Legacy CrewAI entry agents with deterministic tools.

    if USE_UNICORN:
        _log("  Entry Gate: UNICORN (cached LLM research + deterministic execute)")
        try:
            from unicorn_raw_query import UnicornRawQuery
            from unicorn_debate import run_unicorn_debate
            from unicorn_anomaly import safe_debate
            from unicorn_research_cache import (
                load_debate_points,
                save_debate_points,
                compute_signature,
                cache_age_sec,
            )

            raw_query = UnicornRawQuery()
            raw_json = raw_query._run("NIFTY")
            raw_data = json.loads(raw_json)
            sig = compute_signature(raw_data)

            def _debate_or_fallback(raw, gate, label):
                """Load cached LLM points → verify (Python) → decide (Python).
                If cache miss → deterministic fallback + trigger async research.
                ALL paths sub-second, zero LLM API calls on this execution path."""
                import time as _time

                t0 = _time.time()
                advocate_pts, skeptic_pts = load_debate_points(gate, raw_signature=sig)
                if advocate_pts and skeptic_pts:
                    age = cache_age_sec(gate)
                    _log(
                        f"    {label}: Cache HIT ({age:.0f}s old, "
                        f"{len(advocate_pts)}a+{len(skeptic_pts)}s points)"
                    )
                    result = run_unicorn_debate(raw, gate, advocate_pts, skeptic_pts)
                    _log(
                        f"    {label}: → {result.get('signal', '?')} "
                        f"go={result.get('go')} conf={result.get('confidence')} "
                        f"({_time.time() - t0:.2f}s)"
                    )
                    return result
                else:
                    age = cache_age_sec(gate)
                    reason = f"expired ({age:.0f}s)" if age is not None else "empty"
                    _log(f"    {label}: Cache MISS ({reason}) → deterministic + async research")
                    _trigger_unicorn_research(gate)
                    result = run_unicorn_debate(raw, gate)
                    _log(
                        f"    {label}: → {result.get('signal', '?')} "
                        f"go={result.get('go')} conf={result.get('confidence')} "
                        f"({_time.time() - t0:.2f}s)"
                    )
                    return result

            not_up_decision = _debate_or_fallback(raw_data, "NOT_UP", "NOT_UP")
            not_down_decision = _debate_or_fallback(raw_data, "NOT_DOWN", "NOT_DOWN")

            # Run regime agent separately (unchanged CrewAI)
            regime_crew = Crew(
                agents=[regime_agent],
                tasks=[regime_task],
                process=Process.sequential,
                verbose=False,
                step_callback=_make_crew_step_callback("regime"),
                after_kickoff_callbacks=[_make_crew_after_callback("regime")],
            )
            try:
                regime_result = regime_crew.kickoff()
                regime = (
                    extract_task_output(regime_result.tasks_output[0])
                    if hasattr(regime_result, "tasks_output")
                    and len(regime_result.tasks_output) > 0
                    else {}
                )
            except Exception as e:
                _log(f"  Regime agent failed: {e}")
                regime = {}
            verify_regime_provenance(regime, vix, adx) if regime else None

        except Exception as e:
            _err(f"UNICORN entry gate failed: {e}")
            return deterministic_fallback(entry_time, spot, atm, vix, adx, snap)

    else:
        # ── Legacy ENTRY GATE: Run dual Entry Agents sequentially ─────────
        entry_crew = Crew(
            agents=[not_up_entry_agent, not_down_entry_agent, regime_agent],
            tasks=[not_up_entry_task, not_down_entry_task, regime_task],
            process=Process.sequential,
            verbose=False,
            step_callback=_make_crew_step_callback("entry_legacy"),
            after_kickoff_callbacks=[_make_crew_after_callback("entry_legacy")],
        )
        try:
            entry_result = entry_crew.kickoff()
        except Exception as e:
            _log(f"  Entry Crew failed: {e}")
            return deterministic_fallback(entry_time, spot, atm, vix, adx, snap)

        # Parse dual Entry Agents output
        not_up_decision = {}
        not_down_decision = {}
        regime = {}
        if hasattr(entry_result, "tasks_output"):
            try:
                not_up_decision = extract_task_output(entry_result.tasks_output[0])  # NOT_UP agent
                not_down_decision = extract_task_output(
                    entry_result.tasks_output[1]
                )  # NOT_DOWN agent
                regime = (
                    extract_task_output(entry_result.tasks_output[2])
                    if len(entry_result.tasks_output) > 2
                    else {}
                )  # Regime

                # Provenance guard: clamp hallucinated numbers to deterministic tool values
                verify_provenance(not_up_decision, "NOT_UP") if not_up_decision else None
                verify_provenance(not_down_decision, "NOT_DOWN") if not_down_decision else None
                verify_regime_provenance(regime, vix, adx) if regime else None

            except Exception as e:
                _err(f"Entry gate parse failed: {e}")
                return deterministic_fallback(entry_time, spot, atm, vix, adx, snap)

    agent_log(_agent, "NotUpEntry_Agent", not_up_decision)
    agent_log(_agent, "NotDownEntry_Agent", not_down_decision)

    # ── ENTRY GATE: Check both agents' decisions ─────────────────────────
    go_call_spread = not_up_decision.get("go", False)
    go_put_spread = not_down_decision.get("go", False)

    _log(
        f"  Entry Agents: NOT_UP={go_call_spread} ({not_up_decision.get('confidence', 0)}%) | "
        f"NOT_DOWN={go_put_spread} ({not_down_decision.get('confidence', 0)}%)"
    )

    # Block if BOTH reject (no opportunity)
    if not go_call_spread and not go_put_spread:
        _log("  Entry Agents: Both NO-GO (no trade opportunity)")
        return {
            "recommendation": "no_go",
            "not_up_decision": not_up_decision,
            "not_down_decision": not_down_decision,
            "entry_decision": {
                "source": not_up_decision.get("source", "canonical"),
                "signal": not_up_decision.get("signal"),
                "go": False,
                "confidence": not_up_decision.get("confidence"),
            },
            "regime": {
                "regime": regime.get("regime") or _snapshot_regime(adx, snap),
                "recommendation": regime.get("recommendation"),
                "vix": vix,
            },
            "spot": spot,
        }

    # Regime gate
    if regime.get("recommendation") == "skip":
        _log(f"  Regime: SKIP — VIX={regime.get('vix', '?')} | {regime.get('reason', '?')}")
        return {
            "recommendation": "regime_skip",
            "not_up_decision": not_up_decision,
            "not_down_decision": not_down_decision,
            "entry_decision": {
                "source": not_up_decision.get("source", "canonical"),
                "signal": not_up_decision.get("signal"),
                "go": False,
                "confidence": not_up_decision.get("confidence"),
            },
            "regime": {
                "regime": regime.get("regime") or _snapshot_regime(adx, snap),
                "recommendation": regime.get("recommendation"),
                "vix": vix,
            },
            "spot": spot,
        }

    if regime.get("recommendation") == "caution":
        _log(f"  Regime: CAUTION — VIX={regime.get('vix', '?')} | {regime.get('reason', '?')}")
        # Allow entry on caution but limit position size (Strategy agent handles this)

    _log(
        f"  Regime: {regime.get('regime')} (VIX={regime.get('vix', '?')}) → {regime.get('recommendation')}"
    )

    # ── Determine which spread to execute. When both gates fire, pick one based on
    # trend direction. The other gate fires in the next cycle, forming a dual spread
    # naturally. Morph system handles shifting if needed.
    # ─────────────────────────────────────────────────────────────────────────────

    entry_decision = {
        "go_call_spread": go_call_spread,
        "go_put_spread": go_put_spread,
        "not_up_signal": not_up_decision.get("signal"),
        "not_up_confidence": not_up_decision.get("confidence", 0),
        "not_down_signal": not_down_decision.get("signal"),
        "not_down_confidence": not_down_decision.get("confidence", 0),
        "regime": regime.get("regime"),
        "vix": regime.get("vix", 0),
        "strategy_to_execute": (
            "CALL_SPREAD" if go_call_spread else ("PUT_SPREAD" if go_put_spread else "NONE")
        ),
    }

    # Compute top-level signal/confidence/go (for downstream consumers like kickoff)
    if go_call_spread and go_put_spread:
        entry_decision["go"] = True
        entry_decision["signal"] = entry_decision["strategy_to_execute"]
        entry_decision["confidence"] = max(
            not_up_decision.get("confidence", 0),
            not_down_decision.get("confidence", 0),
        )
    elif go_call_spread:
        entry_decision["go"] = True
        entry_decision["signal"] = not_up_decision.get("signal", "NOT_UP")
        entry_decision["confidence"] = not_up_decision.get("confidence", 0)
    elif go_put_spread:
        entry_decision["go"] = True
        entry_decision["signal"] = not_down_decision.get("signal", "NOT_DOWN")
        entry_decision["confidence"] = not_down_decision.get("confidence", 0)
    else:
        entry_decision["go"] = False
        entry_decision["signal"] = "UNKNOWN"
        entry_decision["confidence"] = 0

    # ── NOW run remaining agents (Strategy, Contract, Execution, Risk) ─────────
    # Inject overridden entry decisions into strategy task (CrewAI context uses
    # original task outputs, not post-processed dicts)
    strategy_task.description = (
        strategy_task.description
        + f"\n\nOVERRIDDEN ENTRY DECISIONS (use these, not task context):\n"
        + f"  NOT_UP: go={go_call_spread}, confidence={entry_decision['not_up_confidence']}%\n"
        + f"  NOT_DOWN: go={go_put_spread}, confidence={entry_decision['not_down_confidence']}%\n"
        + f"  strategy_must_use: {entry_decision['strategy_to_execute']}\n"
    )
    try:
        full_crew = Crew(
            agents=[
                strategy_agent,
                contract_agent,
                execution_agent,
                risk_agent,
            ],
            tasks=[
                strategy_task,
                contract_task,
                execution_task,
                risk_task,
            ],
            process=Process.sequential,
            verbose=True,
            step_callback=_make_crew_step_callback("full"),
            after_kickoff_callbacks=[_make_crew_after_callback("full")],
            context=[
                not_up_entry_task,
                not_down_entry_task,
                regime_task,
            ],  # Pass dual entry + regime context
        )
        result = full_crew.kickoff()
    except Exception as e:
        _log(f"  Strategy/Execution Crew failed: {e}")
        return deterministic_fallback(entry_time, spot, atm, vix, adx, snap)

    # ── Log remaining agent outputs ─────────────────────────────────────
    agent_names = ["Strategy", "Contract", "Execution", "Risk"]
    parsed_outputs = [{}, {}, {}, {}]
    if hasattr(result, "tasks_output"):
        for i, name in enumerate(agent_names):
            if i < len(result.tasks_output):
                try:
                    parsed = extract_task_output(result.tasks_output[i])
                    parsed_outputs[i] = parsed
                    agent_log(_agent, f"{name}_Agent", parsed)
                    if not parsed:
                        _err(f"{name} Agent extracted empty: {str(result.tasks_output[i])[:200]}")
                except Exception as e:
                    _err(f"{name} Agent parse failed: {e} :: {str(result.tasks_output[i])[:200]}")
    else:
        _err(
            f"Strategy crew returned no tasks_output: type={type(result).__name__} "
            f"repr={repr(result)[:300]}"
        )

    strategy = parsed_outputs[0]
    contracts_data = parsed_outputs[1]
    trade = parsed_outputs[2]
    risk_confirmation = parsed_outputs[3]

    # ── Strategy summary ────────────────────────────────────────────────
    ww = strategy.get("wing_width", 200)
    sl_p = strategy.get("sl_pct", 0.25)
    tp_p = strategy.get("tp_pct", 0.50)
    stype = strategy.get("strategy_type", "NONE")
    regime_entry_signal = regime.get("entry_signal") or entry_decision.get("signal", "NOT_UP")

    strat_clean = verify_strategy_provenance(strategy)
    ww = strategy.get("wing_width", 200)
    sl_p = strategy.get("sl_pct", 0.25)
    tp_p = strategy.get("tp_pct", 0.50)

    _log(
        f"  Strategy: {stype} wings={ww} sl={sl_p} tp={tp_p} "
        f"| signal={regime_entry_signal}"
        f"{' — provenance OK' if strat_clean else ' — provenance CLAMPED'}"
    )

    # Return parsed outputs for run_full_chain to use
    return {
        "entry_decision": entry_decision,
        "regime": regime,
        "strategy": strategy,
        "contracts_data": contracts_data,
        "trade": trade,
        "risk_confirmation": risk_confirmation,
        "atm": atm,
        "spot": spot,
        "vix": vix,
        "adx": adx,
        "expiry": expiry,
        "regime_entry_signal": regime_entry_signal,
    }


def run_full_chain(
    entry_time: str, entry_signal: str = None, entry_confidence: int = 0
) -> dict | None:
    """
    Run full 6-agent pipeline: Entry → Regime → Strategy → Contract → Execution → Risk.
    All 6 agents run as a single sequential Crew. No separate Python phases.
    Returns trade dict or None if gate blocked.
    """
    from persistence import init_db

    init_db()

    crew_result = run_sequential_crew(entry_time)

    def _audit_entry_check(outcome: str, **extra):
        # Audit every entry-gate evaluation (GO and rejections) to the
        # structured monitoring JSONL. Lazy import avoids circular import.
        try:
            from logger import log_monitoring_event

            ed = (crew_result or {}).get("entry_decision", {})
            rg = (crew_result or {}).get("regime", {})
            log_monitoring_event(
                "ENTRY_CHECK",
                "NO_TRADE",
                entry_time=entry_time,
                outcome=outcome,
                signal=ed.get("signal"),
                confidence=ed.get("confidence"),
                go=ed.get("go"),
                regime=rg.get("regime"),
                regime_recommendation=rg.get("recommendation"),
                vix=rg.get("vix"),
                **extra,
            )

            # DAMBUILDER T5 — persist decision trace to capture SQLite
            spot = (crew_result or {}).get("spot")
            _dambuilder_trace(
                gate="NOT_UP",
                entry_decision=ed,
                regime=rg,
                outcome=outcome,
                spot=spot,
            )
            not_down_ed = (crew_result or {}).get("not_down_decision", {})
            _dambuilder_trace(
                gate="NOT_DOWN",
                entry_decision=not_down_ed if isinstance(not_down_ed, dict) else {},
                regime=rg,
                outcome=outcome,
                spot=spot,
            )
        except Exception as e:
            get_logger("chain").warning(f"entry-check audit failed: {e}")

    if crew_result is None:
        _audit_entry_check("crew_none")
        return None

    # Check entry gate
    if crew_result.get("recommendation") == "no_go":
        _audit_entry_check("no_go")
        _log("  Entry gate: NO-GO — aborting")
        return None

    # Check regime gate
    regime = crew_result.get("regime", {})
    if regime.get("recommendation") == "skip":
        _audit_entry_check("regime_skip")
        _log("  Regime gate: SKIP — aborting")
        return regime

    # Entry window gate: refuse entries after 15:00 IST (post-close tail)
    now_ist = datetime.now()
    if now_ist.hour > 15 or (now_ist.hour == 15 and now_ist.minute >= 5):
        _log("  Entry window: POST-CLOSE — refusing entry")
        return None

    # Extract trade from Execution Agent's output
    trade = crew_result.get("trade", {})
    if not trade:
        # Split-brain guard: CrewAI lost the crew output but orders may be live.
        # Reconcile from the cache written atomically by BuildAndExecuteTradeTool.
        from tools.chain_tools import get_last_built_trade

        recovered = get_last_built_trade(max_age_sec=60.0)
        if recovered:
            _log(
                "  ⚠ Execution: crew output lost — RECOVERED from trade cache "
                f"(id={recovered.get('trade_id')})"
            )
            trade = recovered
        else:
            _audit_entry_check("no_trade_returned")
            _log("  Execution: no trade returned — aborting")
            return None

    entry_decision = crew_result.get("entry_decision", {})

    # Ensure regime has fallback for GO-path audit (not just rejection paths)
    if regime and not regime.get("regime"):
        regime["regime"] = _snapshot_regime(
            crew_result.get("adx", 0), crew_result.get("spot_snapshot", {})
        )

    _audit_entry_check("go")

    # Attach ALL agent outputs for postmortem analysis
    # ── Entry Agent ────────────────────────────────────────
    trade["entry_scores"] = entry_decision
    trade["entry_gate_signal"] = entry_decision.get("signal", "UNKNOWN")
    trade["entry_confidence"] = entry_decision.get("confidence", 0)

    # ── Regime Agent ───────────────────────────────────────
    trade["regime_analysis"] = regime  # regime classification, VIX, ADX, recommendation

    # ── Strategy Agent ─────────────────────────────────────
    strategy = crew_result.get("strategy", {})
    trade["strategy_analysis"] = strategy  # wing_width optimization reasoning

    # ── Contract Agent ─────────────────────────────────────
    contracts_data = crew_result.get("contracts_data", {})
    trade["contracts_analysis"] = contracts_data  # contract resolution details

    # ── Execution Agent ────────────────────────────────────
    # (trade dict already contains: legs, net_credit, sl, tp, spot_at_entry, etc.)
    trade["execution_analysis"] = {
        "leg_count": trade.get("leg_count"),
        "net_credit": trade.get("net_credit"),
        "premium_sell": trade.get("premium_sell"),
        "premium_buy": trade.get("premium_buy"),
    }

    # ── Risk Agent ─────────────────────────────────────────
    risk_confirmation = crew_result.get("risk_confirmation", {})
    trade["risk_confirmation"] = risk_confirmation  # order_ids, placement status

    # Log chain summary
    chain_summary(
        _agent,
        {
            "entry_time": entry_time,
            "signal": entry_decision.get("signal", "?"),
            "confidence": entry_decision.get("confidence", 0),
            "strategy": trade.get("strategy_type", "?"),
            "legs": trade.get("leg_count", 0),
            "net_credit": trade.get("net_credit", 0),
            "wing_width": trade.get("wing_width", 0),
        },
    )

    # Optional CrewAI Execution→Risk chain test
    try:
        from crewai_chain import run_crewai_chain

        if run_crewai_chain(trade).get("status") == "success":
            _log("CrewAI Chain: ✅ context passed")
    except Exception:
        pass

    return trade
