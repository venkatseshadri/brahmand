"""Demonstrate check_feed_callbacks detects error-from-callback lines in feed.log."""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent.parent / "brahmand"
sys.path.insert(0, str(ROOT))


def test_no_errors_silent():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        f.write("09:15:23 INFO: feed started\n09:16:00 INFO: bar close\n")
        tmp = f.name
    try:
        log_path = Path("/home/trading_ceo/projects/antariksh/logs/feed.log")
        os.makedirs(log_path.parent, exist_ok=True)
        # Save original, replace with clean test log
        orig_exists = log_path.exists()
        if orig_exists:
            orig_backup = log_path.read_bytes()
        try:
            log_path.write_text(Path(tmp).read_text())
            from data_health import check_feed_callbacks

            ok, warnings = check_feed_callbacks()
            assert ok, f"Clean feed.log should pass: {warnings}"
        finally:
            if orig_exists:
                log_path.write_bytes(orig_backup)
            elif log_path.exists():
                log_path.unlink()
    finally:
        Path(tmp).unlink()


@patch("data_health._is_market_hours", return_value=True)
def test_errors_warn(mock_market):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        f.write(
            "09:15:23 INFO: feed started\n"
            "10:08:00 error from callback <function on_bar at 0x7f>: NameError: name 'instrument' is not defined\n"
            "10:09:00 INFO: bar close\n"
            "14:51:00 error from callback <function on_tick at 0x7f>: NameError: name 'r' is not defined\n"
        )
        tmp = f.name
    try:
        log_path = Path("/home/trading_ceo/projects/antariksh/logs/feed.log")
        os.makedirs(log_path.parent, exist_ok=True)
        orig_exists = log_path.exists()
        if orig_exists:
            orig_backup = log_path.read_bytes()
        try:
            log_path.write_text(Path(tmp).read_text())
            from data_health import check_feed_callbacks

            ok, warnings = check_feed_callbacks()
            assert not ok, "feed.log with 2 callback errors should WARN"
            assert len(warnings) == 1
            assert "2 'error from callback'" in warnings[0]
        finally:
            if orig_exists:
                log_path.write_bytes(orig_backup)
            elif log_path.exists():
                log_path.unlink()
    finally:
        Path(tmp).unlink()


if __name__ == "__main__":
    # Only run during non-market hours or mock market hours
    with patch("data_health._is_market_hours", return_value=True):
        test_no_errors_silent()
        print("  PASS  test_no_errors_silent")
        test_errors_warn()
        print("  PASS  test_errors_warn")
    print("  SENTINEL DEMO: 2/2 PASSED")
