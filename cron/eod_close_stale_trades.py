#!/usr/bin/env python3
"""EOD backstop — close trades left open at their session close.

Why this exists: a trade that doesn't hit SL/TP can linger open past the close
(run_bridge's EOD square-off + the CLOSED-terminal guard normally handle it, but
this backstops both), and a single lingering trade jams entry_setup's
single-position / MAX_TRADES guard, blocking every new entry. This job force-closes
any still-open trade for the named indices in BOTH stores so the next session
starts clean.

Closes BOTH ledgers (the JSON<->DuckDB split-brain means a trade can be open in one
and not the other): the DuckDB active_trades (the store get_active_trades / the
entry guard read) AND order_ledger.json. "Open" = any status that is not CLOSED
(ACTIVE, SL_TP_PLACED, CLOSING) — earlier this only matched status=="ACTIVE" in the
JSON store, so SL_TP_PLACED trades (the common case) slipped through.

Scoped by index so each market is cleaned at its OWN close:
  - NIFTY/SENSEX cash close 15:30  → cron 58 15 (--indices NIFTY SENSEX), AFTER the
    entry tail (kickoff runs to ~15:56) so late entries don't escape the cleanup.
  - MCX close ~23:30               → cron 35 23 (--indices MCX)  [only if MCX traded]
A trade is only touched if its legs identify it as one of the requested indices.
MCX (and any unidentifiable trade) is left alone by the equity job.

Paper-trading ledger backstop: it marks CLOSED (DuckDB: archive to trade_history +
status CLOSED; JSON: status CLOSED); it does not place square-off orders.

Usage: python3 eod_close_stale_trades.py [--indices NIFTY SENSEX] [--dry-run]
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

LEDGER = Path(__file__).resolve().parent.parent / "data" / "order_ledger.json"
KNOWN_INDICES = ("NIFTY", "SENSEX", "MCX")
# MCX index options trade under per-commodity symbols, not an "MCX" prefix.
MCX_PREFIXES = ("GOLD", "SILVER", "CRUDE", "NATGAS", "COPPER", "ZINC",
                "ALUMINI", "LEAD", "NICKEL")


def _underlying(trade: dict) -> str | None:
    for leg in trade.get("legs", []) or []:
        tsym = (leg.get("tsym") or "").upper()
        if tsym.startswith("NIFTY"):
            return "NIFTY"
        if tsym.startswith("SENSEX"):
            return "SENSEX"
        if any(tsym.startswith(p) for p in MCX_PREFIXES):
            return "MCX"
    return None


def _close_duckdb(want: set, stamp: str, tag: str, dry_run: bool) -> int:
    """Force-close still-open DuckDB trades (the store the entry guard reads).
    Archives to trade_history if not already there, then flips status to CLOSED.
    Idempotent: a trade already in history is just flipped (no duplicate insert)."""
    try:
        from trade_execution_db import get_active_trades, _connect
    except Exception as e:
        print(f"[{stamp}] eod_close[{tag}]: DuckDB unavailable ({e})")
        return 0

    open_trades = [t for t in get_active_trades() if _underlying(t) in want]
    if not open_trades:
        print(f"[{stamp}] eod_close[{tag}]: DuckDB — no open {tag} trades")
        return 0

    print(f"[{stamp}] eod_close[{tag}]: DuckDB — {len(open_trades)} open trade(s)"
          + (" (DRY-RUN)" if dry_run else ""))
    if dry_run:
        for t in open_trades:
            print(f"  WOULD CLOSE (duckdb): {t['trade_id']} [{_underlying(t)}] {t.get('status')}")
        return len(open_trades)

    with _connect() as conn:
        for t in open_trades:
            tid = t["trade_id"]
            exists = conn.execute(
                "SELECT 1 FROM trade_history WHERE trade_id = ?", [tid]
            ).fetchone()
            if not exists:
                conn.execute(
                    "INSERT INTO trade_history (trade_id, entry_time, close_time, "
                    "strategy, close_reason, entry_pnl, final_pnl, duration_mins, legs) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    [tid, t.get("entry_time"), now_iso(), t.get("strategy"),
                     f"EOD_AUTO_CLOSE_{_underlying(t)}", None, 0, 0,
                     json.dumps(t.get("legs", []))],
                )
            conn.execute(
                "UPDATE active_trades SET status='CLOSED' WHERE trade_id = ?", [tid]
            )
            print(f"  CLOSED (duckdb): {tid} [{_underlying(t)}]")
        conn.commit()
    return len(open_trades)


def now_iso() -> str:
    return datetime.now().isoformat()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--indices", nargs="+", default=["NIFTY", "SENSEX"],
                    choices=KNOWN_INDICES, help="which indices to close")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    want = set(args.indices)

    now = datetime.now()
    stamp = now.strftime("%Y-%m-%d %H:%M:%S")
    tag = "+".join(sorted(want))

    # 1) DuckDB ledger — the store the entry guard actually reads.
    _close_duckdb(want, stamp, tag, args.dry_run)

    # 2) JSON ledger (order_ledger.json) — keep the audit store consistent.
    if not LEDGER.exists():
        print(f"[{stamp}] eod_close[{tag}]: no ledger at {LEDGER}")
        return 0

    led = json.loads(LEDGER.read_text())
    trades = led.get("_trades", {})

    # Any non-CLOSED trade (ACTIVE, SL_TP_PLACED, CLOSING) whose legs identify it as
    # a requested index. Matching only "ACTIVE" before let SL_TP_PLACED trades — the
    # common case — slip through. Unidentifiable / other-index trades are left alone.
    to_close = [
        (tid, t) for tid, t in trades.items()
        if t.get("status") != "CLOSED" and _underlying(t) in want
    ]

    if not to_close:
        print(f"[{stamp}] eod_close[{tag}]: no ACTIVE {tag} trades — clean")
        return 0

    print(f"[{stamp}] eod_close[{tag}]: {len(to_close)} ACTIVE trade(s) to force-close"
          + (" (DRY-RUN)" if args.dry_run else ""))
    for tid, t in to_close:
        und = _underlying(t)
        print(f"  {'WOULD CLOSE' if args.dry_run else 'CLOSED'}: {tid} "
              f"[{und}] {t.get('strategy_type', '?')} entry={t.get('entry_time', '?')}")
        if not args.dry_run:
            t["status"] = "CLOSED"
            t["exit_reason"] = f"EOD_AUTO_CLOSE_{und}"
            t["exit_time"] = now.isoformat()

    if not args.dry_run:
        tmp = LEDGER.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(led, indent=2, default=str))
        os.replace(tmp, LEDGER)  # atomic
        print(f"[{stamp}] eod_close[{tag}]: ledger updated ({len(to_close)} closed)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
