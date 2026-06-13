"""T23(f) regression: stale option_prices reads return newest + age-out refuse.

Inserts 3 rows same tsym (09:15/12:00/15:00), verifies:
  1. _live_ltp returns the NEWEST row (15:00 ltp=80)
  2. _live_ltp returns 0.0 when newest > max_age_sec old
  3. max_age_sec=0 suppresses staleness check
"""

import os
import sys
import sqlite3
import tempfile
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent  # /home/trading_ceo
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "brahmand"))


def test_newest_returned():
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, "capture_nifty.sqlite")
    conn = sqlite3.connect(db_path)
    conn.execute("""CREATE TABLE option_prices (
        timestamp TEXT, tsym TEXT, ltp REAL, instrument TEXT
    )""")
    tsym = "NIFTY16JUN26C24000"
    now = datetime(2026, 6, 16, 15, 0, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    inserts = [
        (now.replace(hour=9, minute=15).isoformat(), tsym, 100.0, "NIFTY"),
        (now.replace(hour=12, minute=0).isoformat(), tsym, 50.0, "NIFTY"),
        (now.replace(hour=15, minute=0).isoformat(), tsym, 80.0, "NIFTY"),
    ]
    conn.executemany("INSERT INTO option_prices VALUES(?,?,?,?)", inserts)
    conn.commit()
    conn.close()

    try:
        # Monkey-patch get_sqlite_capture_path to return tmp
        import antariksh.config.sqlite_schema as sc

        orig = sc.get_sqlite_capture_path
        sc.get_sqlite_capture_path = lambda _: Path(db_path)

        from order_routing import _live_ltp

        result = _live_ltp(tsym, max_age_sec=0)
        assert result == 80.0, f"Expected newest (80.0), got {result}"

        sc.get_sqlite_capture_path = orig
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return True


def test_stale_refuses():
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, "capture_nifty.sqlite")
    conn = sqlite3.connect(db_path)
    conn.execute("""CREATE TABLE option_prices (
        timestamp TEXT, tsym TEXT, ltp REAL, instrument TEXT
    )""")
    tsym = "NIFTY16JUN26C24000"
    # Only old row — 4 minutes ago
    old = (
        datetime.now(timezone(timedelta(hours=5, minutes=30))) - timedelta(minutes=4)
    ).isoformat()
    conn.execute("INSERT INTO option_prices VALUES(?,?,?,?)", (old, tsym, 50.0, "NIFTY"))
    conn.commit()
    conn.close()

    try:
        import antariksh.config.sqlite_schema as sc

        orig = sc.get_sqlite_capture_path
        sc.get_sqlite_capture_path = lambda _: Path(db_path)

        from order_routing import _live_ltp

        result = _live_ltp(tsym, max_age_sec=180.0)
        assert result == 0.0, f"Expected 0.0 (stale refuse), got {result}"

        # max_age_sec=0 suppresses staleness
        result2 = _live_ltp(tsym, max_age_sec=0)
        assert result2 == 50.0, f"Expected 50.0 (age check suppressed), got {result2}"

        sc.get_sqlite_capture_path = orig
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return True


if __name__ == "__main__":
    test_newest_returned()
    print("  PASS  test_newest_returned")
    test_stale_refuses()
    print("  PASS  test_stale_refuses")
    print("  T23(f) regression: ALL TESTS PASSED")
