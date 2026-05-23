"""Phase integration tests: Entry Phase — from signal detection to trade execution."""

import pytest


@pytest.mark.phase
class TestEntryPhase:
    def test_bearish_trend_plus_tl_creates_call_spread(
        self, market_snapshot_bearish, sample_trade_call_spread, contracts_call_spread
    ):
        assert market_snapshot_bearish["trend_signal"] == "BEARISH"
        assert market_snapshot_bearish["traffic_light_signal"] == "BEARISH"
        assert sample_trade_call_spread["strategy_type"] == "CALL_SPREAD"
        assert contracts_call_spread["contracts"]["sell_ce"]["option_type"] == "CE"

    def test_bullish_trend_plus_tl_creates_put_spread(
        self, market_snapshot_bullish, sample_trade_put_spread, contracts_put_spread
    ):
        assert market_snapshot_bullish["trend_signal"] == "BULLISH"
        assert sample_trade_put_spread["strategy_type"] == "PUT_SPREAD"
        assert (
            contracts_put_spread["contracts"]["sell_pe"]["strike"]
            > contracts_put_spread["contracts"]["buy_pe"]["strike"]
        )

    def test_high_vix_adjusts_wing_width(
        self, market_snapshot_high_vix, strategy_decision_high_vix
    ):
        assert market_snapshot_high_vix["india_vix"] > 20
        assert strategy_decision_high_vix["wing_width"] > 200

    def test_low_vix_narrows_wing_width(
        self, market_snapshot_low_vix, strategy_decision_low_vix
    ):
        assert market_snapshot_low_vix["india_vix"] < 15
        assert strategy_decision_low_vix["wing_width"] < 200

    def test_entry_signals_match_strategy_selection(
        self, entry_decision_bearish, entry_decision_bullish
    ):
        assert entry_decision_bearish["signal"] != entry_decision_bullish["signal"]
        assert entry_decision_bearish["go"] is True
        assert entry_decision_bullish["go"] is True
