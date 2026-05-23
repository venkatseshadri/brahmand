"""Unit tests: Execution Agent — builds paper trades, routes orders (dumb executor)."""

import pytest


@pytest.mark.unit
class TestExecutionAgent:
    def test_call_spread_net_credit_positive(self, sample_trade_call_spread):
        assert sample_trade_call_spread["net_credit"] > 0

    def test_put_spread_margin_required(self, sample_trade_put_spread):
        assert sample_trade_put_spread["margin_required"] > 0

    def test_trade_has_valid_legs_and_id(self, sample_trade_call_spread):
        assert sample_trade_call_spread["trade_id"].startswith("TRD-")
        assert len(sample_trade_call_spread["legs"]) == 2
