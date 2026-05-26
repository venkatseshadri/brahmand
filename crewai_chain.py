"""
CrewAI Execution→Risk Chain — Test module for agent dependencies.

Creates Execution and Risk agents via AgentFactory, wires them with
Task(context=[...]) so Risk formally receives Execution's TradeSignal output.
Writes results to state.db alongside the procedural chain.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
load_dotenv()

from factory import AgentFactory, ToolFactory
from persistence import save_execution_report
from schemas import ExecutionReport


def run_crewai_chain(trade: dict) -> dict:
    """
    Run the Execution→Risk CrewAI chain with context passing.

    Execution Agent produces TradeSignal JSON.
    Risk Agent receives it via Task.context → validates → places mock SL/TP.

    Returns: dict with agent_outputs or error
    """
    try:
        from crewai import Agent, Task, Crew, Process, LLM
        from tools.execution_tools import ExecuteTradeTool
        from tools.risk_tools import MonitorPnLGreeksTool
    except ImportError as e:
        return {"status": "skipped", "reason": f"Import error: {e}"}

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        return {"status": "skipped", "reason": "DEEPSEEK_API_KEY not set"}

    llm = LLM(
        model="deepseek/deepseek-chat",
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        api_key=api_key,
        temperature=0,
    )

    af = AgentFactory()

    # ── Execution Agent ──────────────────────────────────────────────
    executor = af.create_agent(
        "execution_agent",
        {
            "market_type": "NSE_OPTIONS",
            "strategy_type": "IRON_BUTTERFLY",
            "ticker": "NIFTY",
            "mock_mode": "DRY-RUN",
        },
        tools=[ExecuteTradeTool()],
    )
    executor.llm = llm

    # ── Risk Agent ───────────────────────────────────────────────────
    from tools.risk_tools import (
        TSLEngineTool,
        TradeCommandHandlerTool,
        PlaceSLOrderTool,
        PlaceTPOrderTool,
        ModifySLOrderTool,
        CancelOrderTool,
        PatternQueryTool,
    )

    risk = af.create_agent(
        "risk_agent",
        {
            "market_type": "NSE_OPTIONS",
            "ticker": "NIFTY",
            "daily_sl": 4500,
            "max_drawdown": 4500,
            "max_lots": 1,
            "mock_mode": "DRY-RUN",
        },
        tools=[
            PatternQueryTool(),
            MonitorPnLGreeksTool(),
            TSLEngineTool(),
            TradeCommandHandlerTool(),
            PlaceSLOrderTool(),
            PlaceTPOrderTool(),
            ModifySLOrderTool(),
            CancelOrderTool(),
        ],
    )
    risk.llm = llm

    # ── Task 1: Execution ────────────────────────────────────────────
    exec_task = Task(
        description=f"""SIMULATE an Iron Butterfly trade with these fills (DO NOT call broker):
{trade["legs"]}

Produce a JSON TradeSignal with: market, ticker, action, strategy_type, size,
strikes, sl_level, tp_level. Use the actual fill prices from above.""",
        expected_output="TradeSignal JSON",
        agent=executor,
    )

    # ── Task 2: Risk (context from Execution) ────────────────────────
    risk_task = Task(
        description=f"""You are the Risk Sentry. The Executioner has placed these legs:
{json.dumps(trade["legs"], default=str)}

Risk Limits: net_credit=₹{trade["net_credit"]}, VIX={trade["vix"]}, spot={trade["spot_at_entry"]}
SL levels (premium × 1.50): {trade["sl"]}
TP levels (premium × 0.50): {trade["tp"]}
Expiry: {trade["expiry"]}

STEP 1: Call query_pattern to get 6-TF traffic light pattern + P(UP/DOWN/SIDE) for 15m horizon.
        Use risk_guidance to set SL/TP adaptation: trending → tighten SL, sideways → widen SL.
STEP 2: Call monitor_pnl_greeks with these legs to get current P&L + Greeks.
STEP 3: For each SELL leg, call place_sl_order at SL price (from pattern guidance) and place_tp_order at TP price.
STEP 4: Call tsl_engine with entry_price and current_price for each SELL leg.
STEP 5: If TSL decision=TRAIL, call modify_sl_order with new tsl_level.
STEP 6: Output risk_decision JSON with all order_ids, pattern guidance, P&L, and TSL status.""",
        expected_output="Risk decision JSON with pattern-driven SL/TP, order IDs, and TSL monitoring active",
        agent=risk,
        context=[exec_task],  # ← Risk receives Execution's TradeSignal
    )

    # ── Run Crew ─────────────────────────────────────────────────────
    crew = Crew(
        agents=[executor, risk],
        tasks=[exec_task, risk_task],
        process=Process.sequential,
        verbose=False,
    )
    result = crew.kickoff()

    # Log to state.db from CrewAI chain
    for leg in trade["legs"]:
        if leg["action"] == "SELL":
            t = leg["type"].lower()
            save_execution_report(
                ExecutionReport(
                    order_id=f"AI-SL-{leg['tsym']}",
                    status="MOCK",
                    fill_price=trade["sl"][t],
                    agent_version="crewai-chain",
                )
            )
            save_execution_report(
                ExecutionReport(
                    order_id=f"AI-TP-{leg['tsym']}",
                    status="MOCK",
                    fill_price=trade["tp"][t],
                    agent_version="crewai-chain",
                )
            )

    return {
        "status": "success",
        "exec_output": str(result)[:300],
        "chain": "Execution → Risk (context)",
    }
