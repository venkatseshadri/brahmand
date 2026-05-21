#!/usr/bin/env python3
"""
Leg Shifter — Shift position legs when premium decays.

Two agents:
1. HEDGE_SHIFTER (50% decay) — Shift hedge closer to SELL (narrower wing, lower margin)
   Action: Open new HEDGE (closer) → Close old HEDGE (always safe, margin decreases)

2. SELL_SHIFTER (60% decay) — Shift SELL farther from hedge (wider wing, higher margin)
   Action: Close old SELL → Open new SELL (margin check required, wing widens)

Both shift only if their counterpart leg exists.
Margin check only for SELL_SHIFTER (hedge shift always reduces margin).
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Tuple

sys.path.insert(0, str(Path(__file__).parent))

from duckdb_tool import _connect
from order_agent import place_order, cancel_order


def _load_margin_matrix() -> dict:
    """Load pre-captured margin matrix from brahmand/data/margin_matrix.json."""
    matrix_path = Path(__file__).parent / "data" / "margin_matrix.json"
    if not matrix_path.exists():
        return {}
    try:
        return json.loads(matrix_path.read_text())
    except Exception as e:
        print(f"[LEG_SHIFTER] Error loading margin_matrix: {e}")
        return {}


def _lookup_margin_from_matrix(
    sell_strike: int, buy_strike: int, option_type: str, matrix: dict
) -> Optional[float]:
    """
    Look up margin for (sell_strike, buy_strike, option_type) in margin_matrix.
    Returns margin in ₹, or None if not found.
    """
    if not matrix or "spreads" not in matrix:
        return None

    for spread in matrix["spreads"]:
        if (
            spread.get("type") == option_type
            and spread.get("sell_strike") == sell_strike
            and spread.get("buy_strike") == buy_strike
        ):
            return spread.get("margin")
    return None


def _get_current_atm(trade: dict) -> int:
    """Get ATM from trade setup."""
    return trade.get("setup", {}).get("atm_strike", 0) if isinstance(trade.get("setup"), dict) else 0


def _classify_legs(trade: dict) -> Tuple[Optional[dict], Optional[dict], str]:
    """
    Classify legs into SELL and HEDGE for each option type.
    Returns: (sell_leg, hedge_leg, option_type)
    For PE: SELL PE at higher strike, HEDGE PE at lower strike
    For CE: SELL CE at lower strike, HEDGE CE at higher strike
    """
    legs = trade.get("legs", [])
    pe_legs = [l for l in legs if l.get("type") == "PE"]
    ce_legs = [l for l in legs if l.get("type") == "CE"]

    # PE: SELL > HEDGE in strike
    if pe_legs and len(pe_legs) >= 2:
        sell_pe = max(pe_legs, key=lambda l: l.get("strike", 0)) if any(
            l.get("action") == "SELL" for l in pe_legs
        ) else None
        hedge_pe = min(pe_legs, key=lambda l: l.get("strike", 0)) if any(
            l.get("action") == "BUY" for l in pe_legs
        ) else None
        if sell_pe and hedge_pe:
            return (sell_pe, hedge_pe, "PE")

    # CE: SELL < HEDGE in strike
    if ce_legs and len(ce_legs) >= 2:
        sell_ce = min(ce_legs, key=lambda l: l.get("strike", 0)) if any(
            l.get("action") == "SELL" for l in ce_legs
        ) else None
        hedge_ce = max(ce_legs, key=lambda l: l.get("strike", 0)) if any(
            l.get("action") == "BUY" for l in ce_legs
        ) else None
        if sell_ce and hedge_ce:
            return (sell_ce, hedge_ce, "CE")

    return (None, None, "")


def _calculate_decay(fill_price: float, current_ltp: float) -> float:
    """Calculate premium decay as percentage."""
    if not fill_price or fill_price <= 0:
        return 0
    return ((fill_price - current_ltp) / fill_price) * 100


def evaluate_hedge_shift(trade: dict) -> Optional[Dict]:
    """
    HEDGE_SHIFTER: Evaluate if hedge should be shifted closer (narrower wing, lower margin).

    Condition: Hedge decay > 50%
    Action: Open new HEDGE (closer) → Close old HEDGE
    Margin: Not needed (wing shrinks)

    Returns dict with shift proposal or None if no shift needed.
    """
    if not trade or not trade.get("legs"):
        return None

    # Get LTPs from live feed
    con = _connect()
    try:
        sell_leg, hedge_leg, option_type = _classify_legs(trade)
        if not sell_leg or not hedge_leg:
            return None  # Need both to shift hedge

        expiry = trade.get("expiry", "")

        # Get current LTPs
        hedge_ltp = con.execute(
            "SELECT ltp FROM option_snapshots WHERE expiry_date = ? AND strike = ? AND option_type = ? "
            "ORDER BY timestamp DESC LIMIT 1",
            (expiry, hedge_leg.get("strike"), option_type)
        ).fetchone()
        hedge_ltp = float(hedge_ltp[0]) if hedge_ltp else hedge_leg.get("fill_price", 0)

        hedge_decay = _calculate_decay(hedge_leg.get("fill_price", 0), hedge_ltp)

        # HEDGE_SHIFTER trigger: decay > 50%
        if hedge_decay <= 50:
            return None  # Not decayed enough

        # Determine new hedge strike (closer to SELL)
        strike_step = 50 if option_type == "PE" else 50  # NIFTY = 50pt steps
        sell_strike = sell_leg.get("strike", 0)
        old_hedge_strike = hedge_leg.get("strike", 0)

        # Move hedge closer by one step
        if option_type == "PE":
            new_hedge_strike = old_hedge_strike + strike_step  # Closer to SELL PE
        else:  # CE
            new_hedge_strike = old_hedge_strike - strike_step  # Closer to SELL CE

        # New wing width (should be narrower)
        old_wing = abs(sell_strike - old_hedge_strike)
        new_wing = abs(sell_strike - new_hedge_strike)

        if new_wing >= old_wing:
            return None  # Not actually closer, skip

        return {
            "shifter_type": "HEDGE",
            "option_type": option_type,
            "old_hedge_strike": old_hedge_strike,
            "new_hedge_strike": new_hedge_strike,
            "sell_strike": sell_strike,
            "old_wing": old_wing,
            "new_wing": new_wing,
            "hedge_decay_pct": round(hedge_decay, 1),
            "timestamp": datetime.now().isoformat(),
        }
    finally:
        con.close()


def evaluate_sell_shift(trade: dict, available_margin: float) -> Optional[Dict]:
    """
    SELL_SHIFTER: Evaluate if SELL should be shifted farther (wider wing, higher margin).

    Condition: SELL decay > 60%
    Action: Close old SELL → Open new SELL
    Margin: CHECK REQUIRED (wing widens, margin increases)

    Returns dict with shift proposal or None if no shift needed.
    """
    if not trade or not trade.get("legs"):
        return None

    # Get LTPs from live feed
    con = _connect()
    try:
        sell_leg, hedge_leg, option_type = _classify_legs(trade)
        if not sell_leg or not hedge_leg:
            return None  # Need both to shift SELL

        expiry = trade.get("expiry", "")

        # Get current LTP for SELL
        sell_ltp = con.execute(
            "SELECT ltp FROM option_snapshots WHERE expiry_date = ? AND strike = ? AND option_type = ? "
            "ORDER BY timestamp DESC LIMIT 1",
            (expiry, sell_leg.get("strike"), option_type)
        ).fetchone()
        sell_ltp = float(sell_ltp[0]) if sell_ltp else sell_leg.get("fill_price", 0)

        sell_decay = _calculate_decay(sell_leg.get("fill_price", 0), sell_ltp)

        # SELL_SHIFTER trigger: decay > 60%
        if sell_decay <= 60:
            return None  # Not decayed enough

        # Determine new SELL strike (farther from hedge)
        strike_step = 50  # NIFTY = 50pt steps
        old_sell_strike = sell_leg.get("strike", 0)
        hedge_strike = hedge_leg.get("strike", 0)

        # Move SELL farther by one step
        if option_type == "PE":
            new_sell_strike = old_sell_strike + strike_step  # Farther from hedge PE
        else:  # CE
            new_sell_strike = old_sell_strike - strike_step  # Farther from hedge CE

        # New wing width (should be wider)
        old_wing = abs(old_sell_strike - hedge_strike)
        new_wing = abs(new_sell_strike - hedge_strike)

        if new_wing <= old_wing:
            return None  # Not actually farther, skip

        # Get margin matrix
        matrix = _load_margin_matrix()

        # Look up old margin
        old_margin = _lookup_margin_from_matrix(
            old_sell_strike, hedge_strike, option_type, matrix
        )
        if not old_margin:
            return None  # Can't find old margin in matrix

        # Look up new margin (or will need to call SPAN API if not in matrix)
        new_margin = _lookup_margin_from_matrix(
            new_sell_strike, hedge_strike, option_type, matrix
        )

        if not new_margin:
            # Not in matrix — would need SPAN API call (defer for now, mark as TBD)
            # For MVP, we'll skip shifts outside the pre-captured matrix
            return None

        # MARGIN CHECK
        # When closing old SELL, old_margin is released
        # available_after_close = available_margin + old_margin
        available_after_close = available_margin + old_margin

        if new_margin > available_after_close:
            # Insufficient margin for new SELL
            return {
                "shifter_type": "SELL",
                "status": "REJECTED",
                "reason": "INSUFFICIENT_MARGIN",
                "new_margin_required": new_margin,
                "available_margin": available_after_close,
                "timestamp": datetime.now().isoformat(),
            }

        # Margin check passed
        return {
            "shifter_type": "SELL",
            "option_type": option_type,
            "old_sell_strike": old_sell_strike,
            "new_sell_strike": new_sell_strike,
            "hedge_strike": hedge_strike,
            "old_wing": old_wing,
            "new_wing": new_wing,
            "old_margin": old_margin,
            "new_margin": new_margin,
            "margin_impact": round(new_margin - old_margin, 0),
            "sell_decay_pct": round(sell_decay, 1),
            "timestamp": datetime.now().isoformat(),
        }
    finally:
        con.close()


def run_leg_shifter(trade: dict, available_margin: float) -> Dict:
    """
    Main entry point: Evaluate both shifters sequentially.
    Run HEDGE_SHIFTER first (always safe), then SELL_SHIFTER (needs margin check).

    Args:
        trade: Active trade dict
        available_margin: Available margin from broker get_limits() API

    Returns:
        {
            "hedge_shift": proposal or None,
            "sell_shift": proposal or None,
            "timestamp": iso_timestamp
        }
    """
    hedge_shift = evaluate_hedge_shift(trade)
    sell_shift = evaluate_sell_shift(trade, available_margin)

    return {
        "hedge_shift": hedge_shift,
        "sell_shift": sell_shift,
        "timestamp": datetime.now().isoformat(),
    }


def execute_hedge_shift(trade: dict, proposal: Dict) -> Dict:
    """
    Execute HEDGE_SHIFTER: Open new hedge → Close old hedge.

    Updates trade["legs"] with new hedge strike and position.
    Returns execution result.
    """
    if not proposal or proposal.get("shifter_type") != "HEDGE":
        return {"status": "INVALID"}

    option_type = proposal["option_type"]
    old_hedge_strike = proposal["old_hedge_strike"]
    new_hedge_strike = proposal["new_hedge_strike"]

    # Get new hedge's current LTP (entry point for new position)
    con = _connect()
    try:
        expiry = trade.get("expiry", "")
        row = con.execute(
            "SELECT ltp FROM option_snapshots WHERE expiry_date = ? AND strike = ? AND option_type = ? "
            "ORDER BY timestamp DESC LIMIT 1",
            (expiry, new_hedge_strike, option_type),
        ).fetchone()
        new_hedge_ltp = float(row[0]) if row else 0

        if new_hedge_ltp <= 0:
            return {"status": "FAILED", "reason": "NO_LTP_DATA"}

        # Step 1: Place BUY order for new hedge (OPEN)
        new_hedge_tsym = f"NIFTY{trade.get('expiry', '').replace('-', '')}{option_type}{new_hedge_strike}"
        open_order = place_order(
            symbol=new_hedge_tsym,
            action_type="BUY",
            quantity=65,
            price=new_hedge_ltp,
            order_type="SHIFT_OPEN",
            component="leg_shifter",
            trade_id=trade.get("trade_id"),
            reason=f"HEDGE_SHIFT: {old_hedge_strike}→{new_hedge_strike}",
        )

        # Step 2: Place SELL order for old hedge (CLOSE)
        old_hedge_tsym = f"NIFTY{trade.get('expiry', '').replace('-', '')}{option_type}{old_hedge_strike}"
        old_hedge_leg = next(
            (l for l in trade.get("legs", [])
             if l.get("type") == option_type and l.get("action") == "BUY" and l.get("strike") == old_hedge_strike),
            None,
        )
        old_hedge_ltp = 0
        if old_hedge_leg:
            row_old = con.execute(
                "SELECT ltp FROM option_snapshots WHERE expiry_date = ? AND strike = ? AND option_type = ? "
                "ORDER BY timestamp DESC LIMIT 1",
                (expiry, old_hedge_strike, option_type),
            ).fetchone()
            old_hedge_ltp = float(row_old[0]) if row_old else old_hedge_leg.get("fill_price", 0)

        close_order = place_order(
            symbol=old_hedge_tsym,
            action_type="SELL",
            quantity=65,
            price=old_hedge_ltp or old_hedge_leg.get("fill_price", 0) if old_hedge_leg else 0,
            order_type="SHIFT_CLOSE",
            component="leg_shifter",
            trade_id=trade.get("trade_id"),
            reason=f"HEDGE_SHIFT_CLOSE: {old_hedge_strike}",
        )

        # Step 3: Remove old hedge leg from trade
        trade["legs"] = [
            l
            for l in trade.get("legs", [])
            if not (l.get("type") == option_type and l.get("action") == "BUY" and l.get("strike") == old_hedge_strike)
        ]

        # Step 4: Add new hedge leg (BUY at new_hedge_strike)
        # New fill_price = current LTP (fresh entry for TSL)
        trade["legs"].append(
            {
                "action": "BUY",
                "type": option_type,
                "strike": new_hedge_strike,
                "fill_price": new_hedge_ltp,
                "tsym": new_hedge_tsym,
                "order_id": open_order.get("order_id"),  # Track order
            }
        )

        return {
            "status": "SUCCESS",
            "shifter_type": "HEDGE",
            "option_type": option_type,
            "old_strike": old_hedge_strike,
            "new_strike": new_hedge_strike,
            "new_fill_price": round(new_hedge_ltp, 2),
            "open_order_id": open_order.get("order_id"),
            "close_order_id": close_order.get("order_id"),
            "timestamp": datetime.now().isoformat(),
        }

    finally:
        con.close()


def execute_sell_shift(trade: dict, proposal: Dict) -> Dict:
    """
    Execute SELL_SHIFTER: Close old SELL → Open new SELL.

    Closes old SELL at current LTP (books profit), opens new SELL at current LTP.
    Updates trade["legs"] and sets new SL/TP.
    Returns execution result.
    """
    if not proposal or proposal.get("shifter_type") != "SELL":
        return {"status": "INVALID"}

    if proposal.get("status") == "REJECTED":
        return {"status": "REJECTED", "reason": proposal.get("reason")}

    option_type = proposal["option_type"]
    old_sell_strike = proposal["old_sell_strike"]
    new_sell_strike = proposal["new_sell_strike"]

    # Get new SELL's current LTP (entry point for new position)
    con = _connect()
    try:
        expiry = trade.get("expiry", "")
        row = con.execute(
            "SELECT ltp FROM option_snapshots WHERE expiry_date = ? AND strike = ? AND option_type = ? "
            "ORDER BY timestamp DESC LIMIT 1",
            (expiry, new_sell_strike, option_type),
        ).fetchone()
        new_sell_ltp = float(row[0]) if row else 0

        if new_sell_ltp <= 0:
            return {"status": "FAILED", "reason": "NO_LTP_DATA"}

        # Get old SELL's current LTP to book profit
        row_old = con.execute(
            "SELECT ltp FROM option_snapshots WHERE expiry_date = ? AND strike = ? AND option_type = ? "
            "ORDER BY timestamp DESC LIMIT 1",
            (expiry, old_sell_strike, option_type),
        ).fetchone()
        old_sell_ltp = float(row_old[0]) if row_old else 0

        # Get old SELL leg for profit calculation and order tracking
        old_sell_leg = next(
            (l for l in trade.get("legs", [])
             if l.get("type") == option_type and l.get("action") == "SELL" and l.get("strike") == old_sell_strike),
            None,
        )
        profit = 0

        # Step 1: Book profit on old SELL (realized P&L) + place CLOSE order
        if old_sell_ltp > 0 and old_sell_leg:
            profit = old_sell_leg.get("fill_price", 0) - old_sell_ltp
            trade["cumulative_pnl"] = trade.get("cumulative_pnl", 0) + (profit * 65)  # 65 = NIFTY lot size

            # Place BUY order to close old SELL (buy back)
            old_sell_tsym = f"NIFTY{expiry.replace('-', '')}{option_type}{old_sell_strike}"
            close_order = place_order(
                symbol=old_sell_tsym,
                action_type="BUY",
                quantity=65,
                price=old_sell_ltp,
                order_type="SHIFT_CLOSE",
                component="leg_shifter",
                trade_id=trade.get("trade_id"),
                reason=f"SELL_SHIFT_CLOSE: {old_sell_strike} (profit=₹{profit*65:.0f})",
            )

        # Step 2: Remove old SELL leg
        trade["legs"] = [
            l
            for l in trade.get("legs", [])
            if not (l.get("type") == option_type and l.get("action") == "SELL" and l.get("strike") == old_sell_strike)
        ]

        # Step 3: Place SELL order for new SELL position (OPEN)
        new_sell_tsym = f"NIFTY{expiry.replace('-', '')}{option_type}{new_sell_strike}"
        open_order = place_order(
            symbol=new_sell_tsym,
            action_type="SELL",
            quantity=65,
            price=new_sell_ltp,
            order_type="SHIFT_OPEN",
            component="leg_shifter",
            trade_id=trade.get("trade_id"),
            reason=f"SELL_SHIFT: {old_sell_strike}→{new_sell_strike}",
        )

        # Step 4: Add new SELL leg
        # New fill_price = current LTP (fresh entry for TSL)
        trade["legs"].append(
            {
                "action": "SELL",
                "type": option_type,
                "strike": new_sell_strike,
                "fill_price": new_sell_ltp,
                "tsym": new_sell_tsym,
                "order_id": open_order.get("order_id"),  # Track order
            }
        )

        # Step 5: Set new SL/TP for new SELL leg
        t = option_type.lower()
        trade["sl"][t] = round(new_sell_ltp * 1.10, 2)  # SL at 10% above entry
        trade["tp"][t] = round(new_sell_ltp * 0.50, 2)  # TP at 50% below entry

        return {
            "status": "SUCCESS",
            "shifter_type": "SELL",
            "option_type": option_type,
            "old_strike": old_sell_strike,
            "new_strike": new_sell_strike,
            "old_pnl_booked": round(profit, 2) if profit > 0 else 0,
            "new_fill_price": round(new_sell_ltp, 2),
            "new_sl": trade["sl"][t],
            "new_tp": trade["tp"][t],
            "close_order_id": close_order.get("order_id") if old_sell_ltp > 0 else None,
            "open_order_id": open_order.get("order_id"),
            "timestamp": datetime.now().isoformat(),
        }

    finally:
        con.close()


if __name__ == "__main__":
    # Test with mock trade
    print("[LEG_SHIFTER] Test mode\n")
    print("Import via: from leg_shifter import run_leg_shifter, execute_hedge_shift, execute_sell_shift")
    print("Call: proposals = run_leg_shifter(trade, available_margin)")
    print("Then: result = execute_hedge_shift(trade, proposals['hedge_shift'])")
    print("      result = execute_sell_shift(trade, proposals['sell_shift'])")
