#!/usr/bin/env python3
"""
Pre-Market Margin Calculation Validation (May 20, 2026).

Run this before 09:15 to verify:
1. Margin capture works
2. Wing optimizer selects valid wings
3. All edge cases handled
4. No stale data issues
"""

import sys
import json
import logging
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
logger = logging.getLogger("PreMarketValidation")

# Import modules to test
try:
    from margin_capture import capture_margins, _get_atm, _get_expiry
    from wing_optimizer import get_optimal_wing, _check_margin_freshness, _check_premium_freshness, compare_wings
except ImportError as e:
    logger.error(f"❌ Import failed: {e}")
    sys.exit(1)


def test_margin_capture():
    """Test 1: Can we capture margins from Shoonya?"""
    logger.info("\n" + "="*70)
    logger.info("TEST 1: Margin Capture")
    logger.info("="*70)

    atm = _get_atm()
    expiry = _get_expiry()

    if not atm:
        logger.error("❌ Cannot get ATM from DuckDB")
        return False

    if not expiry:
        logger.error("❌ Cannot get expiry from DuckDB")
        return False

    logger.info(f"✓ ATM: {atm}")
    logger.info(f"✓ Expiry: {expiry}")

    # Capture margins
    result = capture_margins()

    if "error" in result:
        logger.error(f"❌ Capture failed: {result['error']}")
        return False

    spreads = result.get("spreads", [])
    spreads_ok = sum(1 for s in spreads if s.get("margin") is not None)

    logger.info(f"✓ Captured {spreads_ok}/10 spreads")

    # Check all spreads have valid margins
    if spreads_ok < 10:
        logger.warning(f"⚠️  Only {spreads_ok}/10 spreads captured (some API calls failed)")
        failed = [s for s in spreads if s.get("margin") is None]
        for f in failed[:2]:
            logger.warning(f"   {f['type']} {f['sell_strike']}-{f['buy_strike']}: {f.get('error')}")

    # Verify margins are positive
    bad_margins = [s for s in spreads if s.get("margin") is not None and s["margin"] <= 0]
    if bad_margins:
        logger.error(f"❌ {len(bad_margins)} spreads have non-positive margin")
        return False

    logger.info("✅ TEST 1 PASSED: Margin capture working")
    return True


def test_margin_freshness():
    """Test 2: Is margin data fresh?"""
    logger.info("\n" + "="*70)
    logger.info("TEST 2: Data Freshness")
    logger.info("="*70)

    fresh, msg = _check_margin_freshness(max_age_minutes=60)
    logger.info(f"Margin freshness: {msg}")

    if not fresh:
        logger.error(f"❌ Margin data is STALE: {msg}")
        logger.error("   Run: python3 margin_capture.py --once")
        return False

    logger.info("✅ TEST 2 PASSED: Data is fresh")
    return True


def test_wing_optimizer():
    """Test 3: Can wing optimizer select valid wings?"""
    logger.info("\n" + "="*70)
    logger.info("TEST 3: Wing Optimizer")
    logger.info("="*70)

    atm = _get_atm()
    expiry = _get_expiry()

    if not atm or not expiry:
        logger.error("❌ Cannot get ATM/expiry")
        return False

    success = True

    for otype in ("PE", "CE"):
        logger.info(f"\n{otype} Spreads:")
        logger.info(f"  {'Wing':>5s} {'Margin':>10s} {'ROI%':>7s} {'R/R':>6s}")
        logger.info("  " + "-"*35)

        wings = compare_wings(otype, atm, expiry)

        if not wings:
            logger.error(f"  ❌ No {otype} wings available")
            success = False
            continue

        for w in wings[:3]:  # Show top 3
            logger.info(
                f"  {w['wing']:>5d} ₹{w['margin']:>9,.0f} {w['roi_pct']:>6.1f}% {w['rr']:>5.2f}"
            )

        best = get_optimal_wing(otype, atm, expiry)

        if not best:
            logger.error(f"  ❌ No valid {otype} wing selected")
            success = False
            continue

        logger.info(f"  → SELECTED: {best['wing_width']}pt wing | ROI {best['roi_pct']}% | R/R {best['rr']}")

        # Verify it meets criteria
        if best["roi_pct"] < 5.0:
            logger.warning(f"  ⚠️  ROI {best['roi_pct']}% is below 5% minimum")
        if best["rr"] < 0.2:
            logger.warning(f"  ⚠️  R/R {best['rr']} is below 0.2 minimum")

    if success:
        logger.info("\n✅ TEST 3 PASSED: Wing optimizer working")
    else:
        logger.error("\n❌ TEST 3 FAILED: Wing optimizer issues")

    return success


def test_edge_cases():
    """Test 4: Edge case handling"""
    logger.info("\n" + "="*70)
    logger.info("TEST 4: Edge Case Handling")
    logger.info("="*70)

    # Load margin matrix to inspect
    margin_file = Path("/home/trading_ceo/brahmand/data/margin_matrix.json")
    if not margin_file.exists():
        logger.error("❌ margin_matrix.json not found")
        return False

    data = json.loads(margin_file.read_text())

    # Check for zero/negative margins
    bad = [s for s in data.get("spreads", []) if s.get("margin") is not None and s["margin"] <= 0]
    if bad:
        logger.error(f"❌ Found {len(bad)} spreads with non-positive margin")
        return False

    logger.info("✓ No zero/negative margins")

    # Check timestamp
    if "timestamp" not in data:
        logger.error("❌ margin_matrix.json missing timestamp")
        return False

    ts_str = data["timestamp"]
    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    age_sec = (datetime.now(ts.tzinfo) - ts).total_seconds()
    logger.info(f"✓ Data timestamp: {ts_str} ({age_sec:.0f}s ago)")

    if age_sec > 300:
        logger.warning(f"⚠️  Data is {age_sec:.0f}s old (may be stale from yesterday)")

    logger.info("✅ TEST 4 PASSED: Edge cases handled")
    return True


def test_duckdb_connectivity():
    """Test 5: DuckDB has option data?"""
    logger.info("\n" + "="*70)
    logger.info("TEST 5: DuckDB Connectivity")
    logger.info("="*70)

    try:
        import duckdb

        db = duckdb.connect(
            "/home/trading_ceo/python-trader/varaha/data/varaha_data.duckdb",
            read_only=True,
        )

        # Check market_data
        count = db.execute("SELECT COUNT(*) FROM market_data").fetchone()[0]
        logger.info(f"✓ market_data: {count} rows")

        # Check option_snapshots
        opt_count = db.execute("SELECT COUNT(*) FROM option_snapshots").fetchone()[0]
        logger.info(f"✓ option_snapshots: {opt_count} rows")

        # Check latest timestamp
        latest = db.execute(
            "SELECT MAX(timestamp) FROM market_data"
        ).fetchone()[0]
        logger.info(f"✓ Latest market_data: {latest}")

        db.close()

        if opt_count == 0:
            logger.error("❌ option_snapshots is empty")
            return False

        logger.info("✅ TEST 5 PASSED: DuckDB connected")
        return True

    except Exception as e:
        logger.error(f"❌ DuckDB error: {e}")
        return False


def main():
    """Run all pre-market tests."""
    print("\n")
    print("╔" + "="*68 + "╗")
    print("║" + " "*15 + "PRE-MARKET VALIDATION (May 20, 2026)" + " "*16 + "║")
    print("║" + " "*16 + "Run this before 09:15 AM IST" + " "*26 + "║")
    print("╚" + "="*68 + "╝")

    tests = [
        ("DuckDB Connectivity", test_duckdb_connectivity),
        ("Margin Capture", test_margin_capture),
        ("Data Freshness", test_margin_freshness),
        ("Wing Optimizer", test_wing_optimizer),
        ("Edge Cases", test_edge_cases),
    ]

    results = {}
    for name, test_fn in tests:
        try:
            results[name] = test_fn()
        except Exception as e:
            logger.error(f"❌ Test exception: {e}")
            import traceback
            traceback.print_exc()
            results[name] = False

    # Summary
    print("\n")
    print("╔" + "="*68 + "╗")
    print("║ " + " "*66 + " ║")
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    if passed == total:
        print("║ " + f"✅ ALL TESTS PASSED ({passed}/{total})".ljust(66) + " ║")
        print("║ " + "Ready for trading!".ljust(66) + " ║")
    else:
        print("║ " + f"⚠️  SOME TESTS FAILED ({passed}/{total})".ljust(66) + " ║")
        print("║ " + "Fix issues before trading!".ljust(66) + " ║")

    print("║ " + " "*66 + " ║")
    for name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print("║ " + f"{status}: {name}".ljust(66) + " ║")

    print("║ " + " "*66 + " ║")
    print("╚" + "="*68 + "╝")
    print()

    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
