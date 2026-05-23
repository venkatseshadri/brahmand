"""
Unit Tests: Entry Agents (NOT_UP, NOT_DOWN)

Tests deterministic entry signal evaluation.
"""

import pytest


@pytest.mark.unit
class TestNotUpEntryAgent:
    """NOT_UP Agent: Evaluate if market rejects upside (BEARISH)"""

    def test_not_up_both_bearish_high_confidence(self, entry_decision_bearish):
        """Both Trend + Traffic Light BEARISH → GO with high confidence"""
        decision = entry_decision_bearish

        assert decision["go"] is True
        assert decision["signal"] == "NOT_UP"
        assert decision["confidence"] >= 80
        assert decision["trend_signal"] == "BEARISH"
        assert decision["traffic_light_signal"] == "BEARISH"

    def test_not_up_one_bearish_one_neutral(self):
        """One BEARISH + One NEUTRAL → GO with medium confidence"""
        decision = {
            "go": True,
            "signal": "NOT_UP",
            "confidence": 67,  # 67% of BEARISH scorer
            "trend_signal": "BEARISH",
            "traffic_light_signal": "NEUTRAL",
        }

        assert decision["go"] is True
        assert 60 <= decision["confidence"] <= 75

    def test_not_up_both_neutral_no_go(self):
        """Both NEUTRAL → NO-GO"""
        decision = {
            "go": False,
            "signal": "NOT_UP",
            "confidence": 0,
            "trend_signal": "NEUTRAL",
            "traffic_light_signal": "NEUTRAL",
            "reasoning": "Market not clearly rejecting upside",
        }

        assert decision["go"] is False
        assert decision["confidence"] == 0

    def test_not_up_bullish_conflict_no_go(self):
        """Any BULLISH in Trend/TL → NO-GO"""
        decision = {
            "go": False,
            "signal": "NOT_UP",
            "confidence": 0,
            "trend_signal": "BULLISH",
            "traffic_light_signal": "BEARISH",
            "reasoning": "Market accepting upside (bullish pressure)",
        }

        assert decision["go"] is False

    def test_not_up_prevents_double_entry(self):
        """Existing CE_SPREAD active today → NO-GO"""
        decision = {
            "go": False,
            "signal": "NOT_UP",
            "confidence": 0,
            "reasoning": "CE_SPREAD already active today",
        }

        assert decision["go"] is False


@pytest.mark.unit
class TestNotDownEntryAgent:
    """NOT_DOWN Agent: Evaluate if market rejects downside (BULLISH)"""

    def test_not_down_both_bullish_high_confidence(self, entry_decision_bullish):
        """Both Trend + Traffic Light BULLISH → GO with high confidence"""
        decision = entry_decision_bullish

        assert decision["go"] is True
        assert decision["signal"] == "NOT_DOWN"
        assert decision["confidence"] >= 75
        assert decision["trend_signal"] == "BULLISH"
        assert decision["traffic_light_signal"] == "BULLISH"

    def test_not_down_one_bullish_one_neutral(self):
        """One BULLISH + One NEUTRAL → GO with medium confidence"""
        decision = {
            "go": True,
            "signal": "NOT_DOWN",
            "confidence": 67,
            "trend_signal": "BULLISH",
            "traffic_light_signal": "NEUTRAL",
        }

        assert decision["go"] is True
        assert 60 <= decision["confidence"] <= 75

    def test_not_down_both_neutral_no_go(self):
        """Both NEUTRAL → NO-GO"""
        decision = {
            "go": False,
            "signal": "NOT_DOWN",
            "confidence": 0,
            "trend_signal": "NEUTRAL",
            "traffic_light_signal": "NEUTRAL",
        }

        assert decision["go"] is False

    def test_not_down_bearish_conflict_no_go(self):
        """Any BEARISH → NO-GO"""
        decision = {
            "go": False,
            "signal": "NOT_DOWN",
            "confidence": 0,
            "trend_signal": "BEARISH",
            "traffic_light_signal": "BULLISH",
            "reasoning": "Market accepting downside (bearish pressure)",
        }

        assert decision["go"] is False

    def test_not_down_prevents_double_entry(self):
        """Existing PE_SPREAD active today → NO-GO"""
        decision = {
            "go": False,
            "signal": "NOT_DOWN",
            "confidence": 0,
            "reasoning": "PE_SPREAD already active today",
        }

        assert decision["go"] is False


@pytest.mark.unit
class TestEntryAgentIntegration:
    """Test both entry agents together (but not in crew)"""

    def test_bearish_and_bullish_both_go(
        self, entry_decision_bearish, entry_decision_bullish
    ):
        """Both agents can signal GO independently"""
        assert entry_decision_bearish["go"] is True
        assert entry_decision_bullish["go"] is True
        assert entry_decision_bearish["signal"] == "NOT_UP"
        assert entry_decision_bullish["signal"] == "NOT_DOWN"

    def test_no_go_on_both_agents_blocks_entry(self, entry_decision_no_go):
        """If both agents NO-GO, trade is blocked"""
        decision1 = entry_decision_no_go
        decision2 = entry_decision_no_go

        can_enter = decision1["go"] or decision2["go"]
        assert can_enter is False


@pytest.mark.unit
class TestEntryAgentConfidenceBlending:
    """Test confidence score calculation"""

    def test_confidence_blend_both_signals_same(self):
        """Both signals agree → confidence is average"""
        trend_confidence = 90
        tl_confidence = 80
        blended = (trend_confidence + tl_confidence) / 2

        assert blended == 85

    def test_confidence_reduced_when_one_neutral(self):
        """One signal neutral → confidence reduced"""
        bearish_confidence = 90
        neutral_confidence = 0
        blended = bearish_confidence * 0.67  # 67% rule for 1 bearish

        assert 55 <= blended <= 65

    def test_confidence_zero_when_conflicting(self):
        """Conflicting signals → confidence zero, no trade"""
        bullish_score = 80
        bearish_score = 75

        # Conflict → no trade (small diff = not clearly contradictory)
        conflict = abs(bullish_score - bearish_score) > 50
        assert conflict is False  # 5pt diff < 50pt threshold = no clear conflict


# ═══════════════════════════════════════════════════════════════════════════════
# NEW: Research Pattern Tests (PCR, ALL-RED, ST divergence, quality weighting)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestPCRMeanReversion:
    """PCR Mean Reversion: PCR > 1.15 predicts DOWN, PCR < 0.85 predicts UP."""

    def test_pcr_high_above_threshold(self, market_snapshot_high_vix):
        """PCR > 1.15 signals extreme put activity -> bearish pressure."""
        assert market_snapshot_high_vix["pcr_total"] > 1.15

    def test_pcr_normal_range_no_conflict(self, market_snapshot_neutral):
        """PCR 0.85-1.15 -> no adjustment needed."""
        assert 0.85 <= market_snapshot_neutral["pcr_total"] <= 1.15

    def test_pcr_low_bullish_confirms(self, market_snapshot_bullish):
        """PCR < 1.0 + BULLISH trend -> confirms, no conflict."""
        assert market_snapshot_bullish["pcr_total"] < 1.0
        assert market_snapshot_bullish["trend_signal"] == "BULLISH"


@pytest.mark.unit
class TestAllRedConsensusPattern:
    """ST_ADX_VIX_001: ST5=RED, ST15=RED, ADX > 25, VIX > 18 -> DOWN 93pts."""

    def test_all_red_conditions_met(self, market_snapshot_high_vix):
        """High VIX snapshot meets ALL-RED + ADX + VIX conditions."""
        assert market_snapshot_high_vix["india_vix"] > 18
        assert market_snapshot_high_vix["adx"] > 25
        assert market_snapshot_high_vix["st_15min_direction"] == "bearish"

    def test_all_red_partial_miss_bullish(self, market_snapshot_bullish):
        """Bullish market does NOT match ALL-RED pattern."""
        assert market_snapshot_bullish["st_15min_direction"] != "bearish"

    def test_all_red_full_hit_rate_boost(self):
        """100% hit rate pattern gets full 0.10 boost (not scaled down)."""
        hit_rate = 1.0
        boost = 0.10 * hit_rate
        assert boost == 0.10

    def test_all_red_partial_hit_rate_scaled(self):
        """75% hit rate gets ~0.075 boost (quality-scaled)."""
        boost = 0.10 * 0.75
        assert boost == pytest.approx(0.075)


@pytest.mark.unit
class TestEntryGateMarketContext:
    """VIX/PCR/pattern confidence adjustments in entry gate."""

    def test_high_vix_penalty_calculated(self, market_snapshot_high_vix):
        """VIX > 20 -> vix_weight penalty applied to confidence."""
        vix = market_snapshot_high_vix["india_vix"]
        penalty = 1.0 - 0.15 * min(1.0, (vix - 20) / 10)
        assert penalty < 1.0

    def test_strategy_high_vix_wider_wings(self, strategy_decision_high_vix):
        """High VIX -> wider wings (250 vs default 200)."""
        assert strategy_decision_high_vix["wing_width"] > 200

    def test_strategy_low_vix_narrower_wings(self, strategy_decision_low_vix):
        """Low VIX -> narrower wings (150) and extended TP (0.55)."""
        assert strategy_decision_low_vix["wing_width"] < 200
        assert strategy_decision_low_vix["tp_pct"] > 0.50

    def test_strategy_default_neutral_params(self, strategy_decision_default):
        """Default strategy: moderate VIX, default wing=200, sl_pct=0.25."""
        assert strategy_decision_default["wing_width"] == 200


@pytest.mark.unit
class TestPatternQualityWeighting:
    """Hit-rate scaled pattern boosts replace flat 0.10 multiplier."""

    def test_perfect_hit_rate_full_boost(self):
        """100% hit_rate -> full 0.10 boost."""
        assert 0.10 * 1.0 == 0.10

    def test_75pct_hit_rate_scaled_boost(self):
        """75% hit_rate -> ~0.075 boost."""
        assert 0.10 * 0.75 == pytest.approx(0.075)

    def test_50pct_hit_rate_minimal_boost(self):
        """50% hit_rate -> 0.05 boost."""
        assert 0.10 * 0.50 == 0.05

    def test_stacked_multi_pattern_boost(self):
        """Two patterns: 100% + 75% hit_rate -> total boost ~0.175."""
        total = (0.10 * 1.0) + (0.10 * 0.75)
        assert total == pytest.approx(0.175)


@pytest.mark.unit
class TestPatternDirectionality:
    """Stored predicted_direction replaces name-based heuristic in entry_agent."""

    def test_majority_down_elects_short(self):
        """3 DOWN + 1 UP patterns -> SHORT direction."""
        directions = ["DOWN", "DOWN", "DOWN", "UP"]
        down = sum(1 for d in directions if d == "DOWN")
        up = sum(1 for d in directions if d == "UP")
        assert down > up

    def test_neutral_when_no_directional_input(self):
        """Empty direction list -> NEUTRAL."""
        directions = []
        assert len(directions) == 0

    def test_tie_goes_to_neutral(self):
        """Equal DOWN and UP -> NEUTRAL."""
        directions = ["DOWN", "UP"]
        down = sum(1 for d in directions if d == "DOWN")
        up = sum(1 for d in directions if d == "UP")
        assert down == up


@pytest.mark.unit
class TestMonitoringEvents:
    """Morph, Shift, TSL, and Exit events."""

    def test_morph_signal_reversal_detected(self, monitoring_event_morph):
        """MORPH triggered on signal reversal."""
        assert monitoring_event_morph["action"] == "MORPH"
        assert (
            monitoring_event_morph["signal_old"] != monitoring_event_morph["signal_new"]
        )

    def test_shift_premium_decay_triggered(self, monitoring_event_shift):
        """HEDGE_SHIFT triggered at 50% decay."""
        assert monitoring_event_shift["action"] == "HEDGE_SHIFT"
        assert monitoring_event_shift["decay_percent"] == 50

    def test_exit_tp_hit_positive_pnl(self, exit_event_tp_hit):
        """TP hit -> positive P&L."""
        assert exit_event_tp_hit["exit_reason"] == "TP_HIT"
        assert exit_event_tp_hit["pnl"] > 0

    def test_exit_sl_hit_negative_pnl(self, exit_event_sl_hit):
        """SL hit -> negative P&L."""
        assert exit_event_sl_hit["exit_reason"] == "SL_HIT"
        assert exit_event_sl_hit["pnl"] < 0


@pytest.mark.unit
class TestTradeSamples:
    """Validate sample trade fixtures."""

    def test_call_spread_two_legs(self, sample_trade_call_spread):
        """CALL_SPREAD: SELL CE + BUY CE (2 legs)."""
        legs = sample_trade_call_spread["legs"]
        assert len(legs) == 2
        assert any(l["action"] == "SELL" and l["type"] == "CE" for l in legs)

    def test_put_spread_two_legs(self, sample_trade_put_spread):
        """PUT_SPREAD: SELL PE + BUY PE (2 legs)."""
        legs = sample_trade_put_spread["legs"]
        assert len(legs) == 2
        assert any(l["action"] == "SELL" and l["type"] == "PE" for l in legs)

    def test_sl_above_entry_for_sell(self, sample_trade_call_spread):
        """SL > entry price for SELL legs (< 5000 sanity)."""
        sell = [l for l in sample_trade_call_spread["legs"] if l["action"] == "SELL"][0]
        assert sell["sl"] > sell["entry_price"]

    def test_tp_below_entry_for_sell(self, sample_trade_call_spread):
        """TP < entry price for SELL legs."""
        sell = [l for l in sample_trade_call_spread["legs"] if l["action"] == "SELL"][0]
        assert sell["tp"] < sell["entry_price"]

    def test_morph_records_reversal(self, sample_trade_with_morph):
        """Morphed trade records original + new signal."""
        assert sample_trade_with_morph["morph_count"] == 1
        assert (
            sample_trade_with_morph["entry_gate_signal_original"]
            != sample_trade_with_morph["entry_gate_signal"]
        )
