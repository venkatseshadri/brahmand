#!/usr/bin/env python3
"""
Risk Agent Crew — Standalone CrewAI flow for post-entry position management.

Agents:
  1. MORPHER  — Decides signal-driven morphs (add/remove CE or PE side)
  2. SHIFTER  — Decides theta-decay roll to new strikes
  3. RISK     — Places SL/TP orders, TSL ratcheting, exit decisions

Architecture:
  position_manager.py (bridge) → risk_agent_crew.evaluate_trade(trade) → decisions
  Runs every 1 min via cron. Reads from trade_execution_db DuckDB.

Usage:
  python3 risk_agent_crew.py               # Evaluate all active trades
  python3 risk_agent_crew.py --trade-id=X  # Evaluate specific trade
"""

import json
import os
import sys
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s"
)
logger = logging.getLogger("RiskAgentCrew")


# ── LLM Provider ──────────────────────────────────────────────────────────────


def _get_llm():
    """Return DeepSeek LLM or None if unavailable."""
    try:
        from crewai import LLM

        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            logger.warning("DEEPSEEK_API_KEY not set — Risk Agent disabled")
            return None
        return LLM(
            model="deepseek/deepseek-chat",
            base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
            api_key=api_key,
        )
    except Exception as e:
        logger.warning(f"LLM init failed: {e}")
        return None


# ── Trade Loader ──────────────────────────────────────────────────────────────


def load_active_trades() -> list:
    """Load all ACTIVE trades from trade_execution_db (DuckDB)."""
    try:
        from trade_execution_db import get_active_trades

        return get_active_trades()
    except Exception as e:
        logger.error(f"Failed to load active trades: {e}")
        return []


# ── CrewAI Tool: Morph Detection ──────────────────────────────────────────────


class DetectMorphInput:
    """Input schema for detect_morph tool."""

    current_position: str  # "BULLISH" | "BEARISH" | "NEUTRAL"
    entry_gate_signal: str  # Current signal from entry gate
    morph_count: int = 0  # Morphs done today
    legs_json: str  # JSON string of current legs


def detect_morph(
    current_position: str,
    entry_gate_signal: str,
    morph_count: int = 0,
    legs_json: str = "[]",
) -> dict:
    """Check if entry gate signal changed vs current position. Returns morph proposal."""
    from position_manager import MAX_MORPHS

    legs = json.loads(legs_json) if isinstance(legs_json, str) else legs_json

    if morph_count >= MAX_MORPHS:
        return {
            "morph_needed": False,
            "reason": f"MAX_MORPHS ({MAX_MORPHS}) reached",
            "from_type": current_position,
            "to_type": entry_gate_signal,
            "morph_count": morph_count,
        }

    if (
        (current_position == "BULLISH" and entry_gate_signal in ("NEUTRAL", "BEARISH"))
        or (
            current_position == "BEARISH"
            and entry_gate_signal in ("NEUTRAL", "BULLISH")
        )
        or (
            current_position == "NEUTRAL"
            and entry_gate_signal in ("BULLISH", "BEARISH")
        )
    ):
        return {
            "morph_needed": True,
            "reason": f"Signal changed: {current_position} → {entry_gate_signal}",
            "from_type": current_position,
            "to_type": entry_gate_signal,
            "morph_count": morph_count,
            "leg_count": len(legs),
        }

    return {
        "morph_needed": False,
        "reason": f"Signal stable: {current_position} matches {entry_gate_signal}",
        "from_type": current_position,
        "to_type": entry_gate_signal,
    }


# ── CrewAI Tool: Theta Decay Detection ────────────────────────────────────────


class DetectThetaInput:
    """Input schema for detect_theta tool."""

    legs_json: str  # JSON string of legs with fill_price and ltp
    atm: int  # ATM strike


def detect_theta_decay(legs_json: str, atm: int) -> dict:
    """Calculate theta decay % for each SELL leg. Returns roll proposal if > 37.5%."""
    from position_manager import DECAY_PCT

    legs = json.loads(legs_json) if isinstance(legs_json, str) else legs_json
    results = []
    for leg in legs:
        if leg.get("action") != "SELL":
            continue
        fill = leg.get("fill_price", 0)
        ltp = leg.get("ltp", fill)
        if fill <= 0:
            continue
        decay_pct = round((fill - ltp) / fill * 100, 1)
        results.append(
            {
                "leg_type": leg.get("type"),
                "strike": leg.get("strike"),
                "fill_price": fill,
                "ltp": ltp,
                "decay_pct": decay_pct,
                "needs_roll": decay_pct >= DECAY_PCT * 100,
            }
        )
    return {
        "legs": results,
        "atm": atm,
        "decay_threshold_pct": DECAY_PCT * 100,
        "any_needs_roll": any(r["needs_roll"] for r in results),
    }


# ── CrewAI Tool: Execute Morph ────────────────────────────────────────────────


def execute_morph(
    from_type: str, to_type: str, trade_id: str, legs_json: str, atm: int
) -> dict:
    """Execute a morph action via position_manager. Returns updated trade legs."""
    from position_manager import execute_action as pm_execute
    from position_manager import MORPH

    legs = json.loads(legs_json) if isinstance(legs_json, str) else legs_json

    action = {
        "type": MORPH,
        "from_type": from_type,
        "to_type": to_type,
        "priority": 3,
        "reason": f"MORPH {from_type} → {to_type}",
    }

    trade = {"legs": legs, "cumulative_pnl": 0, "sl": {}, "tp": {}, "morph_count": 0}
    try:
        updated = pm_execute(action, trade)
        logger.info(
            f"MORPH executed: {from_type} → {to_type} | legs={len(updated.get('legs', []))}"
        )
        return {
            "success": True,
            "action": f"MORPH_{from_type}_TO_{to_type}",
            "legs": updated.get("legs", legs),
        }
    except Exception as e:
        logger.error(f"MORPH failed: {e}")
        return {"success": False, "error": str(e)[:200]}


# ── CrewAI Tool: Execute Roll ─────────────────────────────────────────────────


def execute_roll(
    leg_type: str,
    old_strike: int,
    new_strike: int,
    old_fill: float,
    new_fill: float,
    tsym: str,
    new_tsym: str,
    legs_json: str,
) -> dict:
    """Execute a roll action via position_manager. Closes old leg, opens new."""
    from position_manager import execute_action as pm_execute
    from position_manager import ROLL

    legs = json.loads(legs_json) if isinstance(legs_json, str) else legs_json

    action = {
        "type": ROLL,
        "priority": 1,
        "reason": f"ROLL {old_strike}{leg_type} → {new_strike}{leg_type}",
        "leg": {
            "action": "SELL",
            "type": leg_type,
            "strike": old_strike,
            "fill": old_fill,
            "ltp": old_fill,
            "tsym": tsym,
        },
        "new_strike": new_strike,
        "new_fill": new_fill,
        "new_tsym": new_tsym,
    }

    trade = {"legs": legs, "cumulative_pnl": 0, "sl": {}, "tp": {}}
    try:
        updated = pm_execute(action, trade)
        logger.info(f"ROLL executed: {old_strike}{leg_type} → {new_strike}{leg_type}")
        return {
            "success": True,
            "action": f"ROLL_{leg_type}_{old_strike}_TO_{new_strike}",
            "legs": updated.get("legs", legs),
        }
    except Exception as e:
        logger.error(f"ROLL failed: {e}")
        return {"success": False, "error": str(e)[:200]}


# ── CrewAI Tool: Report Position Closed ───────────────────────────────────────


def report_position_closed(trade_id: str, reason: str, final_pnl: float = 0) -> dict:
    """Mark trade as CLOSED in trade_execution_db. Signals kickoff for next entry."""
    try:
        from trade_execution_db import close_trade

        close_trade(trade_id, close_reason=reason, final_pnl=final_pnl)
        logger.info(f"Trade {trade_id} closed: {reason} | P&L={final_pnl:.0f}")
    except Exception as e:
        logger.error(f"Failed to close trade in DuckDB: {e}")
        return {"success": False, "error": str(e)[:200]}

    # Also clear kickoff JSON state so kickoff can enter next trade
    try:
        STATE_FILE = Path("/tmp/brahmand_kickoff.json")
        if STATE_FILE.exists():
            state = json.loads(STATE_FILE.read_text())
            if state.get("active_trade"):
                closed_trade = state["active_trade"]
                closed_trade["status"] = "CLOSED"
                closed_trade["close_reason"] = reason
                closed_trade["close_time"] = datetime.now().isoformat()
                closed_trade["final_pnl"] = final_pnl
                if state.get("all_trades") is not None:
                    state["all_trades"].append(closed_trade)
                state["active_trade"] = None
                STATE_FILE.write_text(json.dumps(state, indent=2, default=str))
                logger.info(f"Kickoff JSON updated: trade closed")
    except Exception as e:
        logger.warning(f"Failed to update kickoff JSON: {e}")

    return {
        "success": True,
        "trade_id": trade_id,
        "reason": reason,
        "final_pnl": final_pnl,
    }


# ── Crew Assembly ─────────────────────────────────────────────────────────────


def build_risk_crew(llm):
    """Build the 3-agent risk crew: Morpher → Shifter → Risk."""
    from crewai import Agent, Task, Crew, Process
    from tools.risk_tools import (
        PatternQueryTool,
        TSLEngineTool,
        MonitorPnLGreeksTool,
        PlaceSLOrderTool,
        PlaceTPOrderTool,
        ModifySLOrderTool,
        CancelOrderTool,
    )

    # ── Morpher Agent ─────────────────────────────────────────────
    morpher = Agent(
        role="Position Morpher",
        goal=(
            "Monitor entry gate signal changes. When signal diverges from current "
            "position type, decide whether to morph (add or remove CE/PE sides). "
            "Consider pattern probabilities and VIX before morphing — a borderline "
            "signal change may be noise."
        ),
        backstory=(
            "You are the structural optimizer. The entry gate says BULLISH/BEARISH/NEUTRAL "
            "every 5 minutes. Your job: detect when the signal no longer matches the position. "
            "BULLISH→NEUTRAL? Add a call spread (become iron butterfly). "
            "NEUTRAL→BULLISH? Close the call spread (become put spread). "
            "Use query_pattern to check if the signal change is backed by probabilities."
        ),
        tools=[PatternQueryTool()],
        allow_delegation=False,
        verbose=False,
    )
    morpher.llm = llm

    # ── Shifter Agent ─────────────────────────────────────────────
    shifter = Agent(
        role="Leg Shifter",
        goal=(
            "Monitor theta decay on sold legs. When premium has decayed past threshold "
            "(37.5%), find the optimal new strike to roll to. Consider ATM proximity "
            "and remaining time value."
        ),
        backstory=(
            "You optimize premium capture. Short options decay fast near expiry. "
            "When theta has extracted most of the premium, you find the next best strike "
            "to harvest fresh premium from. Call detect_theta_decay to check decay. "
            "If roll is needed, suggest the new ATM strike."
        ),
        tools=[],
        allow_delegation=False,
        verbose=False,
    )
    shifter.llm = llm

    # ── Risk Coordinator ──────────────────────────────────────────
    risk = Agent(
        role="Risk Coordinator",
        goal=(
            "Manage SL/TP orders, TSL ratcheting, and exit decisions. "
            "Place initial SL/TP orders when a trade is first seen. "
            "Ratchet SL via TSL engine as premium decays. "
            "Close trades when SL/TP hit or market closes."
        ),
        backstory=(
            "You protect capital. On first cycle for a trade: place SL-LMT and TP-LMT orders "
            "via place_sl_order and place_tp_order. On subsequent cycles: call tsl_engine "
            "to check if SL should trail. If tsl_engine returns TRAIL, call modify_sl_order. "
            "If SL/TP is hit, call report_position_closed."
        ),
        tools=[
            MonitorPnLGreeksTool(),
            TSLEngineTool(),
            PlaceSLOrderTool(),
            PlaceTPOrderTool(),
            ModifySLOrderTool(),
            CancelOrderTool(),
        ],
        allow_delegation=False,
        verbose=False,
    )
    risk.llm = llm

    return morpher, shifter, risk


# ── Task Builder ──────────────────────────────────────────────────────────────


def build_tasks(morpher, shifter, risk, trade: dict):
    """Build task list for the current trade state."""
    from crewai import Task

    trade_json = json.dumps(trade, default=str)
    entry_time = trade.get("entry_time", "?")
    strategy = trade.get("strategy", "?")
    legs = trade.get("legs", [])
    has_pe = any(l.get("type") == "PE" and l.get("action") == "SELL" for l in legs)
    has_ce = any(l.get("type") == "CE" and l.get("action") == "SELL" for l in legs)
    position_type = (
        "NEUTRAL" if (has_pe and has_ce) else ("BULLISH" if has_pe else "BEARISH")
    )
    sl = trade.get("sl", {})
    tp = trade.get("tp", {})

    trade_id = trade.get("trade_id", "unknown")
    legs_json = json.dumps(legs, default=str)

    # Extract ATM from first SELL leg
    atm = 0
    for l in legs:
        if l.get("action") == "SELL":
            atm = l.get("strike", 0)
            break

    entry_gate_signal = trade.get("entry_gate_signal", position_type)
    morph_count = trade.get("morph_count", 0)

    # ── Task 1: Morpher ──────────────────────────────────────────
    morph_task = Task(
        description=f"""Check if position needs to morph.

Current position type: {position_type} (PE={"YES" if has_pe else "NO"}, CE={"YES" if has_ce else "NO"})
Latest entry gate signal: {entry_gate_signal}
Morphs used today: {morph_count} / 3

STEP 1: Call detect_morph with:
  - current_position = "{position_type}"
  - entry_gate_signal = "{entry_gate_signal}"
  - morph_count = {morph_count}
  - legs_json = '{legs_json}'

STEP 2: If morph_needed=True AND you assess the signal change is genuine (not noise):
  - Call query_pattern to check P(UP|DOWN|SIDE) for 15m horizon
  - If pattern probabilities support the new direction, call execute_morph:
    - from_type = result.from_type
    - to_type = result.to_type
    - trade_id = "{trade_id}"
    - legs_json = '{legs_json}'
    - atm = {atm}

STEP 3: Output: {{"morph_decision": "HOLD"|"MORPHED", "reason": "..."}}""",
        expected_output="Morph decision JSON",
        agent=morpher,
    )

    # ── Task 2: Shifter ──────────────────────────────────────────
    shift_task = Task(
        description=f"""Check if any sold legs need theta decay roll.

ATM: {atm} | Strategy: {strategy} | Entry: {entry_time}
Legs: {legs_json}

STEP 1: Call detect_theta_decay with:
  - legs_json = '{legs_json}'
  - atm = {atm}

STEP 2: If any SELL leg has decay_pct >= 37.5%:
  - Propose rolling that leg to ATM strike ({atm})
  - Call execute_roll with the new strike

STEP 3: Output: {{"shift_decision": "HOLD"|"ROLLED", "leg": "...", "reason": "..."}}""",
        expected_output="Shift decision JSON",
        agent=shifter,
    )

    # ── Task 3: Risk Coordinator ─────────────────────────────────
    sl_pe = sl.get("pe", "NOT SET")
    sl_ce = sl.get("ce", "NOT SET")
    tp_pe = tp.get("pe", "NOT SET")
    tp_ce = tp.get("ce", "NOT SET")

    risk_task = Task(
        description=f"""Manage SL/TP orders and exit checks.

Trade ID: {trade_id}
Strategy: {strategy} | Entry: {entry_time}
Position: {position_type} | ATM: {atm}
Legs: {legs_json}
SL: PE={sl_pe}, CE={sl_ce}
TP: PE={tp_pe}, CE={tp_ce}

STEP 1: Call monitor_pnl_greeks with these legs to get current P&L + LTPs.

STEP 2: For each SELL leg:
  - If this is the FIRST cycle (no SL/TP orders placed yet):
    → Call place_sl_order and place_tp_order
  - If orders already placed:
    → Call tsl_engine to check if TSL should activate
    → If tsl_engine returns decision=TRAIL, call modify_sl_order with new tsl_level

STEP 3: Check exit conditions:
  - If current P&L hit SL or TP → call report_position_closed(trade_id="{trade_id}", reason="SL_HIT"|"TP_HIT")
  - If market closing (after 15:25) → call report_position_closed(trade_id="{trade_id}", reason="MARKET_CLOSE")

STEP 4: Output: {{"risk_decision": "ACTIVE"|"CLOSED", "actions": [...], "pnl": X}}""",
        expected_output="Risk decision JSON with order IDs and P&L",
        agent=risk,
        context=[morph_task, shift_task],  # Risk sees morph/shift decisions
    )

    return [morph_task, shift_task, risk_task]


# ── Main Entry ────────────────────────────────────────────────────────────────


def evaluate_trade(trade: dict) -> dict:
    """Evaluate a single trade through the risk agent crew. Returns decisions."""
    llm = _get_llm()
    if not llm:
        return {"error": "LLM unavailable", "trade_id": trade.get("trade_id")}

    try:
        from crewai import Crew, Process

        morpher, shifter, risk = build_risk_crew(llm)
        tasks = build_tasks(morpher, shifter, risk, trade)

        crew = Crew(
            agents=[morpher, shifter, risk],
            tasks=tasks,
            process=Process.sequential,
            verbose=False,
        )
        result = crew.kickoff()
        logger.info(f"Trade {trade.get('trade_id')} evaluated: {str(result)[:200]}")
        return {
            "trade_id": trade.get("trade_id"),
            "result": str(result),
            "status": "ok",
        }
    except Exception as e:
        logger.error(f"Risk agent crew failed for trade {trade.get('trade_id')}: {e}")
        return {"error": str(e)[:200], "trade_id": trade.get("trade_id")}


def evaluate_all() -> list:
    """Evaluate all active trades from the ledger."""
    trades = load_active_trades()
    if not trades:
        logger.info("No active trades — skipping risk agent cycle")
        return []

    results = []
    for trade in trades:
        result = evaluate_trade(trade)
        results.append(result)

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--trade-id", type=str, help="Evaluate specific trade")
    parser.add_argument("--once", action="store_true", help="Single cycle and exit")
    args = parser.parse_args()

    if args.trade_id:
        trades = load_active_trades()
        target = next((t for t in trades if t["trade_id"] == args.trade_id), None)
        if target:
            result = evaluate_trade(target)
            print(json.dumps(result, indent=2, default=str))
        else:
            print(f"Trade {args.trade_id} not found")
    else:
        results = evaluate_all()
        print(json.dumps(results, indent=2, default=str))
