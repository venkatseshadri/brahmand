#!/usr/bin/env python3
"""
Margin Capture — Shoonya Span Calculator every 5 min.

For each ATM ± N strikes (N=5), calculates margin required for:
  - PE spreads: SELL ATM PE + BUY (ATM-N) PE
  - CE spreads: SELL ATM CE + BUY (ATM+N) CE

Uses Shoonya span_calculator API. Caches to brahmand/data/margin_matrix.json.
The position manager reads this to select optimal wing width based on risk/reward.

Usage:
    python3 margin_capture.py              # run once, capture + exit
    python3 margin_capture.py --loop       # every 5 min (for cron)
    python3 margin_capture.py --once       # single capture
"""

import json
import os
import sys
import time
import logging
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional

sys.path.insert(0, str(Path("/home/trading_ceo/python-trader/Shoonya_oAuthAPI-py")))

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s"
)
logger = logging.getLogger("MarginCapture")

# ── Config ──
STRIKE_COUNT = 5  # Capture ATM ±5 strikes
STRIKE_STEP = 50  # NIFTY strike gap
LOT_SIZE = 50  # NIFTY lot size (paper: assume 100 qty for 2 lots)
DEFAULT_QTY = 50  # Per leg quantity for span calc
MARKET_CLOSE = "15:30"

# Output
MARGIN_FILE = Path("/home/trading_ceo/brahmand/data/margin_matrix.json")

CRED_FILE = Path("/home/trading_ceo/python-trader/Shoonya_oAuthAPI-py/cred.yml")
EXPIRY_FILE = Path("/home/trading_ceo/python-trader/orbiter/config/expiry_dates.json")


def _load_cred() -> dict:
    import yaml

    with open(CRED_FILE) as f:
        return yaml.safe_load(f)


def _get_expiry() -> str:
    """Get current weekly expiry from DuckDB or config."""
    try:
        import duckdb

        # Try DuckDB first
        db = duckdb.connect(
            "/home/trading_ceo/python-trader/varaha/data/varaha_data.duckdb",
            read_only=True,
        )
        row = db.execute(
            "SELECT expiry_weekly FROM market_data WHERE index_name='NIFTY' AND expiry_weekly IS NOT NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        db.close()
        if row:
            return str(row[0]).strip()
    except Exception:
        pass

    # Fallback: from config or manual
    if EXPIRY_FILE.exists():
        data = json.loads(EXPIRY_FILE.read_text())
        return data.get("weekly", "22-MAY-2026")
    return "22-MAY-2026"


def _get_atm() -> Optional[int]:
    """Get current ATM strike from DuckDB spot price."""
    try:
        import duckdb

        db = duckdb.connect(
            "/home/trading_ceo/python-trader/varaha/data/varaha_data.duckdb",
            read_only=True,
        )
        row = db.execute(
            "SELECT spot FROM market_data WHERE index_name='NIFTY' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        db.close()
        if row:
            spot = float(row[0])
            return round(spot / STRIKE_STEP) * STRIKE_STEP
    except Exception:
        pass
    return None


def _build_position(
    prd: str,
    exch: str,
    instname: str,
    symname: str,
    expiry: str,
    optt: str,
    strprc: str,
    buyqty: str,
    sellqty: str,
    netqty: str,
):
    """Build a position object for span_calculator."""
    from NorenRestApiPy.NorenApi import position

    p = position()
    p.prd = prd
    p.exch = exch
    p.instname = instname
    p.symname = symname
    p.exd = expiry
    p.optt = optt
    p.strprc = strprc
    p.buyqty = buyqty
    p.sellqty = sellqty
    p.netqty = netqty
    return p


def capture_margins() -> dict:
    """Capture margin matrix for all wing widths. Returns {atm, timestamp, spreads: [...]}."""
    cred = _load_cred()
    atm = _get_atm()
    expiry = _get_expiry()

    if not atm:
        logger.error("Cannot determine ATM — DuckDB empty?")
        return {"error": "no_atm", "timestamp": datetime.now().isoformat()}

    logger.info(f"ATM: {atm} | Expiry: {expiry}")

    # ── Auth ──
    from api_helper import NorenApiPy

    api = NorenApiPy()
    try:
        api.injectOAuthHeader(cred["Access_token"], cred["UID"], cred["Account_ID"])
    except Exception as e:
        logger.error(f"Auth failed: {e}")
        return {"error": "auth_failed", "timestamp": datetime.now().isoformat()}

    actid = cred["Account_ID"]
    results = {
        "atm": atm,
        "expiry": expiry,
        "timestamp": datetime.now().isoformat(),
        "strike_step": STRIKE_STEP,
        "lot_size": LOT_SIZE,
        "spreads": [],
    }

    # ── PE spreads: SELL ATM PE + BUY (ATM-N) PE for N=1..5 ──
    for offset in range(1, STRIKE_COUNT + 1):
        wing = atm - offset * STRIKE_STEP
        try:
            pos_list = [
                _build_position(
                    "H",
                    "NFO",
                    "OPTIDX",
                    "NIFTY",
                    expiry,
                    "PE",
                    str(atm),
                    "0",
                    str(DEFAULT_QTY),
                    str(-DEFAULT_QTY),
                ),
                _build_position(
                    "H",
                    "NFO",
                    "OPTIDX",
                    "NIFTY",
                    expiry,
                    "PE",
                    str(wing),
                    str(DEFAULT_QTY),
                    "0",
                    str(DEFAULT_QTY),
                ),
            ]
            resp = api.span_calculator(actid, pos_list)
            margin = _parse_margin(resp)
            results["spreads"].append(
                {
                    "type": "PE",
                    "sell_strike": atm,
                    "buy_strike": wing,
                    "wing_width": offset * STRIKE_STEP,
                    "margin": margin,
                }
            )
            logger.debug(f"  PE {atm}-{wing}: margin=₹{margin}")
        except Exception as e:
            logger.warning(f"  PE {atm}-{wing} failed: {e}")
            results["spreads"].append(
                {
                    "type": "PE",
                    "sell_strike": atm,
                    "buy_strike": wing,
                    "wing_width": offset * STRIKE_STEP,
                    "margin": None,
                    "error": str(e)[:100],
                }
            )

    # ── CE spreads: SELL ATM CE + BUY (ATM+N) CE for N=1..5 ──
    for offset in range(1, STRIKE_COUNT + 1):
        wing = atm + offset * STRIKE_STEP
        try:
            pos_list = [
                _build_position(
                    "H",
                    "NFO",
                    "OPTIDX",
                    "NIFTY",
                    expiry,
                    "CE",
                    str(atm),
                    "0",
                    str(DEFAULT_QTY),
                    str(-DEFAULT_QTY),
                ),
                _build_position(
                    "H",
                    "NFO",
                    "OPTIDX",
                    "NIFTY",
                    expiry,
                    "CE",
                    str(wing),
                    str(DEFAULT_QTY),
                    "0",
                    str(DEFAULT_QTY),
                ),
            ]
            resp = api.span_calculator(actid, pos_list)
            margin = _parse_margin(resp)
            results["spreads"].append(
                {
                    "type": "CE",
                    "sell_strike": atm,
                    "buy_strike": wing,
                    "wing_width": offset * STRIKE_STEP,
                    "margin": margin,
                }
            )
            logger.debug(f"  CE {atm}-{wing}: margin=₹{margin}")
        except Exception as e:
            logger.warning(f"  CE {atm}-{wing} failed: {e}")
            results["spreads"].append(
                {
                    "type": "CE",
                    "sell_strike": atm,
                    "buy_strike": wing,
                    "wing_width": offset * STRIKE_STEP,
                    "margin": None,
                    "error": str(e)[:100],
                }
            )

    # ── Save ──
    MARGIN_FILE.parent.mkdir(parents=True, exist_ok=True)
    MARGIN_FILE.write_text(json.dumps(results, indent=2, default=str))
    logger.info(f"Saved {len(results['spreads'])} spreads to {MARGIN_FILE}")

    return results


def _parse_margin(resp) -> Optional[float]:
    """Extract total margin from span_calculator response."""
    if not resp:
        return None
    if isinstance(resp, (int, float)):
        return float(resp)
    if isinstance(resp, dict):
        # Try common keys: margin, total_margin, span_margin, total
        for key in ("total", "totalmargin", "margin", "spanmargin"):
            if key in resp:
                return float(resp[key])
        # Nest: {'data': {'margin': ...}} or {'result': {...}}
        for sub in ("data", "result", "margin"):
            if sub in resp and isinstance(resp[sub], dict):
                return _parse_margin(resp[sub])
        # First float value
        for v in resp.values():
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    if isinstance(resp, list) and resp:
        return _parse_margin(resp[0])
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Margin Capture — Shoonya Span Calculator"
    )
    parser.add_argument(
        "--loop", action="store_true", help="Run every 5 min during market hours"
    )
    parser.add_argument("--once", action="store_true", help="Single capture and exit")
    args = parser.parse_args()

    if args.loop:
        logger.info("Margin capture loop started (every 5 min)")
        while True:
            now = datetime.now().strftime("%H:%M")
            if now <= MARKET_CLOSE:
                try:
                    capture_margins()
                except Exception as e:
                    logger.error(f"Capture failed: {e}")
            else:
                logger.info("Market closed — exiting loop")
                break
            time.sleep(300)
    else:
        res = capture_margins()
        print(json.dumps(res, indent=2, default=str))


if __name__ == "__main__":
    main()
