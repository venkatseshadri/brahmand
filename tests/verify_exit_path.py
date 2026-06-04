#!/usr/bin/env python3
"""
Verify the EXIT half of the lifecycle end-to-end, in SANDBOX mode.

Seeds a real ACTIVE paper trade (real option tsym + today's LTP) into the
sandbox trade store, then drives position_manager.run_bridge() and asserts the
trade is monitored, SL-exited with real P&L, and persisted CLOSED to both stores.

This is the path that has written 0 bytes every day because (a) entry was always
blocked so no trade existed, and (b) _close_side was undefined → SL/TP exit crashed.

Run (evening/market-closed is fine — uses today's hot option_prices):
    python3 tests/verify_exit_path.py
"""
import os
import sys
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SANDBOX = REPO / "data" / "verify_exit_sandbox"
(SANDBOX / "state").mkdir(parents=True, exist_ok=True)
(SANDBOX / "state" / "order_ledger.json").write_text(
    json.dumps({"orders": {}, "order_counter": 0, "_trades": {}})
)
os.environ["BRAHMAND_SANDBOX"] = str(SANDBOX)
sys.path.insert(0, str(REPO))
sys.path.insert(0, "/home/trading_ceo")  # so `antariksh.config...` imports

import sqlite3
CAP = "/home/trading_ceo/python-trader/varaha/data/capture_nifty.sqlite"
_c = sqlite3.connect(CAP)
_c.row_factory = sqlite3.Row
ce = _c.execute(
    "SELECT tsym,strike,ltp FROM option_prices WHERE option_type='CE' AND ltp>0 "
    "ORDER BY ltp DESC LIMIT 1"
).fetchone()
_c.close()
assert ce, "no CE option_prices row to test with"
ltp = float(ce["ltp"])
print(f"Real option leg: {ce['tsym']} strike={ce['strike']} live_ltp={ltp}")

# A SELL CE entered cheaper (0.6x) that has since risen to live ltp → a loss,
# with per-leg SL at 0.9x (BELOW live ltp) so the SL is already hit.
fill = round(ltp * 0.6, 2)
leg = {
    "action": "SELL", "type": "CE", "strike": int(ce["strike"]), "tsym": ce["tsym"],
    "fill_price": fill, "quantity": 75,
    "sl": round(ltp * 0.9, 2), "tp": round(ltp * 0.3, 2),
}
print(f"Seeded SELL CE: fill={fill} sl={leg['sl']} tp={leg['tp']} (live {ltp} >= sl → SL_HIT expected)")

import trade_execution_db as tdb
import position_manager as pm

tdb.init_db()
from datetime import datetime
# Unique id per run → no PK collision in active_trades / trade_history.
TID = "VERIFY-EXIT-" + datetime.now().strftime("%H%M%S")
entry_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
tdb.add_active_trade(TID, entry_ts, "IRON_FLY", "NOT_UP", [leg], {}, {})
# Mirror into the JSON ledger as the entry path does, to prove both stores close.
_lp = SANDBOX / "state" / "order_ledger.json"
_led = json.loads(_lp.read_text())
_led["_trades"][TID] = {"trade_id": TID, "status": "ACTIVE", "legs": [leg],
                        "entry_time": entry_ts, "sl": {}, "tp": {}}
_lp.write_text(json.dumps(_led, indent=2))

print("\n[1] get_active_trades() sees the seeded trade:")
act = tdb.get_active_trades()
print("   active:", [(t["trade_id"], t["status"]) for t in act])
assert any(t["trade_id"] == TID for t in act), "monitor would not see the trade!"

print("\n[2] _check_sl_tp() against real option_prices:")
res = pm._check_sl_tp(act[0])
print("   ->", {k: res.get(k) for k in ("action", "ltp", "sl", "mtm")})

print("\n[3] run_bridge() — drive the exit (bump MARKET_CLOSE so the SL/TP branch runs, not EOD):")
pm.MARKET_CLOSE = "23:59"
pm.run_bridge()

print("\n[4] post-conditions:")
act_after = tdb.get_active_trades()
print("   active after:", [(t["trade_id"], t["status"]) for t in act_after])
led = json.loads((SANDBOX / "state" / "order_ledger.json").read_text())
jstatus = led.get("_trades", {}).get(TID, {}).get("status")
print("   JSON ledger status:", jstatus)
with tdb._connect() as con:
    dstatus = con.execute(
        "SELECT status FROM active_trades WHERE trade_id = ?", [TID]
    ).fetchone()
    hist = con.execute(
        "SELECT close_reason, final_pnl FROM trade_history WHERE trade_id = ?", [TID]
    ).fetchone()
print("   DuckDB active_trades status:", dstatus and dstatus[0])
print("   DuckDB trade_history (reason, final_pnl):", hist)

ok = (
    not any(t["trade_id"] == TID for t in act_after)
    and res["action"] == "SL_HIT"
    and dstatus and dstatus[0] == "CLOSED"
    and jstatus == "CLOSED"
    and hist is not None
)
print("\n" + ("PASS ✅ exit path completes: ACTIVE → SL_HIT → CLOSED + P&L"
              if ok else "FAIL ❌ see above"))
