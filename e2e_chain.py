"""
Brahmand E2E Chain — Full 5-agent pipeline for autonomous dry-run.

Chain: Regime → Strategy → Contract → Execution → Risk
All agents created via AgentFactory from YAML blueprints.
All data from DuckDB. All orders mock (state.db only).

Usage:
    from e2e_chain import run_full_chain
    trade = run_full_chain(entry_time)
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def _log(msg: str):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line)
    sys.stdout.flush()


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


def run_full_chain(entry_time: str) -> dict | None:
    """
    Run the full 5-agent chain. Returns trade dict or None if skipped.

    Agents:
      1. Regime     — DuckDB → classification
      2. Strategy   — regime output → strategy params
      3. Contract   — strategy + DuckDB → contract tsyms
      4. Execution  — contracts → fill simulation → state.db
      5. Risk       — Execution output → mock SL/TP → state.db
    """
    llm = _get_llm()

    from factory import AgentFactory
    from duckdb_tool import (
        MarketDataQueryTool,
        OptionSnapshotQueryTool,
        get_latest_market_snapshot,
    )
    from persistence import init_db, save_execution_report, get_today_date_int
    from schemas import ExecutionReport

    init_db()
    af = AgentFactory()
    market_tool = MarketDataQueryTool()
    option_tool = OptionSnapshotQueryTool()
    snap = get_latest_market_snapshot()

    spot = float(snap.get("spot", 0))
    atm = int(float(snap.get("atm_strike", 0)))
    expiry = snap.get("expiry_weekly", "")
    vix = float(snap.get("india_vix", 0))
    adx_val = snap.get("adx")
    adx = float(adx_val) if adx_val and adx_val != "None" else 0.0

    if not spot or not atm:
        _log("  E2E Chain: ⚠ DuckDB empty — skipping")
        return None

    # ── Agent 1: Regime ───────────────────────────────────────────────
    regime = {"regime": "unknown", "recommendation": "enter", "confidence": 0.5}
    if llm:
        try:
            agent = af.create_agent("regime_agent", {}, tools=[market_tool])
            agent.llm = llm
            from crewai import Task, Crew, Process

            snap_json = json.dumps(
                {
                    k: snap.get(k, "")
                    for k in [
                        "spot",
                        "india_vix",
                        "adx",
                        "supertrend_direction",
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
            task = Task(
                description=f"Classify NIFTY regime: {snap_json}. Output JSON: {{'regime','confidence','recommendation'}}",
                expected_output="Regime JSON",
                agent=agent,
            )
            result = Crew(
                agents=[agent], tasks=[task], process=Process.sequential, verbose=False
            ).kickoff()
            raw = str(result)
            s = raw.find("{")
            e = raw.rfind("}") + 1
            if s >= 0 and e > s:
                regime = json.loads(raw[s:e])
        except Exception as e:
            _log(f"  Regime Agent: ⚠ {e}")
    else:
        regime = {
            "regime": "sideways" if adx < 25 else "trending",
            "recommendation": "caution" if vix > 18 else "enter",
            "confidence": 0.6,
        }

    _log(f"  Regime: {regime.get('regime')} → {regime.get('recommendation')}")

    # Regime Agent gate: if it says skip, stop here
    if regime.get("recommendation") == "skip":
        _log("  Regime says SKIP — aborting chain")
        return regime  # return regime dict so wrapper can see why

    # ── Agent 2: Strategy ─────────────────────────────────────────────
    strategy = {
        "strategy_type": "IRON_BUTTERFLY",
        "wing_width": 200,
        "sl_pct": 0.25,
        "tp_pct": 0.50,
        "entry_delay": 5,
    }
    if llm:
        try:
            agent = af.create_agent("strategy_agent", {}, tools=[market_tool])
            agent.llm = llm
            task = Task(
                description=f"Regime: {json.dumps(regime)}. VIX: {vix}. Select strategy + params. Output JSON: {{'strategy_type','wing_width','sl_pct','tp_pct','entry_delay'}}",
                expected_output="StrategySpec JSON",
                agent=agent,
            )
            result = Crew(
                agents=[agent], tasks=[task], process=Process.sequential, verbose=False
            ).kickoff()
            raw = str(result)
            s = raw.find("{")
            e = raw.rfind("}") + 1
            if s >= 0 and e > s:
                strategy = json.loads(raw[s:e])
        except Exception as e:
            _log(f"  Strategy Agent: ⚠ {e}")

    ww = strategy.get("wing_width", 200)
    sl_p = strategy.get("sl_pct", 0.25)
    tp_p = strategy.get("tp_pct", 0.50)
    _log(f"  Strategy: {strategy.get('strategy_type')} wings={ww} sl={sl_p} tp={tp_p}")

    # ── Agent 3: Contract ─────────────────────────────────────────────
    contracts, leg_specs = _resolve_contracts(
        atm, ww, expiry, option_tool, strategy.get("strategy_type", "IRON_BUTTERFLY")
    )
    if not contracts:
        _log("  Contract: ⚠ no data — skipping")
        return None

    ctsyms = [c.get("tsym", "?") for c in contracts.values()]
    stype = strategy.get("strategy_type", "IRON_BUTTERFLY")
    _log(f"  Strategy: {stype} wings={ww} sl={sl_p} tp={tp_p}")
    _log(f"  Contracts: {', '.join(ctsyms)}")

    # ── Agent 4: Execution ────────────────────────────────────────────
    trade = _build_trade(
        entry_time, spot, atm, vix, expiry, ww, sl_p, tp_p, contracts, stype
    )
    if not trade:
        return None

    for leg in trade["legs"]:
        if leg["action"] == "SELL":
            save_execution_report(
                ExecutionReport(
                    order_id=f"SIM-{leg['tsym']}",
                    status="MOCK",
                    fill_price=leg["fill_price"],
                    agent_version="e2e-chain",
                )
            )

    _log(f"  Execution: net_credit=₹{trade['net_credit']}")

    # ── Agent 5: Risk ─────────────────────────────────────────────────
    for leg in trade["legs"]:
        if leg["action"] == "SELL":
            t = leg["type"].lower()
            save_execution_report(
                ExecutionReport(
                    order_id=f"SL-{leg['tsym']}",
                    status="MOCK",
                    fill_price=trade["sl"][t],
                    agent_version="e2e-risk",
                )
            )
            save_execution_report(
                ExecutionReport(
                    order_id=f"TP-{leg['tsym']}",
                    status="MOCK",
                    fill_price=trade["tp"][t],
                    agent_version="e2e-risk",
                )
            )
    _log(f"  Risk: 4 orders placed (2 SL + 2 TP)")

    # ── CrewAI Execution→Risk chain (optional, tests context) ─────────
    if llm:
        try:
            from crewai_chain import run_crewai_chain

            cr = run_crewai_chain(trade)
            if cr.get("status") == "success":
                _log(f"  CrewAI Chain: ✅ context passed")
        except Exception:
            pass

    return trade


def _resolve_contracts(
    atm: int, wing_width: int, expiry: str, option_tool, strategy_type: str
) -> tuple:
    """Generate leg specs from strategy + query DuckDB for contract tsyms/LTPs."""
    from duckdb_tool import _connect

    if strategy_type == "BULL_PUT_SPREAD":
        leg_specs = [
            ("sell_pe", atm, "PE", "SELL"),
            ("buy_pe", atm - wing_width, "PE", "BUY"),
        ]
    elif strategy_type == "BEAR_CALL_SPREAD":
        leg_specs = [
            ("sell_ce", atm, "CE", "SELL"),
            ("buy_ce", atm + wing_width, "CE", "BUY"),
        ]
    else:  # IRON_BUTTERFLY
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
    entry_time: str,
    spot: float,
    atm: int,
    vix: float,
    expiry: str,
    ww: int,
    sl_p: float,
    tp_p: float,
    contracts: dict,
    strategy_type: str,
) -> dict:
    """Build trade dict from contract data. Works for 2-leg and 4-leg strategies."""
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

    net = prem_sell - prem_buy

    return {
        "entry_time": entry_time,
        "spot_at_entry": spot,
        "atm_strike": atm,
        "vix": vix,
        "expiry": expiry,
        "wing_width": ww,
        "strategy_type": strategy_type,
        "leg_count": len(legs),
        "net_credit": round(net, 2),
        "premium_sell": round(prem_sell, 2),
        "premium_buy": round(prem_buy, 2),
        "legs": legs,
        "sl": sl,
        "tp": tp,
        "status": "OPEN",
    }
