#!/usr/bin/env python3
"""
Order Agent — Centralized order routing for paper and live trading.

Routes orders from:
  - position_manager (MORPH execution)
  - leg_shifter (HEDGE_SHIFT, SELL_SHIFT)
  - risk_agent (MODIFY, CANCEL, EXIT)
  - executioner (initial entry)

Paper mode: updates internal ledger (no broker calls).
Live mode: forwards to Shoonya API and tracks order status.
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, List
from enum import Enum

sys.path.insert(0, str(Path(__file__).parent))

LEDGER_FILE = Path(__file__).parent / "data" / "order_ledger.json"
LIVE_MODE = False  # Set to True when going live

# Import trade execution DB for dual-write
try:
    from trade_execution_db import add_active_trade
except ImportError:
    add_active_trade = None  # Optional, graceful fallback


class OrderStatus(Enum):
    PLACED = "PLACED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    PENDING = "PENDING"


class OrderType(Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    SL = "SL"
    TP = "TP"
    MODIFY_SL = "MODIFY_SL"
    MODIFY_TP = "MODIFY_TP"
    SHIFT_CLOSE = "SHIFT_CLOSE"
    SHIFT_OPEN = "SHIFT_OPEN"


def _load_ledger() -> dict:
    """Load order ledger from disk."""
    if LEDGER_FILE.exists():
        return json.loads(LEDGER_FILE.read_text())
    return {"orders": {}, "order_counter": 0}


def _save_ledger(ledger: dict):
    """Save order ledger to disk."""
    LEDGER_FILE.write_text(json.dumps(ledger, indent=2, default=str))


def _generate_order_id() -> str:
    """Generate unique order ID."""
    ledger = _load_ledger()
    order_counter = ledger.get("order_counter", 0) + 1
    ledger["order_counter"] = order_counter
    _save_ledger(ledger)
    return f"ORD-{datetime.now().strftime('%Y%m%d')}-{order_counter:04d}"


def place_entry_orders(legs: List[Dict]) -> Dict:
    """
    Place all entry orders for a trade (4 legs: 2 SELL, 2 BUY).

    Args:
        legs: List of leg dicts with tsym, action, strike, type, fill_price

    Returns:
        {
            "trade_id": str,
            "entry_orders": [order_id, ...],
            "total_orders": int,
            "mode": "PAPER" | "LIVE",
            "status": "FILLED" | "PLACED"
        }
    """
    trade_id = f"TRD-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    entry_orders = []

    for leg in legs:
        result = place_order(
            symbol=leg.get("tsym", ""),
            action_type=leg.get("action", "BUY"),
            quantity=leg.get("quantity", 65),
            price=leg.get("fill_price", 0),
            order_type="ENTRY",
            component="execution_agent",
            trade_id=trade_id,
            reason=f"{leg.get('type')} {leg.get('action')} @ {leg.get('strike')}"
        )
        entry_orders.append(result["order_id"])

    return {
        "trade_id": trade_id,
        "entry_orders": entry_orders,
        "total_orders": len(entry_orders),
        "mode": "LIVE" if LIVE_MODE else "PAPER",
        "status": "FILLED" if not LIVE_MODE else "PLACED"
    }


def place_sl_tp_orders(trade_id: str, legs: List[Dict]) -> Dict:
    """
    Place SL and TP orders for all SELL legs.

    Args:
        trade_id: Trade ID from entry
        legs: List of leg dicts with tsym, action, type, sl, tp

    Returns:
        {
            "trade_id": str,
            "sl_orders": [order_id, ...],
            "tp_orders": [order_id, ...],
            "total_orders": int,
            "mode": "PAPER" | "LIVE"
        }
    """
    sl_orders = []
    tp_orders = []

    for leg in legs:
        if leg.get("action") != "SELL":
            continue

        # Place SL order
        if leg.get("sl"):
            sl_result = place_order(
                symbol=leg.get("tsym", ""),
                action_type="BUY",  # Buy to close the short
                quantity=leg.get("quantity", 65),
                price=leg.get("sl"),
                order_type="SL",
                component="risk_agent",
                trade_id=trade_id,
                reason=f"SL for {leg.get('tsym')}"
            )
            sl_orders.append(sl_result["order_id"])

        # Place TP order
        if leg.get("tp"):
            tp_result = place_order(
                symbol=leg.get("tsym", ""),
                action_type="BUY",  # Buy to close the short
                quantity=leg.get("quantity", 65),
                price=leg.get("tp"),
                order_type="TP",
                component="risk_agent",
                trade_id=trade_id,
                reason=f"TP for {leg.get('tsym')}"
            )
            tp_orders.append(tp_result["order_id"])

    return {
        "trade_id": trade_id,
        "sl_orders": sl_orders,
        "tp_orders": tp_orders,
        "total_orders": len(sl_orders) + len(tp_orders),
        "mode": "LIVE" if LIVE_MODE else "PAPER"
    }


def place_order(
    symbol: str,
    action_type: str,  # BUY or SELL
    quantity: int,
    price: Optional[float] = None,
    order_type: str = "ENTRY",
    component: str = "unknown",
    trade_id: Optional[str] = None,
    reason: str = "",
) -> Dict:
    """
    Place an order (PAPER or LIVE depending on LIVE_MODE).

    Returns:
        {
            "order_id": str,
            "symbol": str,
            "status": str,
            "mode": "PAPER" | "LIVE",
            "timestamp": str,
            "execution_time": optional str,
            "error": optional str
        }
    """
    order_id = _generate_order_id()
    timestamp = datetime.now().isoformat()

    # Build order record
    order_record = {
        "order_id": order_id,
        "component": component,
        "symbol": symbol,
        "action_type": action_type,
        "quantity": quantity,
        "price": price,
        "order_type": order_type,
        "trade_id": trade_id,
        "reason": reason,
        "timestamp": timestamp,
        "status": OrderStatus.PLACED.value,
        "mode": "LIVE" if LIVE_MODE else "PAPER",
    }

    if not LIVE_MODE:
        # PAPER: directly mark as FILLED, update ledger
        order_record["status"] = OrderStatus.FILLED.value
        order_record["execution_time"] = timestamp
        order_record["execution_price"] = price or 0.0

        ledger = _load_ledger()
        ledger["orders"][order_id] = order_record
        _save_ledger(ledger)

        return {
            "order_id": order_id,
            "symbol": symbol,
            "action_type": action_type,
            "quantity": quantity,
            "price": price,
            "status": "FILLED",
            "mode": "PAPER",
            "timestamp": timestamp,
            "execution_time": timestamp,
        }

    else:
        # LIVE: forward to Shoonya API (not implemented yet)
        # This is where the broker integration happens
        ledger = _load_ledger()
        ledger["orders"][order_id] = order_record
        _save_ledger(ledger)

        # TODO: Call Shoonya API: api.place_order(...)
        # await response, update status to PENDING -> FILLED/REJECTED
        return {
            "order_id": order_id,
            "symbol": symbol,
            "action_type": action_type,
            "quantity": quantity,
            "price": price,
            "status": "PENDING",
            "mode": "LIVE",
            "timestamp": timestamp,
            "error": "LIVE mode not yet implemented",
        }


def modify_order(
    order_id: str,
    new_trigger: Optional[float] = None,
    new_price: Optional[float] = None,
    reason: str = "",
) -> Dict:
    """
    Modify an existing order (SL/TP update).

    Returns:
        {
            "order_id": str,
            "status": str,
            "mode": "PAPER" | "LIVE",
            "error": optional str
        }
    """
    ledger = _load_ledger()
    if order_id not in ledger["orders"]:
        return {"order_id": order_id, "status": "REJECTED", "error": "Order not found"}

    order = ledger["orders"][order_id]

    if not LIVE_MODE:
        # PAPER: directly update order record
        if new_trigger is not None:
            order["trigger"] = new_trigger
        if new_price is not None:
            order["price"] = new_price
        order["modified_at"] = datetime.now().isoformat()
        order["modify_reason"] = reason
        ledger["orders"][order_id] = order
        _save_ledger(ledger)

        return {
            "order_id": order_id,
            "status": "MODIFIED",
            "mode": "PAPER",
            "timestamp": datetime.now().isoformat(),
        }

    else:
        # LIVE: forward to Shoonya API (not implemented yet)
        # TODO: Call api.modify_order(order_id, new_trigger, new_price)
        return {
            "order_id": order_id,
            "status": "PENDING",
            "mode": "LIVE",
            "error": "LIVE mode not yet implemented",
        }


def cancel_order(order_id: str, reason: str = "") -> Dict:
    """
    Cancel an existing order.

    Returns:
        {
            "order_id": str,
            "status": str,
            "mode": "PAPER" | "LIVE",
            "error": optional str
        }
    """
    ledger = _load_ledger()
    if order_id not in ledger["orders"]:
        return {"order_id": order_id, "status": "REJECTED", "error": "Order not found"}

    order = ledger["orders"][order_id]

    if not LIVE_MODE:
        # PAPER: directly mark as CANCELLED
        order["status"] = OrderStatus.CANCELLED.value
        order["cancelled_at"] = datetime.now().isoformat()
        order["cancel_reason"] = reason
        ledger["orders"][order_id] = order
        _save_ledger(ledger)

        return {
            "order_id": order_id,
            "status": "CANCELLED",
            "mode": "PAPER",
            "timestamp": datetime.now().isoformat(),
            "reason": reason,
        }

    else:
        # LIVE: forward to Shoonya API (not implemented yet)
        # TODO: Call api.cancel_order(order_id)
        return {
            "order_id": order_id,
            "status": "PENDING",
            "mode": "LIVE",
            "error": "LIVE mode not yet implemented",
        }


def get_order(order_id: str) -> Optional[Dict]:
    """Get order details from ledger."""
    ledger = _load_ledger()
    return ledger["orders"].get(order_id)


def get_trade_orders(trade_id: str) -> List[Dict]:
    """Get all orders for a specific trade."""
    ledger = _load_ledger()
    return [
        order
        for order in ledger["orders"].values()
        if order.get("trade_id") == trade_id
    ]


def clear_ledger():
    """Clear order ledger (for testing only)."""
    LEDGER_FILE.write_text(json.dumps({"orders": {}, "order_counter": 0}))


if __name__ == "__main__":
    # Test: place a few orders
    clear_ledger()

    o1 = place_order(
        "NIFTY23750PE",
        "SELL",
        65,
        150.0,
        order_type="ENTRY",
        component="executioner",
        trade_id="trade_001",
        reason="Initial entry",
    )
    print(f"Order 1: {json.dumps(o1, indent=2)}")

    o2 = place_order(
        "NIFTY23800CE",
        "BUY",
        65,
        100.0,
        order_type="ENTRY",
        component="executioner",
        trade_id="trade_001",
        reason="Initial entry hedge",
    )
    print(f"Order 2: {json.dumps(o2, indent=2)}")

    # Modify an order
    mod = modify_order(o1["order_id"], new_trigger=160.0, reason="TSL update")
    print(f"Modified: {json.dumps(mod, indent=2)}")

    # Cancel an order
    cancel = cancel_order(o2["order_id"], reason="Manual cancel")
    print(f"Cancelled: {json.dumps(cancel, indent=2)}")

    # Retrieve trade orders
    trade_orders = get_trade_orders("trade_001")
    print(f"\nTrade orders for trade_001:")
    for order in trade_orders:
        print(
            f"  {order['order_id']}: {order['action_type']} {order['symbol']} @ {order['status']}"
        )
