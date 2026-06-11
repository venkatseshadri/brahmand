"""T17: Margin lifecycle gate — pre-entry check, post-fill refresh, leg-shift resolution.

Run: python3 -m pytest tests/test_t17_margin_gate.py -q
"""

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "brahmand"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

IST = timezone(timedelta(hours=5, minutes=30))


def _write_limits(path: Path, free_margin: float, ts: str):
    path.write_text(
        json.dumps(
            {
                "timestamp": ts,
                "free_margin": free_margin,
                "total_margin_available": 500000,
                "used_margin": 0,
            }
        )
    )


def _write_matrix(path: Path, spreads: list):
    path.write_text(
        json.dumps(
            {
                "atm": 23200,
                "expiry": "16-JUN-2026",
                "lot_size": 65,
                "spreads": spreads,
            }
        )
    )


def test_entry_margin_ok():
    from margin_gate import check_entry_margin

    with tempfile.TemporaryDirectory() as td:
        limits = Path(td) / "broker_limits.json"
        matrix = Path(td) / "margin_matrix.json"
        _write_limits(limits, 566000, datetime.now(IST).isoformat())
        _write_matrix(
            matrix,
            [
                {
                    "type": "CE",
                    "sell_strike": 23200,
                    "buy_strike": 23400,
                    "wing_width": 200,
                    "margin": 156000,
                },
            ],
        )
        with (
            patch("margin_gate._LIMITS_FILE", limits),
            patch("margin_gate._MATRIX_FILE", matrix),
        ):
            ok, reason = check_entry_margin(
                "NIFTY",
                "CE",
                [
                    {"action": "SELL", "strike": 23200, "type": "CE"},
                    {"action": "BUY", "strike": 23400, "type": "CE"},
                ],
            )
            assert ok, f"Should pass, got {reason}"
            assert "MARGIN_OK" in reason


def test_entry_margin_insufficient():
    from margin_gate import check_entry_margin

    with tempfile.TemporaryDirectory() as td:
        limits = Path(td) / "broker_limits.json"
        matrix = Path(td) / "margin_matrix.json"
        _write_limits(limits, 100000, datetime.now(IST).isoformat())
        _write_matrix(
            matrix,
            [
                {
                    "type": "CE",
                    "sell_strike": 23200,
                    "buy_strike": 23400,
                    "wing_width": 200,
                    "margin": 156000,
                },
            ],
        )
        with (
            patch("margin_gate._LIMITS_FILE", limits),
            patch("margin_gate._MATRIX_FILE", matrix),
        ):
            ok, reason = check_entry_margin(
                "NIFTY",
                "CE",
                [
                    {"action": "SELL", "strike": 23200, "type": "CE"},
                    {"action": "BUY", "strike": 23400, "type": "CE"},
                ],
            )
            assert not ok
            assert "INSUFFICIENT" in reason


def test_entry_margin_stale():
    from margin_gate import check_entry_margin

    with tempfile.TemporaryDirectory() as td:
        limits = Path(td) / "broker_limits.json"
        matrix = Path(td) / "margin_matrix.json"
        stale_ts = (datetime.now(IST) - timedelta(minutes=10)).isoformat()
        _write_limits(limits, 566000, stale_ts)
        _write_matrix(
            matrix,
            [
                {
                    "type": "CE",
                    "sell_strike": 23200,
                    "buy_strike": 23400,
                    "wing_width": 200,
                    "margin": 156000,
                },
            ],
        )
        with (
            patch("margin_gate._LIMITS_FILE", limits),
            patch("margin_gate._MATRIX_FILE", matrix),
        ):
            ok, reason = check_entry_margin(
                "NIFTY",
                "CE",
                [
                    {"action": "SELL", "strike": 23200, "type": "CE"},
                    {"action": "BUY", "strike": 23400, "type": "CE"},
                ],
            )
            assert not ok
            assert "STALE" in reason


def test_entry_margin_missing_file():
    from margin_gate import check_entry_margin

    with tempfile.TemporaryDirectory() as td:
        with (
            patch("margin_gate._LIMITS_FILE", Path(td) / "nonexistent.json"),
            patch("margin_gate._MATRIX_FILE", Path(td) / "nonexistent.json"),
        ):
            ok, reason = check_entry_margin(
                "NIFTY",
                "CE",
                [
                    {"action": "SELL", "strike": 23200, "type": "CE"},
                    {"action": "BUY", "strike": 23400, "type": "CE"},
                ],
            )
            assert not ok
            assert "MISSING" in reason


def test_90pct_buffer_applied():
    from margin_gate import check_entry_margin

    with tempfile.TemporaryDirectory() as td:
        limits = Path(td) / "broker_limits.json"
        matrix = Path(td) / "margin_matrix.json"
        # Free = 173,334 → net (90%) = 156,000 → barely exactly at threshold
        _write_limits(limits, 173334, datetime.now(IST).isoformat())
        _write_matrix(
            matrix,
            [
                {
                    "type": "CE",
                    "sell_strike": 23200,
                    "buy_strike": 23400,
                    "wing_width": 200,
                    "margin": 156000,
                },
            ],
        )
        with (
            patch("margin_gate._LIMITS_FILE", limits),
            patch("margin_gate._MATRIX_FILE", matrix),
        ):
            ok, _ = check_entry_margin(
                "NIFTY",
                "CE",
                [
                    {"action": "SELL", "strike": 23200, "type": "CE"},
                    {"action": "BUY", "strike": 23400, "type": "CE"},
                ],
            )
            assert ok, "156000 <= 173334*0.90 should pass"


def test_is_margin_fresh():
    from margin_gate import is_margin_fresh

    with tempfile.TemporaryDirectory() as td:
        limits = Path(td) / "broker_limits.json"
        _write_limits(limits, 500000, datetime.now(IST).isoformat())
        with patch("margin_gate._LIMITS_FILE", limits):
            assert is_margin_fresh()


def test_is_margin_stale():
    from margin_gate import is_margin_fresh

    with tempfile.TemporaryDirectory() as td:
        limits = Path(td) / "broker_limits.json"
        _write_limits(
            limits, 500000, (datetime.now(IST) - timedelta(minutes=10)).isoformat()
        )
        with patch("margin_gate._LIMITS_FILE", limits):
            assert not is_margin_fresh()
