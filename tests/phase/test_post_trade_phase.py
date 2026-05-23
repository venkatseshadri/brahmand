"""Phase integration tests: Post-Trade Phase — postmortem analysis and learning."""

import pytest


@pytest.mark.phase
class TestPostTradePhase:
    def test_winning_trade_correct_signal(self, postmortem_analysis_success):
        assert postmortem_analysis_success["signal_accuracy"] is True

    def test_losing_trade_incorrect_signal(self, postmortem_analysis_loss):
        assert postmortem_analysis_loss["signal_accuracy"] is False

    def test_regime_classification_produces_learning(self, postmortem_analysis_success):
        assert "regime_classification_correct" in postmortem_analysis_success

    def test_postmortem_learning_fed_to_weights(
        self, postmortem_analysis_success, postmortem_analysis_loss
    ):
        assert (
            postmortem_analysis_success["learning_notes"]
            != postmortem_analysis_loss["learning_notes"]
        )
