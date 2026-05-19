#!/usr/bin/env python3
"""
EMA Integration Hook — Called by v3.1 Data Capture every 60 seconds.

This hook:
1. Receives the latest 1-min bar from v3.1
2. Calls ema_aggregator to update rolling EMA buffers
3. Logs EMA status for debugging
4. Ready to be called from data_capture_v3.1_duckdb.py

Integration point:
  In data_capture_v3.1_duckdb.py, after pushing bar to Redis:

    from ema_integration_hook import on_new_bar
    on_new_bar(latest_bar_dict)
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

# Add brahmand to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from ema_aggregator import update_ema, get_all_emas, get_ema_status, PERIODS, TIMEFRAMES


def on_new_bar(bar: Dict[str, Any], index: str = "NIFTY") -> dict:
    """
    Hook called by v3.1 Data Capture when a new 1-min bar arrives.

    Args:
        bar: {"close": 23745.5, "timestamp": "2026-05-20T09:16:00Z", ...}
        index: "NIFTY" or "SENSEX" (for logging)

    Returns:
        {
            "status": "success",
            "index": "NIFTY",
            "bar_timestamp": "2026-05-20T09:16:00Z",
            "close": 23745.5,
            "available_emas": {5: 23745.1, 20: None, 50: None, ...},
            "timestamp": "2026-05-20T09:16:00Z"
        }
    """
    try:
        close = float(bar.get("close", 0))
        if close <= 0:
            return {
                "status": "error",
                "error": f"Invalid close price: {close}",
                "timestamp": datetime.now().isoformat()
            }

        # Update 1-min EMA buffers
        update_ema(close, tf="1min")

        # Get available EMAs for 1min TF
        emas_1min = get_all_emas("1min")

        return {
            "status": "success",
            "index": index,
            "bar_timestamp": bar.get("timestamp", "unknown"),
            "close": close,
            "available_emas": emas_1min["1min"],
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


def get_ema_summary(tf: str = "1min") -> dict:
    """
    Get summary of EMA aggregator state for a TF (for logging/debugging).

    Args:
        tf: Timeframe to summarize (default "1min")

    Returns:
        {
            "ema_5": {"ema_value": 23745.1, "available": True, "status": "ready", ...},
            "ema_20": {"ema_value": None, "available": False, "status": "not_enough_data", ...},
            ...
        }
    """
    summary = {}
    for period in PERIODS:
        status = get_ema_status(tf, period)
        summary[f"ema_{period}"] = status
    return summary


# ============================================================
# INTEGRATION EXAMPLE for data_capture_v3.1_duckdb.py
# ============================================================

"""
In data_capture_v3.1_duckdb.py, add this:

    # After pushing bar to Redis
    r.lpush("v3_ohlcv_queue", json.dumps({
        "timestamp": bar_timestamp,
        "index": index,
        "open": bar_open,
        "high": bar_high,
        "low": bar_low,
        "close": bar_close,
        "volume": bar_volume,
        # ... other indicators
    }))

    # NEW: Update EMA aggregator
    from ema_integration_hook import on_new_bar

    ema_result = on_new_bar({
        "close": bar_close,
        "timestamp": bar_timestamp
    }, index=index)

    if ema_result["status"] == "success":
        # Log available EMAs periodically
        if bar_count % 5 == 0:  # Every 5 bars
            logger.debug(f"[V3.1→EMA] Available: {ema_result['available_emas']}")
"""

if __name__ == "__main__":
    # Test integration
    print("[TEST] EMA Integration Hook\n")

    # Simulate bars
    for i in range(1, 11):
        bar = {
            "close": 23740.0 + (i * 0.5),
            "timestamp": f"2026-05-20T09:{15+i:02d}:00Z"
        }

        result = on_new_bar(bar)

        print(f"\nBar {i}:")
        print(f"  Status: {result['status']}")
        print(f"  Close: {result.get('close', 'N/A')}")
        print(f"  Available EMAs: {result.get('available_emas', {})}")
        print(f"  Thresholds crossed: {result.get('thresholds_crossed', [])}")

    print("\n" + "=" * 60)
    print("Final Summary:")
    print("=" * 60)
    summary = get_ema_summary()
    for ema_key, status in summary.items():
        if status["available"]:
            print(
                f"{ema_key}: {status['ema_value']:.4f} "
                f"(ready, {status['buffer_count']} bars)"
            )
        else:
            print(
                f"{ema_key}: None "
                f"({status['buffer_count']}/{status['bars_needed']} bars)"
            )
