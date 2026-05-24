"""
Isolated paper-lifecycle test. Redirects trade_execution.duckdb and order_ledger.json
to throwaway temp files — NO production state is touched. No live market data needed.

Proves (or breaks) three things:
  A. SL/TP placement (LLM-down fallback) + idempotency + position visibility
  B. Side-close invariant: PUT SL hit -> short PE *and* hedge PE both close, CE side intact,
     trade auto-closes only when flat, re-entry then allowed.
  C. CLOSE_ALL (floor / market-close) squares off everything and archives.

Run: python3 tests/e2e/test_paper_lifecycle.py
"""

import sys, tempfile, json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import trade_execution_db as tdb
import order_agent as oa

# ── Redirect ALL state to throwaway files ──
tmpdir = Path(tempfile.mkdtemp(prefix="paperlc_"))
tdb.DB_PATH = tmpdir / "trade_execution.duckdb"
tdb._LOCK_PATH = Path(str(tdb.DB_PATH) + ".lock")
oa.LEDGER_FILE = tmpdir / "order_ledger.json"

import position_manager as pm

print(f"sandbox: {tmpdir}\n")

PASS, FAIL = [], []
def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")

def attach_ltp(legs, sell_ltp, buy_ltp):
    out = []
    for l in legs:
        ld = dict(l)
        ld["ltp"] = sell_ltp if l["action"] == "SELL" else buy_ltp
        ld["fill"] = l["fill_price"]
        out.append(ld)
    return out

# ════════════════════════════════════════════════════════════════════
print("GROUP A — SL/TP placement + idempotency + visibility")
tA = "TEST-A-ENTRY"
legsA = [
    {"action":"SELL","type":"PE","strike":24500,"fill_price":80.0,"tsym":"A-PE-SELL","quantity":65},
    {"action":"BUY","type":"PE","strike":24300,"fill_price":40.0,"tsym":"A-PE-HEDGE","quantity":65},
]
tdb.add_active_trade(tA, "2026-05-25T09:30:00", "credit_spread", "NOT_DOWN",
                     legsA, {"pe":120.0}, {"pe":40.0})
check("entry lands as ACTIVE + visible", tdb.has_active_trades() is True)

legs_for_orders = []
for l in legsA:
    l2 = dict(l)
    if l["action"] == "SELL":
        l2["sl"] = 120.0; l2["tp"] = 40.0
    legs_for_orders.append(l2)
r1 = oa.place_sl_tp_orders(tA, legs_for_orders)
check("SL+TP placed for the short leg (2 orders)", r1["total_orders"] == 2)
r2 = oa.place_sl_tp_orders(tA, legs_for_orders)
check("place_sl_tp_orders idempotent (2nd call no-op)", r2.get("skipped") == "already_placed")
check("position STILL visible after SL/TP placed", tdb.has_active_trades() is True)

# clean A out of the way so later groups read cleanly
tdb.close_trade(tA, "MANUAL")

# ════════════════════════════════════════════════════════════════════
print("\nGROUP B — PUT SL hit closes short + hedge; flat only when both sides gone")
tB = "TEST-B-IRONFLY"
legsB = [
    {"action":"SELL","type":"PE","strike":24500,"fill_price":80.0,"tsym":"B-PE-SELL","quantity":65},
    {"action":"BUY","type":"PE","strike":24300,"fill_price":40.0,"tsym":"B-PE-HEDGE","quantity":65},
    {"action":"SELL","type":"CE","strike":24500,"fill_price":78.0,"tsym":"B-CE-SELL","quantity":65},
    {"action":"BUY","type":"CE","strike":24700,"fill_price":38.0,"tsym":"B-CE-HEDGE","quantity":65},
]
tdb.add_active_trade(tB, "2026-05-25T09:30:00", "iron_butterfly", "NEUTRAL",
                     legsB, {"pe":120.0,"ce":117.0}, {"pe":40.0,"ce":39.0})
trade = {"trade_id": tB, "legs": [dict(l) for l in legsB],
         "sl": {"pe":120.0,"ce":117.0}, "tp": {"pe":40.0,"ce":39.0}, "cumulative_pnl": 0}

# PUT SL: LTP of short PE rises above SL
action_pe_sl = {"type": pm.CLOSE_SIDE, "priority": 4, "side": "PE",
                "legs": attach_ltp([l for l in legsB if l["type"]=="PE"], 130.0, 20.0),
                "ltp": 130.0, "reason": "SL: PE24500 LTP=130 >= SL=120"}
trade = pm.execute_action(action_pe_sl, trade)

types_left = {l["type"] for l in trade["legs"]}
check("INVARIANT: no PE-side leg remains after PUT SL", "PE" not in types_left)
check("CE side intact (2 legs) after PUT SL", sum(1 for l in trade["legs"] if l["type"]=="CE") == 2)

ledger = json.loads(oa.LEDGER_FILE.read_text())
exits = {o["symbol"]: o["action_type"] for o in ledger["orders"].values() if o["order_type"]=="EXIT"}
check("EXIT order placed for short PE (BUY-to-close)", exits.get("B-PE-SELL") == "BUY")
check("EXIT order placed for HEDGE PE (SELL-to-close)", exits.get("B-PE-HEDGE") == "SELL")

tdb.update_active_trade(tB, legs=trade["legs"], sl=trade["sl"], tp=trade["tp"])
check("trade still ACTIVE after one-side close (CE open)", tdb.has_active_trades() is True)

# CALL TP: short CE LTP drops below TP -> now flat
action_ce_tp = {"type": pm.CLOSE_SIDE, "priority": 5, "side": "CE",
                "legs": attach_ltp([l for l in trade["legs"] if l["type"]=="CE"], 38.0, 60.0),
                "ltp": 38.0, "reason": "TP: CE24500 LTP=38 <= TP=39"}
trade = pm.execute_action(action_ce_tp, trade)
check("INVARIANT: zero legs remain after both sides closed", len(trade["legs"]) == 0)
check("flat position auto-closed (re-entry allowed)", tdb.has_active_trades() is False)

with tdb._connect() as con:
    hist = con.execute("SELECT close_reason FROM trade_history WHERE trade_id=?", [tB]).fetchall()
check("closed trade archived to history", len(hist) == 1)

# ════════════════════════════════════════════════════════════════════
print("\nGROUP C — CLOSE_ALL (floor / market-close) squares off everything")
tC = "TEST-C-FLOOR"
legsC = [
    {"action":"SELL","type":"PE","strike":24500,"fill_price":80.0,"tsym":"C-PE-SELL","quantity":65},
    {"action":"BUY","type":"PE","strike":24300,"fill_price":40.0,"tsym":"C-PE-HEDGE","quantity":65},
]
tdb.add_active_trade(tC, "2026-05-25T10:00:00", "credit_spread", "NOT_DOWN",
                     legsC, {"pe":120.0}, {"pe":40.0})
tradeC = {"trade_id": tC, "legs": attach_ltp(legsC, 150.0, 10.0),
          "sl": {"pe":120.0}, "tp": {"pe":40.0}, "cumulative_pnl": 0}
act_floor = {"type": pm.CLOSE_ALL, "priority": 6, "reason": "Cumulative P&L below floor"}
tradeC = pm.execute_action(act_floor, tradeC)
check("CLOSE_ALL removes all legs", len(tradeC["legs"]) == 0)
check("CLOSE_ALL archives + clears active", tdb.has_active_trades() is False)
with tdb._connect() as con:
    histc = con.execute("SELECT close_reason FROM trade_history WHERE trade_id=?", [tC]).fetchall()
check("CLOSE_ALL trade archived to history", len(histc) == 1)

# ════════════════════════════════════════════════════════════════════
print(f"\n==== RESULT: {len(PASS)} passed, {len(FAIL)} failed ====")
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL PAPER-LIFECYCLE CHECKS PASS")
