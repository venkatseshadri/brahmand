"""
Chain Tools — Contract Resolution + Execution + Order Routing tools for the E2E pipeline.
Contract Agent uses resolve_option_contracts.
Execution Agent uses execute_paper_trade + place_entry_orders.
Risk Agent uses place_sl_tp_orders.
Order routing via order_routing module functions.
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field


class ResolveContractsInput(BaseModel):
    strategy_type: str = Field(
        default="IRON_BUTTERFLY",
        description="PUT_SPREAD | CALL_SPREAD | IRON_BUTTERFLY",
    )
    atm: int = Field(default=0, description="At-the-money strike price")
    wing_width: int = Field(default=200, description="Wing width from ATM")
    expiry: str = Field(default="", description="Expiry date, e.g. 26-MAY-2026")


# ── Contract Agent Tool ──────────────────────────────────────────────────


class ResolveOptionContractsTool(BaseTool):
    name: str = "resolve_option_contracts"
    description: str = (
        "Resolve trading symbols (tsym) and current LTP for options contracts "
        "based on strategy type, ATM strike, wing width, and expiry. "
        "Queries DuckDB option_snapshots for real contract data. "
        "Returns JSON array of contracts: {label: {tsym, ltp, strike, option_type, action}} "
        "PUT_SPREAD → 2 legs (sell PE, buy PE lower). CALL_SPREAD → 2 legs (sell CE, buy CE higher). "
        "IRON_BUTTERFLY → 4 legs (sell CE+PE, buy CE+PE wings)."
    )
    args_schema: Type[BaseModel] = ResolveContractsInput

    def _run(
        self,
        strategy_type: str = "IRON_BUTTERFLY",
        atm: int = 0,
        wing_width: int = 200,
        expiry: str = "",
    ) -> str:
        if atm <= 0 or not expiry:
            return json.dumps({"error": "atm and expiry required"})

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
            return json.dumps({"contracts": result, "count": len(result)}, indent=2)
        finally:
            con.close()


# ── Execution Agent Tool ─────────────────────────────────────────────────


class ExecutePaperTradeInput(BaseModel):
    contracts_json: str = Field(
        default="{}",
        description="JSON string of contracts from resolve_option_contracts",
    )
    strategy_type: str = Field(default="IRON_BUTTERFLY")
    entry_time: str = Field(default="", description="HH:MM entry time")
    spot: float = Field(default=0.0)
    atm: int = Field(default=0)
    vix: float = Field(default=0.0)
    expiry: str = Field(default="")
    wing_width: int = Field(default=200)
    sl_pct: float = Field(default=0.25)
    tp_pct: float = Field(default=0.50)


class ExecutePaperTradeTool(BaseTool):
    name: str = "execute_paper_trade"
    description: str = (
        "Build and save a paper trade to state.db. Calculates net credit, "
        "SL/TP levels for each SELL leg, writes SIM orders. "
        "Returns the trade dict with legs, net_credit, sl, tp. "
        "Does NOT place real orders — paper mode only."
    )
    args_schema: Type[BaseModel] = ExecutePaperTradeInput

    def _run(
        self,
        contracts_json: str = "{}",
        strategy_type: str = "IRON_BUTTERFLY",
        entry_time: str = "",
        spot: float = 0.0,
        atm: int = 0,
        vix: float = 0.0,
        expiry: str = "",
        wing_width: int = 200,
        sl_pct: float = 0.25,
        tp_pct: float = 0.50,
    ) -> str:
        try:
            data = json.loads(contracts_json)
        except Exception:
            return json.dumps({"error": "invalid contracts_json"})

        # Accept both {\"contracts\": {...}} and flat list [{\"tsym\":...,\"action\":...}]
        if isinstance(data, list):
            contracts = {}
            for c in data:
                key = f"{c.get('action', '').lower()}_{c.get('type', c.get('option_type', '')).lower()}"
                contracts[key] = {
                    "action": c.get("action"),
                    "strike": c.get("strike"),
                    "option_type": c.get("type") or c.get("option_type"),
                    "tsym": c.get("tsym"),
                    "ltp": c.get("ltp"),
                }
        elif isinstance(data, dict):
            contracts = data.get("contracts", data.get("legs", data))
        else:
            return json.dumps({"error": "invalid contracts_json"})

        if not contracts:
            return json.dumps({"error": "no contracts resolved"})

        from persistence import save_execution_report
        from schemas import ExecutionReport

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
                sl[key] = round(c["ltp"] * (1 + sl_pct), 2)
                tp[key] = round(c["ltp"] * (1 - tp_pct), 2)
            else:
                prem_buy += c["ltp"]

        net = round(prem_sell - prem_buy, 2)

        trade = {
            "entry_time": entry_time,
            "spot_at_entry": spot,
            "atm_strike": atm,
            "vix": vix,
            "expiry": expiry,
            "wing_width": wing_width,
            "strategy_type": strategy_type,
            "leg_count": len(legs),
            "net_credit": net,
            "premium_sell": round(prem_sell, 2),
            "premium_buy": round(prem_buy, 2),
            "legs": legs,
            "sl": sl,
            "tp": tp,
            "status": "OPEN",
        }

        # Save SIM orders
        for leg in legs:
            if leg["action"] == "SELL":
                save_execution_report(
                    ExecutionReport(
                        order_id=f"SIM-{leg['tsym']}",
                        status="MOCK",
                        fill_price=leg["fill_price"],
                        agent_version="execution-agent",
                    )
                )

        return json.dumps(trade, indent=2, default=str)


class BuildAndExecuteTradeTool(BaseTool):
    """Build trade dict from contracts AND route entry orders atomically.

    Combines ExecutePaperTradeTool (build) + PlaceEntryOrdersTool (route).
    Single tool for the Execution Agent so the LLM doesn't have to decide
    which of two tools to call — both happen in one deterministic step.
    """

    name: str = "build_and_execute_trade"
    description: str = (
        "Build legs, calculate net credit and SL/TP, then route ALL entry orders "
        "through the centralized order hub. Returns complete trade dict with trade_id."
    )
    args_schema: Type[BaseModel] = ExecutePaperTradeInput

    def _run(
        self,
        contracts_json: str = "{}",
        strategy_type: str = "IRON_BUTTERFLY",
        entry_time: str = "",
        spot: float = 0.0,
        atm: int = 0,
        vix: float = 0.0,
        expiry: str = "",
        wing_width: int = 200,
        sl_pct: float = 0.25,
        tp_pct: float = 0.50,
    ) -> str:
        try:
            data = json.loads(contracts_json)
        except Exception:
            return json.dumps({"error": "invalid contracts_json"})

        if isinstance(data, list):
            contracts = {}
            for c in data:
                key = f"{c.get('action', '').lower()}_{c.get('type', c.get('option_type', '')).lower()}"
                contracts[key] = {
                    "action": c.get("action"),
                    "strike": c.get("strike"),
                    "option_type": c.get("type") or c.get("option_type"),
                    "tsym": c.get("tsym"),
                    "ltp": c.get("ltp"),
                }
        elif isinstance(data, dict):
            contracts = data.get("contracts", data.get("legs", data))
        else:
            return json.dumps({"error": "invalid contracts_json"})

        if not contracts:
            return json.dumps({"error": "no contracts resolved"})

        from persistence import save_execution_report
        from schemas import ExecutionReport

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
                sl[key] = round(c["ltp"] * (1 + sl_pct), 2)
                tp[key] = round(c["ltp"] * (1 - tp_pct), 2)
            else:
                prem_buy += c["ltp"]

        net = round(prem_sell - prem_buy, 2)

        trade = {
            "entry_time": entry_time,
            "spot_at_entry": spot,
            "atm_strike": atm,
            "vix": vix,
            "expiry": expiry,
            "wing_width": wing_width,
            "strategy_type": strategy_type,
            "leg_count": len(legs),
            "net_credit": net,
            "premium_sell": round(prem_sell, 2),
            "premium_buy": round(prem_buy, 2),
            "legs": legs,
            "sl": sl,
            "tp": tp,
            "status": "OPEN",
        }

        for leg in legs:
            if leg["action"] == "SELL":
                save_execution_report(
                    ExecutionReport(
                        order_id=f"SIM-{leg['tsym']}",
                        status="MOCK",
                        fill_price=leg["fill_price"],
                        agent_version="execution-agent",
                    )
                )

        sys.path.insert(0, str(Path(__file__).parent.parent))
        try:
            from order_routing import place_entry_orders

            result = place_entry_orders(legs)
            trade["trade_id"] = result.get("trade_id", "")
            trade["entry_orders"] = result.get("entry_orders", [])
            trade["order_status"] = result.get("status", "")
            trade["order_mode"] = result.get("mode", "PAPER")
        except ImportError as e:
            return json.dumps({"error": f"Failed to import order_routing: {e}"})
        except Exception as e:
            return json.dumps({"error": f"place_entry_orders failed: {str(e)[:200]}"})

        return json.dumps(trade, indent=2, default=str)


# ── Order Routing Tools (centralized) ─────────────────────────────────────


class PlaceEntryOrdersInput(BaseModel):
    legs: list = Field(
        ...,
        description="List of entry leg dicts with tsym, action, strike, type, quantity, fill_price",
    )


class PlaceEntryOrdersTool(BaseTool):
    name: str = "place_entry_orders"
    description: str = (
        "Route all entry orders (typically 4 legs for butterfly, 2 for spreads) "
        "through the Order Agent's centralized hub. "
        "The Order Agent decides: PAPER mode → save to order_ledger.json, "
        "LIVE mode → forward to Shoonya API. "
        "Returns: {trade_id, entry_orders: [order_id list], status: FILLED|PLACED, mode: PAPER|LIVE}"
    )
    args_schema: Type[BaseModel] = PlaceEntryOrdersInput

    def _run(self, legs: list = None) -> str:
        if not legs:
            return json.dumps({"error": "No legs provided"})

        # Import order_routing from parent directory
        sys.path.insert(0, str(Path(__file__).parent.parent))
        try:
            from order_routing import place_entry_orders
        except ImportError as e:
            return json.dumps({"error": f"Failed to import order_routing: {e}"})

        try:
            result = place_entry_orders(legs)
            return json.dumps(result, indent=2, default=str)
        except Exception as e:
            return json.dumps({"error": f"place_entry_orders failed: {str(e)[:200]}"})


class PlaceSLTPOrdersInput(BaseModel):
    trade_id: str = Field(..., description="Trade ID from entry phase")
    legs: list = Field(
        ...,
        description="List of leg dicts with tsym, action, strike, type, quantity, sl, tp",
    )


class PlaceSLTPOrdersTool(BaseTool):
    name: str = "place_sl_tp_orders"
    description: str = (
        "Route all SL/TP orders through the Order Agent's centralized hub. "
        "Receives trade_id and legs (from the entry trade). "
        "For each SELL leg: places SL (buy trigger) and TP (buy limit) order. "
        "BUY legs (hedges) get NO orders — held to expiry. "
        "Returns: {trade_id, sl_orders: [order_ids], tp_orders: [order_ids], mode: PAPER|LIVE}"
    )
    args_schema: Type[BaseModel] = PlaceSLTPOrdersInput

    def _run(self, trade_id: str, legs: list = None) -> str:
        if not trade_id or not legs:
            return json.dumps({"error": "trade_id and legs required"})

        # Import order_routing from parent directory
        sys.path.insert(0, str(Path(__file__).parent.parent))
        try:
            from order_routing import place_sl_tp_orders
        except ImportError as e:
            return json.dumps({"error": f"Failed to import order_routing: {e}"})

        try:
            result = place_sl_tp_orders(trade_id, legs)
            return json.dumps(result, indent=2, default=str)
        except Exception as e:
            return json.dumps({"error": f"place_sl_tp_orders failed: {str(e)[:200]}"})
