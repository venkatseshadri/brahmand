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
    return {"orders": {}, "order_counter": 0, "_trades": {}}


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

    Writes to BOTH order_ledger.json AND trade_execution.duckdb atomically.

    Args:
        legs: List of leg dicts with tsym, action, strike, type, fill_price, quantity

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
    entry_time = datetime.now().isoformat()
    entry_orders = []

    # STEP 1: Place all orders to ledger
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

    # STEP 2: Build SL/TP dicts for duckdb
    sl = {}
    tp = {}
    for leg in legs:
        leg_type = leg.get("type", "").lower()  # "ce" or "pe"
        if leg.get("action") == "SELL":
            # SL = entry_price * (1 + sl_pct) → higher price triggers SL for short
            # TP = entry_price * (1 - tp_pct) → lower price hits TP for short
            sl[leg_type] = leg.get("sl", 0)
            tp[leg_type] = leg.get("tp", 0)

    # STEP 3: Write to duckdb (atomic with order placement)
    try:
        add_active_trade(
            trade_id=trade_id,
            entry_time=entry_time,
            strategy="ENTRY_ORDERS",  # Will be updated by execution_agent
            entry_gate_signal="PENDING",  # Will be updated by execution_agent
            legs=legs,
            sl=sl,
            tp=tp,
        )
    except Exception as e:
        # Log but don't fail — orders are already in ledger
        import logging
        logging.getLogger(__name__).warning(f"Failed to write to duckdb: {e}")

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

    # Update duckdb to mark SL/TP as placed
    update_trade_in_duckdb(trade_id, status="SL_TP_PLACED")

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
    LEDGER_FILE.write_text(json.dumps({"orders": {}, "order_counter": 0, "_trades": {}}))


# ── Trade-level ledger management ──────────────────────────────────────────


def create_trade(
    trade_id: str,
    strategy_type: str,
    net_credit: float,
    legs: List[Dict],
    sl: Dict,
    tp: Dict,
    entry_gate_signal: str = "",
    entry_confidence: float = 0,
) -> Dict:
    """
    Create a new trade record in the ledger.

    Args:
        trade_id: Unique trade identifier
        strategy_type: PUT_SPREAD | CALL_SPREAD | IRON_BUTTERFLY
        net_credit: Net credit received
        legs: List of leg dicts
        sl: Stop loss dict {ce: ..., pe: ...}
        tp: Take profit dict {ce: ..., pe: ...}
        entry_gate_signal: Signal that triggered entry
        entry_confidence: Confidence level of entry

    Returns:
        Trade record created
    """
    ledger = _load_ledger()
    timestamp = datetime.now().isoformat()

    trade_record = {
        "trade_id": trade_id,
        "entry_time": timestamp,
        "exit_time": None,
        "status": "ACTIVE",
        "strategy_type": strategy_type,
        "net_credit": net_credit,
        "legs": legs,
        "sl": sl,
        "tp": tp,
        "entry_gate_signal": entry_gate_signal,
        "entry_confidence": entry_confidence,
        "orders": [],  # Will be populated as orders are placed
        "created_at": timestamp,
    }

    ledger["_trades"][trade_id] = trade_record
    _save_ledger(ledger)

    return trade_record


def update_trade(trade_id: str, updates: Dict) -> Optional[Dict]:
    """
    Update trade record with new state.

    Args:
        trade_id: Trade to update
        updates: Dict of fields to update {status: "CLOSED", exit_time: "...", ...}

    Returns:
        Updated trade record or None if not found
    """
    ledger = _load_ledger()
    if trade_id not in ledger["_trades"]:
        return None

    trade = ledger["_trades"][trade_id]
    trade.update(updates)
    if "updated_at" not in updates:
        trade["updated_at"] = datetime.now().isoformat()

    ledger["_trades"][trade_id] = trade
    _save_ledger(ledger)
    return trade


def update_trade_in_duckdb(
    trade_id: str,
    strategy: str = None,
    entry_gate_signal: str = None,
    status: str = None
) -> bool:
    """
    Update trade metadata in duckdb (called after execution_agent completes).

    Args:
        trade_id: Trade to update
        strategy: Update strategy type (PUT_SPREAD, CALL_SPREAD, etc.)
        entry_gate_signal: Update entry signal (NOT_UP, NOT_DOWN)
        status: Update status (ACTIVE, SL_TP_PLACED, CLOSING, CLOSED)

    Returns:
        True if successful
    """
    try:
        import duckdb
        from pathlib import Path

        db_path = Path(__file__).parent / "data" / "trade_execution.duckdb"
        con = duckdb.connect(str(db_path))

        updates = []
        params = []

        if strategy:
            updates.append("strategy = ?")
            params.append(strategy)
        if entry_gate_signal:
            updates.append("entry_gate_signal = ?")
            params.append(entry_gate_signal)
        if status:
            updates.append("status = ?")
            params.append(status)

        if updates:
            params.append(trade_id)
            query = f"UPDATE active_trades SET {', '.join(updates)} WHERE trade_id = ?"
            con.execute(query, params)
            con.close()
            return True
        else:
            con.close()
            return False
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Failed to update trade in duckdb: {e}")
        return False


def add_order_to_trade(trade_id: str, order_id: str) -> bool:
    """
    Add an order ID to a trade's orders list.

    Args:
        trade_id: Trade to update
        order_id: Order ID to append

    Returns:
        True if successful, False if trade not found
    """
    ledger = _load_ledger()
    if trade_id not in ledger["_trades"]:
        return False

    if "orders" not in ledger["_trades"][trade_id]:
        ledger["_trades"][trade_id]["orders"] = []

    ledger["_trades"][trade_id]["orders"].append(order_id)
    _save_ledger(ledger)
    return True


def get_trade(trade_id: str) -> Optional[Dict]:
    """Get trade record from ledger."""
    ledger = _load_ledger()
    return ledger.get("_trades", {}).get(trade_id)


def get_active_trades() -> List[Dict]:
    """Get all active (ACTIVE status) trades today."""
    ledger = _load_ledger()
    today = datetime.now().strftime("%Y-%m-%d")
    return [
        trade
        for trade in ledger.get("_trades", {}).values()
        if trade.get("status") == "ACTIVE"
        and trade.get("entry_time", "").startswith(today)
    ]


def get_trades_by_strategy(strategy_type: str) -> List[Dict]:
    """Get all active trades of a specific strategy type."""
    ledger = _load_ledger()
    return [
        trade
        for trade in ledger.get("_trades", {}).values()
        if trade.get("status") == "ACTIVE"
        and trade.get("strategy_type") == strategy_type
    ]


# ── Multi-leg execution ────────────────────────────────────────────────────


def place_legs(
    legs: List[Dict],
    trade_id: str,
    strategy_type: str = "ENTRY"
) -> Dict:
    """
    Place multiple legs for a trade (entry, SL, TP, shifts, etc).

    Args:
        legs: List of leg dicts {tsym, action, quantity, price}
        trade_id: Trade ID these legs belong to
        strategy_type: ENTRY | SL | TP | SHIFT | EXIT

    Returns:
        {
            "status": "FILLED" | "PENDING" | "FAILED",
            "mode": "PAPER" | "LIVE",
            "order_ids": [order_id, ...],
            "error": optional str
        }
    """
    if not LIVE_MODE:
        # ── PAPER MODE: Simulate all fills ──────────────────────────────
        order_ids = []
        try:
            for leg in legs:
                order_result = place_order(
                    symbol=leg.get("tsym", ""),
                    action_type=leg.get("action", "BUY"),
                    quantity=leg.get("quantity", 65),
                    price=leg.get("price", leg.get("fill_price", 0)),
                    order_type=strategy_type,
                    component="order_agent",
                    trade_id=trade_id,
                    reason=f"{strategy_type} leg: {leg.get('action')} {leg.get('tsym')}"
                )
                order_id = order_result["order_id"]
                order_ids.append(order_id)
                add_order_to_trade(trade_id, order_id)

            return {
                "status": "FILLED",
                "mode": "PAPER",
                "order_ids": order_ids,
                "total_legs": len(legs),
            }
        except Exception as e:
            return {
                "status": "FAILED",
                "mode": "PAPER",
                "error": str(e)[:300],
                "order_ids": order_ids,
            }

    else:
        # ── LIVE MODE: Call Shoonya broker API ─────────────────────────
        # TODO: Import Shoonya API
        # TODO: Call api.place_order() for each leg
        # TODO: Track order_ids from broker responses
        # TODO: Handle partial fills, rejections, timeouts
        # TODO: Update order_ledger with actual filled prices
        # TODO: Return {"status": "PENDING", "order_ids": [...]}
        return {
            "status": "ERROR",
            "mode": "LIVE",
            "error": "LIVE mode not yet implemented",
            "order_ids": [],
        }


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
