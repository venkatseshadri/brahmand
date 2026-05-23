"""Unit tests: Postmortem Agent — analyzes trade outcomes, feeds learning."""

import pytest


@pytest.mark.unit
class TestPostmortemAgent:
    def test_winning_trade_signal_accurate(self, postmortem_analysis_success):
        assert postmortem_analysis_success["signal_accuracy"] is True
        assert postmortem_analysis_success["pnl"] > 0
        assert postmortem_analysis_success["exit_reason"] == "TP_HIT"

    def test_losing_trade_captures_learning(self, postmortem_analysis_loss):
        assert postmortem_analysis_loss["signal_accuracy"] is False
        assert postmortem_analysis_loss["exit_reason"] == "SL_HIT"
        assert "learning_notes" in postmortem_analysis_loss
