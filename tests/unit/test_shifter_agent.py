"""Unit tests: Shifter Agent — detects theta decay, rolls legs to new strikes."""

import pytest


@pytest.mark.unit
class TestShifterAgent:
    def test_shift_on_premium_decay(self, monitoring_event_shift):
        assert monitoring_event_shift["action"] == "HEDGE_SHIFT"
        assert monitoring_event_shift["decay_percent"] == 50

    def test_shift_trade_records_action(self, sample_trade_with_shift):
        assert sample_trade_with_shift["shift_count"] == 1
        assert sample_trade_with_shift["shift_actions"][0]["action"] == "HEDGE_SHIFT"
