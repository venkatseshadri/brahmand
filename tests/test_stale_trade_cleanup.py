"""Regression: the stale-trade jam (trades stuck open → single-position entry guard
blocks every new entry).

Two root-cause fixes pinned here:
  1. CLOSED is TERMINAL — order_routing.update_trade_in_duckdb must NOT resurrect a
     closed trade back to SL_TP_PLACED (a stray place_sl_tp_orders after a close was
     doing exactly that → trade in trade_history AND status!=CLOSED forever).
  2. EOD cleanup closes the DuckDB ledger (not just JSON) and matches ANY non-CLOSED
     status (not just "ACTIVE") — SL_TP_PLACED was the common case that slipped through.

Uses a sandbox DuckDB under tests/ (BRAHMAND_SANDBOX) — no live data, no /tmp.

Run: python3 tests/test_stale_trade_cleanup.py   (from brahmand/)
"""
import os
import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
os.environ["BRAHMAND_SANDBOX"] = str(_HERE / "_tmp_stale_cleanup")
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE.parent / "cron"))

import trade_execution_db as tedb  # noqa: E402
from order_routing import update_trade_in_duckdb  # noqa: E402
import eod_close_stale_trades as eod  # noqa: E402


def _reset():
    tedb.init_db()
    with tedb._connect() as c:
        c.execute("DELETE FROM active_trades")
        c.execute("DELETE FROM trade_history")
        c.commit()


def _status(tid):
    with tedb._connect() as c:
        r = c.execute("SELECT status FROM active_trades WHERE trade_id=?", [tid]).fetchone()
    return r[0] if r else None


def _ck(name, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    return cond


def main():
    ok = True
    _reset()

    legs = [{"type": "CE", "action": "SELL", "tsym": "NIFTY25JUN23000CE", "strike": 23000}]
    tedb.add_active_trade("T1", datetime.now().isoformat(), "IRON_FLY", "NOT_DOWN", legs, {}, {})

    # placing SL/TP on an OPEN trade is allowed
    update_trade_in_duckdb("T1", status="SL_TP_PLACED")
    ok &= _ck("open trade → SL_TP_PLACED allowed", _status("T1") == "SL_TP_PLACED")

    # close it
    tedb.close_trade("T1", close_reason="SL_HIT", final_pnl=0)
    ok &= _ck("close_trade → CLOSED", _status("T1") == "CLOSED")

    # THE FIX: a stray status update must NOT resurrect a closed trade
    update_trade_in_duckdb("T1", status="SL_TP_PLACED")
    ok &= _ck("CLOSED is terminal — cannot be flipped back to SL_TP_PLACED",
              _status("T1") == "CLOSED")
    ok &= _ck("closed trade absent from get_active_trades",
              "T1" not in [t["trade_id"] for t in tedb.get_active_trades()])

    # ── cleanup hardening: closes a SL_TP_PLACED NIFTY trade in the DuckDB ledger ──
    _reset()
    tedb.add_active_trade("T2", datetime.now().isoformat(), "IRON_FLY", "NOT_DOWN", legs, {}, {})
    update_trade_in_duckdb("T2", status="SL_TP_PLACED")
    ok &= _ck("seed: T2 open as SL_TP_PLACED",
              "T2" in [t["trade_id"] for t in tedb.get_active_trades()])

    eod._close_duckdb({"NIFTY"}, "test", "NIFTY", dry_run=False)
    ok &= _ck("EOD cleanup closes SL_TP_PLACED NIFTY trade (DuckDB)",
              "T2" not in [t["trade_id"] for t in tedb.get_active_trades()])
    with tedb._connect() as c:
        archived = c.execute("SELECT 1 FROM trade_history WHERE trade_id='T2'").fetchone()
    ok &= _ck("cleanup archived T2 to trade_history", archived is not None)

    # MCX-style trade is left alone by the equity job (index scoping)
    _reset()
    mcx_legs = [{"type": "CE", "action": "SELL", "tsym": "CRUDE25JUN6000CE"}]
    tedb.add_active_trade("T3", datetime.now().isoformat(), "X", "NOT_DOWN", mcx_legs, {}, {})
    update_trade_in_duckdb("T3", status="SL_TP_PLACED")
    eod._close_duckdb({"NIFTY", "SENSEX"}, "test", "NIFTY+SENSEX", dry_run=False)
    ok &= _ck("equity cleanup leaves MCX trade untouched",
              "T3" in [t["trade_id"] for t in tedb.get_active_trades()])

    _reset()
    print(f"\n{'ALL PASS' if ok else 'FAILURES'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
