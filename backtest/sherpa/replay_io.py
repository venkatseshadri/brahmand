#!/usr/bin/env python3
"""SHERPA Phase 2 — replay I/O driver.

Feeds the REAL canonical_strategy scorers through their production I/O seams:
  - EMA state files   (score_trend_redis      ← BRAHMAND_EMA_DIR)
  - Redis bar queue   (get_live_candles       ← REPLAY=true + BRAHMAND_REPLAY_REDIS_DB)
  - prev_close key    (_get_gap_from_redis)
  - replay clock      (SHERPA_AS_OF)

No strategy logic is reimplemented here (PORCUPINE philosophy: inject at the
I/O seams only). Uses Redis db 9 — isolated from production db 0.
"""

import json
import os
from datetime import datetime
from pathlib import Path

import redis

EMA_PERIODS = [5, 20, 50, 100, 200]
REPLAY_REDIS_DB = 9


class ReplayIO:
    def __init__(self, sandbox: Path, index: str = "NIFTY"):
        self.sandbox = Path(sandbox)
        self.index = index
        self.ema_dir = self.sandbox / "ema_state" / "60min"
        self.ema_dir.mkdir(parents=True, exist_ok=True)
        self.ema: dict[int, float] = {}
        self.last_60m_close: float | None = None
        self.bar_count = 0
        self.r = redis.Redis(
            host="localhost", port=6379, db=REPLAY_REDIS_DB, decode_responses=True
        )
        self.queue_key = f"v3_ohlcv_queue_{index}_replay"
        # Env contract for the production scorers (process-wide)
        os.environ["REPLAY"] = "true"
        os.environ["BRAHMAND_REPLAY_REDIS_DB"] = str(REPLAY_REDIS_DB)
        os.environ["BRAHMAND_EMA_DIR"] = str(self.sandbox / "ema_state")

    # ── EMA replication (same recurrence the live 60-min updater runs) ──────

    def seed_emas(self, closes: list[float]):
        """Warm up all EMAs over historical 60-min closes (SMA seed, then EMA)."""
        for p in EMA_PERIODS:
            if len(closes) < p:
                continue
            ema = sum(closes[:p]) / p
            alpha = 2 / (p + 1)
            for c in closes[p:]:
                ema = c * alpha + ema * (1 - alpha)
            self.ema[p] = ema
        self.last_60m_close = closes[-1] if closes else None
        self.bar_count = len(closes)

    def push_60m_close(self, close: float):
        for p, ema in list(self.ema.items()):
            alpha = 2 / (p + 1)
            self.ema[p] = close * alpha + ema * (1 - alpha)
        self.last_60m_close = close
        self.bar_count += 1

    def write_ema_files(self):
        """Exact live ema_state shape. timestamp = real now so the scorer's
        24h-staleness guard never falls back to the 1min dir."""
        for p in EMA_PERIODS:
            payload = {
                "tf": "60min",
                "period": p,
                "ema_value": self.ema.get(p),
                "available": p in self.ema,
                "status": "ready" if p in self.ema else "not_enough_data",
                "last_bars": [self.last_60m_close] if self.last_60m_close else [],
                "buffer_count": self.bar_count,
                "multiplier": 2 / (p + 1),
                "threshold_crossed_at": datetime.now().isoformat(),
                "timestamp": datetime.now().isoformat(),
            }
            (self.ema_dir / f"ema_{p}.json").write_text(json.dumps(payload))

    # ── Redis bar queue (get_live_candles reads head = newest) ──────────────

    def start_day(self, yesterday_bars: list[dict], prev_close: float | None):
        """Reset the queue with yesterday's tail (for the 1440m/gap logic)."""
        pipe = self.r.pipeline()
        pipe.delete(self.queue_key)
        for b in yesterday_bars:  # chronological → LPUSH leaves newest at head
            pipe.lpush(self.queue_key, json.dumps(b))
        if prev_close is not None:
            pipe.set(f"prev_close_{self.index}", prev_close)
        pipe.execute()

    def push_minute_bar(self, ts: str, o: float, h: float, lo: float, c: float):
        bar = {
            "index": self.index,
            "timestamp": ts,
            "open": o,
            "high": h,
            "low": lo,
            "close": c,
        }
        self.r.lpush(self.queue_key, json.dumps(bar))
        self.r.ltrim(self.queue_key, 0, 499)

    # ── replay clock ─────────────────────────────────────────────────────────

    def set_as_of(self, ts: str):
        """ts = 'YYYY-MM-DD HH:MM:SS' — drives get_live_candles' 'today' and
        _compute_completion_by_tf."""
        os.environ["SHERPA_AS_OF"] = ts

    def close(self):
        for k in ("SHERPA_AS_OF", "REPLAY", "BRAHMAND_REPLAY_REDIS_DB", "BRAHMAND_EMA_DIR"):
            os.environ.pop(k, None)
        self.r.delete(self.queue_key)
