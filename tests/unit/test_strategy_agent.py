"""Unit tests: Strategy Agent — selects spread type, wing_width, SL/TP based on VIX/ADX."""

import pytest


@pytest.mark.unit
class TestStrategyAgent:
    def test_default_params_for_neutral_vix(self, strategy_decision_default):
        assert strategy_decision_default["wing_width"] == 200
        assert strategy_decision_default["sl_pct"] == 0.25
        assert strategy_decision_default["tp_pct"] == 0.50

    def test_high_vix_wider_wings_tighter_sl(self, strategy_decision_high_vix):
        assert strategy_decision_high_vix["wing_width"] > 200
        assert strategy_decision_high_vix["sl_pct"] > 0.25

    def test_low_vix_narrower_wings_extended_tp(self, strategy_decision_low_vix):
        assert strategy_decision_low_vix["wing_width"] < 200
        assert strategy_decision_low_vix["tp_pct"] > 0.50

    def test_strategy_type_matches_signal_context(
        self, strategy_decision_low_vix, market_snapshot_low_vix
    ):
        assert strategy_decision_low_vix["strategy_type"] in (
            "CALL_SPREAD",
            "PUT_SPREAD",
            "IRON_BUTTERFLY",
        )
        assert market_snapshot_low_vix["india_vix"] < 15
