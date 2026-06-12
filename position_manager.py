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
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv(str(Path(__file__).parent / ".env"))

from logger import get_logger, log_exception

_pm_log = get_logger("position_manager")

# ── Defaults (tune from observed data over days) ──
DECAY_PCT = 0.375  # 37.5% theta decay → roll trigger
HEDGE_GAP = 150  # pts from sold strike → tighten hedge
SL_PCT = 0.50  # 50% above entry → SL
TP_PCT = 0.50  # 50% below entry → TP
FLOOR = -500  # cumulative P&L floor
MAX_MORPHS = 3  # max morphs per day
WING_SPREAD = 150  # wing width for credit spreads
WING_DUAL = 200  # wing width for dual spread
MARKET_CLOSE = "15:30"

# Action types
ROLL = "ROLL"
TIGHTEN = "TIGHTEN"
MORPH = "MORPH"
CLOSE_SIDE = "CLOSE_SIDE"
CLOSE_ALL = "CLOSE_ALL"
NOTHING = "NOTHING"

from market_data import now_str


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
            # Sideways → dual spread regime, keep wider SL to avoid noise exits
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

    except Exception as e:
        _pm_log.debug("Pattern risk adjust skipped: %s", e)


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
                min(sold_strikes, key=lambda s: abs(s - ld["strike"])) if sold_strikes else None
            )
            if nearest_sold and abs(ld["strike"] - nearest_sold) > HEDGE_GAP:
                # Tighten: close old hedge, open new at NEAREST_SOLD ± WING_SPREAD
                otype = ld["type"]
                new_strike = (
                    nearest_sold - WING_SPREAD if otype == "PE" else nearest_sold + WING_SPREAD
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

        # ── P6: Cumulative floor (realized + live mark-to-market) ──
        realized = trade.get("cumulative_pnl", 0)
        unrealized = sum(
            (ld["fill"] - ld["ltp"]) if ld["action"] == "SELL" else (ld["ltp"] - ld["fill"])
            for ld in legs_data
            if ld["ltp"] > 0
        )
        cumulative = realized + unrealized
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
    has_pe = any(l["type"] == "PE" and l["action"] == "SELL" for l in trade.get("legs", []))
    has_ce = any(l["type"] == "CE" and l["action"] == "SELL" for l in trade.get("legs", []))
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


def _norm_close_reason(reason: str) -> str:
    """Map a free-text action reason to a trade_history.close_reason code."""
    r = (reason or "").upper()
    if "SL" in r:
        return "SL_HIT"
    if "TP" in r:
        return "TP_HIT"
    if "FLOOR" in r or "CUMULATIVE" in r:
        return "FLOOR"
    if "MARKET CLOSE" in r:
        return "MARKET_CLOSE"
    return "MANUAL"


def _read_live_ltp(tsym: str) -> float:
    """Read live LTP from SQLite option_prices table. Returns 0.0 if missing."""
    try:
        import sqlite3
        from antariksh.config.sqlite_schema import get_sqlite_capture_path

        db = get_sqlite_capture_path("NIFTY")
        if not db.exists():
            return 0.0
        conn = sqlite3.connect(str(db))
        row = conn.execute("SELECT ltp FROM option_prices WHERE tsym=?", (tsym,)).fetchone()
        conn.close()
        return float(row[0]) if row and row[0] else 0.0
    except Exception:
        return 0.0


def _square_off(legs: list, trade_id: str, reason: str) -> float:
    """Place EXIT (square-off) orders for each leg and return realized P&L (points).

    BUY-to-close shorts, SELL-to-close longs. In paper mode order_routing fills the
    mock order; in live mode it routes to the broker. P&L uses the live LTP when
    present, else the entry fill (so a missing tick books 0 rather than a phantom).
    """
    try:
        from order_routing import place_order
    except Exception:
        place_order = None
    pnl = 0.0
    for leg in legs:
        fill = leg.get("fill_price", leg.get("fill", 0)) or 0
        ltp = leg.get("ltp", fill) or 0
        # T23(f): stale fill guard — refuse phantom ₹0 when LTP is 0 or equals entry
        if ltp <= 0 or abs(ltp - fill) < 0.05:
            live = _read_live_ltp(leg.get("tsym", ""))
            if live > 0:
                ltp = live
            elif ltp <= 0:
                _pm_log.warning("Exit aborted: no live LTP for %s", leg.get("tsym"))
                return 0.0
        if leg.get("action") == "SELL":
            pnl += fill - ltp
            close_action = "BUY"
        else:
            pnl += ltp - fill
            close_action = "SELL"
        if place_order:
            try:
                place_order(
                    symbol=leg.get("tsym", ""),
                    action_type=close_action,
                    quantity=leg.get("quantity", 65),
                    price=ltp,
                    order_type="EXIT",
                    component="position_manager",
                    trade_id=trade_id,
                    reason=reason,
                )
            except Exception as e:
                _pm_log.warning("Order placement failed for %s: %s", leg.get("tsym", "?"), e)
    return pnl


def _close_in_db(trade_id: str, reason: str, trade: dict):
    """Mark the trade CLOSED in BOTH stores so the 5-min entry flow can re-enter.

    Writing only DuckDB (the old behaviour) left order_ledger.json._trades stuck
    ACTIVE, so entry_setup's single-position / MAX_TRADES guard blocked every new
    entry — the JSON<->DuckDB split-brain. Closes now propagate to both.
    """
    code = _norm_close_reason(reason)
    try:
        from trade_execution_db import close_trade

        close_trade(
            trade_id,
            close_reason=code,
            final_pnl=trade.get("cumulative_pnl"),
        )
    except Exception as e:
        log_exception(_pm_log, e, f"DuckDB close_trade failed for {trade_id}")

    # Write-through to order_ledger.json — the store entry_setup's guard reads.
    try:
        from datetime import datetime
        from order_routing import _load_ledger, _save_ledger

        led = _load_ledger()
        jt = led.get("_trades", {}).get(trade_id)
        if jt and jt.get("status") != "CLOSED":
            jt["status"] = "CLOSED"
            jt["exit_reason"] = code
            jt["exit_time"] = datetime.now().isoformat()
            _save_ledger(led)

            # DAMBUILDER T5 — persist outcome for research
            try:
                from antariksh.research.outcome_tables import (
                    write_trade_outcome as _wto,
                )

                _wto(
                    os.environ.get(
                        "CAPTURE_SQLITE",
                        "/home/trading_ceo/python-trader/varaha/data/capture_nifty.sqlite",
                    ),
                    {
                        "trade_id": trade_id,
                        "entry_time": jt.get("entry_time"),
                        "exit_time": jt.get("exit_time"),
                        "strategy": jt.get("strategy"),
                        "wing_width": jt.get("wing_width", trade.get("wing_width")),
                        "entry_pnl": jt.get("entry_pnl"),
                        "final_pnl": trade.get("cumulative_pnl"),
                        "duration_mins": jt.get("duration_mins"),
                        "close_reason": code,
                        "legs": jt.get("legs", []),
                    },
                )
            except Exception:
                _pm_log.debug("trade_outcomes write failed for %s", trade_id)
    except Exception as e:
        log_exception(_pm_log, e, f"JSON ledger close write-through failed for {trade_id}")


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
    trade_id = trade.get("trade_id", "?")

    if action["type"] == CLOSE_SIDE:
        side = action.get("side", "")
        side_legs = action.get("legs", [l for l in trade.get("legs", []) if l.get("type") == side])
        trade["cumulative_pnl"] += _square_off(
            side_legs, trade_id, action.get("reason", "CLOSE_SIDE")
        )
        trade["legs"] = [l for l in trade.get("legs", []) if l.get("type") != side]
        sk = side.lower()
        trade["sl"][sk] = None
        trade["tp"][sk] = None
        # No sold legs left → the position is flat, close it out fully.
        if not any(l.get("action") == "SELL" for l in trade["legs"]):
            _close_in_db(trade_id, action.get("reason", "CLOSE_SIDE"), trade)
        return trade

    if action["type"] == CLOSE_ALL:
        # Mark every leg to its live LTP first: _square_off books P&L from
        # leg['ltp'] (else the entry fill). EOD/floor CLOSE_ALL reaches here
        # straight from run_bridge with unmarked legs, so without this it booked
        # a phantom ₹0 on a deep-underwater position (the SL/TP path already
        # marks via _close_side).
        _mark_legs_to_ltp(trade.get("legs", []))
        trade["cumulative_pnl"] += _square_off(
            trade.get("legs", []), trade_id, action.get("reason", "CLOSE_ALL")
        )
        trade["legs"] = []
        trade["sl"] = {}
        trade["tp"] = {}
        _close_in_db(trade_id, action.get("reason", "CLOSE_ALL"), trade)
        return trade

    if action["type"] in (ROLL, TIGHTEN):
        leg = action["leg"]
        # Book P&L on closing leg
        pnl = leg["fill"] - leg["ltp"] if leg["action"] == "SELL" else leg["ltp"] - leg["fill"]
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
                trade["legs"].extend(
                    [
                        {
                            "action": "SELL",
                            "strike": atm,
                            "type": "CE",
                            "fill_price": sell_ce_fill,
                            "tsym": f"NIFTY{expiry.replace('-', '')}{atm}C",
                        },
                        {
                            "action": "BUY",
                            "strike": atm + WING_DUAL,
                            "type": "CE",
                            "fill_price": buy_ce_fill,
                            "tsym": f"NIFTY{expiry.replace('-', '')}{atm + WING_DUAL}C",
                        },
                    ]
                )
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
                trade["legs"].extend(
                    [
                        {
                            "action": "SELL",
                            "strike": atm,
                            "type": "PE",
                            "fill_price": sell_pe_fill,
                            "tsym": f"NIFTY{expiry.replace('-', '')}{atm}P",
                        },
                        {
                            "action": "BUY",
                            "strike": atm - WING_DUAL,
                            "type": "PE",
                            "fill_price": buy_pe_fill,
                            "tsym": f"NIFTY{expiry.replace('-', '')}{atm - WING_DUAL}P",
                        },
                    ]
                )
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
                trade["legs"].extend(
                    [
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
                    ]
                )
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
                trade["legs"].extend(
                    [
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
                    ]
                )
                trade["sl"]["pe"] = round(40.0 * (1 + SL_PCT), 2)
                trade["tp"]["pe"] = round(40.0 * (1 - TP_PCT), 2)

    return trade


def _get_atm_from_legs(legs: list) -> int:
    """Extract ATM strike from legs (all legs at ATM have same strike for sold legs)."""
    sold_legs = [l for l in legs if l.get("action") == "SELL"]
    if sold_legs:
        return sold_legs[0].get("strike", 0)
    return 0


# ── Bridge: Order Ledger → Risk Agent Crew ────────────────────────────────


def _ensure_sl_tp_orders(trade: dict, trade_id: str):
    """Fallback (LLM-down): place resting SL/TP for SELL legs if none exist yet.

    The LLM RISK agent is the PRIMARY placer and owner of SL/TP + exit strategy.
    This ONLY backstops it when the agent is unavailable. place_sl_tp_orders is
    idempotent, so this no-ops if the agent already placed them. Do NOT promote
    this to an unconditional/at-entry placement — see risk_agent_crew docstring.
    """
    try:
        from order_routing import place_sl_tp_orders

        sl_map = trade.get("sl", {}) or {}
        tp_map = trade.get("tp", {}) or {}
        legs_for_orders = []
        for leg in trade.get("legs", []):
            lt = leg.get("type", "").lower()
            leg2 = dict(leg)
            if leg.get("action") == "SELL":
                leg2["sl"] = sl_map.get(lt)
                leg2["tp"] = tp_map.get(lt)
            legs_for_orders.append(leg2)
        res = place_sl_tp_orders(trade_id, legs_for_orders)
        if res.get("total_orders"):
            _pm_log.info("Fallback SL/TP placed (LLM down): %s orders", res["total_orders"])
    except Exception as e:
        _pm_log.error("Fallback SL/TP placement failed: %s", e)


def _check_sl_tp(trade: dict) -> dict:
    """Deterministic SL/TP check before LLM dispatch.

    Reads live LTPs from SQLite option_prices (populated by penguin consumer).
    Returns action dict: {"action": "SL_HIT"|"TP_HIT", "leg": {...}, "mtm": X}
    or {"action": "ACTIVE", "mtm": X}
    """
    import sqlite3
    from antariksh.config.sqlite_schema import get_sqlite_capture_path

    db_path = get_sqlite_capture_path("NIFTY")
    if not db_path.exists():
        return {"action": "ACTIVE", "mtm": 0.0}

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    mtm = 0.0

    try:
        for leg in trade.get("legs", []):
            tsym = leg.get("tsym", "")
            fill_price = leg.get("fill_price", leg.get("fill", 0)) or 0
            action = leg.get("action", "")
            qty = leg.get("quantity", 65)
            sl = leg.get("sl")
            tp = leg.get("tp")

            row = conn.execute("SELECT ltp FROM option_prices WHERE tsym = ?", (tsym,)).fetchone()
            current_ltp = row["ltp"] if row else fill_price

            if action == "SELL":
                mtm += (fill_price - current_ltp) * qty
            else:
                mtm += (current_ltp - fill_price) * qty

            if action == "SELL":
                if sl is not None and current_ltp >= sl:
                    return {
                        "action": "SL_HIT",
                        "leg": dict(leg),
                        "ltp": current_ltp,
                        "sl": sl,
                        "mtm": round(mtm, 2),
                    }
                if tp is not None and current_ltp <= tp:
                    return {
                        "action": "TP_HIT",
                        "leg": dict(leg),
                        "ltp": current_ltp,
                        "tp": tp,
                        "mtm": round(mtm, 2),
                    }
    finally:
        conn.close()

    return {"action": "ACTIVE", "mtm": round(mtm, 2)}


def _mark_legs_to_ltp(legs: list) -> None:
    """Set each leg's live 'ltp' from SQLite option_prices (same source as
    _check_sl_tp), so square-off books real P&L instead of the entry fill."""
    import sqlite3

    try:
        from antariksh.config.sqlite_schema import get_sqlite_capture_path

        db_path = get_sqlite_capture_path("NIFTY")
    except Exception:
        return
    if not db_path.exists():
        return
    conn = sqlite3.connect(str(db_path))
    try:
        for leg in legs:
            row = conn.execute(
                "SELECT ltp FROM option_prices WHERE tsym = ?", (leg.get("tsym", ""),)
            ).fetchone()
            if row and row[0] is not None:
                leg["ltp"] = float(row[0])
    finally:
        conn.close()


def _close_side(trade: dict, side: str) -> dict:
    """Square off one side (CE/PE) on an SL/TP hit, booking real P&L, and close
    the trade in both stores if no short legs remain.

    Was referenced by run_bridge() but never defined — every SL_HIT/TP_HIT raised
    NameError, so the intraday SL/TP exit never completed. Marks the side's legs to
    live LTP, then delegates to the existing CLOSE_SIDE action (square-off + persist).
    """
    side_legs = [l for l in trade.get("legs", []) if l.get("type") == side]
    _mark_legs_to_ltp(side_legs)
    return execute_action(
        {"type": CLOSE_SIDE, "side": side, "legs": side_legs, "reason": "SL_TP_EXIT"},
        trade,
    )


def _discretionary_actions(trade: dict, trade_id: str, mtm: float) -> list:
    """Return the DISCRETIONARY (morph/roll/tighten) actions for this cycle.

    Prefer the cached position-research assessment (fresh + signature-matched);
    on a cache miss / material change / any error, fall back to a LIVE deterministic
    P1–P7 recompute (today's behaviour). Protective triggers (SL/TP/floor/EOD) are
    handled by run_bridge directly and are NOT routed through this path.
    Extracted from run_bridge so the cache HIT/MISS branch is unit-testable."""
    try:
        from position_research_cache import (
            load_assessment,
            compute_position_signature,
            cache_age_sec,
        )

        sig = compute_position_signature(trade, mtm=mtm)
        assessment = load_assessment(trade_id, signature=sig)
        if assessment is not None:
            age = cache_age_sec(trade_id) or 0
            _pm_log.info(
                "Research cache HIT (%ds): %s — %s",
                int(age),
                assessment.get("recommendation", "?"),
                str(assessment.get("reason", ""))[:80],
            )
            return assessment.get("actions", []) or []
        _pm_log.info("Research cache MISS/stale → live deterministic P1-P7")
        return run(trade)
    except Exception as e:
        _pm_log.warning("Research path failed: %s → live deterministic P1-P7", e)
        return run(trade)
    except Exception as e:
        print(f"  ⚠️  Research path failed: {e} → live deterministic P1-P7")
        return run(trade)


def run_bridge():
    """Read active trades from order_ledger (DuckDB), dispatch to risk_agent_crew.

    This is the entry point for the 1-min cron. It replaces the old kickoff-driven
    monitoring loop. The CrewAI risk agent (LLM) decides morph/roll/SL/TP/exit.
    When LLM is unavailable, falls back to deterministic P1-P7.
    """
    import sys

    sys.path.insert(0, str(Path(__file__).parent))

    try:
        from trade_execution_db import (
            get_active_trades as ledger_get_active,
            update_active_trade,
            log_monitor_action,
        )

        trades = ledger_get_active()
    except Exception as e:
        _pm_log.error("Ledger read failed: %s", e)
        return

    if not trades:
        return  # No active trades — silent

    for trade in trades:
        trade_id = trade.get("trade_id", "?")
        _pm_log.info("Evaluating trade %s (%s)", trade_id, trade.get("strategy", "?"))

        # ── Deterministic EOD square-off (hard rule, NOT LLM discretion) ──
        # Index positions must be flat by the cash close. This is the operational
        # close-out; the LLM still owns all discretionary intraday exits. Restores
        # the MARKET_CLOSE rule that was stranded in the dead run() path, so trades
        # no longer carry over ACTIVE (and a post-close entry is squared off next
        # minute). MARKET_CLOSE=15:30 is correct for the only traded indices
        # (NIFTY/SENSEX); make it per-index if MCX trading is ever added.
        if now_str() >= MARKET_CLOSE:
            _pm_log.warning("EOD %s → square-off CLOSE_ALL", MARKET_CLOSE)
            execute_action({"type": CLOSE_ALL, "reason": f"Market close ({MARKET_CLOSE})"}, trade)
            continue

        # ── DETERMINISTIC SL/TP CHECK (reads SQLite option_prices) ─────────
        sl_result = _check_sl_tp(trade)
        trade["last_mtm"] = sl_result.get("mtm", 0)
        if sl_result["action"] in ("SL_HIT", "TP_HIT"):
            leg = sl_result["leg"]
            _pm_log.warning(
                "%s: %s ltp=%.2f mtm=%.2f",
                sl_result["action"],
                leg["tsym"],
                sl_result["ltp"],
                sl_result["mtm"],
            )
            if sl_result["action"] == "SL_HIT":
                execute_action({"type": "SL_HIT", "leg": leg, "pnl": sl_result["mtm"]}, trade)
                _close_side(trade, leg["type"])
            else:
                execute_action({"type": "TP_HIT", "leg": leg, "pnl": sl_result["mtm"]}, trade)
                _close_side(trade, leg["type"])
            continue  # Skip LLM — SL/TP is arithmetic

        _pm_log.info("MTM = %.2f (ACTIVE)", sl_result["mtm"])

        # ── PROTECTIVE: cumulative P&L floor (P6), live every cycle, NEVER cached ──
        # SL/TP (P4/P5) and EOD (P7) are already handled above; the floor is the
        # remaining protective trigger, so evaluate it live here before any cached
        # discretionary action — same formula as run()'s P6 (realized + unrealized).
        cumulative = trade.get("cumulative_pnl", 0) + sl_result["mtm"]
        if cumulative <= FLOOR:
            _pm_log.warning("P&L floor hit: cumulative ₹%.0f ≤ ₹%d → CLOSE ALL", cumulative, FLOOR)
            execute_action(
                {
                    "type": CLOSE_ALL,
                    "reason": f"Cumulative P&L ₹{cumulative:.0f} ≤ floor ₹{FLOOR}",
                },
                trade,
            )
            continue

        # ── DISCRETIONARY: cached position research (morph/roll/tighten — P1–P3) ──
        # The slow research cron (position_research.py, every 15 min) caches a
        # per-trade assessment; here we apply it in sub-second time. This is the
        # UNICORN entry pattern (cached LLM research → fast deterministic apply)
        # ported to the position manager: the LLM (future) owns the discretionary
        # judgement; the hot path just executes it. Cache miss OR a material
        # change (signature) → live deterministic P1–P7 recompute (today's behaviour).
        actions = _discretionary_actions(trade, trade_id, sl_result["mtm"])

        # Discretionary research never places protective orders → always ensure
        # resting SL/TP exist (idempotent). Also covers the cache-HIT path.
        _ensure_sl_tp_orders(trade, trade_id)

        # Execute all actions and persist
        for action in actions:
            trade = execute_action(action, trade)
            # Log each morph/shift/TSL action to DuckDB
            try:
                log_monitor_action(
                    trade_id,
                    current_ltp={"ltp": action.get("ltp")},
                    current_pnl=trade.get("cumulative_pnl", 0),
                    action_taken=action.get("type", "monitor"),
                    note=json.dumps(action, default=str)[:500],
                )
            except Exception as e:
                _pm_log.debug("log_monitor_action failed for %s: %s", trade_id, e)

        if actions:
            _pm_log.info("%d actions executed", len(actions))
            # Persist modified trade (legs, SL/TP) to DuckDB
            try:
                update_active_trade(
                    trade_id,
                    legs=trade.get("legs"),
                    sl=trade.get("sl"),
                    tp=trade.get("tp"),
                )
            except Exception as e:
                _pm_log.error("Failed to persist trade %s: %s", trade_id, e)


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(Path(__file__).parent))

    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--bridge",
        action="store_true",
        help="Bridge mode: read ledger → dispatch to risk_agent_crew",
    )
    parser.add_argument(
        "--test", action="store_true", help="Test mode: run P1-P7 on kickoff JSON state"
    )
    args = parser.parse_args()

    if args.bridge:
        run_bridge()
    elif args.test:
        from state import load_state

        state = load_state()
        t = state.get("active_trade")
        if t:
            actions = run(t)
            _pm_log.info("Position Manager (%d actions):", len(actions))
            for a in actions:
                _pm_log.info("  P%d: %-12s — %s", a["priority"], a["type"], a["reason"])
        else:
            _pm_log.info("No active trade")
    else:
        run_bridge()  # Default: bridge mode
