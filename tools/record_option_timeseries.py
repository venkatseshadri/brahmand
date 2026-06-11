#!/usr/bin/env python3
"""Record a live time-series of the NIFTY/SENSEX option feed + index feed from
Redis, for offline replay validation of the merged single-writer enricher.

Polls every INTERVAL seconds, appends one JSON line per poll, self-terminates at
15:30 IST (market close) or after MAX_HOURS. Writes into the recording dir whose
path is read from data/recordings/.latest.

Run (background):
    python3 tools/record_option_timeseries.py
"""
import json
import time
from datetime import datetime, time as dtime
from pathlib import Path

import redis

INTERVAL = 60  # seconds
MAX_HOURS = 6
ROOT = Path(__file__).resolve().parent.parent
latest = (ROOT / "data/recordings/.latest").read_text().strip()
OUT_DIR = ROOT / latest
OUT = OUT_DIR / "option_timeseries.jsonl"

r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
deadline = time.time() + MAX_HOURS * 3600
close_t = dtime(15, 30)

n = 0
with OUT.open("a") as f:
    while time.time() < deadline and datetime.now().time() < close_t:
        snap = {
            "ts": datetime.now().isoformat(),
            "nifty_feed": r.lrange("feed:NIFTY", 0, 5),  # list: newest bars
            "sensex_feed": r.lrange("feed:SENSEX", 0, 5),
            "nifty_options": r.hgetall("feed:NIFTY:options:ltp"),
            "sensex_options": r.hgetall("feed:SENSEX:options:ltp"),
            "nifty_window": r.get("feed:NIFTY:options:window"),
        }
        f.write(json.dumps(snap) + "\n")
        f.flush()
        n += 1
        time.sleep(INTERVAL)
print(f"recorded {n} option snapshots to {OUT}")
