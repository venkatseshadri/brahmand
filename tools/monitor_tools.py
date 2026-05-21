"""
Monitoring Tools — MORPH detection + premium-decay shift proposals for the monitoring Crew.
Wraps existing position_manager.py and leg_shifter.py logic as CrewAI tools.

Called by Morpher Agent and Shifter Agent every 5 minutes while a trade is active.
Both agents use Risk Agent's tools (place_sl, place_tp, cancel_order) to execute actions.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field


# ── Tool 1: Morph Detection ────────────────────────────────────────────


class MorphCheckInput(BaseModel):
    trade_json: str = Field(
        default="{}",
        description="JSON string of the active trade dict from kickoff state",
    )


class MorphCheckTool(BaseTool):
    name: str = "check_for_morph"
    description: str = (
        "Check if the trade should MORPH based on current entry signal vs the trade's "
        "original entry_gate_signal. Reads latest entry_check signal from file, "
        "compares against trade's entry signal. "
        "Returns proposed morph actions: [{type: 'MORPH', from_type, to_type, reason}] or empty list. "
        "A morph happens when the market signal changes direction — e.g., BULLISH → BEARISH "
        "means the put spread should switch to a call spread (or add a butterfly side). "
        "MORPH rules: 1) BULLISH→BEARISH or BEARISH→BULLISH triggers morph. "
        "2) NEUTRAL from directional triggers butterfly addition. "
        "3) Max 3 morphs per day."
    )
    args_schema: Type[BaseModel] = MorphCheckInput

    def _run(self, trade_json: str = "{}") -> str:
        try:
            trade = json.loads(trade_json)
        except Exception:
            return json.dumps({"error": "invalid trade_json", "actions": []})

        # Read current entry signal
        ec_path = Path("/home/trading_ceo/antariksh/logs/entry_check_latest.json")
        current_signal = "NEUTRAL"
        if ec_path.exists():
            try:
                current_signal = json.loads(ec_path.read_text()).get(
                    "signal", "NEUTRAL"
                )
            except Exception:
                pass

        entry_signal = trade.get("entry_gate_signal", "NEUTRAL")
        strategy = trade.get("strategy_type", "IRON_BUTTERFLY")
        morph_count = trade.get("morph_count", 0)
        max_morphs = 3

        if morph_count >= max_morphs:
            return json.dumps(
                {"actions": [], "reason": f"max morphs ({max_morphs}) reached"}
            )

        actions = []
        if entry_signal == "BULLISH" and current_signal == "BEARISH":
            actions.append(
                {
                    "type": "MORPH",
                    "from_type": "PUT_SPREAD",
                    "to_type": "CALL_SPREAD",
                    "from_signal": entry_signal,
                    "to_signal": current_signal,
                    "reason": f"Signal reversed: {entry_signal}→{current_signal}. Close PUT side, open CALL side.",
                }
            )
        elif entry_signal == "BEARISH" and current_signal == "BULLISH":
            actions.append(
                {
                    "type": "MORPH",
                    "from_type": "CALL_SPREAD",
                    "to_type": "PUT_SPREAD",
                    "from_signal": entry_signal,
                    "to_signal": current_signal,
                    "reason": f"Signal reversed: {entry_signal}→{current_signal}. Close CALL side, open PUT side.",
                }
            )
        elif current_signal == "NEUTRAL" and entry_signal in ("BULLISH", "BEARISH"):
            if "BUTTERFLY" not in strategy:
                actions.append(
                    {
                        "type": "MORPH",
                        "from_type": strategy,
                        "to_type": "IRON_BUTTERFLY",
                        "from_signal": entry_signal,
                        "to_signal": current_signal,
                        "reason": f"Signal neutralized: {entry_signal}→{current_signal}. Add opposite side for butterfly.",
                    }
                )

        return json.dumps(
            {
                "current_signal": current_signal,
                "entry_signal": entry_signal,
                "morph_count": morph_count,
                "actions": actions,
            },
            indent=2,
        )


# ── Tool 2: Premium Decay Shift Detection ──────────────────────────────


class ShiftCheckInput(BaseModel):
    trade_json: str = Field(
        default="{}",
        description="JSON string of the active trade dict from kickoff state",
    )


class ShiftCheckTool(BaseTool):
    name: str = "check_for_shift"
    description: str = (
        "Check if any SELL leg's premium has decayed enough to warrant shifting the position. "
        "Queries DuckDB for current LTP on each leg, calculates decay percentages. "
        "HEDGE_SHIFT (50% decay): narrow the wing by moving hedge closer to SELL. "
        "Always safe — reduces margin. Action: open new hedge → close old hedge. "
        "SELL_SHIFT (60% decay): widen the wing by moving SELL farther. "
        "Requires margin check. Action: close old sell → open new sell. "
        "Returns shift proposals with exact strike prices, decay percentages, and margin impact."
    )
    args_schema: Type[BaseModel] = ShiftCheckInput

    def _run(self, trade_json: str = "{}") -> str:
        try:
            trade = json.loads(trade_json)
        except Exception:
            return json.dumps({"error": "invalid trade_json"})

        if not trade.get("legs"):
            return json.dumps({"proposals": {"hedge_shift": None, "sell_shift": None}})

        from duckdb_tool import _connect

        expiry = trade.get("expiry", "")
        atm = trade.get("atm_strike", trade.get("spot_at_entry", 0))
        legs = trade["legs"]
        con = _connect()
        proposals = {"hedge_shift": None, "sell_shift": None}

        try:
            sell_legs = [l for l in legs if l.get("action") == "SELL"]
            for leg in sell_legs:
                strike = leg["strike"]
                otype = leg["type"]
                fill = leg.get("fill_price", 0)
                if fill <= 0:
                    continue

                row = con.execute(
                    "SELECT ltp FROM option_snapshots WHERE expiry_date = ? "
                    "AND strike = ? AND option_type = ? AND tsym IS NOT NULL "
                    "ORDER BY timestamp DESC LIMIT 1",
                    (expiry, strike, otype),
                ).fetchone()
                current_ltp = (
                    float(row[0]) if row and row[0] and float(row[0]) < 5000 else 0
                )
                if current_ltp <= 0:
                    continue

                decay_pct = (fill - current_ltp) / fill if fill > 0 else 0

                # Find the corresponding hedge leg
                hedge_legs = [
                    l
                    for l in legs
                    if l.get("action") == "BUY" and l.get("type") == otype
                ]
                if hedge_legs:
                    hedge = hedge_legs[0]
                    old_wing = abs(strike - hedge["strike"])
                    old_hedge_strike = hedge["strike"]

                    # HEDGE_SHIFT: 50% decay → tighten hedge
                    if decay_pct >= 0.50:
                        new_wing = max(50, int(old_wing * 0.5))
                        hedge_shift = {
                            "option_type": otype,
                            "sell_strike": strike,
                            "old_hedge_strike": old_hedge_strike,
                            "new_hedge_strike": strike
                            + (-new_wing if otype == "PE" else new_wing),
                            "old_wing": old_wing,
                            "new_wing": new_wing,
                            "hedge_decay_pct": round(decay_pct * 100),
                        }
                        proposals["hedge_shift"] = hedge_shift

                    # SELL_SHIFT: 60% decay → move sell farther
                    if decay_pct >= 0.60 and proposals["hedge_shift"]:
                        new_sell_wing = int(old_wing * 1.5)
                        new_sell_strike = atm + (
                            new_sell_wing * (1 if otype == "CE" else -1)
                        )
                        proposals["sell_shift"] = {
                            "option_type": otype,
                            "old_sell_strike": strike,
                            "new_sell_strike": new_sell_strike,
                            "old_wing": old_wing,
                            "new_wing": new_sell_wing,
                            "sell_decay_pct": round(decay_pct * 100),
                            "status": "PENDING_MARGIN_CHECK",
                        }
        finally:
            con.close()

        return json.dumps({"proposals": proposals}, indent=2, default=str)
