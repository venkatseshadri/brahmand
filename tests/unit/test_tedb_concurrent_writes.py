"""
Concurrency test for trade_execution_db: 3 processes hammer the same DuckDB file
through the flock+retry _connect() context manager. Uses a throwaway temp DB —
no production state touched.

Run: python3 tests/unit/test_tedb_concurrent_writes.py
"""

import sys, tempfile
from pathlib import Path
import multiprocessing as mp

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
import trade_execution_db as t

tmp = Path(tempfile.gettempdir()) / "tedb_locktest.duckdb"
for p in (tmp, Path(str(tmp) + ".lock"), Path(str(tmp) + ".wal")):
    if p.exists():
        p.unlink()
# point the module at the temp DB (inherited by forked children)
t.DB_PATH = tmp
t._LOCK_PATH = Path(str(tmp) + ".lock")


def worker(n):
    import trade_execution_db as t  # same module object under fork
    ok = 0
    for i in range(20):
        try:
            t.add_active_trade(
                f"T{n}-{i:02d}", "2026-05-25T09:30:00", "CALL_SPREAD",
                "NOT_UP", [{"strike": 24500, "type": "CE"}], {"ce": 1}, {"ce": 2},
            )
            t.has_active_trades()
            t.log_monitor_action(f"T{n}-{i:02d}", {"ce": 1.0}, 5.0, None, "tick")
            ok += 1
        except Exception as e:
            return (n, ok, f"FAIL: {type(e).__name__}: {e}")
    return (n, ok, "ok")


if __name__ == "__main__":
    t.init_db()
    procs = 3
    with mp.Pool(procs) as pool:
        results = pool.map(worker, range(procs))
    fails = [r for r in results if r[2] != "ok"]
    total_ok = sum(r[1] for r in results)
    rows = t.get_active_trades()
    print("results:", results)
    print(f"total successful write-cycles: {total_ok}/{procs * 20}")
    print(f"active_trades rows in DB: {len(rows)} (expect {procs * 20})")
    print("LOCK TEST:", "PASS" if not fails and len(rows) == procs * 20 else "FAIL")
