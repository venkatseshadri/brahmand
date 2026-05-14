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
    adx = float(snap.get("adx", 0) or 0)

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
    contracts = _resolve_contracts(atm, ww, expiry, option_tool, llm, af)
    if not contracts or all(c.get("ltp", 0) == 0 for c in contracts.values()):
        _log("  Contract: ⚠ no data — skipping")
        return None

    ctsyms = [c.get("tsym", "?") for c in contracts.values()]
    _log(f"  Contracts: {', '.join(ctsyms)}")

    # ── Agent 4: Execution ────────────────────────────────────────────
    trade = _build_trade(entry_time, spot, atm, vix, expiry, ww, sl_p, tp_p, contracts)
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
    atm: int, wing_width: int, expiry: str, option_tool, llm, af
) -> dict:
    """Query DuckDB for contract tsyms and LTPs for all 4 legs."""
    from duckdb_tool import _connect
    import duckdb

    con = _connect()
    try:
        result = {}
        legs = [
            ("center_ce", atm, "CE", "SELL"),
            ("center_pe", atm, "PE", "SELL"),
            ("wing_ce", atm - wing_width, "CE", "BUY"),
            ("wing_pe", atm + wing_width, "PE", "BUY"),
        ]
        for label, strike, ot, action in legs:
            row = con.execute(
                "SELECT tsym, ltp FROM market.option_snapshots "
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
        return result
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
) -> dict:
    """Build trade dict from contract data."""
    c = contracts
    prem_sell = c["center_ce"]["ltp"] + c["center_pe"]["ltp"]
    prem_buy = c["wing_ce"]["ltp"] + c["wing_pe"]["ltp"]
    net = prem_sell - prem_buy

    return {
        "entry_time": entry_time,
        "spot_at_entry": spot,
        "atm_strike": atm,
        "vix": vix,
        "expiry": expiry,
        "wing_width": ww,
        "net_credit": round(net, 2),
        "premium_sell": round(prem_sell, 2),
        "premium_buy": round(prem_buy, 2),
        "legs": [
            {
                "action": "SELL",
                "strike": atm,
                "type": "CE",
                "fill_price": c["center_ce"]["ltp"],
                "tsym": c["center_ce"]["tsym"],
            },
            {
                "action": "SELL",
                "strike": atm,
                "type": "PE",
                "fill_price": c["center_pe"]["ltp"],
                "tsym": c["center_pe"]["tsym"],
            },
            {
                "action": "BUY",
                "strike": atm - ww,
                "type": "CE",
                "fill_price": c["wing_ce"]["ltp"],
                "tsym": c["wing_ce"]["tsym"],
            },
            {
                "action": "BUY",
                "strike": atm + ww,
                "type": "PE",
                "fill_price": c["wing_pe"]["ltp"],
                "tsym": c["wing_pe"]["tsym"],
            },
        ],
        "sl": {
            "ce": round(c["center_ce"]["ltp"] * sl_p, 2),
            "pe": round(c["center_pe"]["ltp"] * sl_p, 2),
        },
        "tp": {
            "ce": round(c["center_ce"]["ltp"] * tp_p, 2),
            "pe": round(c["center_pe"]["ltp"] * tp_p, 2),
        },
        "status": "OPEN",
    }
