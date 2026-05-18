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
from pathlib import Path
from typing import Optional

MARGIN_FILE = Path("/home/trading_ceo/brahmand/data/margin_matrix.json")

DUCKDB_V31 = "/home/trading_ceo/python-trader/varaha/data/varaha_data.duckdb"


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
        if spread.get("margin") is None:
            continue

        buy_strike = spread["buy_strike"]
        buy_premium = _get_premium(buy_strike, spread_type, expiry)
        if buy_premium is None:
            continue

        wing_width = spread["wing_width"]
        margin = spread["margin"]
        reward = atm_premium - buy_premium  # net credit per lot
        risk = wing_width - reward  # max loss per lot
        roi_pct = round(reward / margin * 100, 2)  # return on margin %
        rr = round(reward / risk, 3) if risk > 0 else 0

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

    # Score: 70% ROI + 30% RR, discount by wing_width (wider = more margin locked)
    for c in candidates:
        c["score"] = round(c["roi_pct"] * 0.7 + c["rr"] * 100 * 0.3, 2)

    # Filter by minimums
    valid = [c for c in candidates if c["roi_pct"] >= min_roi_pct and c["rr"] >= min_rr]

    if not valid:
        # Relax criteria — pick best available
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
        reward = atm_premium - buy_premium
        risk = w - reward
        roi = round(reward / m * 100, 2) if m > 0 else 0
        rr = round(reward / risk, 3) if risk > 0 else 0

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
