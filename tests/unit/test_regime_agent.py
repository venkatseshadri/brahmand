"""Unit tests: Regime Agent — detects BULLISH/BEARISH/SIDEWAYS from VIX, ADX, price action."""

import pytest


@pytest.mark.unit
class TestRegimeAgent:
    def test_bullish_regime_uptrend(self, market_snapshot_bullish):
        assert market_snapshot_bullish["trend_signal"] == "BULLISH"
        assert market_snapshot_bullish["adx"] >= 15

    def test_bearish_regime_downtrend(self, market_snapshot_high_vix):
        assert market_snapshot_high_vix["trend_signal"] == "BEARISH"
        assert market_snapshot_high_vix["adx"] >= 20

    def test_sideways_regime_low_adx(self, market_snapshot_neutral):
        assert market_snapshot_neutral["adx"] <= 20
        assert market_snapshot_neutral["trend_signal"] == "NEUTRAL"
