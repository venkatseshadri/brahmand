#!/usr/bin/env python3
"""
Wing Width Optimizer — selects best strike spread based on risk/reward.

Reads:
  - brahmand/data/margin_matrix.json  (span margins from Shoonya)
  - DuckDB option_snapshots            (real premium data)
Computes:
  - Reward = premium_sell - premium_buy   (net credit per lot)
  - Risk = wing_width - (premium_sell - premium_buy)  (max loss per lot)
  - ROI = Reward / Margin  (return on margin)
  - RR = Reward / Risk     (risk-to-reward ratio)

Usage:
  from wing_optimizer import get_optimal_wing
  best = get_optimal_wing("PE", atm=25000)
  # {strike: 24700, wing_width: 300, margin: 85000, reward: 75, risk: 225, roi_pct: 8.8, rr: 0.33}
"""

import json
import os
import time
import logging
from pathlib import Path
from typing import Optional
from datetime import datetime, timedelta

MARGIN_FILE = Path("/home/trading_ceo/brahmand/data/margin_matrix.json")
DUCKDB_V31 = "/home/trading_ceo/python-trader/varaha/data/varaha_data.duckdb"

logger = logging.getLogger("WingOptimizer")


def _check_margin_freshness(max_age_minutes: int = 60) -> tuple[bool, str]:
    """Check if margin_matrix.json is fresh (not stale from yesterday)."""
    if not MARGIN_FILE.exists():
        return False, "margin_matrix.json not found"

    # Check file timestamp
    mtime = MARGIN_FILE.stat().st_mtime
    age_min = (time.time() - mtime) / 60
    if age_min > max_age_minutes:
        return False, f"margin_matrix.json is {age_min:.0f}min old (stale)"

    # Check JSON timestamp field
    try:
        data = json.loads(MARGIN_FILE.read_text())
        if "timestamp" not in data:
            return False, "margin_matrix.json missing timestamp field"
        ts_str = data["timestamp"]
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        age_sec = (datetime.now(ts.tzinfo) - ts).total_seconds() / 60
        if age_sec > max_age_minutes:
            return False, f"margin data is {age_sec:.0f}min old"
        return True, f"margin data is {age_sec:.0f}min old ✓"
    except Exception as e:
        return False, f"timestamp parse error: {e}"


def _check_premium_freshness(strike: int, otype: str, expiry: str, max_age_sec: int = 300) -> Optional[float]:
    """Get premium only if data is fresh (< max_age_sec old)."""
    try:
        import duckdb

        db = duckdb.connect(DUCKDB_V31, read_only=True)
        row = db.execute(
            "SELECT ltp, timestamp FROM option_snapshots "
            "WHERE strike = ? AND option_type = ? AND expiry_date = ? "
            "AND tsym IS NOT NULL ORDER BY timestamp DESC LIMIT 1",
            (strike, otype, expiry),
        ).fetchone()
        db.close()

        if not row:
            return None

        ltp, ts_str = row
        # Check if data is fresh
        ts = datetime.fromisoformat(ts_str)
        age_sec = (datetime.now() - ts).total_seconds()
        if age_sec > max_age_sec:
            logger.warning(f"Premium data too stale for {strike}{otype}: {age_sec:.0f}s old")
            return None
        return float(ltp)
    except Exception:
        return None


def _get_premium(strike: int, otype: str, expiry: str) -> Optional[float]:
    """Get latest option premium from DuckDB option_snapshots."""
    try:
        import duckdb

        db = duckdb.connect(DUCKDB_V31, read_only=True)
        row = db.execute(
            "SELECT ltp FROM option_snapshots "
            "WHERE strike = ? AND option_type = ? AND expiry_date = ? "
            "AND tsym IS NOT NULL ORDER BY timestamp DESC LIMIT 1",
            (strike, otype, expiry),
        ).fetchone()
        db.close()
        return float(row[0]) if row else None
    except Exception:
        return None


def get_optimal_wing(
    spread_type: str,  # "PE" or "CE"
    atm: int,  # ATM strike
    expiry: str,  # Expiry date
    min_roi_pct: float = 5.0,  # Minimum ROI % to consider
    min_rr: float = 0.2,  # Minimum risk/reward ratio
) -> Optional[dict]:
    """
    Find the optimal wing width for a credit spread.
    Balances margin efficiency, risk/reward, and premium capture.

    Returns best spread dict or None if no spread meets criteria.
    """
    if not MARGIN_FILE.exists():
        return None

    margins = json.loads(MARGIN_FILE.read_text())
    atm_premium = _get_premium(atm, spread_type, expiry)

    if atm_premium is None:
        return None

    candidates = []
    for spread in margins.get("spreads", []):
        if spread["type"] != spread_type:
            continue
        if spread.get("margin") is None or spread.get("margin") <= 0:
            continue  # Skip zero/negative margin

        buy_strike = spread["buy_strike"]
        buy_premium = _check_premium_freshness(buy_strike, spread_type, expiry, max_age_sec=300)
        if buy_premium is None:
            continue

        wing_width = spread["wing_width"]
        margin = spread["margin"]

        # Per-lot calculations (NIFTY lot = 65)
        lot = 65
        net_credit_ps = atm_premium - buy_premium  # per share

        # Skip if no credit (or loss on entry)
        if net_credit_ps <= 0:
            continue  # Won't trade a debit spread

        # Skip if risk is inverted/negative
        if wing_width <= net_credit_ps:
            continue  # Risk would be zero or negative

        reward = net_credit_ps * lot  # max gain per lot
        risk = (wing_width - net_credit_ps) * lot  # max loss per lot

        # Safe division for ROI
        roi_pct = round(reward / margin * 100, 2) if margin > 0 else 0
        rr = round(net_credit_ps / (wing_width - net_credit_ps), 3)

        candidates.append(
            {
                "type": spread_type,
                "sell_strike": atm,
                "buy_strike": buy_strike,
                "wing_width": wing_width,
                "margin": margin,
                "sell_premium": atm_premium,
                "buy_premium": buy_premium,
                "reward": round(reward, 2),
                "risk": round(risk, 2),
                "roi_pct": roi_pct,
                "rr": rr,
            }
        )

    if not candidates:
        return None

    # Score: 70% ROI + 30% RR
    for c in candidates:
        c["score"] = round(c["roi_pct"] * 0.7 + c["rr"] * 100 * 0.3, 2)

    # Filter by minimums (strict criteria for live trading)
    valid = [c for c in candidates if c["roi_pct"] >= min_roi_pct and c["rr"] >= min_rr]

    if not valid:
        # No spreads meet criteria — log warning but still pick best
        import logging
        logger = logging.getLogger("WingOptimizer")
        best_avail = max(candidates, key=lambda c: c["score"])
        logger.warning(
            f"⚠️  No {spread_type} spreads meet criteria (ROI>={min_roi_pct}%, RR>={min_rr}). "
            f"Selecting best available: wing={best_avail['wing_width']}pt, "
            f"ROI={best_avail['roi_pct']}%, RR={best_avail['rr']}"
        )
        valid = candidates

    # Sort by score descending
    valid.sort(key=lambda c: c["score"], reverse=True)
    return valid[0]


def compare_wings(spread_type: str, atm: int, expiry: str) -> list[dict]:
    """Return all wing options with scoring for analysis."""
    if not MARGIN_FILE.exists():
        return []

    margins = json.loads(MARGIN_FILE.read_text())
    atm_premium = _get_premium(atm, spread_type, expiry)
    if atm_premium is None:
        return []

    candidates = []
    for spread in margins.get("spreads", []):
        if spread["type"] != spread_type:
            continue
        buy_premium = _get_premium(spread["buy_strike"], spread_type, expiry)
        if buy_premium is None or spread.get("margin") is None:
            continue

        w = spread["wing_width"]
        m = spread["margin"]
        lot = 65
        net_credit_ps = atm_premium - buy_premium
        reward = net_credit_ps * lot
        risk = (w - net_credit_ps) * lot
        roi = round(reward / m * 100, 2) if m > 0 else 0
        rr = round(net_credit_ps / (w - net_credit_ps), 3) if w > net_credit_ps else 0

        candidates.append(
            {
                "wing": w,
                "buy_strike": spread["buy_strike"],
                "margin": m,
                "reward": round(reward, 2),
                "risk": round(risk, 2),
                "roi_pct": roi,
                "rr": rr,
                "score": round(roi * 0.7 + rr * 100 * 0.3, 2),
            }
        )

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates


if __name__ == "__main__":
    import sys

    # Demo: compare all wing options
    from margin_capture import _get_atm, _get_expiry

    atm = _get_atm()
    exp = _get_expiry()
    print(f"ATM: {atm} | Expiry: {exp}")
    print()

    for otype in ("PE", "CE"):
        print(f"=== {otype} SPREADS ===")
        print(
            f"{'Wing':>5s} {'Margin':>10s} {'Reward':>8s} {'Risk':>8s} {'ROI%':>7s} {'R/R':>6s} {'Score':>6s}"
        )
        print("-" * 60)
        for c in compare_wings(otype, atm, exp):
            print(
                f"{c['wing']:>5d} ₹{c['margin']:>9,.0f} ₹{c['reward']:>7.1f} ₹{c['risk']:>7.1f} {c['roi_pct']:>6.1f}% {c['rr']:>5.2f} {c['score']:>6.1f}"
            )

        best = get_optimal_wing(otype, atm, exp)
        if best:
            print(
                f"\n  → OPTIMAL: {best['wing_width']}pt wing | ROI {best['roi_pct']}% | R/R {best['rr']} | Margin ₹{best['margin']:,.0f}"
            )
        print()
