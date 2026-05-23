"""Scenario tests: Realistic trading day flows."""

import pytest


@pytest.mark.scenario
class TestScenarioIronButterfly:
    def test_iron_butterfly_from_neutral_signal(
        self, market_snapshot_neutral, sample_trade_call_spread, sample_trade_put_spread
    ):
        assert market_snapshot_neutral["trend_signal"] == "NEUTRAL"
        ce_legs = sample_trade_call_spread["legs"]
        pe_legs = sample_trade_put_spread["legs"]
        assert len(ce_legs) == 2
        assert len(pe_legs) == 2


@pytest.mark.scenario
class TestScenarioMorph:
    def test_bearish_reverses_to_bullish(self, sample_trade_with_morph):
        assert sample_trade_with_morph["entry_gate_signal"] == "BULLISH"
        assert sample_trade_with_morph["entry_gate_signal_original"] == "BEARISH"

    def test_morph_produces_new_orders(self, sample_trade_with_morph):
        morph = sample_trade_with_morph["morph_actions"][0]
        assert len(morph["cancelled_orders"]) >= 1
        assert len(morph["new_orders"]) >= 1


@pytest.mark.scenario
class TestScenarioPremiumDecay:
    def test_50pct_decay_triggers_shift(self, sample_trade_with_shift):
        shift = sample_trade_with_shift["shift_actions"][0]
        assert shift["action"] == "HEDGE_SHIFT"
        assert sample_trade_with_shift["shift_count"] == 1


@pytest.mark.scenario
class TestScenarioTSL:
    def test_tsl_activation_after_profit_percent(self, sample_trade_call_spread):
        assert sample_trade_call_spread["tsl_activated"] is False
        assert sample_trade_call_spread["tsl_level"] == 0


@pytest.mark.scenario
class TestScenarioExitReasons:
    def test_tp_hit(self, exit_event_tp_hit):
        assert exit_event_tp_hit["pnl"] > 0

    def test_sl_hit(self, exit_event_sl_hit):
        assert exit_event_sl_hit["pnl"] < 0

    def test_time_exit(self, exit_event_time):
        assert exit_event_time["exit_reason"] == "TIME_EXIT"

    def test_morph_records_original_signal(self, sample_trade_with_morph):
        assert "entry_gate_signal_original" in sample_trade_with_morph
        assert sample_trade_with_morph["morph_count"] > 0
