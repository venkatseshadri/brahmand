#!/usr/bin/env python3
"""
Verify the full UNICORN/PENGUIN entry path end-to-end, in SANDBOX mode.

Drives e2e_chain.run_full_chain() against today's live Penguin capture
(capture_nifty.sqlite) with BRAHMAND_SANDBOX set, so any paper order is written
to a sandbox ledger — NEVER the live data/order_ledger.json (avoids re-creating
the stale-trade poison pill).

Run (market closed is fine — the chain gates on snapshot freshness, not wall clock,
and today's capture is the freshest data):
    python3 tests/verify_entry_path.py
"""
import os
import sys
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CAPTURE_DIR = Path("/home/trading_ceo/projects/varaha/data")
SANDBOX = REPO / "data" / "verify_sandbox"
(SANDBOX / "state").mkdir(parents=True, exist_ok=True)
(SANDBOX / "state" / "order_ledger.json").write_text(
    json.dumps({"orders": {}, "order_counter": 0, "_trades": {}})
)
# BRAHMAND_SANDBOX makes market_data look for capture files IN the sandbox dir.
# Symlink the real (today's) capture so reads hit live data; only the ledger is sandboxed.
for fname in ("capture_nifty.sqlite", "market_data_multitf_nifty.duckdb"):
    link = SANDBOX / fname
    if link.exists() or link.is_symlink():
        link.unlink()
    src = CAPTURE_DIR / fname
    if src.exists():
        link.symlink_to(src)

# Must be set BEFORE importing order_routing (it resolves the path at import).
os.environ["BRAHMAND_SANDBOX"] = str(SANDBOX)
sys.path.insert(0, str(REPO))

from market_data import get_latest_market_snapshot, now_str  # noqa: E402

snap = get_latest_market_snapshot() or {}
print("=" * 60)
print("PENGUIN SNAPSHOT (today's capture):")
for k in ["date", "spot", "atm_strike", "india_vix", "adx", "rsi",
          "supertrend_direction", "expiry_weekly"]:
    print(f"  {k}: {snap.get(k)}")
print("=" * 60)

from e2e_chain import run_full_chain  # noqa: E402

entry_time = now_str()
print(f"Running full chain @ {entry_time} (sandbox={SANDBOX}) ...\n")
trade = run_full_chain(entry_time)

print("\n" + "=" * 60)
print("CHAIN RESULT:")
if trade is None:
    print("  → None (entry gate rejected / no signal). See chain log above for reason.")
else:
    print(json.dumps(trade, indent=2, default=str)[:2000])
print("=" * 60)

led = json.loads((SANDBOX / "state" / "order_ledger.json").read_text())
print("SANDBOX LEDGER _trades:", json.dumps(led.get("_trades", {}), indent=2, default=str)[:2000])
print("LIVE ledger untouched:", json.loads((REPO / "data" / "order_ledger.json").read_text()).get("_trades", {}))
