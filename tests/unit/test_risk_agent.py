"""Unit tests: Risk Agent — monitors SL/TP, TSL ratcheting, pattern-based adaptation."""

import pytest


@pytest.mark.unit
class TestRiskAgent:
    def test_sell_leg_sl_is_protective(self, sample_trade_call_spread):
        sell = [l for l in sample_trade_call_spread["legs"] if l["action"] == "SELL"][0]
        assert sell["sl"] > sell["entry_price"]  # SELL: SL above entry

    def test_sell_leg_tp_is_profit_target(self, sample_trade_call_spread):
        sell = [l for l in sample_trade_call_spread["legs"] if l["action"] == "SELL"][0]
        assert sell["tp"] < sell["entry_price"]  # SELL: TP below entry

    def test_tsl_not_active_at_entry(self, sample_trade_call_spread):
        assert sample_trade_call_spread["tsl_activated"] is False

    def test_morph_count_starts_at_zero(self, sample_trade_call_spread):
        assert sample_trade_call_spread["morph_count"] == 0
