"""
Position Manager — Single owner of all position adjustments.

Runs every 5 minutes. Priority order:
  P1: Theta decay ≥ DECAY_PCT on sold leg → ROLL to ATM
  P2: Hedge > HEDGE_GAP pts from sold strike → TIGHTEN hedge
  P3: Entry gate signal changed → MORPH (add/remove side)
  P4: SL hit on any sold leg → CLOSE that side
  P5: TP hit on any sold leg → CLOSE that side
  P6: Cumulative P&L ≤ FLOOR → CLOSE ALL
  P7: Market close → CLOSE ALL

One system, one owner. No conflict with risk monitor — this IS the risk monitor.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── Defaults (tune from observed data over days) ──
DECAY_PCT = 0.375  # 37.5% theta decay → roll trigger
HEDGE_GAP = 150  # pts from sold strike → tighten hedge
SL_PCT = 0.50  # 50% above entry → SL
TP_PCT = 0.50  # 50% below entry → TP
FLOOR = -500  # cumulative P&L floor
MAX_MORPHS = 3  # max morphs per day
WING_SPREAD = 150  # wing width for credit spreads
WING_BUTTERFLY = 200  # wing width for iron butterfly
MARKET_CLOSE = "15:30"

# Action types
ROLL = "ROLL"
TIGHTEN = "TIGHTEN"
MORPH = "MORPH"
CLOSE_SIDE = "CLOSE_SIDE"
CLOSE_ALL = "CLOSE_ALL"
NOTHING = "NOTHING"


def now_str() -> str:
    return datetime.now().strftime("%H:%M")


def _get_ltp(con, expiry: str, strike: int, otype: str) -> float:
    """Query DuckDB for latest option LTP."""
    row = con.execute(
        "SELECT ltp FROM option_snapshots "
        "WHERE expiry_date = ? AND strike = ? AND option_type = ? "
        "AND tsym IS NOT NULL ORDER BY timestamp DESC LIMIT 1",
        (expiry, strike, otype),
    ).fetchone()
    ltp = float(row[0] or 0) if row else 0
    return ltp if ltp < 5000 else 0  # sanity: option LTP < spot


def _get_spot(con, index: str = "NIFTY") -> float:
    row = con.execute(
        "SELECT spot FROM market_data WHERE index_name = ? ORDER BY id DESC LIMIT 1",
        (index,),
    ).fetchone()
    return float(row[0]) if row else 0


def _load_entry_signal() -> dict:
    """Read latest entry gate decision from file."""
    p = Path("/home/trading_ceo/antariksh/logs/entry_check_latest.json")
    if p.exists():
        return json.loads(p.read_text())
    return {"signal": "NEUTRAL", "confidence": 0, "score": 0}


def _pattern_risk_adjust(trade: dict) -> None:
    """P3.5: Adapt SL/TP and TSL lock ratio based on current traffic light pattern.

    Runs every 5-min monitoring cycle. Learning: as data accumulates, predict_live()
    gets more confident → SL/TP adjustments become tighter/wider based on regime.
    """
    try:
        from pattern_analyzer import PatternAnalyzer

        pa = PatternAnalyzer(min_samples=5)
        result = pa.predict_live()
        if result is None or result.get("status") == "insufficient_data":
            return

        conf = result.get("confidence", 0) or 0
        if conf < 50:
            return  # Not enough confidence to adapt

        up = result.get("up_15m", 0) or 0
        down = result.get("down_15m", 0) or 0
        side = result.get("side_15m", 0) or 0
        current_type = _classify_position(trade)

        # Directional agreement: pattern agrees with position → tighten SL (protect gains)
        if (current_type == "BULLISH" and up >= 0.65) or (
            current_type == "BEARISH" and down >= 0.65
        ):
            new_sl_pct = 0.35
            new_tsl = 0.7
        elif side >= 0.60:
            # Sideways → iron fly regime, keep wider SL to avoid noise exits
            new_sl_pct = 0.60
            new_tsl = 0.4
        else:
            return  # No strong signal, don't adapt

        # Update SL levels in-place for all SELL legs
        for leg in trade.get("legs", []):
            if leg["action"] != "SELL":
                continue
            t = leg["type"].lower()
            fill = leg.get("fill_price", 0)
            if fill and trade["sl"].get(t):
                trade["sl"][t] = round(fill * (1 + new_sl_pct), 2)

        trade["tsl_lock_ratio"] = new_tsl
        trade["pattern_confidence"] = conf

    except Exception:
        pass  # Never block position manager for pattern errors


def run(trade: dict, entry_scores: dict = None) -> list[dict]:
    """
    Main entry point. Called from kickoff.py every 5 min.

    Args:
        trade: current active_trade from state
        entry_scores: entry gate output at time of entry (optional)

    Returns:
        list of action dicts: [{type: ROLL|TIGHTEN|MORPH|CLOSE_SIDE|CLOSE_ALL,
                                leg: {...}, old_strike: X, new_strike: Y, reason: "..."}]
        Empty list = nothing to do.
    """
    from duckdb_tool import _connect

    if not trade or not trade.get("legs"):
        return []

    con = _connect()
    try:
        spot = _get_spot(con)
        expiry = trade.get("expiry", "")
        sig = _load_entry_signal()
        actions = []

        # ── Gather LTPs for all open legs ──
        legs_data = []
        for leg in trade["legs"]:
            ltp = _get_ltp(con, expiry, leg["strike"], leg["type"])
            fill = leg.get("fill_price", 0)
            decay = (fill - ltp) / fill if fill > 0 else 0  # +ve = winning
            legs_data.append(
                {
                    **leg,
                    "ltp": ltp,
                    "fill": fill,
                    "decay": decay,
                }
            )

        # ── P1: Theta decay on SOLD legs ──
        for ld in legs_data:
            if ld["action"] != "SELL":
                continue
            if ld["decay"] >= DECAY_PCT and ld["ltp"] > 0:
                # Roll: close this leg, open at new ATM
                atm = round(spot / 50) * 50
                if atm != ld["strike"]:
                    actions.append(
                        {
                            "type": ROLL,
                            "priority": 1,
                            "leg": ld,
                            "old_strike": ld["strike"],
                            "new_strike": atm,
                            "old_ltp": ld["ltp"],
                            "old_fill": ld["fill"],
                            "decay_pct": round(ld["decay"] * 100, 1),
                            "reason": f"{ld['type']} {ld['strike']} decayed {ld['decay'] * 100:.0f}% → roll to {atm}",
                        }
                    )

        # ── P2: Hedge > HEDGE_GAP from nearest sold strike ──
        sold_strikes = [ld["strike"] for ld in legs_data if ld["action"] == "SELL"]
        for ld in legs_data:
            if ld["action"] != "BUY":
                continue
            nearest_sold = (
                min(sold_strikes, key=lambda s: abs(s - ld["strike"]))
                if sold_strikes
                else None
            )
            if nearest_sold and abs(ld["strike"] - nearest_sold) > HEDGE_GAP:
                # Tighten: close old hedge, open new at NEAREST_SOLD ± WING_SPREAD
                otype = ld["type"]
                new_strike = (
                    nearest_sold - WING_SPREAD
                    if otype == "PE"
                    else nearest_sold + WING_SPREAD
                )
                actions.append(
                    {
                        "type": TIGHTEN,
                        "priority": 2,
                        "leg": ld,
                        "old_strike": ld["strike"],
                        "new_strike": new_strike,
                        "old_ltp": ld["ltp"],
                        "old_fill": ld["fill"],
                        "gap_from_sold": abs(ld["strike"] - nearest_sold),
                        "reason": f"Hedge {ld['type']}{ld['strike']} {abs(ld['strike'] - nearest_sold)}pt from sold → tighten to {new_strike}",
                    }
                )

        # ── P3: Threshold-based spread control ──
        # Score > -3.0 → PUT_SPREAD should exist
        # Score < 3.0 → CALL_SPREAD should exist
        # Score >= 3.0 → close CALL_SPREAD (threshold override)
        # Score <= -3.0 → close PUT_SPREAD (threshold override)
        score = sig.get("score", 0)
        has_put = _has_put_spread(trade)
        has_call = _has_call_spread(trade)
        morph_count = trade.get("morph_count", 0)

        if score >= 3.0 and has_call and morph_count < MAX_MORPHS:
            # BULLISH: close CALL_SPREAD (threshold override, close at market immediately)
            actions.append(
                {
                    "type": MORPH,
                    "priority": 3,
                    "from_type": "NEUTRAL",
                    "to_type": "BULLISH",
                    "legs": legs_data,
                    "score": score,
                    "threshold_override": True,
                    "reason": f"Score {score:.2f} >= 3.0: close CALL_SPREAD (threshold override)",
                }
            )
        elif score <= -3.0 and has_put and morph_count < MAX_MORPHS:
            # BEARISH: close PUT_SPREAD (threshold override, close at market immediately)
            actions.append(
                {
                    "type": MORPH,
                    "priority": 3,
                    "from_type": "NEUTRAL",
                    "to_type": "BEARISH",
                    "legs": legs_data,
                    "score": score,
                    "threshold_override": True,
                    "reason": f"Score {score:.2f} <= -3.0: close PUT_SPREAD (threshold override)",
                }
            )
        elif -3.0 < score < 3.0:
            # NEUTRAL zone: ensure both spreads exist
            current_type = _classify_position(trade)
            if current_type == "BULLISH" and not has_call and morph_count < MAX_MORPHS:
                # Add CALL_SPREAD
                actions.append(
                    {
                        "type": MORPH,
                        "priority": 3,
                        "from_type": "BULLISH",
                        "to_type": "NEUTRAL",
                        "legs": legs_data,
                        "score": score,
                        "reason": f"Score {score:.2f} in neutral zone: add CALL_SPREAD",
                    }
                )
            elif current_type == "BEARISH" and not has_put and morph_count < MAX_MORPHS:
                # Add PUT_SPREAD
                actions.append(
                    {
                        "type": MORPH,
                        "priority": 3,
                        "from_type": "BEARISH",
                        "to_type": "NEUTRAL",
                        "legs": legs_data,
                        "score": score,
                        "reason": f"Score {score:.2f} in neutral zone: add PUT_SPREAD",
                    }
                )

        # ── P3.5: Pattern-driven risk adjustment ──
        _pattern_risk_adjust(trade)

        # ── P4: SL check ──
        for ld in legs_data:
            if ld["action"] != "SELL":
                continue
            sl = ld["fill"] * (1 + SL_PCT)
            if ld["ltp"] > 0 and ld["ltp"] >= sl:
                actions.append(
                    {
                        "type": CLOSE_SIDE,
                        "priority": 4,
                        "side": ld["type"],
                        "legs": [
                            l for l in legs_data if l["type"] == ld["type"]
                        ],  # both sold+bought of same type
                        "sl_price": sl,
                        "ltp": ld["ltp"],
                        "reason": f"SL: {ld['type']}{ld['strike']} LTP={ld['ltp']:.0f} ≥ SL={sl:.0f}",
                    }
                )

        # ── P5: TP check ──
        for ld in legs_data:
            if ld["action"] != "SELL":
                continue
            tp = ld["fill"] * (1 - TP_PCT)
            if ld["ltp"] > 0 and ld["ltp"] <= tp:
                actions.append(
                    {
                        "type": CLOSE_SIDE,
                        "priority": 5,
                        "side": ld["type"],
                        "legs": [l for l in legs_data if l["type"] == ld["type"]],
                        "tp_price": tp,
                        "ltp": ld["ltp"],
                        "reason": f"TP: {ld['type']}{ld['strike']} LTP={ld['ltp']:.0f} ≤ TP={tp:.0f}",
                    }
                )

        # ── P6: Cumulative floor ──
        cumulative = trade.get("cumulative_pnl", trade.get("pnl", 0))
        if cumulative <= FLOOR:
            actions.append(
                {
                    "type": CLOSE_ALL,
                    "priority": 6,
                    "cumulative_pnl": cumulative,
                    "reason": f"Cumulative P&L ₹{cumulative} ≤ floor ₹{FLOOR}",
                }
            )

        # ── P7: Market close ──
        if now_str() >= MARKET_CLOSE:
            actions.append(
                {
                    "type": CLOSE_ALL,
                    "priority": 7,
                    "reason": f"Market close ({MARKET_CLOSE})",
                }
            )

        # Sort by priority, deduplicate CLOSE_SIDE (only highest priority)
        actions.sort(key=lambda a: a["priority"])
        seen_sides = set()
        deduped = []
        for a in actions:
            if a["type"] == CLOSE_SIDE:
                if a["side"] in seen_sides:
                    continue
                seen_sides.add(a["side"])
            deduped.append(a)
            if a["type"] == CLOSE_ALL:
                deduped = [a]  # close all overrides everything
                break

        return deduped
    finally:
        con.close()


def _classify_position(trade: dict) -> str:
    """Classify current position: BULLISH (put spread only), BEARISH (call spread only), NEUTRAL (both)."""
    has_pe = any(
        l["type"] == "PE" and l["action"] == "SELL" for l in trade.get("legs", [])
    )
    has_ce = any(
        l["type"] == "CE" and l["action"] == "SELL" for l in trade.get("legs", [])
    )
    if has_pe and has_ce:
        return "NEUTRAL"
    if has_pe:
        return "BULLISH"
    if has_ce:
        return "BEARISH"
    return "NEUTRAL"


def _has_put_spread(trade: dict) -> bool:
    """Check if PUT_SPREAD (PE SELL leg) exists."""
    return any(l["type"] == "PE" and l["action"] == "SELL" for l in trade.get("legs", []))


def _has_call_spread(trade: dict) -> bool:
    """Check if CALL_SPREAD (CE SELL leg) exists."""
    return any(l["type"] == "CE" and l["action"] == "SELL" for l in trade.get("legs", []))


def execute_action(action: dict, trade: dict) -> dict:
    """
    Execute a position manager action. Position Manager OWNS SL/TP.
    When a leg is rolled/morphed, SL/TP are recalculated automatically.
    No conflict with risk system — this IS the risk system.
    """
    trade.setdefault("cumulative_pnl", 0)
    trade.setdefault("sl", {})
    trade.setdefault("tp", {})
    side_key = action.get("leg", {}).get("type", "").lower()

    if action["type"] in (CLOSE_ALL,):
        return trade

    if action["type"] in (ROLL, TIGHTEN):
        leg = action["leg"]
        # Book P&L on closing leg
        pnl = (
            leg["fill"] - leg["ltp"]
            if leg["action"] == "SELL"
            else leg["ltp"] - leg["fill"]
        )
        trade["cumulative_pnl"] += pnl
        # Remove old leg
        trade["legs"] = [
            l
            for l in trade["legs"]
            if not (l["strike"] == leg["strike"] and l["type"] == leg["type"])
        ]
        # Clear old SL/TP for this option type
        trade["sl"][side_key] = None
        trade["tp"][side_key] = None
        # Estimate new fill (mock paper)
        new_fill = round(leg["ltp"] * (0.85 if leg["action"] == "SELL" else 1.15), 2)
        trade["legs"].append(
            {
                "action": leg["action"],
                "strike": action["new_strike"],
                "type": leg["type"],
                "fill_price": new_fill,
                "tsym": f"NIFTY{trade.get('expiry', '').replace('-', '')}{leg['type']}{action['new_strike']}",
            }
        )
        # Set new SL/TP for replaced sold leg
        if leg["action"] == "SELL":
            trade["sl"][side_key] = round(new_fill * (1 + SL_PCT), 2)
            trade["tp"][side_key] = round(new_fill * (1 - TP_PCT), 2)

    if action["type"] == MORPH:
        trade["morph_count"] = trade.get("morph_count", 0) + 1
        from_type = action.get("from_type", "NEUTRAL")
        to_type = action.get("to_type", "NEUTRAL")
        legs = action.get("legs", trade.get("legs", []))

        # ── Scenario 1: BULLISH → NEUTRAL (Add CALL_SPREAD) ──
        if from_type == "BULLISH" and to_type == "NEUTRAL":
            atm = _get_atm_from_legs(legs)
            expiry = trade.get("expiry", "")
            if atm > 0 and expiry:
                # Add SELL CE and BUY CE (protection)
                sell_ce_fill = 40.0  # Estimate
                buy_ce_fill = 30.0
                trade["legs"].extend([
                    {
                        "action": "SELL",
                        "strike": atm,
                        "type": "CE",
                        "fill_price": sell_ce_fill,
                        "tsym": f"NIFTY{expiry.replace('-', '')}{atm}C",
                    },
                    {
                        "action": "BUY",
                        "strike": atm + WING_BUTTERFLY,
                        "type": "CE",
                        "fill_price": buy_ce_fill,
                        "tsym": f"NIFTY{expiry.replace('-', '')}{atm + WING_BUTTERFLY}C",
                    },
                ])
                trade["sl"]["ce"] = round(sell_ce_fill * (1 + SL_PCT), 2)
                trade["tp"]["ce"] = round(sell_ce_fill * (1 - TP_PCT), 2)

        # ── Scenario 2: BEARISH → NEUTRAL (Add PUT_SPREAD) ──
        elif from_type == "BEARISH" and to_type == "NEUTRAL":
            atm = _get_atm_from_legs(legs)
            expiry = trade.get("expiry", "")
            if atm > 0 and expiry:
                # Add SELL PE and BUY PE (protection)
                sell_pe_fill = 40.0
                buy_pe_fill = 30.0
                trade["legs"].extend([
                    {
                        "action": "SELL",
                        "strike": atm,
                        "type": "PE",
                        "fill_price": sell_pe_fill,
                        "tsym": f"NIFTY{expiry.replace('-', '')}{atm}P",
                    },
                    {
                        "action": "BUY",
                        "strike": atm - WING_BUTTERFLY,
                        "type": "PE",
                        "fill_price": buy_pe_fill,
                        "tsym": f"NIFTY{expiry.replace('-', '')}{atm - WING_BUTTERFLY}P",
                    },
                ])
                trade["sl"]["pe"] = round(sell_pe_fill * (1 + SL_PCT), 2)
                trade["tp"]["pe"] = round(sell_pe_fill * (1 - TP_PCT), 2)

        # ── Scenario 3: NEUTRAL → BULLISH (Close CALL_SPREAD, keep PUT) ──
        elif from_type == "NEUTRAL" and to_type == "BULLISH":
            # Close CE legs (both SELL and BUY)
            ce_legs = [l for l in trade.get("legs", []) if l["type"] == "CE"]
            pnl_ce = 0
            for leg in ce_legs:
                # Get current LTP (estimate from fill price if not available)
                ltp = leg.get("ltp", leg.get("fill_price", 0))
                if leg["action"] == "SELL":
                    pnl_ce += leg["fill_price"] - ltp
                else:
                    pnl_ce += ltp - leg["fill_price"]
            trade["cumulative_pnl"] += pnl_ce
            # Remove CE legs
            trade["legs"] = [l for l in trade.get("legs", []) if l["type"] != "CE"]
            # Clear CE SL/TP
            trade["sl"]["ce"] = None
            trade["tp"]["ce"] = None

        # ── Scenario 4: NEUTRAL → BEARISH (Close PUT_SPREAD, keep CALL) ──
        elif from_type == "NEUTRAL" and to_type == "BEARISH":
            # Close PE legs (both SELL and BUY)
            pe_legs = [l for l in trade.get("legs", []) if l["type"] == "PE"]
            pnl_pe = 0
            for leg in pe_legs:
                ltp = leg.get("ltp", leg.get("fill_price", 0))
                if leg["action"] == "SELL":
                    pnl_pe += leg["fill_price"] - ltp
                else:
                    pnl_pe += ltp - leg["fill_price"]
            trade["cumulative_pnl"] += pnl_pe
            # Remove PE legs
            trade["legs"] = [l for l in trade.get("legs", []) if l["type"] != "PE"]
            # Clear PE SL/TP
            trade["sl"]["pe"] = None
            trade["tp"]["pe"] = None

        # ── Scenario 5: BULLISH → BEARISH (Close PUT, add CALL) ──
        elif from_type == "BULLISH" and to_type == "BEARISH":
            # Close PE legs
            pe_legs = [l for l in trade.get("legs", []) if l["type"] == "PE"]
            pnl_pe = 0
            for leg in pe_legs:
                ltp = leg.get("ltp", leg.get("fill_price", 0))
                if leg["action"] == "SELL":
                    pnl_pe += leg["fill_price"] - ltp
                else:
                    pnl_pe += ltp - leg["fill_price"]
            trade["cumulative_pnl"] += pnl_pe
            trade["legs"] = [l for l in trade.get("legs", []) if l["type"] != "PE"]
            trade["sl"]["pe"] = None
            trade["tp"]["pe"] = None

            # Add CALL_SPREAD
            atm = _get_atm_from_legs(legs)
            expiry = trade.get("expiry", "")
            if atm > 0 and expiry:
                trade["legs"].extend([
                    {
                        "action": "SELL",
                        "strike": atm,
                        "type": "CE",
                        "fill_price": 40.0,
                        "tsym": f"NIFTY{expiry.replace('-', '')}{atm}C",
                    },
                    {
                        "action": "BUY",
                        "strike": atm + WING_SPREAD,
                        "type": "CE",
                        "fill_price": 30.0,
                        "tsym": f"NIFTY{expiry.replace('-', '')}{atm + WING_SPREAD}C",
                    },
                ])
                trade["sl"]["ce"] = round(40.0 * (1 + SL_PCT), 2)
                trade["tp"]["ce"] = round(40.0 * (1 - TP_PCT), 2)

        # ── Scenario 6: BEARISH → BULLISH (Close CALL, add PUT) ──
        elif from_type == "BEARISH" and to_type == "BULLISH":
            # Close CE legs
            ce_legs = [l for l in trade.get("legs", []) if l["type"] == "CE"]
            pnl_ce = 0
            for leg in ce_legs:
                ltp = leg.get("ltp", leg.get("fill_price", 0))
                if leg["action"] == "SELL":
                    pnl_ce += leg["fill_price"] - ltp
                else:
                    pnl_ce += ltp - leg["fill_price"]
            trade["cumulative_pnl"] += pnl_ce
            trade["legs"] = [l for l in trade.get("legs", []) if l["type"] != "CE"]
            trade["sl"]["ce"] = None
            trade["tp"]["ce"] = None

            # Add PUT_SPREAD
            atm = _get_atm_from_legs(legs)
            expiry = trade.get("expiry", "")
            if atm > 0 and expiry:
                trade["legs"].extend([
                    {
                        "action": "SELL",
                        "strike": atm,
                        "type": "PE",
                        "fill_price": 40.0,
                        "tsym": f"NIFTY{expiry.replace('-', '')}{atm}P",
                    },
                    {
                        "action": "BUY",
                        "strike": atm - WING_SPREAD,
                        "type": "PE",
                        "fill_price": 30.0,
                        "tsym": f"NIFTY{expiry.replace('-', '')}{atm - WING_SPREAD}P",
                    },
                ])
                trade["sl"]["pe"] = round(40.0 * (1 + SL_PCT), 2)
                trade["tp"]["pe"] = round(40.0 * (1 - TP_PCT), 2)

    return trade


def _get_atm_from_legs(legs: list) -> int:
    """Extract ATM strike from legs (all legs at ATM have same strike for sold legs)."""
    sold_legs = [l for l in legs if l.get("action") == "SELL"]
    if sold_legs:
        return sold_legs[0].get("strike", 0)
    return 0


if __name__ == "__main__":
    # Quick test
    import sys

    sys.path.insert(0, str(Path(__file__).parent))
    from kickoff import load_state

    state = load_state()
    t = state.get("active_trade")
    if t:
        actions = run(t)
        print(f"\nPosition Manager ({len(actions)} actions):")
        for a in actions:
            print(f"  P{a['priority']}: {a['type']:12s} — {a['reason']}")
    else:
        print("No active trade")
