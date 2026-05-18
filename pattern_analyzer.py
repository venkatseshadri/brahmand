#!/usr/bin/env python3
"""
Pattern Analyzer — probabilistic multi-TF traffic light predictions.

Reads from market_data_patterns (enriched v4 data).
For each observed 6-TF pattern, computes:
  - P(UP | pattern, horizon)     — spot change > +threshold%
  - P(DOWN | pattern, horizon)   — spot change < -threshold%
  - P(SIDE | pattern, horizon)   — |spot change| ≤ threshold%
  - Median forward move, sample count

Pattern format: "GRGRGG" where position 0 = daily, 5 = 5m.

Usage:
  from pattern_analyzer import PatternAnalyzer
  pa = PatternAnalyzer()
  prob = pa.predict_pattern("GRGRGG")
  # {up_5m: 0.58, down_5m: 0.12, side_5m: 0.30, n_samples: 47, ...}
"""

import sys, json, logging
from pathlib import Path
from datetime import datetime
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent / "python-trader"))

logger = logging.getLogger("PatternAnalyzer")

V4_DB = Path("/home/trading_ceo/python-trader/varaha/data/market_data_multitf.duckdb")

# Thresholds: what counts as UP / DOWN vs SIDEWAYS (in %)
UP_THRESHOLD = 0.2  # >0.2% move = UP
DOWN_THRESHOLD = -0.2  # <-0.2% move = DOWN
# between = SIDEWAYS


class PatternAnalyzer:
    """Statistical pattern → probability engine."""

    def __init__(self, min_samples: int = 5):
        self.min_samples = min_samples

    def predict_pattern(self, pattern: str) -> dict:
        """
        Query historical outcomes for a given 6-TF pattern.
        Returns probability dict per horizon.
        """
        import duckdb

        db = duckdb.connect(str(V4_DB), read_only=True)

        try:
            rows = db.execute(
                """SELECT fwd_5m, fwd_15m, fwd_30m, fwd_1h, fwd_4h
                   FROM market_data_patterns
                   WHERE pattern = ? AND fwd_5m IS NOT NULL
                   ORDER BY timestamp DESC LIMIT 200""",
                (pattern,),
            ).fetchall()
        except Exception:
            rows = []
        finally:
            db.close()

        if not rows or len(rows) < self.min_samples:
            return {
                "pattern": pattern,
                "n_samples": len(rows),
                "status": "insufficient_data",
            }

        n = len(rows)
        result = {"pattern": pattern, "n_samples": n}

        for horizon, col_idx in [
            ("5m", 0),
            ("15m", 1),
            ("30m", 2),
            ("1h", 3),
            ("4h", 4),
        ]:
            values = [r[col_idx] for r in rows if r[col_idx] is not None]
            if not values:
                result[f"up_{horizon}"] = None
                result[f"down_{horizon}"] = None
                result[f"side_{horizon}"] = None
                continue

            up = sum(1 for v in values if v > UP_THRESHOLD) / len(values)
            down = sum(1 for v in values if v < DOWN_THRESHOLD) / len(values)
            side = 1.0 - up - down

            result[f"up_{horizon}"] = round(up, 3)
            result[f"down_{horizon}"] = round(down, 3)
            result[f"side_{horizon}"] = round(side, 3)
            result[f"med_{horizon}"] = round(_median(values), 3)

        # Best direction and horizon
        best_dir, best_hor, best_prob = "side", "5m", 0.0
        for d, h, prob in self._iter_directions(result):
            if prob > best_prob:
                best_dir, best_hor, best_prob = d, h, prob

        result["prediction"] = best_dir.upper()
        result["confidence"] = round(best_prob * 100, 1)
        result["horizon"] = best_hor
        return result

    def predict_live(self) -> Optional[dict]:
        """Read current pattern from v4 bars, return prediction."""
        import duckdb

        db = duckdb.connect(str(V4_DB), read_only=True)

        tf_order = [
            (1440, "1440m"),
            (240, "240m"),
            (60, "60m"),
            (30, "30m"),
            (15, "15m"),
            (5, "5m"),
        ]
        pattern = ""
        for tf_min, _ in tf_order:
            row = db.execute(
                """SELECT open, close FROM market_data_multitf
                   WHERE index_name = 'NIFTY' AND timeframe_min = ?
                   ORDER BY timestamp DESC LIMIT 1""",
                (tf_min,),
            ).fetchone()
            if row and row[0] and row[1]:
                pattern += "G" if row[1] > row[0] else "R"
            else:
                pattern += "-"
        db.close()

        if "-" in pattern:
            return None
        return self.predict_pattern(pattern)

    def top_patterns(self, n: int = 10) -> list:
        """Return top N most frequent patterns with probabilities."""
        import duckdb

        db = duckdb.connect(str(V4_DB), read_only=True)
        rows = db.execute(
            """SELECT pattern, COUNT(*) as cnt
               FROM market_data_patterns
               WHERE pattern NOT LIKE '%-%'
               GROUP BY pattern
               HAVING cnt >= ?
               ORDER BY cnt DESC LIMIT ?""",
            (self.min_samples, n),
        ).fetchall()
        db.close()

        results = []
        for pat, cnt in rows:
            pred = self.predict_pattern(pat)
            pred["total_count"] = cnt
            results.append(pred)
        return results

    def _iter_directions(self, result):
        for horizon in ["5m", "15m", "30m", "1h", "4h"]:
            yield "up", horizon, result.get(f"up_{horizon}", 0) or 0
            yield "down", horizon, result.get(f"down_{horizon}", 0) or 0


def _median(values: list) -> float:
    if not values:
        return 0
    s = sorted(values)
    n = len(s)
    if n % 2:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--live", action="store_true", help="Predict current live pattern"
    )
    parser.add_argument(
        "--pattern", type=str, help="Query specific pattern e.g. GRGRGG"
    )
    parser.add_argument("--top", type=int, default=10, help="Show top N patterns")
    args = parser.parse_args()

    pa = PatternAnalyzer()

    if args.live:
        res = pa.predict_live()
        print(json.dumps(res, indent=2))

    elif args.pattern:
        res = pa.predict_pattern(args.pattern)
        print(json.dumps(res, indent=2))

    elif args.top:
        print(f"\n=== TOP {args.top} PATTERNS ===")
        for p in pa.top_patterns(args.top):
            pred = p.get("prediction", "?")
            conf = p.get("confidence", 0)
            hor = p.get("horizon", "?")
            n = p.get("n_samples", 0)
            up5 = p.get("up_5m", "?")
            dn5 = p.get("down_5m", "?")
            print(
                f"  {p['pattern']:>6s}  n={n:>4d}  → {pred:>6s}@{hor:>3s} {conf:.0f}%  (P_up@5m={up5} P_dn@5m={dn5})"
            )

    else:
        print("Usage: python3 pattern_analyzer.py --live | --pattern GRGRGG | --top 10")
