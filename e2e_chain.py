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
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
load_dotenv()


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
        temperature=0,
    )


def _parse_json_output(raw: str) -> dict:
    """Extract JSON from agent raw output (may have markdown fences)."""
    import re

    if not raw or not raw.strip():
        return {}
    match = re.search(r"\{(?:[^{}]|\{[^{}]*\})*\}", raw, re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return {}


def _recompute_regime(vix: float, adx: float) -> dict:
    """Deterministic regime from VIX/ADX. Same rules as entry_tools.score_regime()."""
    if vix > 25:
        return {"recommendation": "skip", "vix": vix, "adx": adx}
    if adx and adx < 20:
        return {"recommendation": "skip", "vix": vix, "adx": adx}
    if vix > 18:
        return {"recommendation": "caution", "vix": vix, "adx": adx}
    if adx and adx < 25:
        return {"recommendation": "caution", "vix": vix, "adx": adx}
    return {"recommendation": "enter", "vix": vix, "adx": adx}


def _verify_regime_provenance(regime: dict, vix: float, adx: float) -> bool:
    """Verify regime agent recommendation against deterministic recomputation.
    Clamps hallucinated VIX/ADX values and incorrect recommendations."""
    expected = _recompute_regime(vix, adx)
    violations = []
    agent_vix = regime.get("vix", 0)
    agent_adx = regime.get("adx", 0)

    if agent_vix and abs(agent_vix - vix) > 0.5:
        violations.append(f"vix agent={agent_vix:.1f} actual={vix:.1f}")
        regime["vix"] = vix
    if agent_adx and abs(agent_adx - adx) > 1.0:
        violations.append(f"adx agent={agent_adx:.1f} actual={adx:.1f}")
        regime["adx"] = adx

    if regime.get("recommendation") != expected["recommendation"]:
        violations.append(
            f"rec agent={regime.get('recommendation')} expected={expected['recommendation']}"
        )
        regime["recommendation"] = expected["recommendation"]

    if violations:
        _err(f"PROVENANCE VIOLATION [REGIME]: {', '.join(violations)} — CLAMPED")
        return False

    _log(
        f"  Regime: {regime['recommendation'].upper()} "
        f"(VIX={vix:.1f}, ADX={adx:.1f}) — provenance OK"
    )
    return True


def _verify_strategy_provenance(strategy: dict) -> bool:
    """Verify strategy agent output against deterministic parameter rules.
    Validates and clamps: wing_width, sl_pct, tp_pct, strategy_type."""
    violations = []

    VALID_TYPES = {"CALL_SPREAD", "PUT_SPREAD", "IRON_BUTTERFLY"}
    if strategy.get("strategy_type") not in VALID_TYPES:
        violations.append(f"strategy_type={strategy.get('strategy_type')}")
        strategy["strategy_type"] = "IRON_BUTTERFLY"

    ww = strategy.get("wing_width", 200)
    if not isinstance(ww, (int, float)) or ww < 50 or ww > 500:
        violations.append(f"wing_width={ww}")
        strategy["wing_width"] = 200

    sl_p = strategy.get("sl_pct", 0.25)
    if not isinstance(sl_p, (int, float)) or sl_p < 0.10 or sl_p > 0.50:
        violations.append(f"sl_pct={sl_p}")
        strategy["sl_pct"] = 0.25

    tp_p = strategy.get("tp_pct", 0.50)
    if not isinstance(tp_p, (int, float)) or tp_p < 0.15 or tp_p > 0.75:
        violations.append(f"tp_pct={tp_p}")
        strategy["tp_pct"] = 0.50

    if violations:
        _err(f"PROVENANCE VIOLATION [STRATEGY]: {', '.join(violations)} — CLAMPED")
        return False
    return True


def _recompute_gate(decision: dict, gate_type: str) -> dict:
    """Recompute the deterministic gate output from agent's trend+TL signals.
    Returns (expected_go, expected_confidence). Used for provenance check.
    """
    t_sig = decision.get("trend_signal", "NEUTRAL").upper()
    t_conf = decision.get("trend_confidence", 50)
    tl_sig = decision.get("traffic_light_signal", "NEUTRAL").upper()
    tl_conf = decision.get("traffic_light_confidence", 50)

    go = False
    confidence = 0

    if gate_type == "NOT_UP":
        if t_sig == "BEARISH" and tl_sig == "BEARISH":
            go = True
            confidence = round((t_conf + tl_conf) / 2)
        elif (t_sig == "BEARISH" and tl_sig == "NEUTRAL") or (
            t_sig == "NEUTRAL" and tl_sig == "BEARISH"
        ):
            go = True
            confidence = round(max(t_conf if t_sig == "BEARISH" else tl_conf, 0) * 0.67)
        elif t_sig == "BULLISH" or tl_sig == "BULLISH":
            go = False
            confidence = 0
        else:
            go = False
            confidence = 0
    else:  # NOT_DOWN
        if t_sig == "BULLISH" and tl_sig == "BULLISH":
            go = True
            confidence = round((t_conf + tl_conf) / 2)
        elif (t_sig == "BULLISH" and tl_sig == "NEUTRAL") or (
            t_sig == "NEUTRAL" and tl_sig == "BULLISH"
        ):
            go = True
            confidence = round(max(t_conf if t_sig == "BULLISH" else tl_conf, 0) * 0.67)
        elif t_sig == "BEARISH" or tl_sig == "BEARISH":
            go = False
            confidence = 0
        else:
            go = False
            confidence = 0

    return {"go": go, "confidence": confidence}


def _verify_provenance(decision: dict, gate_type: str) -> bool:
    """Verify agent decision numbers match deterministic gate recomputation.
    Returns True if clean, False if hallucination detected (patches decision)."""
    expected = _recompute_gate(decision, gate_type)

    violations = []
    if decision.get("go") != expected["go"]:
        violations.append(f"go agent={decision.get('go')} expected={expected['go']}")
        decision["go"] = expected["go"]  # clamp to truth
    if decision.get("confidence", 0) != expected["confidence"]:
        violations.append(
            f"confidence agent={decision.get('confidence')} expected={expected['confidence']}"
        )
        decision["confidence"] = expected["confidence"]  # clamp to truth

    if violations:
        _err(
            f"PROVENANCE VIOLATION [{gate_type}]: {', '.join(violations)}  "
            f"trend={decision.get('trend_signal')}/{decision.get('trend_confidence')}% "
            f"tl={decision.get('traffic_light_signal')}/{decision.get('traffic_light_confidence')}% "
            f"— CLAMPED to deterministic values"
        )
        return False
    return True


def _get_research_consensus() -> str:
    """Load ChromaDB research patterns and return consensus direction.
    Returns BULLISH, BEARISH, NEUTRAL, or UNKNOWN if ChromaDB unavailable."""
    try:
        from entry_agent import EntryAgent

        ea = EntryAgent()
        if not ea.patterns:
            return "UNKNOWN"

        directions = [p.get("predicted_direction", "NEUTRAL") for p in ea.patterns]
        bull = sum(1 for d in directions if d == "BULLISH")
        bear = sum(1 for d in directions if d == "BEARISH")
        neutral = sum(1 for d in directions if d == "NEUTRAL")

        if neutral >= len(directions) * 0.5:
            return "NEUTRAL"
        elif bull > bear:
            return "BULLISH"
        elif bear > bull:
            return "BEARISH"
        return "NEUTRAL"
    except Exception:
        return "UNKNOWN"


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
        return _deterministic_fallback(entry_time, spot, atm, vix, adx, snap)

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
        return _deterministic_fallback(entry_time, spot, atm, vix, adx, snap)

    expiry = snap.get("expiry_weekly", "")
    # Guard: if data capture didn't run today, expiry_weekly may be stale (yesterday's)
    # Never trade expired contracts — compute fresh expiry
    from datetime import date as _dt

    try:
        expiry_dt = datetime.strptime(expiry, "%d-%b-%Y").date()
        if expiry_dt < _dt.today():
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
    from crewai import Task, Crew, Process

    # ── Task 1a: NOT_UP Entry Agent (CALL_SPREAD gate) ─────────────────
    not_up_entry_task = Task(
        description=(
            "Independently evaluate if market rejects upside (bearish pressure).\n\n"
            "Your sole job: Decide whether to PLACE CALL_SPREAD.\n\n"
            "STEP 1: Call query_trend_ema(NIFTY) to get Trend signal.\n"
            "STEP 2: Call query_traffic_light(NIFTY) to get Traffic Light signal.\n"
            "STEP 3: Apply NOT_UP rejection logic:\n"
            "  - Both BEARISH → go:true, confidence 90%\n"
            "  - One BEARISH + one NEUTRAL → go:true, confidence 60%\n"
            "  - Both NEUTRAL or any BULLISH → go:false\n\n"
            "IMPORTANT: Return ONLY valid JSON:\n"
            '{"go": true/false, "signal": "NOT_UP", "confidence": 0-100, '
            '"trend_signal": "BEARISH"|"NEUTRAL"|"BULLISH", '
            '"traffic_light_signal": "BEARISH"|"NEUTRAL"|"BULLISH", '
            '"reasoning": "why market rejects upside or not"}'
        ),
        expected_output="NOT_UP entry decision JSON with go flag",
        agent=not_up_entry_agent,
    )

    # ── Task 1b: NOT_DOWN Entry Agent (PUT_SPREAD gate) ────────────────
    not_down_entry_task = Task(
        description=(
            "Independently evaluate if market rejects downside (bullish pressure).\n\n"
            "Your sole job: Decide whether to PLACE PUT_SPREAD.\n\n"
            "STEP 1: Call query_trend_ema(NIFTY) to get Trend signal.\n"
            "STEP 2: Call query_traffic_light(NIFTY) to get Traffic Light signal.\n"
            "STEP 3: Apply NOT_DOWN rejection logic:\n"
            "  - Both BULLISH → go:true, confidence 90%\n"
            "  - One BULLISH + one NEUTRAL → go:true, confidence 60%\n"
            "  - Both NEUTRAL or any BEARISH → go:false\n\n"
            "IMPORTANT: Return ONLY valid JSON:\n"
            '{"go": true/false, "signal": "NOT_DOWN", "confidence": 0-100, '
            '"trend_signal": "BULLISH"|"NEUTRAL"|"BEARISH", '
            '"traffic_light_signal": "BULLISH"|"NEUTRAL"|"BEARISH", '
            '"reasoning": "why market rejects downside or not"}'
        ),
        expected_output="NOT_DOWN entry decision JSON with go flag",
        agent=not_down_entry_agent,
    )

    # ── Task 2: Regime Agent ───────────────────────────────────────────
    regime_task = Task(
        description=(
            "Get market regime data for position sizing + morpher.\n\n"
            "ONE TOOL CALL: query_market_data(query_type='full_regime') to fetch VIX, ADX, ADX direction.\n\n"
            "Gating rules (VIX only):\n"
            "  - VIX > 25 → recommendation: 'skip' (panic, no entries)\n"
            "  - VIX > 18 → recommendation: 'caution' (reduce size)\n"
            "  - Else → recommendation: 'enter'\n\n"
            "ADX is a dummy pass-through — does NOT block entry.\n"
            "It is passed to position manager for stop/morph decisions.\n\n"
            "OUTPUT only valid JSON:\n"
            '{"vix": 0.0, "adx": 0.0, "recommendation": "enter"|"caution"|"skip", "reason": "..."}'
        ),
        expected_output="Regime JSON with VIX and ADX",
        agent=regime_agent,
        context=[],
    )

    # ── Task 3: Strategy Agent (sequential execution - one spread per cycle) ────────────────────
    strategy_task = Task(
        description=(
            "Dual-Entry Sequential Execution: Pick ONE spread to execute this cycle.\n\n"
            "STEP 1: Parse both entry decisions from context:\n"
            "  - NOT_UP decision: go=true/false → execute CALL_SPREAD if true\n"
            "  - NOT_DOWN decision: go=true/false → execute PUT_SPREAD if true\n\n"
            "STEP 2: SEQUENTIAL LOGIC (one spread per cycle):\n"
            "  IF BOTH go_call_spread AND go_put_spread are true:\n"
            "    → Market is sideways (both sides valid). Output IRON_BUTTERFLY.\n"
            "    → Use IRON_BUTTERFLY with wing_width optimization from Regime (VIX) data.\n"
            "  ELSE IF go_call_spread=true: output CALL_SPREAD parameters (this cycle)\n"
            "  ELSE IF go_put_spread=true: output PUT_SPREAD parameters (this cycle)\n"
            '  ELSE: return {"skip": true}\n\n'
            "STEP 3: Optimize parameters from Regime data (VIX, ADX):\n"
            "  - wing_width: 200 default, 150 if VIX<15, 250 if VIX>20\n"
            "  - sl_pct: 0.25 default, 0.35 if VIX>18\n"
            "  - tp_pct: 0.50 default, 0.40 if ADX>30, 0.55 if ADX<20\n"
            "  - IRON_BUTTERFLY gets same wing_width optimization\n\n"
            "OUTPUT JSON (one of):\n"
            '{"strategy_type": "CALL_SPREAD", "wing_width": 200, "sl_pct": 0.25, "tp_pct": 0.50}\n'
            'OR {"strategy_type": "PUT_SPREAD", "wing_width": 200, "sl_pct": 0.25, "tp_pct": 0.50}\n'
            'OR {"strategy_type": "IRON_BUTTERFLY", "wing_width": 200, "sl_pct": 0.25, "tp_pct": 0.50}'
        ),
        expected_output="CALL_SPREAD, PUT_SPREAD, or IRON_BUTTERFLY parameters",
        agent=strategy_agent,
        context=[not_up_entry_task, not_down_entry_task, regime_task],
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
            "═══ PHASE 1 (Current): NIFTY/SENSEX Options ═══\n"
            "YOU ARE A DUMB EXECUTOR. All decisions are made upstream.\n\n"
            "UPSTREAM DECISIONS (already made):\n"
            "  ✓ Entry Agent: Is there a signal? → YES\n"
            "  ✓ Regime Agent: What's the regime? → Sideways\n"
            "  ✓ Strategy Agent: What to trade? → CALL_SPREAD (wing_width=200, sl=0.25, tp=0.50)\n"
            "  ✓ Contract Agent: What contracts? → Resolved tsyms + ltps\n"
            "  ✓ Asset (Phase 1): NIFTY (only option in Phase 1)\n\n"
            "YOUR JOB:\n"
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
            "Output the complete trade dict with entry_order_results (trade_id + order_ids).\n\n"
            "═══ PHASE 2+ (Future): Multi-Asset Expansion ═══\n"
            "YOU REMAIN A DUMB EXECUTOR. Architecture changes UPSTREAM, not here.\n\n"
            "NEW UPSTREAM WORKFLOW:\n"
            "  1. Entry Agent → Regime Agent → Strategy Agent → [NEW] Asset Selector Agent\n"
            "  2. Asset Selector Agent: queries ChromaDB for best asset\n"
            "     Output: {asset_class: 'NIFTY'|'Reliance'|'Crude'|'BTC', confidence, position_size}\n"
            "  3. Contract Agent: resolves contracts for picked asset\n"
            "  4. YOU receive: {asset_class, contracts, strategy_type, wing_width, sl_pct, tp_pct}\n"
            "  5. YOU execute: same logic as Phase 1, just different assets\n\n"
            "YOUR CODE STAYS IDENTICAL:\n"
            "  - execute_paper_trade() works for any asset (NIFTY, Reliance, Crude, BTC)\n"
            "  - place_entry_orders() works for any asset\n"
            "  - You don't care which asset — just build + route\n\n"
            "YOU DO NOT:\n"
            "  ❌ Query historical win rates\n"
            "  ❌ Decide which asset to trade\n"
            "  ❌ Optimize parameters\n"
            "  ❌ Check liquidity\n"
            "  ❌ Make any decisions"
        ),
        expected_output="Trade dict with legs, net_credit, sl, tp, trade_id, entry_orders",
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

    # ── ENTRY GATE: Run dual Entry Agents sequentially (deterministic check) ─────────
    entry_crew = Crew(
        agents=[not_up_entry_agent, not_down_entry_agent, regime_agent],
        tasks=[not_up_entry_task, not_down_entry_task, regime_task],
        process=Process.sequential,
        verbose=False,
    )
    try:
        entry_result = entry_crew.kickoff()
    except Exception as e:
        _log(f"  Entry Crew failed: {e}")
        return _deterministic_fallback(entry_time, spot, atm, vix, adx, snap)

    # Parse dual Entry Agents output
    not_up_decision = {}
    not_down_decision = {}
    regime = {}
    if hasattr(entry_result, "tasks_output"):
        try:
            not_up_decision = _parse_json_output(
                str(entry_result.tasks_output[0])
            )  # NOT_UP agent
            not_down_decision = _parse_json_output(
                str(entry_result.tasks_output[1])
            )  # NOT_DOWN agent
            regime = (
                _parse_json_output(str(entry_result.tasks_output[2]))
                if len(entry_result.tasks_output) > 2
                else {}
            )  # Regime

            # Provenance guard: clamp hallucinated numbers to deterministic tool values
            _verify_provenance(not_up_decision, "NOT_UP") if not_up_decision else None
            _verify_provenance(
                not_down_decision, "NOT_DOWN"
            ) if not_down_decision else None
            _verify_regime_provenance(regime, vix, adx) if regime else None

            # ── Research Override: research is macro regime, trend+TL is micro timing ──
            # No signal (both NEUTRAL) or conflict (trend≠TL) = market uncertain
            # → take Iron Butterfly at moderate confidence
            research_consensus = _get_research_consensus()
            if research_consensus == "NEUTRAL":
                t_sig = not_up_decision.get("trend_signal", "").upper()
                tl_sig = not_up_decision.get("traffic_light_signal", "").upper()

                trend_bull = t_sig == "BULLISH"
                trend_bear = t_sig == "BEARISH"
                tl_bull = tl_sig == "BULLISH"
                tl_bear = tl_sig == "BEARISH"
                conflict = (trend_bull and tl_bear) or (trend_bear and tl_bull)
                both_neutral = t_sig == "NEUTRAL" and tl_sig == "NEUTRAL"

                if both_neutral or conflict:
                    not_up_decision["go"] = True
                    not_up_decision["confidence"] = 40 if conflict else 50
                    not_down_decision["go"] = True
                    not_down_decision["confidence"] = 40 if conflict else 50
                    what = "conflict" if conflict else "both neutral"
                    reason = (
                        f"Research NEUTRAL → sideways market "
                        f"(trend={t_sig}, TL={tl_sig}, {what}) "
                        f"→ IRON_BUTTERFLY"
                    )
                    not_up_decision["reasoning"] = reason
                    not_down_decision["reasoning"] = reason
                    not_up_decision["_overridden"] = True  # flag for strategy picker
                    not_down_decision["_overridden"] = True
                    _log(f"  Research Override: {reason}")

                if not regime:
                    regime = {
                        "recommendation": "enter",
                        "reason": "Research consensus NEUTRAL (sideways)",
                    }

        except Exception as e:
            _err(f"Entry gate parse failed: {e}")
            return _deterministic_fallback(entry_time, spot, atm, vix, adx, snap)

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
        }

    # Regime gate
    if regime.get("recommendation") == "skip":
        _log(
            f"  Regime: SKIP — VIX={regime.get('vix', '?')} | {regime.get('reason', '?')}"
        )
        return {
            "recommendation": "regime_skip",
            "not_up_decision": not_up_decision,
            "not_down_decision": not_down_decision,
            "regime": regime,
        }

    if regime.get("recommendation") == "caution":
        _log(
            f"  Regime: CAUTION — VIX={regime.get('vix', '?')} | {regime.get('reason', '?')}"
        )
        # Allow entry on caution but limit position size (Strategy agent handles this)

    _log(
        f"  Regime: {regime.get('regime')} (VIX={regime.get('vix', '?')}) → {regime.get('recommendation')}"
    )

    # ── Determine which spread to execute (if both go, regime preferences one) ─────────────────────
    # For now: execute both if both are true (iron butterfly on same cycle)
    # If only one is true: execute that one (PUT_SPREAD or CALL_SPREAD)
    # If both false: abort (already handled above)

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
            # Override path: both GO from research (conflict or both neutral)
            # → Iron Butterfly always (market uncertain, collect theta from both sides)
            "IRON_BUTTERFLY"
            if (go_call_spread and go_put_spread and not_up_decision.get("_overridden"))
            # Natural path: single gate firing → use that gate's direction
            else (
                "PUT_SPREAD"
                if (
                    go_call_spread
                    and go_put_spread
                    and not_up_decision.get("trend_signal", "") == "BULLISH"
                )
                else (
                    "CALL_SPREAD"
                    if (
                        go_call_spread
                        and go_put_spread
                        and not_up_decision.get("trend_signal", "") == "BEARISH"
                    )
                    else (
                        "CALL_SPREAD"
                        if go_call_spread
                        else ("PUT_SPREAD" if go_put_spread else "NONE")
                    )
                )
            )
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
            context=[
                not_up_entry_task,
                not_down_entry_task,
                regime_task,
            ],  # Pass dual entry + regime context
        )
        result = full_crew.kickoff()
    except Exception as e:
        _log(f"  Strategy/Execution Crew failed: {e}")
        return _deterministic_fallback(entry_time, spot, atm, vix, adx, snap)

    # ── Log remaining agent outputs ─────────────────────────────────────
    agent_names = ["Strategy", "Contract", "Execution", "Risk"]
    parsed_outputs = [{}, {}, {}, {}]
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

    strategy = parsed_outputs[0]
    contracts_data = parsed_outputs[1]
    trade = parsed_outputs[2]
    risk_confirmation = parsed_outputs[3]

    # ── Strategy summary ────────────────────────────────────────────────
    ww = strategy.get("wing_width", 200)
    sl_p = strategy.get("sl_pct", 0.25)
    tp_p = strategy.get("tp_pct", 0.50)
    stype = strategy.get("strategy_type", "IRON_BUTTERFLY")
    regime_entry_signal = regime.get("entry_signal") or entry_decision.get(
        "signal", "NOT_UP"
    )

    strat_clean = _verify_strategy_provenance(strategy)
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
        "NOT_UP": "CALL_SPREAD",
        "NOT_DOWN": "PUT_SPREAD",
    }.get(decision["signal"], "CALL_SPREAD")

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
    """Generate leg specs from strategy + query SQLite option_prices for tsyms/LTPs."""
    import sqlite3
    from antariksh.config.sqlite_schema import get_sqlite_capture_path

    db_path = get_sqlite_capture_path("NIFTY")

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

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        result = {}
        for label, strike, ot, action in leg_specs:
            row = conn.execute(
                "SELECT tsym, ltp FROM option_prices "
                "WHERE strike = ? AND option_type = ? "
                "ORDER BY timestamp DESC LIMIT 1",
                (strike, ot),
            ).fetchone()
            if row and row["tsym"]:
                result[label] = {
                    "tsym": row["tsym"],
                    "ltp": float(row["ltp"] or 0),
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
        conn.close()


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
        except Exception:
            pass

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

    # Extract trade from Execution Agent's output
    trade = crew_result.get("trade", {})
    if not trade:
        _audit_entry_check("no_trade_returned")
        _log("  Execution: no trade returned — aborting")
        return None

    entry_decision = crew_result.get("entry_decision", {})
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
