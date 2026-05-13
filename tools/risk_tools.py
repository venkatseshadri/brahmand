"""Risk Management tools — The Sentry's arsenal.

Monitors live positions, calculates trailing stops, and emits exit signals.
The Risk Agent NEVER places orders directly — it sends formatted exit commands
to the Execution Specialist.

Tools:
  1. monitor_pnl_greeks   — Fetches live MTM P&L + aggregate Greeks from DuckDB
  2. tsl_engine            — Pure trailing stop-loss calculator
  3. exit_signal_handler   — Formats a JSON exit command for the Executioner

Uses BaseTool subclass for strict args_schema enforcement in CrewAI 1.14.4.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Type, List, Optional, Any

from pydantic import BaseModel, Field
from crewai.tools import BaseTool

LIVE_DB = {
    "NIFTY": Path("/home/trading_ceo/python-trader/varaha/data/varaha_data.duckdb"),
    "SENSEX": Path(
        "/home/trading_ceo/python-trader/varaha/data/varaha_data_sensex.duckdb"
    ),
}


def _get_greeks_conn(live_db_path: Path):
    """Open ATTACH connection to live DuckDB (READ_ONLY — no lock contention)."""
    import duckdb

    con = duckdb.connect(":memory:")
    if live_db_path.exists():
        con.execute(f"ATTACH '{live_db_path}' AS live (READ_ONLY)")
    return con


# ══════════════════════════════════════════════════════════════════════════════
# TOOL 1: Monitor P&L + Greeks
# ══════════════════════════════════════════════════════════════════════════════


class PositionLeg(BaseModel):
    tsym: str = Field(..., description="Trading symbol, e.g., NIFTY14MAY202623650CE")
    action: str = Field(..., description="BUY or SELL")
    entry_price: float = Field(..., description="Average entry price per contract")
    quantity: int = Field(..., description="Number of lots")
    lot_size: int = Field(..., description="Lot size (65 for NIFTY)")
    token: Optional[str] = Field(default=None, description="Shoonya token (optional)")


class PnLMonitorInput(BaseModel):
    symbol: str = Field(default="NIFTY", description="Index symbol: NIFTY or SENSEX")
    legs: List[PositionLeg] = Field(
        ..., description="Active position legs to monitor for P&L"
    )


class MonitorPnLGreeksTool(BaseTool):
    name: str = "monitor_pnl_greeks"
    description: str = (
        "Fetch live MTM P&L for an active position + current aggregate Greeks. "
        "Queries DuckDB for latest spot, greeks, and option chain LTPs.\n\n"
        "Call this EVERY monitoring cycle to check if SL/TP thresholds are breached. "
        "Returns: per-leg MTM, total P&L, net Greeks, spot, VIX.\n\n"
        "Use this BEFORE calling tsl_engine to get the current price input."
    )
    args_schema: Type[BaseModel] = PnLMonitorInput

    def _run(self, symbol: str = "NIFTY", legs: list = None) -> str:
        safe = symbol.upper().strip()
        db_path = LIVE_DB.get(safe)
        if not db_path or not db_path.exists():
            return json.dumps({"error": f"Database not found for {safe}"})

        if not legs:
            return json.dumps({"error": "No position legs provided"})

        try:
            con = _get_greeks_conn(db_path)

            spot_row = con.execute(
                "SELECT spot FROM live.market_data WHERE spot IS NOT NULL ORDER BY id DESC LIMIT 1"
            ).fetchone()
            spot = float(spot_row[0]) if spot_row else 0

            greeks_row = con.execute(
                "SELECT agg_delta, agg_gamma, agg_vega, agg_theta, wings_delta, body_delta "
                "FROM live.market_data WHERE agg_delta IS NOT NULL ORDER BY id DESC LIMIT 1"
            ).fetchone()

            snapshot = con.execute(
                "SELECT strike, option_type, ltp FROM live.option_snapshots "
                "WHERE timestamp = (SELECT MAX(timestamp) FROM live.option_snapshots)"
            ).fetchdf()

            # Try VIX from market_data
            vix_row = con.execute(
                "SELECT india_vix FROM live.market_data WHERE india_vix IS NOT NULL ORDER BY id DESC LIMIT 1"
            ).fetchone()
            vix = float(vix_row[0]) if vix_row else 0

        except Exception as e:
            return json.dumps({"error": f"Database query failed: {e}"})
        finally:
            if "con" in locals():
                con.close()

        # ── Calculate per-leg MTM + total P&L ────────────────────────────
        leg_results = []
        total_pnl = 0
        total_units = 0

        for i, leg in enumerate(legs):
            action = leg.get("action", "SELL").upper()
            entry = float(leg.get("entry_price", 0))
            qty = int(leg.get("quantity", 1))
            ls = int(leg.get("lot_size", 65))
            tsym = leg.get("tsym", "?")

            # Extract strike + option_type from tsym (e.g., NIFTY14MAY202623650CE → 23650, CE)
            strike = 0
            opt_type = ""
            for ch in tsym:
                if ch.isdigit():
                    strike = strike * 10 + int(ch)
                elif strike > 0:
                    if ch in ("C", "P"):
                        opt_type = tsym[tsym.index(ch) :]
                    break

            if not opt_type:
                # Fallback: parse by position
                if "CE" in tsym:
                    opt_type = "CE"
                    strike_str = tsym.replace("NIFTY", "").split("CE")[0]
                    # Extract digits
                    digits = ""
                    for c in strike_str:
                        if c.isdigit():
                            digits += c
                    strike = int(digits) if digits else 0
                elif "PE" in tsym:
                    opt_type = "PE"
                    strike_str = tsym.replace("NIFTY", "").split("PE")[0]
                    digits = ""
                    for c in strike_str:
                        if c.isdigit():
                            digits += c
                    strike = int(digits) if digits else 0

            # Find current LTP from snapshot
            if strike and opt_type and not snapshot.empty:
                match = snapshot[
                    (snapshot["strike"] == strike)
                    & (snapshot["option_type"] == opt_type)
                ]
                current_ltp = float(match.iloc[0]["ltp"]) if not match.empty else entry
            else:
                current_ltp = entry

            units = qty * ls
            # For SELL: profit = (entry - current) * units, For BUY: profit = (current - entry) * units
            pnl_per_unit = (
                entry - current_ltp if action == "SELL" else current_ltp - entry
            )
            pnl = round(pnl_per_unit * units, 2)
            total_pnl += pnl
            total_units += units

            leg_results.append(
                {
                    "index": i,
                    "tsym": tsym,
                    "action": action,
                    "strike": strike,
                    "option_type": opt_type,
                    "entry_price": entry,
                    "current_ltp": round(current_ltp, 2),
                    "pnl_per_unit": round(pnl_per_unit, 2),
                    "units": units,
                    "leg_pnl": pnl,
                }
            )

        net_greeks = {
            "delta": round(float(greeks_row[0]), 4) if greeks_row else 0,
            "gamma": round(float(greeks_row[1]), 6) if greeks_row else 0,
            "vega": round(float(greeks_row[2]), 4) if greeks_row else 0,
            "theta": round(float(greeks_row[3]), 4) if greeks_row else 0,
            "wings_delta": round(float(greeks_row[4]), 4) if greeks_row else 0,
            "body_delta": round(float(greeks_row[5]), 4) if greeks_row else 0,
        }

        return json.dumps(
            {
                "timestamp": datetime.now().isoformat(),
                "symbol": safe,
                "spot": spot,
                "vix": round(vix, 2),
                "position": {
                    "total_legs": len(legs),
                    "total_units": total_units,
                    "mtm_pnl_total": round(total_pnl, 2),
                },
                "legs": leg_results,
                "greeks": net_greeks,
                "mode": "LIVE_DUCKDB",
            },
            indent=2,
        )


# ══════════════════════════════════════════════════════════════════════════════
# TOOL 2: Trailing Stop-Loss Engine
# ══════════════════════════════════════════════════════════════════════════════


class TSLEngineInput(BaseModel):
    entry_price: float = Field(
        ..., description="Average entry premium for the sold option leg."
    )
    current_price: float = Field(
        ..., description="Current LTP of the sold option from monitor_pnl_greeks."
    )
    highest_favorable: float = Field(
        ...,
        description=(
            "Highest favorable price seen since entry. "
            "For SELL: the LOWEST LTP reached. For BUY: the HIGHEST price reached."
        ),
    )
    sl_buffer_pct: float = Field(
        default=10.0,
        description="SL buffer as percentage. SL = entry_price * (1 + sl_buffer_pct/100) for sells.",
    )
    tsl_activation_pct: float = Field(
        default=50.0,
        description="Profit % of target at which TSL activates. e.g., 50 = activate TSL at 50% of TP.",
    )
    tsl_lock_ratio: float = Field(
        default=0.5,
        description="Lock ratio. For every ₹1 further favorable move, lock ₹0.50 (lock_ratio) of it.",
    )


class TSLEngineTool(BaseTool):
    name: str = "tsl_engine"
    description: str = (
        "Pure trailing stop-loss calculator. Returns whether SL/TSL/TP is triggered "
        "and the new stop level.\n\n"
        "LOGIC:\n"
        "- Hard SL: fixed at entry_price * (1 + sl_buffer_pct%) for shorts.\n"
        "- TP: when price reaches 40% of entry (60% profit for shorts).\n"
        "- TSL: activates when MTM hits tsl_activation_pct% of TP. "
        "Then locks tsl_lock_ratio of every favorable tick.\n\n"
        "Call monitor_pnl_greeks FIRST to get current_price, then pass it here."
    )
    args_schema: Type[BaseModel] = TSLEngineInput

    def _run(
        self,
        entry_price: float,
        current_price: float,
        highest_favorable: float,
        sl_buffer_pct: float = 10.0,
        tsl_activation_pct: float = 50.0,
        tsl_lock_ratio: float = 0.5,
    ) -> str:
        # ── Hard SL ─────────────────────────────────────────────────────
        sl_level = entry_price * (1 + sl_buffer_pct / 100)
        sl_triggered = current_price >= sl_level

        # ── TP (50% profit for shorts) ──────────────────────────────────
        tp_level = entry_price * 0.50
        tp_triggered = current_price <= tp_level

        # ── MTM Profit ──────────────────────────────────────────────────
        current_profit = entry_price - current_price  # Positive = in profit for shorts
        profit_pct = (current_profit / entry_price) * 100 if entry_price > 0 else 0

        # ── TSL ─────────────────────────────────────────────────────────
        tsl_active = False
        tsl_level = None
        if not tp_triggered:
            tp_profit = entry_price - tp_level  # Full TP profit
            tsl_threshold = tp_profit * (tsl_activation_pct / 100)
            if current_profit >= tsl_threshold:
                tsl_active = True
                excess = current_profit - tsl_threshold
                locked_profit = tsl_threshold + (excess * tsl_lock_ratio)
                tsl_level = entry_price - locked_profit

        # ── Decision ────────────────────────────────────────────────────
        if sl_triggered:
            decision = "EXIT_SL"
            exit_reason = f"SL breach: current={current_price:.2f} >= SL={sl_level:.2f}"
        elif tp_triggered:
            decision = "EXIT_TP"
            exit_reason = f"TP hit: current={current_price:.2f} <= TP={tp_level:.2f}"
        elif tsl_active and current_price > entry_price:
            decision = "EXIT_TSL"
            exit_reason = (
                f"TSL breach: price reversed above entry. Current={current_price:.2f}"
            )
        elif tsl_active:
            decision = "TRAIL"
            exit_reason = None
        else:
            decision = "HOLD"
            exit_reason = None

        return json.dumps(
            {
                "entry_price": entry_price,
                "current_price": current_price,
                "highest_favorable": highest_favorable,
                "current_profit": round(current_profit, 2),
                "profit_pct": round(profit_pct, 2),
                "sl_level": round(sl_level, 2),
                "tp_level": round(tp_level, 2),
                "tsl_level": round(tsl_level, 2) if tsl_level else None,
                "tsl_active": tsl_active,
                "sl_triggered": sl_triggered,
                "tp_triggered": tp_triggered,
                "decision": decision,
                "exit_reason": exit_reason,
            },
            indent=2,
        )


# ══════════════════════════════════════════════════════════════════════════════
# TOOL 3: Trade Command Handler — Issues EXIT and MODIFY commands
# The Risk Agent COMMANDS. The Execution Specialist EXECUTES.
# ══════════════════════════════════════════════════════════════════════════════


class TradeCommandInput(BaseModel):
    symbol: str = Field(default="NIFTY", description="Index symbol")
    command_type: str = Field(
        default="EXIT",
        description="EXIT (close position), MODIFY (update SL), or CANCEL (cancel opposite order)",
    )
    reason: str = Field(default="", description="Detailed reason for audit log")
    legs: list = Field(
        default_factory=list,
        description="List of leg dicts {tsym, action, quantity}. EXIT: all legs. Others: pass [].",
    )
    order_id: str = Field(
        default="",
        description="MODIFY or CANCEL: the norenordno. EXIT: leave empty.",
    )
    new_trigger_price: float = Field(
        default=0.0,
        description="MODIFY: new SL trigger price. CANCEL/EXIT: leave 0.",
    )
    cancel_reason: str = Field(
        default="",
        description="CANCEL: reason — TP_FILLED, SL_FILLED, or MANUAL.",
    )
    mtm_pnl: float = Field(default=0.0, description="Current MTM P&L")


class TradeCommandHandlerTool(BaseTool):
    name: str = "trade_command"
    description: str = (
        "Issue a COMMAND to the Execution Specialist.\n\n"
        "command_type='EXIT': Close ALL position legs. Auto-calculates opposite actions.\n"
        "command_type='MODIFY': Update an SL order's trigger price (TSL).\n"
        "command_type='CANCEL': Cancel the OPPOSITE order when SL or TP fills.\n"
        "  - TP FILLED → CANCEL the SL order (cancel_reason='TP_FILLED')\n"
        "  - SL FILLED → CANCEL the TP order (cancel_reason='SL_FILLED')\n\n"
        "Call EXIT when tsl_engine returns decision=EXIT_*.\n"
        "Call MODIFY when tsl_engine returns decision=TRAIL with new tsl_level.\n"
        "Call CANCEL when order_status shows one side COMPLETE — kill the other side."
    )
    args_schema: Type[BaseModel] = TradeCommandInput

    def _run(
        self,
        symbol: str = "NIFTY",
        command_type: str = "EXIT",
        reason: str = "",
        legs: list = None,
        order_id: str = "",
        new_trigger_price: float = 0.0,
        cancel_reason: str = "",
        mtm_pnl: float = 0.0,
    ) -> str:
        if command_type == "CANCEL":
            if not order_id:
                return json.dumps({"error": "CANCEL requires order_id"})
            return json.dumps(
                {
                    "command": "CANCEL_ORDER",
                    "timestamp": datetime.now().isoformat(),
                    "order_id": order_id,
                    "cancel_reason": cancel_reason or "TP_FILLED",
                    "instructions": f"Call cancel_order with order_id='{order_id}', reason='{cancel_reason or 'TP_FILLED'}'",
                    "audit": {
                        "action": "CANCEL_OPPOSITE",
                        "reason": cancel_reason or "TP_FILLED",
                        "order_cancelled": order_id,
                    },
                },
                indent=2,
            )

        if command_type == "MODIFY":
            if not order_id or not new_trigger_price:
                return json.dumps(
                    {"error": "MODIFY requires order_id and new_trigger_price"}
                )
            return json.dumps(
                {
                    "command": "MODIFY_ORDER",
                    "timestamp": datetime.now().isoformat(),
                    "symbol": symbol,
                    "reason": reason,
                    "order_id": order_id,
                    "new_trigger_price": round(new_trigger_price, 2),
                    "instructions": f"Call execute_modify_order with order_id='{order_id}', new_trigger_price={round(new_trigger_price, 2)}",
                    "audit": {
                        "action": "TSL_UPDATE",
                        "reason": reason,
                        "new_sl": round(new_trigger_price, 2),
                    },
                },
                indent=2,
            )

        if not legs:
            return json.dumps({"error": "EXIT requires legs"})

        exit_legs = []
        for leg in legs:
            original = leg.get("action", "SELL").upper()
            exit_act = "BUY" if original == "SELL" else "SELL"
            exit_legs.append(
                {
                    "action": exit_act,
                    "strike": 0,
                    "option_type": "CE" if "CE" in leg.get("tsym", "") else "PE",
                    "quantity": leg.get("quantity", 1),
                }
            )

        return json.dumps(
            {
                "command": "EXIT_POSITION",
                "timestamp": datetime.now().isoformat(),
                "symbol": symbol,
                "exit_type": command_type,
                "reason": reason,
                "mtm_pnl_at_exit": round(mtm_pnl, 2),
                "instructions": f"Pass to execute_broker_trade with strategy='EXIT_{command_type}'",
                "legs": exit_legs,
                "audit": {
                    "trigger": command_type,
                    "reason": reason,
                    "pnl": round(mtm_pnl, 2),
                },
            },
            indent=2,
        )


# ══════════════════════════════════════════════════════════════════════════════
# TOOL 4: WebSocket Subscription — Live Tick + Order Feed
# ══════════════════════════════════════════════════════════════════════════════


class WsSubscribeInput(BaseModel):
    tokens: List[str] = Field(
        ...,
        description="List of Shoonya tokens to subscribe to, e.g., ['35003', '35203'].",
    )
    feed_type: str = Field(
        default="BOTH",
        description="BOTH (order updates + price ticks), ORDERS (order confirmations only), or TICKS (price feed only)",
    )


class WebSocketSubscriptionTool(BaseTool):
    name: str = "live_risk_monitor"
    description: str = (
        "Subscribe to live price ticks and order updates from Shoonya/Flattrade WebSocket. "
        "In production: starts api.start_websocket in a background thread with "
        "event_handler_feed_update + event_handler_order_update callbacks.\n\n"
        "In simulation mode (default): returns a mock tick snapshot from DuckDB.\n\n"
        "MANDATORY: Call this after receiving the Execution Report to confirm ALL legs "
        "are FILLED before starting SL/TSL monitoring. The Sentry only activates risk "
        "management once order status = COMPLETE for every leg.\n\n"
        "Tokens must be in Shoonya format: 'NSE|35003' or 'BFO|45001'."
    )
    args_schema: Type[BaseModel] = WsSubscribeInput

    def _run(self, tokens: list = None, feed_type: str = "BOTH") -> str:
        if not tokens:
            return json.dumps({"error": "No tokens provided for subscription"})

        prefix = "NSE" if any("NIFTY" in str(t) for t in tokens) else "NFO"
        subscribed = [f"{prefix}|{t}" for t in tokens]

        return json.dumps(
            {
                "status": "SUBSCRIBED",
                "mode": "SIMULATION",
                "feed_type": feed_type,
                "subscribed_tokens": subscribed,
                "tick_snapshot": {
                    "token": subscribed[0] if subscribed else None,
                    "lp": "23.45",
                    "ltq": "50",
                    "ltt": datetime.now().isoformat(),
                },
                "order_callbacks": "Monitoring order updates for ALL legs",
                "instructions": "Risk Sentry is now live. SL clock starts when all orders = COMPLETE.",
            },
            indent=2,
        )


# ══════════════════════════════════════════════════════════════════════════════
# TOOL 5: Order Adjuster — TSL modification via Shoonya API
# ══════════════════════════════════════════════════════════════════════════════


class OrderAdjustInput(BaseModel):
    order_id: str = Field(..., description="The norenordno (order number) to modify.")
    tsym: str = Field(..., description="Trading symbol of the order being modified.")
    new_trigger_price: float = Field(
        ...,
        description="New SL trigger price for the TSL update (the 'floor' calculated by tsl_engine).",
    )
    reason: str = Field(
        default="TSL_UPDATE",
        description="Reason for modification: TSL_UPDATE, TIGHTEN_SL, or MANUAL_ADJUST.",
    )


class OrderAdjusterTool(BaseTool):
    name: str = "order_adjuster"
    description: str = (
        "Modify an existing SL-LMT order's trigger price using Shoonya's api.modify_order. "
        "Used for Trailing Stop-Loss (TSL) updates — when tsl_engine returns decision=TRAIL "
        "with a new tsl_level, call this to update the live SL order at the broker.\n\n"
        "In simulation mode: logs the modification. In live mode: calls api.modify_order "
        "with orderno, tradingsymbol, newprice, and trigger_price.\n\n"
        "CRITICAL: Only modify orders that are still OPEN/PENDING. Do NOT modify "
        "COMPLETE or CANCELLED orders."
    )
    args_schema: Type[BaseModel] = OrderAdjustInput

    def _run(
        self,
        order_id: str,
        tsym: str,
        new_trigger_price: float,
        reason: str = "TSL_UPDATE",
    ) -> str:
        # Lazy import to avoid circular dependency
        from tools.execution_tools import _get_api as _get_broker_api

        api, is_sim = _get_broker_api()

        if is_sim:
            return json.dumps(
                {
                    "status": "MODIFIED",
                    "mode": "SIMULATION",
                    "order_id": order_id,
                    "tsym": tsym,
                    "new_trigger_price": new_trigger_price,
                    "reason": reason,
                    "audit": f"TSL updated: {tsym} SL→{new_trigger_price}",
                },
                indent=2,
            )

        try:
            resp = api.modify_order(
                orderno=order_id,
                tradingsymbol=tsym,
                newprice=0,
                newtrigger_price=new_trigger_price,
                exchange="NFO",
            )
            return json.dumps(
                {
                    "status": resp.get("stat", "UNKNOWN"),
                    "mode": "LIVE",
                    "order_id": order_id,
                    "new_trigger_price": new_trigger_price,
                    "raw_response": resp,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps(
                {"status": "ERROR", "mode": "LIVE", "error": str(e)[:300]}
            )
