"""E2E tests: Full trading day workflows from entry to postmortem."""

import pytest


@pytest.mark.e2e
class TestE2EWorkflows:
    def test_call_spread_entry_to_exit(
        self,
        entry_decision_bearish,
        sample_trade_call_spread,
        order_result_entry,
        order_result_sl_tp,
        exit_event_tp_hit,
    ):
        assert entry_decision_bearish["signal"] == "NOT_UP"
        assert sample_trade_call_spread["strategy_type"] == "CALL_SPREAD"
        assert order_result_entry["status"] == "FILLED"
        assert order_result_sl_tp["status"] == "FILLED"
        assert exit_event_tp_hit["pnl"] > 0

    def test_put_spread_morph_exit(
        self,
        entry_decision_bullish,
        sample_trade_put_spread,
        monitoring_event_morph,
        exit_event_sl_hit,
    ):
        assert entry_decision_bullish["signal"] == "NOT_DOWN"
        assert sample_trade_put_spread["strategy_type"] == "PUT_SPREAD"
        assert monitoring_event_morph["action"] == "MORPH"
        assert exit_event_sl_hit["pnl"] < 0

    def test_monitoring_loop_morph_then_tsl(
        self, sample_trade_call_spread, monitoring_event_morph, monitoring_event_shift
    ):
        assert len(sample_trade_call_spread["legs"]) == 2
        assert monitoring_event_morph["action"] == "MORPH"
        assert monitoring_event_shift["action"] == "HEDGE_SHIFT"

    def test_postmortem_feed_learning(
        self, postmortem_analysis_success, postmortem_analysis_loss
    ):
        assert postmortem_analysis_success["pnl"] > 0
        assert postmortem_analysis_loss["pnl"] < 0
        assert (
            "learning_notes" in postmortem_analysis_success
            and "learning_notes" in postmortem_analysis_loss
        )

    def test_complete_day_flow(
        self,
        market_snapshot_bullish,
        entry_decision_bullish,
        sample_trade_put_spread,
        monitoring_event_no_action,
        exit_event_time,
        postmortem_analysis_success,
    ):
        assert market_snapshot_bullish["trend_signal"] == "BULLISH"
        assert entry_decision_bullish["go"] is True
        assert sample_trade_put_spread["net_credit"] > 0
        assert monitoring_event_no_action["action"] == "no_action"
        assert exit_event_time["exit_reason"] == "TIME_EXIT"
        assert postmortem_analysis_success["signal_accuracy"] is True
