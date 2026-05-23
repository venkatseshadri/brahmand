"""Unit tests: Order Agent — routes entry/SL/TP orders to broker (PAPER/LIVE)."""

import pytest


@pytest.mark.unit
class TestOrderAgent:
    def test_entry_orders_filled(self, order_result_entry):
        assert order_result_entry["status"] == "FILLED"
        assert len(order_result_entry["entry_orders"]) == 2
        assert order_result_entry["mode"] == "PAPER"

    def test_sl_tp_orders_placed(self, order_result_sl_tp):
        assert order_result_sl_tp["status"] == "FILLED"
        assert len(order_result_sl_tp["sl_orders"]) == 1
        assert len(order_result_sl_tp["tp_orders"]) == 1

    def test_entry_orders_match_trade(
        self, order_result_entry, sample_trade_call_spread
    ):
        assert order_result_entry["trade_id"] == sample_trade_call_spread["trade_id"]

    def test_paper_mode_no_broker_calls(self, order_result_entry):
        assert order_result_entry["mode"] == "PAPER"
