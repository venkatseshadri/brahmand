"""Unit tests: Morpher Agent — detects signal reversals, executes morph (add/remove sides)."""

import pytest


@pytest.mark.unit
class TestMorpherAgent:
    def test_morph_detected_on_signal_reversal(self, monitoring_event_morph):
        assert monitoring_event_morph["action"] == "MORPH"
        assert monitoring_event_morph["signal_old"] == "BEARISH"
        assert monitoring_event_morph["signal_new"] == "BULLISH"

    def test_morph_cancels_old_sl_tp(self, monitoring_event_morph):
        assert len(monitoring_event_morph["cancelled_orders"]) >= 1
        assert len(monitoring_event_morph["new_orders"]) >= 1

    def test_morph_trade_records_reversal(self, sample_trade_with_morph):
        assert sample_trade_with_morph["morph_count"] == 1
        assert sample_trade_with_morph["entry_gate_signal"] == "BULLISH"
        assert sample_trade_with_morph["entry_gate_signal_original"] == "BEARISH"

    def test_no_action_when_signal_stable(self, monitoring_event_no_action):
        assert monitoring_event_no_action["action"] == "no_action"
