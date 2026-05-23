"""Phase integration tests: Monitoring Phase — morph, shift, SL/TP, TSL."""

import pytest


@pytest.mark.phase
class TestMonitoringPhase:
    def test_morph_on_signal_change(
        self, monitoring_event_morph, sample_trade_call_spread
    ):
        assert monitoring_event_morph["action"] == "MORPH"
        assert (
            sample_trade_call_spread["entry_gate_signal"]
            != monitoring_event_morph["signal_new"]
        )

    def test_shift_on_premium_decay(
        self, monitoring_event_shift, sample_trade_call_spread
    ):
        assert monitoring_event_shift["action"] == "HEDGE_SHIFT"
        assert sample_trade_call_spread["entry_gate_signal"] == "BEARISH"

    def test_tp_hit_closes_position_positive(
        self, exit_event_tp_hit, sample_trade_call_spread
    ):
        assert exit_event_tp_hit["exit_reason"] == "TP_HIT"
        assert exit_event_tp_hit["pnl"] > 0
        assert exit_event_tp_hit["trade_id"] == sample_trade_call_spread["trade_id"]

    def test_sl_hit_closes_position_negative(
        self, exit_event_sl_hit, sample_trade_call_spread
    ):
        assert exit_event_sl_hit["exit_reason"] == "SL_HIT"
        assert exit_event_sl_hit["pnl"] < 0

    def test_time_exit_closes_at_market_close(self, exit_event_time):
        assert exit_event_time["exit_reason"] == "TIME_EXIT"

    def test_morph_cancels_and_places_new_orders(self, monitoring_event_morph):
        assert len(monitoring_event_morph["cancelled_orders"]) >= 1
        assert len(monitoring_event_morph["new_orders"]) >= 1
