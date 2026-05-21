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
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


from logger import get_logger, agent_log, chain_summary, log_exception

_log = get_logger("chain").info
_agent = get_logger("chain")
_err = lambda msg, exc=None: (
    log_exception(get_logger("chain"), exc, msg)
    if exc
    else get_logger("chain").error(msg)
)


def _get_llm():
    """Return DeepSeek LLM or None if unavailable."""
    from crewai import LLM

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        return None
    return LLM(
        model="deepseek/deepseek-chat",
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        api_key=api_key,
    )


def _parse_json_output(raw: str) -> dict:
    """Extract JSON from agent output string."""
    s = raw.find("{")
    e = raw.rfind("}") + 1
    if s >= 0 and e > s:
        return json.loads(raw[s:e])
    return {}


def run_sequential_crew(entry_time: str) -> dict | None:
    """
    Run Entry → Regime → Strategy as a single sequential CrewAI pipeline.
    Returns the combined agent decisions dict or None if Entry says NO-GO
    or if any agent fails.
    """
    llm = _get_llm()

    from factory import AgentFactory
    from duckdb_tool import MarketDataQueryTool, get_latest_market_snapshot

    af = AgentFactory()
    market_tool = MarketDataQueryTool()
    snap = get_latest_market_snapshot()

    spot = float(snap.get("spot", 0))
    atm = int(float(snap.get("atm_strike", 0)))
    vix = float(snap.get("india_vix", 0))
    adx_val = snap.get("adx")
    adx = float(adx_val) if adx_val and adx_val != "None" else 0.0

    if not spot or not atm:
        _log("  E2E Chain: ⚠ DuckDB empty — skipping")
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
        return _deterministic_fallback(entry_time, spot, atm, vix, adx, snap)

    # ── Build tools ────────────────────────────────────────────────────
    from tools.entry_gate_tools import QueryTrendEMA, QueryTrafficLight
    from tools.chain_tools import (
        ResolveOptionContractsTool,
        ExecutePaperTradeTool,
        PlaceEntryOrdersTool,
        PlaceSLTPOrdersTool,
    )

    trend_tool = QueryTrendEMA()
    tl_tool = QueryTrafficLight()
    contract_tool = ResolveOptionContractsTool()
    execution_tool = ExecutePaperTradeTool()
    entry_orders_tool = PlaceEntryOrdersTool()
    sl_tp_orders_tool = PlaceSLTPOrdersTool()

    # Risk tools (still needed for monitoring phase: morph/shift operations)
    from tools.risk_tools import (
        PlaceSLOrderTool,
        PlaceTPOrderTool,
        CancelOrderTool,
        ModifySLOrderTool,
    )

    sl_tool = PlaceSLOrderTool()
    tp_tool = PlaceTPOrderTool()
    cancel_tool = CancelOrderTool()
    modify_sl_tool = ModifySLOrderTool()

    # ── Build agents ───────────────────────────────────────────────────
    try:
        entry_agent = af.create_agent("entry_agent", {}, tools=[trend_tool, tl_tool])
        entry_agent.llm = llm

        regime_agent = af.create_agent("regime_agent", {}, tools=[market_tool])
        regime_agent.llm = llm

        strategy_agent = af.create_agent("strategy_agent", {}, tools=[market_tool])
        strategy_agent.llm = llm

        contract_agent = af.create_agent("contract_agent", {}, tools=[contract_tool])
        contract_agent.llm = llm

        execution_agent = af.create_agent(
            "execution_agent",
            variables={
                "market_type": "NIFTY",
                "strategy_type": "deterministic",
                "ticker": "NIFTY",
                "mock_mode": "paper",
            },
            tools=[execution_tool, entry_orders_tool],
        )
        execution_agent.llm = llm

        risk_agent = af.create_agent(
            "risk_agent",
            variables={"market_type": "NIFTY", "ticker": "NIFTY", "mock_mode": "paper"},
            tools=[sl_tp_orders_tool],  # Entry phase: ONLY use centralized order routing
        )
        risk_agent.llm = llm

        # Order Agent (routes orders through centralized hub)
        order_agent = af.create_agent(
            "order_agent",
            variables={"market_type": "NIFTY", "ticker": "NIFTY"},
            tools=[entry_orders_tool, sl_tp_orders_tool],
        )
        order_agent.llm = llm
    except KeyError as e:
        _log(f"  ⚠ Agent factory: {e}")
        return _deterministic_fallback(entry_time, spot, atm, vix, adx, snap)

    expiry = snap.get("expiry_weekly", "")
    from crewai import Task, Crew, Process

    # ── Task 1: Entry Agent ────────────────────────────────────────────
    entry_task = Task(
        description=(
            "Evaluate whether NOW is a valid entry moment for NIFTY.\n\n"
            "STEP 1: Call query_trend_ema(NIFTY) to get the Trend signal.\n"
            "STEP 2: Call query_traffic_light(NIFTY) to get the Traffic Light signal.\n"
            "STEP 3: Apply the combine rules as described in your backstory:\n"
            "  - Both BULLISH → GO, SELL_PUT, confidence × 1.0\n"
            "  - Both BEARISH → GO, SELL_CALL, confidence × 1.0\n"
            "  - One BULLISH/BEARISH + NEUTRAL → GO, 0.75x confidence\n"
            "  - Both NEUTRAL → GO, IRON_BUTTERFLY, 0.5x confidence\n"
            "  - BULLISH vs BEARISH conflict → NO-GO, NONE\n\n"
            "IMPORTANT: Return ONLY valid JSON with these exact fields:\n"
            '{"go": true/false, "signal": "BULLISH"|"BEARISH"|"NEUTRAL", '
            '"confidence": 0-100, "suggested_trade": "SELL_PUT"|"SELL_CALL"|'
            '"IRON_BUTTERFLY"|"NONE", "reasoning": "..."}'
        ),
        expected_output="Entry decision JSON with go, signal, confidence, suggested_trade",
        agent=entry_agent,
    )

    # ── Task 2: Regime Agent ───────────────────────────────────────────
    regime_task = Task(
        description=(
            "Classify the NIFTY market regime.\n\n"
            "The Entry Agent's decision is in your context. Parse the JSON to get: "
            "go (bool), signal (BULLISH/BEARISH/NEUTRAL), confidence (0-100). "
            "This is ground truth.\n\n"
            "ONE TOOL CALL ONLY: Call query_market_data(query_type='full_regime') "
            "to get spot, EMA_20, st_15min_direction, ADX, VIX, and regime indicators.\n\n"
            "VALIDATE the Entry Agent's signal:\n"
            "- BULLISH: spot > EMA_20 and st_15min_direction = 'bullish'\n"
            "- BEARISH: spot < EMA_20 and st_15min_direction = 'bearish'\n"
            "- NEUTRAL: ADX < 25 and spot near EMA\n\n"
            "ADDITIONAL: VIX > 18 → recommendation='caution'. IV rank > 85 → 'caution'.\n"
            "ADX < 25 → regime='sideways', ADX > 25 → regime='trending_bullish/bearish'.\n\n"
            "Output ONLY valid JSON:\n"
            '{"regime": "trending_bullish"|"trending_bearish"|"sideways", '
            '"confidence": 0.0-1.0, "recommendation": "enter"|"caution"|"skip", '
            '"vix": 0.0, "entry_signal": "BULLISH"|"BEARISH"|"NEUTRAL", "reason": "..."}\n\n'
            "CRITICAL: Preserve Entry Agent's signal as entry_signal. Include VIX in output."
        ),
        expected_output="Regime JSON with entry_signal preserved + vix for Strategy",
        agent=regime_agent,
        context=[entry_task],
    )

    # ── Task 3: Strategy Agent ─────────────────────────────────────────
    strategy_task = Task(
        description=(
            "Select strategy based on context from previous agents.\n\n"
            "Parse the Entry Agent's output to get entry_signal (BULLISH/BEARISH/NEUTRAL).\n"
            "Parse the Regime Agent's output to get VIX and ADX for parameter optimization.\n\n"
            "ENTRY_SIGNAL → STRATEGY MAPPING:\n"
            "- BULLISH → PUT_SPREAD (2 legs: sell ATM PE + buy ATM-ww PE)\n"
            "- BEARISH → CALL_SPREAD (2 legs: sell ATM CE + buy ATM+ww CE)\n"
            "- NEUTRAL → IRON_BUTTERFLY (4 legs: sell ATM CE+PE + buy ATM±ww CE+PE)\n\n"
            "PARAMETERS (from Regime VIX and ADX):\n"
            "- wing_width: 200 default, 150 if VIX < 15, 250 if VIX > 20\n"
            "- sl_pct: 0.25 default, 0.35 if VIX > 18\n"
            "- tp_pct: 0.50 default, 0.40 if ADX > 30, 0.55 if ADX < 20\n"
            "- If VIX/ADX missing from Regime, call query_market_data to get them.\n\n"
            "Strategy type NEVER changes based on regime — entry_signal is final.\n\n"
            "Output ONLY valid JSON:\n"
            '{"strategy_type": "PUT_SPREAD"|"CALL_SPREAD"|"IRON_BUTTERFLY", '
            '"wing_width": 200, "sl_pct": 0.25, "tp_pct": 0.50, "reason": "..."}'
        ),
        expected_output="Strategy JSON",
        agent=strategy_agent,
        context=[entry_task, regime_task],
    )

    # ── Task 4: Contract Agent ─────────────────────────────────────────
    contract_task = Task(
        description=(
            "Resolve option contracts from DuckDB.\n\n"
            "Parse Strategy Agent's output to get strategy_type and wing_width.\n"
            f"ATM: {atm}. Expiry: {expiry}.\n\n"
            "Call resolve_option_contracts(strategy_type, atm, wing_width, expiry).\n"
            "Return the contracts JSON as-is from the tool. Do not modify.\n\n"
            "Output ONLY valid JSON (the tool's output is already correct)."
        ),
        expected_output="Contracts JSON with tsyms and ltps",
        agent=contract_agent,
        context=[strategy_task],
    )

    # ── Task 5: Execution Agent ────────────────────────────────────────
    execution_task = Task(
        description=(
            "Build the trade and route entry orders via the centralized Order Agent.\n\n"
            "STEP 1: Parse Contract Agent's output for resolved contracts (tsym, ltp, strike, action).\n"
            "STEP 2: Parse Strategy Agent's output for strategy_type, wing_width, sl_pct, tp_pct.\n"
            f"STEP 3: Call execute_paper_trade(contracts_json, strategy_type, entry_time, "
            f"spot={spot}, atm={atm}, vix={vix}, expiry='{expiry}', "
            "wing_width, sl_pct, tp_pct) to build trade dict.\n"
            "  This calculates net_credit, SL/TP levels, and returns the complete trade.\n\n"
            "VERIFICATION: Check the trade dict from execute_paper_trade:\n"
            "  ✓ net_credit > 0 (strategy generates premium)\n"
            "  ✓ SL > LTP on every SELL leg (SL is above current price)\n"
            "  ✓ TP < LTP on every SELL leg (TP is below current price)\n"
            "  ✓ leg_count matches strategy (2 for spreads, 4 for butterfly)\n\n"
            "STEP 4: Hand off ALL entry legs to Order Agent via place_entry_orders(legs).\n"
            "  CRITICAL: Call place_entry_orders with the legs from the trade dict.\n"
            "  The Order Agent inside place_entry_orders will:\n"
            "    - PAPER mode: save to order_ledger.json, return order_ids\n"
            "    - LIVE mode:  forward to Shoonya API, return broker order_ids\n"
            "  Return value: {trade_id, entry_orders: [order_ids], status, mode}\n\n"
            "STEP 5: Extract trade_id from place_entry_orders result.\n"
            "  Pass trade_id to Risk Agent (in next task context) for SL/TP routing.\n\n"
            "Output the complete trade dict with entry_order_results (trade_id + order_ids)."
        ),
        expected_output="Trade dict with legs, net_credit, sl, tp, trade_id, and entry_orders routed via Order Agent",
        agent=execution_agent,
        context=[strategy_task, contract_task],
    )

    # ── Task 6: Risk Agent ─────────────────────────────────────────────
    risk_task = Task(
        description=(
            "ENTRY PHASE: Place all SL and TP orders via the centralized Order Agent.\n\n"
            "YOUR ONLY TOOL: place_sl_tp_orders (routes through Order Agent hub)\n\n"
            "STEP 1: Parse Execution Agent's output to extract:\n"
            "  - trade_id (from the execution output)\n"
            "  - legs (array of leg dicts with tsym, action, strike, type, quantity, sl, tp)\n\n"
            "STEP 2: Call place_sl_tp_orders(trade_id=<trade_id>, legs=<legs>)\n"
            "  This is the ONLY way to place SL/TP orders in entry phase.\n"
            "  The Order Agent inside place_sl_tp_orders will:\n"
            "    - PAPER mode: save to order_ledger.json\n"
            "    - LIVE mode:  forward to Shoonya API\n\n"
            "MECHANICS (for reference — Order Agent handles):\n"
            "  - SELL legs (center): get SL (buy trigger when price rises) + TP (buy limit when price falls)\n"
            "  - BUY legs (hedges): get NO orders — held to expiry\n"
            "  - SL = entry_premium × (1 + sl_pct). TP = entry_premium × (1 - tp_pct)\n\n"
            "CRITICAL: Do NOT call place_sl_order or place_tp_order directly.\n"
            "Only call place_sl_tp_orders. All orders route through the centralized hub.\n\n"
            f"Risk limits: max loss per spread = (wing_width - net_credit) * 65.\n\n"
            "Output: confirmation JSON with sl_order_ids and tp_order_ids from the Order Agent."
        ),
        expected_output="Risk confirmation with SL/TP order IDs routed via Order Agent",
        agent=risk_agent,
        context=[execution_task],
    )

    # ── Run full 6-agent sequential Crew ───────────────────────────────
    try:
        crew = Crew(
            agents=[
                entry_agent,
                regime_agent,
                strategy_agent,
                contract_agent,
                execution_agent,
                risk_agent,
            ],
            tasks=[
                entry_task,
                regime_task,
                strategy_task,
                contract_task,
                execution_task,
                risk_task,
            ],
            process=Process.sequential,
            verbose=True,
        )
        result = crew.kickoff()
    except Exception as e:
        _log(f"  Crew pipeline failed: {e}")
        return _deterministic_fallback(entry_time, spot, atm, vix, adx, snap)

    # ── Log each agent's output for troubleshooting ─────────────────────
    agent_names = ["Entry", "Regime", "Strategy", "Contract", "Execution", "Risk"]
    parsed_outputs = [{}, {}, {}, {}, {}, {}]
    if hasattr(result, "tasks_output"):
        for i, name in enumerate(agent_names):
            if i < len(result.tasks_output):
                raw = str(result.tasks_output[i])
                try:
                    parsed = _parse_json_output(raw)
                    parsed_outputs[i] = parsed
                    agent_log(_agent, f"{name}_Agent", parsed)
                except Exception:
                    _err(f"{name} Agent parse failed: {raw[:200]}")
    else:
        raw_str = str(result)
        _err(f"Crew raw output (no tasks_output): {raw_str[:500]}")
        try:
            parsed_outputs[5] = _parse_json_output(raw_str)
        except Exception:
            pass

    entry_decision = parsed_outputs[0]
    regime = parsed_outputs[1]
    strategy = parsed_outputs[2]
    contracts_data = parsed_outputs[3]
    trade = parsed_outputs[4]
    risk_confirmation = parsed_outputs[5]

    # ── Entry gate: NO-GO stops everything ─────────────────────────────
    if not entry_decision.get("go", False):
        _log(
            f"  Entry Agent: NO-GO | {entry_decision.get('signal')} "
            f"{entry_decision.get('confidence')}% | {entry_decision.get('reasoning', '?')}"
        )
        return {"recommendation": "no_go", "entry_decision": entry_decision}

    _log(
        f"  Entry Agent: GO | {entry_decision.get('signal')} "
        f"{entry_decision.get('confidence')}% | → {entry_decision.get('suggested_trade')}"
    )

    # ── Regime gate ────────────────────────────────────────────────────
    if regime.get("recommendation") == "skip":
        _log(f"  Regime: SKIP — {regime.get('reason', '?')}")
        return regime

    _log(f"  Regime: {regime.get('regime')} → {regime.get('recommendation')}")

    # ── Strategy ───────────────────────────────────────────────────────
    ww = strategy.get("wing_width", 200)
    sl_p = strategy.get("sl_pct", 0.25)
    tp_p = strategy.get("tp_pct", 0.50)
    stype = strategy.get("strategy_type", "IRON_BUTTERFLY")
    regime_entry_signal = regime.get("entry_signal") or entry_decision.get(
        "signal", "NEUTRAL"
    )

    _log(
        f"  Strategy: {stype} wings={ww} sl={sl_p} tp={tp_p} | signal={regime_entry_signal}"
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


def _deterministic_fallback(entry_time, spot, atm, vix, adx, snap):
    """Deterministic fallback when LLM is unavailable."""
    from pathlib import Path as _Path

    _ANTARIKSH = _Path(__file__).parent.parent / "antariksh"
    sys.path.insert(0, str(_ANTARIKSH))

    from tools.entry_tools import (
        score_trend_redis,
        score_traffic_light_redis,
        combine_entry_scores,
    )

    trend = score_trend_redis("NIFTY")
    tl = score_traffic_light_redis("NIFTY")
    decision = combine_entry_scores(trend, tl)

    _log(
        f"  Entry (deterministic): {'GO' if decision['go'] else 'NO-GO'} | "
        f"{decision['signal']} {decision['confidence']}% | → {decision.get('suggested_trade')}"
    )

    if not decision["go"]:
        return {"recommendation": "no_go", "entry_decision": decision}

    stype = {
        "BULLISH": "PUT_SPREAD",
        "BEARISH": "CALL_SPREAD",
        "NEUTRAL": "IRON_BUTTERFLY",
    }.get(decision["signal"], "IRON_BUTTERFLY")

    return {
        "entry_decision": decision,
        "regime": {
            "regime": "sideways" if adx < 25 else "trending",
            "recommendation": "caution" if vix > 18 else "enter",
            "confidence": 0.6,
        },
        "strategy": {
            "strategy_type": stype,
            "wing_width": 200,
            "sl_pct": 0.25,
            "tp_pct": 0.50,
            "entry_signal": decision["signal"],
        },
        "atm": atm,
        "spot": spot,
        "vix": vix,
        "adx": adx,
        "regime_entry_signal": decision["signal"],
    }


def _resolve_contracts(
    atm: int, wing_width: int, expiry: str, option_tool, strategy_type: str
) -> tuple:
    """Generate leg specs from strategy + query DuckDB for contract tsyms/LTPs."""
    from duckdb_tool import _connect

    if strategy_type == "PUT_SPREAD":
        leg_specs = [
            ("sell_pe", atm, "PE", "SELL"),
            ("buy_pe", atm - wing_width, "PE", "BUY"),
        ]
    elif strategy_type == "CALL_SPREAD":
        leg_specs = [
            ("sell_ce", atm, "CE", "SELL"),
            ("buy_ce", atm + wing_width, "CE", "BUY"),
        ]
    else:
        leg_specs = [
            ("center_ce", atm, "CE", "SELL"),
            ("center_pe", atm, "PE", "SELL"),
            ("wing_below", atm - wing_width, "PE", "BUY"),
            ("wing_above", atm + wing_width, "CE", "BUY"),
        ]

    con = _connect()
    try:
        result = {}
        for label, strike, ot, action in leg_specs:
            row = con.execute(
                "SELECT tsym, ltp FROM option_snapshots "
                "WHERE expiry_date = ? AND strike = ? AND option_type = ? "
                "AND tsym IS NOT NULL ORDER BY timestamp DESC LIMIT 1",
                (expiry, strike, ot),
            ).fetchone()
            if row:
                result[label] = {
                    "tsym": row[0],
                    "ltp": float(row[1] or 0),
                    "strike": strike,
                    "option_type": ot,
                    "action": action,
                }
            else:
                result[label] = {
                    "tsym": f"NIFTY{expiry.replace('-', '')}{ot[0]}{strike}",
                    "ltp": 0.0,
                    "strike": strike,
                    "option_type": ot,
                    "action": action,
                }
        return result, leg_specs
    finally:
        con.close()


def _build_trade(
    entry_time,
    spot,
    atm,
    vix,
    expiry,
    ww,
    sl_p,
    tp_p,
    contracts,
    strategy_type,
) -> dict:
    legs = []
    sl = {}
    tp = {}
    prem_sell = 0.0
    prem_buy = 0.0
    for label, c in contracts.items():
        leg = {
            "action": c["action"],
            "strike": c["strike"],
            "type": c["option_type"],
            "fill_price": c["ltp"],
            "tsym": c["tsym"],
        }
        legs.append(leg)
        if c["action"] == "SELL":
            prem_sell += c["ltp"]
            key = c["option_type"].lower()
            sl[key] = round(c["ltp"] * (1 + sl_p), 2)
            tp[key] = round(c["ltp"] * (1 - tp_p), 2)
        else:
            prem_buy += c["ltp"]
    return {
        "entry_time": entry_time,
        "spot_at_entry": spot,
        "atm_strike": atm,
        "vix": vix,
        "expiry": expiry,
        "wing_width": ww,
        "strategy_type": strategy_type,
        "leg_count": len(legs),
        "net_credit": round(prem_sell - prem_buy, 2),
        "premium_sell": round(prem_sell, 2),
        "premium_buy": round(prem_buy, 2),
        "legs": legs,
        "sl": sl,
        "tp": tp,
        "status": "OPEN",
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
    if crew_result is None:
        return None

    # Check entry gate
    if crew_result.get("recommendation") == "no_go":
        _log("  Entry gate: NO-GO — aborting")
        return None

    # Check regime gate
    regime = crew_result.get("regime", {})
    if regime.get("recommendation") == "skip":
        _log("  Regime gate: SKIP — aborting")
        return regime

    # Extract trade from Execution Agent's output
    trade = crew_result.get("trade", {})
    if not trade:
        _log("  Execution: no trade returned — aborting")
        return None

    entry_decision = crew_result.get("entry_decision", {})

    # Attach metadata for monitoring
    trade["entry_scores"] = entry_decision
    trade["entry_gate_signal"] = entry_decision.get("signal", "UNKNOWN")
    trade["entry_confidence"] = entry_decision.get("confidence", 0)

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
