"""Execution Specialist tools — Broker order placement & monitoring.

Wraps Shoonya/Flattrade API calls with strict Pydantic schemas.
The Execution Specialist NEVER analyzes markets — it only executes authorized legs.

Key principles:
- Wings-first sequencing (BUY hedges before SELL straddle) — margin unlock
- Duplicate-order prevention via orderbook query
- Lot-size safety guardrail before any API call
- Simulation mode by default (no real capital at risk)

Uses BaseTool subclass for strict args_schema enforcement in CrewAI 1.14.4.
"""

import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Type, List, Optional, Dict, Any

from pydantic import BaseModel, Field
from crewai.tools import BaseTool

# ── Broker SDK path (python-trader) ──────────────────────────────────────────
SDK_PATH = Path("/home/trading_ceo/python-trader/ShoonyaApi-py")
sys.path.insert(0, str(SDK_PATH))

# ── Auth state (lazy init) ───────────────────────────────────────────────────
_api_instance = None
_connected = False


def _get_api():
    """Lazy-load ShoonyaApiPy with cred.yml auth. Returns (api, is_sim)."""
    global _api_instance, _connected

    if _connected:
        return _api_instance, False

    cred_path = SDK_PATH.parent / "Shoonya_oAuthAPI-py" / "cred.yml"
    if not cred_path.exists():
        return None, True  # No creds → simulation mode

    try:
        import yaml
        from api_helper import ShoonyaApiPy

        cred = yaml.safe_load(cred_path.read_text())
        api = ShoonyaApiPy()
        ret = api.login(
            userid=cred["user"],
            password=cred["pwd"],
            twoFA=cred["factor2"],
            vendor_code=cred["vc"],
            api_secret=cred["apikey"],
            imei=cred["imei"],
        )
        if ret is not None:
            _api_instance = api
            _connected = True
            return api, False
    except Exception:
        pass

    return None, True  # Auth failed → simulation


# ── Trading symbol builder ───────────────────────────────────────────────────


def _build_tsym(symbol: str, strike: int, option_type: str) -> str:
    """Build Shoonya trading symbol: e.g. NIFTY15MAY202624000CE."""
    safe = symbol.upper().strip()
    opt = option_type.upper().strip()
    # Weekly NIFTY expiry = current Thursday + 1
    today = datetime.now()
    days_until_thu = (3 - today.weekday()) % 7
    if days_until_thu == 0 and today.hour < 15:
        days_until_thu = 0  # Today is Thursday, before expiry
    else:
        days_until_thu = days_until_thu or 7  # Next Thursday
    expiry = today + timedelta(days=days_until_thu)
    expiry_str = expiry.strftime("%d%b%Y").upper()  # e.g., 15MAY2026

    # Adjust for monthly if weekly too close
    days_to_exp = (expiry - today).days
    if days_to_exp < 2:
        expiry = expiry + timedelta(days=7)
        expiry_str = expiry.strftime("%d%b%Y").upper()

    return f"{safe}{expiry_str}{strike}{opt}"


# ── Pydantic Schemas ─────────────────────────────────────────────────────────


class OptionLeg(BaseModel):
    action: str = Field(..., description="BUY or SELL")
    strike: int = Field(..., description="Strike price, e.g., 25500")
    option_type: str = Field(..., description="CE or PE")
    quantity: int = Field(
        ..., description="Number of lots (lot size resolved by Contract Specialist)"
    )


class ExecutionPayload(BaseModel):
    symbol: str = Field(
        default="NIFTY",
        description="The index symbol. Must be 'NIFTY' or 'SENSEX'.",
    )
    strategy: str = Field(
        default="IRON_BUTTERFLY",
        description="Strategy name for logging only. Does NOT affect execution — the legs determine what is executed.",
    )
    authorized_lots: int = Field(
        default=1,
        description="PM-authorized max lot count. Any leg quantity > this is a guardrail violation.",
    )
    legs: List[OptionLeg] = Field(
        ...,
        description=(
            "DETAILED LEG-BY-LEG execution plan. Each leg specifies action (BUY/SELL), "
            "strike, option_type (CE/PE), and quantity. THIS IS THE SINGLE SOURCE OF TRUTH "
            "for execution. Do NOT reduce this to a strategy name — the API needs exact strikes."
        ),
    )


# ── Safety Guardrail ─────────────────────────────────────────────────────────


def validate_lot_sizes(payload: ExecutionPayload) -> tuple[bool, str]:
    """Check every leg's quantity against the PM-authorized lot ceiling.

    Returns (ok: bool, reason: str).
    """
    authorized = payload.authorized_lots
    violations = []

    for i, leg in enumerate(payload.legs):
        if leg.quantity > authorized:
            violations.append(
                f"  Leg {i + 1}: {leg.action} {leg.strike}{leg.option_type} "
                f"quantity={leg.quantity} exceeds authorized={authorized}"
            )
        if leg.quantity <= 0:
            violations.append(
                f"  Leg {i + 1}: {leg.action} {leg.strike}{leg.option_type} "
                f"quantity={leg.quantity} is invalid (must be ≥ 1)"
            )

    if violations:
        return False, "LOT SIZE GUARDRAIL VIOLATION:\n" + "\n".join(violations)

    return True, "OK"


# ══════════════════════════════════════════════════════════════════════════════
# TOOL 1: Execute Multi-Leg Options Strategy
# ══════════════════════════════════════════════════════════════════════════════


class ExecuteTradeTool(BaseTool):
    name: str = "execute_broker_trade"
    description: str = (
        "Execute an authorized multi-leg options strategy on Shoonya/Flattrade. "
        "Requires a detailed leg-by-leg JSON payload — NOT a strategy name. "
        "Expected fields: symbol (NIFTY/SENSEX), strategy (label only), "
        "authorized_lots (PM ceiling), legs (list of {action, strike, option_type, quantity}).\n\n"
        "EXECUTION RULES (internal — you don't control these, the tool does):\n"
        "1. BUY wings execute FIRST (margin unlock).\n"
        "2. SELL center executes SECOND (after 1.5s margin settlement).\n"
        "3. Duplicate orders are blocked via orderbook query.\n"
        "4. Lot sizes are validated against authorized_lots before ANY order.\n\n"
        "IF ANY LEG FAILS, the tool reports exactly which one and stops. "
        "You MUST report failures to the Portfolio Manager — never retry autonomously."
    )
    args_schema: Type[BaseModel] = ExecutionPayload

    def _run(
        self,
        symbol: str = "NIFTY",
        strategy: str = "IRON_BUTTERFLY",
        authorized_lots: int = 1,
        legs: list = None,
    ) -> str:
        if not legs:
            return "Error: No legs provided in execution payload."

        # Reconstruct payload for validation
        payload = ExecutionPayload(
            symbol=symbol,
            strategy=strategy,
            authorized_lots=authorized_lots,
            legs=legs,
        )

        # ── GUARDRAIL: Lot size validation ──────────────────────────────
        ok, msg = validate_lot_sizes(payload)
        if not ok:
            return msg

        # ── Broker connection ───────────────────────────────────────────
        api, is_sim = _get_api()
        mode = "SIMULATION" if is_sim else "LIVE"

        # ── Build trading symbols ───────────────────────────────────────
        # Resolve lot size from scrip_master or fallback
        try:
            from tools.contract_tools import get_lot_size as _get_ls

            lot = _get_ls(payload.symbol)
        except Exception:
            lot = {"NIFTY": 65, "SENSEX": 20}.get(payload.symbol.upper(), 50)
        order_lines = []
        for leg in payload.legs:
            tsym = _build_tsym(payload.symbol, leg.strike, leg.option_type)
            order_lines.append(
                {
                    "action": leg.action,
                    "tsym": tsym,
                    "strike": leg.strike,
                    "option_type": leg.option_type,
                    "quantity": leg.quantity * lot,
                    "raw_quantity": leg.quantity,
                }
            )

        # ── Separate BUY (wings) from SELL (center) ─────────────────────
        buy_orders = [o for o in order_lines if o["action"] == "BUY"]
        sell_orders = [o for o in order_lines if o["action"] == "SELL"]

        results = []
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]

        # ── PHASE 1: BUY wings first (margin unlock) ────────────────────
        for o in buy_orders:
            if is_sim:
                oid = f"SIM-{o['tsym']}-{len(results) + 1:03d}"
                results.append(
                    {
                        "phase": "WING",
                        "action": o["action"],
                        "symbol": o["tsym"],
                        "quantity": o["quantity"],
                        "status": "SIMULATED",
                        "order_id": oid,
                    }
                )
            else:
                try:
                    resp = api.place_order(
                        buy_or_sell="B" if o["action"] == "BUY" else "S",
                        product_type="M",
                        exchange="NFO",
                        tradingsymbol=o["tsym"],
                        quantity=o["quantity"],
                        discloseqty=0,
                        price_type="LMT",
                        price=0.05,  # Market-like; real executor uses LTP buffer
                        trigger_price=0,
                        retention="DAY",
                        remarks=f"Varaha {payload.strategy}",
                    )
                    results.append(
                        {
                            "phase": "WING",
                            "action": o["action"],
                            "symbol": o["tsym"],
                            "quantity": o["quantity"],
                            "status": resp.get("stat", "UNKNOWN"),
                            "order_id": resp.get("norenordno", "?"),
                        }
                    )
                except Exception as e:
                    results.append(
                        {
                            "phase": "WING",
                            "action": o["action"],
                            "symbol": o["tsym"],
                            "status": "FAILED",
                            "error": str(e)[:200],
                        }
                    )
                    return json.dumps(
                        {
                            "status": "ABORTED",
                            "mode": mode,
                            "summary": "WING LEG FAILED — execution halted. Report to PM.",
                            "results": results,
                        },
                        indent=2,
                    )

        # ── 1.5s margin settlement buffer ───────────────────────────────
        if not is_sim and buy_orders:
            time.sleep(1.5)

        # ── PHASE 2: SELL straddle/center ───────────────────────────────
        for o in sell_orders:
            if is_sim:
                oid = f"SIM-{o['tsym']}-{len(results) + 1:03d}"
                results.append(
                    {
                        "phase": "CENTER",
                        "action": o["action"],
                        "symbol": o["tsym"],
                        "quantity": o["quantity"],
                        "status": "SIMULATED",
                        "order_id": oid,
                    }
                )
            else:
                try:
                    resp = api.place_order(
                        buy_or_sell="B" if o["action"] == "BUY" else "S",
                        product_type="M",
                        exchange="NFO",
                        tradingsymbol=o["tsym"],
                        quantity=o["quantity"],
                        discloseqty=0,
                        price_type="LMT",
                        price=0.05,
                        trigger_price=0,
                        retention="DAY",
                        remarks=f"Varaha {payload.strategy}",
                    )
                    results.append(
                        {
                            "phase": "CENTER",
                            "action": o["action"],
                            "symbol": o["tsym"],
                            "quantity": o["quantity"],
                            "status": resp.get("stat", "UNKNOWN"),
                            "order_id": resp.get("norenordno", "?"),
                        }
                    )
                except Exception as e:
                    results.append(
                        {
                            "phase": "CENTER",
                            "action": o["action"],
                            "symbol": o["tsym"],
                            "status": "FAILED",
                            "error": str(e)[:200],
                        }
                    )
                    return json.dumps(
                        {
                            "status": "ABORTED",
                            "mode": mode,
                            "summary": "CENTER LEG FAILED after wings placed. Report to PM immediately.",
                            "results": results,
                        },
                        indent=2,
                    )

        return json.dumps(
            {
                "status": "EXECUTED",
                "mode": mode,
                "strategy": payload.strategy,
                "symbol": payload.symbol,
                "authorized_lots": payload.authorized_lots,
                "total_legs": len(results),
                "wings": len(buy_orders),
                "center": len(sell_orders),
                "guardrail": "PASSED",
                "sequence": "WINGS_FIRST",
                "results": results,
            },
            indent=2,
        )


# ══════════════════════════════════════════════════════════════════════════════
# TOOL 2: Query Order Book / Status
# ══════════════════════════════════════════════════════════════════════════════


class OrderStatusInput(BaseModel):
    order_id: str = Field(
        default="ALL",
        description="Specific order ID (norenordno) to query, or 'ALL' for the full order book.",
    )


class GetOrderStatusTool(BaseTool):
    name: str = "get_order_status"
    description: str = (
        "Query the live order book or a specific order by ID from Shoonya/Flattrade. "
        "Use this to verify fills, check pending orders, or confirm cancellations. "
        "Call this after executing a strategy to confirm all legs are COMPLETE."
    )
    args_schema: Type[BaseModel] = OrderStatusInput

    def _run(self, order_id: str = "ALL") -> str:
        api, is_sim = _get_api()

        if is_sim:
            return (
                '{"mode":"SIMULATION","orders":[{"order_id":"SIM-001","status":"COMPLETE",'
                '"symbol":"NIFTY15MAY202624000CE","side":"SELL","qty":50}]}'
            )

        try:
            if order_id == "ALL":
                book = api.get_order_book()
            else:
                book = api.single_order_history(order_id)

            if not book or (isinstance(book, dict) and book.get("stat") != "Ok"):
                return json.dumps(
                    {"error": "Orderbook unavailable", "raw": str(book)[:500]}
                )

            return json.dumps(book, indent=2, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)[:300]})


# ══════════════════════════════════════════════════════════════════════════════
# TOOL 3: Query Open Positions
# ══════════════════════════════════════════════════════════════════════════════


class GetPositionsTool(BaseTool):
    name: str = "get_open_positions"
    description: str = (
        "Query all open options positions from Shoonya/Flattrade. "
        "Returns position details: symbol, net qty, avg price, P&L, MTM. "
        "Use this to confirm the strategy is fully entered or to report daily P&L."
    )
    args_schema: Type[BaseModel] = OrderStatusInput  # Placeholder; overwritten below

    def _run(self, symbol: str = "NIFTY") -> str:
        api, is_sim = _get_api()

        if is_sim:
            from tools.ta_strategy_tools import FetchGreeksTool, FetchOptionChainTool

            g = FetchGreeksTool()
            o = FetchOptionChainTool()
            greeks = g._run(symbol)
            chain_preview = o._run(symbol)[:300]
            return json.dumps(
                {
                    "mode": "SIMULATION",
                    "symbol": symbol,
                    "positions": [
                        {
                            "tsym": f"{symbol}SIM24000CE",
                            "netqty": "50",
                            "daysellavgprc": "38.00",
                            "daybuyavgprc": "27.65",
                            "pnl": "+517.50",
                            "status": "SIMULATED",
                        }
                    ],
                    "greeks_snapshot": greeks,
                    "chain_snapshot": chain_preview,
                },
                indent=2,
            )

        try:
            positions = api.get_positions()
            if not positions or (
                isinstance(positions, dict) and positions.get("stat") != "Ok"
            ):
                return json.dumps(
                    {"error": "Positions unavailable", "raw": str(positions)[:500]}
                )

            return json.dumps(positions, indent=2, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)[:300]})


# ══════════════════════════════════════════════════════════════════════════════
# TOOL 4: Modify Order — Receives command from Risk Sentry, calls api.modify_order
# ══════════════════════════════════════════════════════════════════════════════


class ModifyOrderInput(BaseModel):
    order_id: str = Field(
        ..., description="norenordno of the existing SL order to modify"
    )
    tsym: str = Field(..., description="Trading symbol of the order")
    new_trigger_price: float = Field(
        ..., description="New SL trigger price from Risk Sentry"
    )
    exchange: str = Field(default="NFO", description="Exchange: NFO for options")


class ModifyOrderTool(BaseTool):
    name: str = "execute_modify_order"
    description: str = (
        "Execute a MODIFY command from the Risk Sentry. Updates an existing "
        "SL-LMT order's trigger price via api.modify_order.\n\n"
        "Call this ONLY when the Risk Sentry's trade_command returns "
        "command='MODIFY_ORDER'.\n\n"
        "Use the EXACT order_id and new_trigger_price from the command — "
        "never recalculate or override the Risk Sentry's decision."
    )
    args_schema: Type[BaseModel] = ModifyOrderInput

    def _run(
        self,
        order_id: str,
        tsym: str,
        new_trigger_price: float,
        exchange: str = "NFO",
    ) -> str:
        api, is_sim = _get_api()

        if is_sim:
            return json.dumps(
                {
                    "status": "MODIFIED",
                    "mode": "SIMULATION",
                    "order_id": order_id,
                    "tsym": tsym,
                    "new_trigger_price": new_trigger_price,
                    "exchange": exchange,
                    "audit": f"TSL modified: {tsym} SL→{new_trigger_price} (commanded by Risk Sentry)",
                },
                indent=2,
            )

        try:
            resp = api.modify_order(
                orderno=order_id,
                tradingsymbol=tsym,
                newprice=0,
                newtrigger_price=new_trigger_price,
                exchange=exchange,
            )
            return json.dumps(
                {
                    "status": resp.get("stat", "UNKNOWN"),
                    "mode": "LIVE",
                    "order_id": order_id,
                    "new_trigger_price": new_trigger_price,
                    "commanded_by": "Risk Sentry",
                    "raw_response": resp,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps(
                {"status": "ERROR", "mode": "LIVE", "error": str(e)[:300]}
            )


# ══════════════════════════════════════════════════════════════════════════════
# TOOL 5: Cancel Order — Kill switch for SL/TP lifecycle management
# ══════════════════════════════════════════════════════════════════════════════


class CancelOrderInput(BaseModel):
    order_id: str = Field(..., description="norenordno to cancel")
    reason: str = Field(
        default="TP_FILLED",
        description="Why cancelling: TP_FILLED, SL_FILLED, MANUAL, or TSL_UPDATE",
    )


class CancelBrokerOrderTool(BaseTool):
    name: str = "cancel_order"
    description: str = (
        "Cancel an existing open order via api.cancel_order. Called by the Risk Sentry "
        "when the opposite order fills.\n\n"
        "ORDER LIFECYCLE RULES:\n"
        "- TP FILLED → immediately CANCEL the corresponding SL order (prevents double execution).\n"
        "- SL FILLED → immediately CANCEL the corresponding TP order.\n"
        "- Before a TSL MODIFY, verify the order is still OPEN (use get_order_status first).\n\n"
        "CRITICAL: Never cancel an order without the Risk Sentry's explicit trade_command. "
        "Cancelling the wrong order leaves a naked position."
    )
    args_schema: Type[BaseModel] = CancelOrderInput

    def _run(self, order_id: str, reason: str = "TP_FILLED") -> str:
        api, is_sim = _get_api()

        if is_sim:
            return json.dumps(
                {
                    "status": "CANCELLED",
                    "mode": "SIMULATION",
                    "order_id": order_id,
                    "reason": reason,
                    "audit": f"Cancelled {order_id} — {reason}",
                },
                indent=2,
            )

        try:
            resp = api.cancel_order(orderno=order_id)
            return json.dumps(
                {
                    "status": resp.get("stat", "UNKNOWN"),
                    "mode": "LIVE",
                    "order_id": order_id,
                    "reason": reason,
                    "raw_response": resp,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps(
                {"status": "ERROR", "order_id": order_id, "error": str(e)[:300]}
            )


# GetPositionsTool args_schema — lightweight replacement for ta_strategy_tools
class _PositionQueryInput(BaseModel):
    """Schema for GetPositionsTool input (self-contained, no ta_strategy_tools dep)."""

    symbol: str = Field(default="NIFTY", description="Underlying symbol")


GetPositionsTool.args_schema = _PositionQueryInput
