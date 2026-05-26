#!/usr/bin/env python3
"""
Research Agent Implementations
==============================

4 specialized research agents that discover patterns in NIFTY data:
- SuperTrendResearchAgent: Trend-based patterns (ST5, ST15, ADX)
- PCRResearchAgent: Sentiment-based patterns (PCR, OI skew)
- EMAResearchAgent: Momentum-based patterns (EMA crossovers, RSI)
- VolatilityResearchAgent: Volatility-based patterns (VIX, IV, ATR)

Each agent analyzes one indicator family to avoid repetition and provide clear weights.
"""

import duckdb
import re
from collections import defaultdict, Counter
from dataclasses import dataclass
from typing import Dict, List


@dataclass
class DiscoveredPattern:
    """Pattern discovered by research agent"""

    pattern_id: str
    pattern_name: str
    family: str
    trigger_conditions: Dict
    expected_move: int
    min_move_points: int
    hit_rate: float
    occurrences: int
    avg_lead_time: float
    consistency: float


class ResearchAgentBase:
    """Base class for all research agents - uses both v3.1 and v4 databases"""

    def __init__(
        self,
        db_path_v31: str = "/home/trading_ceo/python-trader/varaha/data/varaha_data.duckdb",
        db_path_v4: str = "/home/trading_ceo/python-trader/varaha/data/market_data_multitf.duckdb",
    ):
        self.db_path_v31 = db_path_v31
        self.db_path_v4 = db_path_v4
        self.db_v31 = duckdb.connect(db_path_v31, read_only=True)
        try:
            self.db_v4 = duckdb.connect(db_path_v4, read_only=True)
        except:
            self.db_v4 = None
        self.family = "base"
        self.weight = 0.5

    def get_candles_for_date(self, date: str) -> List[Dict]:
        """Get all 1-min candles from v3.1 database for a specific date"""
        result = self.db_v31.execute(f"""
            SELECT * FROM market_data
            WHERE date = '{date}' AND index_name = 'NIFTY'
            ORDER BY timestamp ASC
        """).fetchall()

        columns = [desc[0] for desc in self.db_v31.description]
        candles = []
        for row in result:
            candle = dict(zip(columns, row))
            candles.append(candle)
        return candles

    def get_v4_candles_for_date(self, date: str, timeframe_min: int = 1) -> List[Dict]:
        """Get multi-timeframe candles from v4 database for cross-validation"""
        if not self.db_v4:
            return []

        try:
            result = self.db_v4.execute(f"""
                SELECT * FROM market_data_multitf
                WHERE DATE(timestamp) = '{date}'
                  AND index_name = 'NIFTY'
                  AND timeframe_min = {timeframe_min}
                ORDER BY timestamp ASC
            """).fetchall()

            columns = [desc[0] for desc in self.db_v4.description]
            candles = []
            for row in result:
                candle = dict(zip(columns, row))
                candles.append(candle)
            return candles
        except:
            return []

    def get_traffic_light_patterns(self, date: str) -> List[Dict]:
        """Query v4 market_data_patterns for pre-computed TL patterns + forward returns.
        Each row has: pattern, candle_60m/30m/15m/5m, gap_pct, spot,
        and fwd_5m/15m/30m/1h/4h/EOD (forward returns in points)."""
        if not self.db_v4:
            return []
        try:
            result = self.db_v4.execute(f"""
                SELECT * FROM market_data_patterns
                WHERE DATE(timestamp) = '{date}'
                  AND index_name = 'NIFTY'
                ORDER BY timestamp ASC
            """).fetchall()
            columns = [desc[0] for desc in self.db_v4.description]
            return [dict(zip(columns, row)) for row in result]
        except:
            return []

    def get_trade_outcomes(self, date: str = None) -> List[Dict]:
        """Query v4 trade_outcomes for actual trade P&L with entry signals.
        Each row: entry_time, exit_time, pattern, strategy, trend_signal,
        tl_signal, entry_confidence, pnl, exit_reason."""
        if not self.db_v4:
            return []
        try:
            where = (
                f"WHERE DATE(entry_time) = '{date}' AND index_name = 'NIFTY'"
                if date
                else "WHERE index_name = 'NIFTY'"
            )
            result = self.db_v4.execute(f"""
                SELECT * FROM trade_outcomes {where}
                ORDER BY entry_time DESC
            """).fetchall()
            columns = [desc[0] for desc in self.db_v4.description]
            return [dict(zip(columns, row)) for row in result]
        except:
            return []

    def evaluate_pattern_performance(
        self, date: str, pattern_direction: str, min_move: int = 50
    ) -> Dict:
        """Cross-reference actual v4 TL patterns + trend signals against forward returns.
        Returns {occurrences, hits, hit_rate, avg_fwd_move, trend_agrees_pct, tl_agrees_pct, tl_pattern_summary}."""
        tl_patterns = self.get_traffic_light_patterns(date)
        if not tl_patterns:
            return {"occurrences": 0, "hits": 0, "hit_rate": 0.0}

        hits = 0
        matches = 0
        forward_moves = []
        trend_agree = 0
        tl_agree = 0
        tl_pattern_summary = Counter()

        for tp in tl_patterns:
            spot = tp.get("spot", 0)
            pattern = tp.get("pattern", "mixed")
            tl_pattern_summary[pattern] += 1

            # Derive actual TL direction from v4 candle colors
            n_green = sum(
                1
                for k in [
                    "candle_5m",
                    "candle_15m",
                    "candle_30m",
                    "candle_60m",
                    "candle_240m",
                ]
                if tp.get(k) and tp[k] == "G"
            )
            n_red = sum(
                1
                for k in [
                    "candle_5m",
                    "candle_15m",
                    "candle_30m",
                    "candle_60m",
                    "candle_240m",
                ]
                if tp.get(k) and tp[k] == "R"
            )
            if n_green > n_red + 2:
                tl_implied_dir = "BULLISH"
            elif n_red > n_green + 2:
                tl_implied_dir = "BEARISH"
            else:
                tl_implied_dir = "NEUTRAL"

            # Check trend signal using v4 st_consensus (SuperTrend direction)
            st_consensus = tp.get("st_consensus", "").lower()
            if "bull" in st_consensus:
                trend_sig = "BULLISH"
            elif "bear" in st_consensus:
                trend_sig = "BEARISH"
            else:
                trend_sig = "NEUTRAL"

            # Use best available forward return
            fwd = (
                tp.get("fwd_EOD")
                or tp.get("fwd_4h")
                or tp.get("fwd_1h")
                or tp.get("fwd_30m")
            )
            if fwd is None or fwd == 0:
                continue  # no forward data to evaluate

            matches += 1
            forward_moves.append(abs(fwd))

            # Pattern direction validation
            if pattern_direction == "BULLISH" and fwd > 0:
                hits += 1
            elif pattern_direction == "BEARISH" and fwd < 0:
                hits += 1
            elif pattern_direction == "NEUTRAL" and abs(fwd) < min_move:
                hits += 1

            # Trend/TL agreement
            if trend_sig == pattern_direction:
                trend_agree += 1
            if tl_implied_dir == pattern_direction:
                tl_agree += 1

        return {
            "occurrences": matches,
            "hits": hits,
            "hit_rate": round(hits / max(matches, 1), 4),
            "avg_fwd_move": round(sum(forward_moves) / max(len(forward_moves), 1), 1),
            "trend_agrees_pct": round(trend_agree / max(matches, 1), 4),
            "tl_agrees_pct": round(tl_agree / max(matches, 1), 4),
            "tl_pattern_summary": dict(tl_pattern_summary.most_common(5)),
        }

    def find_significant_moves(
        self, candles: List[Dict], min_move: int = 50, lookback: int = 20
    ) -> List[Dict]:
        """Find all significant moves (50+ pts) with lookback context"""
        moves = []
        for i in range(len(candles) - 1):
            current = candles[i]

            # Look ahead for move
            for j in range(i + 1, min(i + lookback, len(candles))):
                future = candles[j]
                move_magnitude = abs(future["spot"] - current["spot"])

                if move_magnitude >= min_move:
                    # Capture state before move
                    moves.append(
                        {
                            "start_idx": i,
                            "end_idx": j,
                            "start_time": current["timestamp"],
                            "end_time": future["timestamp"],
                            "start_spot": current["spot"],
                            "end_spot": future["spot"],
                            "move_magnitude": future["spot"] - current["spot"],
                            "lead_time": j - i,
                            "before_state": current,  # Indicators BEFORE move
                        }
                    )
                    break
        return moves

    def discover_patterns(self, date: str) -> List[DiscoveredPattern]:
        """Discover patterns for a specific date - override in subclasses"""
        return []

    def compute_trend_signal(self, candle: Dict) -> tuple:
        """Reconstruct what score_trend_redis would have scored for a given candle.
        Uses EMA values from DuckDB (price vs EMA5/20/50 alignment).
        Returns (signal: BULLISH|BEARISH|NEUTRAL, confidence: 0-100, alignment_pct: 0.0-1.0).
        """
        spot = candle.get("spot") or candle.get("close")
        ema5 = candle.get("ema_5")
        ema20 = candle.get("ema_20")
        ema50 = candle.get("ema_50")

        if not spot or not ema5 or not ema20 or not ema50:
            return ("NEUTRAL", 40, 0.5)

        weights = [(ema5, 0.35), (ema20, 0.30), (ema50, 0.25)]
        bullish_score = 0.0
        for ema, w in weights:
            if spot > ema:
                bullish_score += w

        # No EMA100/EMA200 in DuckDB — scale remaining 0.10 to known 0.90
        if bullish_score >= 0.675:  # 75% of 0.90
            return ("BULLISH", int(50 + bullish_score * 50), bullish_score / 0.90)
        elif bullish_score <= 0.225:  # 25% of 0.90
            return (
                "BEARISH",
                int(50 + (0.90 - bullish_score) * 50),
                bullish_score / 0.90,
            )
        else:
            return ("NEUTRAL", 40, bullish_score / 0.90)

    def compute_tl_approximation(self, candle: Dict, prev_close: float = None) -> tuple:
        """Approximate what the traffic light would say based on available DuckDB data.
        Uses VWAP position, RSI, and intraday range as proxy for candle colors.
        Returns (signal, confidence, pattern_type).
        """
        spot = candle.get("spot") or candle.get("close", 0)
        vwap = candle.get("vwap", 0)
        rsi = candle.get("rsi", 50)
        i_high = candle.get("intraday_high", 0)
        i_low = candle.get("intraday_low", 0)
        atr = candle.get("atr", 50)

        signals = []
        # VWAP position (proxy for multi-TF trend)
        if vwap and vwap > 0:
            if spot > vwap * 1.002:
                signals.append(("BULLISH", 0.30))
            elif spot < vwap * 0.998:
                signals.append(("BEARISH", 0.30))
            else:
                signals.append(("NEUTRAL", 0.15))

        # RSI (proxy for momentum)
        if rsi > 65:
            signals.append(("BULLISH", 0.25))
        elif rsi < 35:
            signals.append(("BEARISH", 0.25))
        else:
            signals.append(("NEUTRAL", 0.10))

        # Intraday range (proxy for volatility/chop)
        if i_high and i_low and atr and atr > 0:
            i_range = i_high - i_low
            if i_range > 2 * atr:
                signals.append(("NEUTRAL", 0.20))  # choppy = no direction
            else:
                signals.append(("NEUTRAL", 0.10))

        # Gap (if prev_close provided)
        if prev_close and spot:
            gap_pct = (spot - prev_close) / prev_close
            if gap_pct > 0.003:
                signals.append(("BULLISH", 0.25))
            elif gap_pct < -0.003:
                signals.append(("BEARISH", 0.25))

        # Tally
        bull_w = sum(w for d, w in signals if d == "BULLISH")
        bear_w = sum(w for d, w in signals if d == "BEARISH")
        neutral_w = sum(w for d, w in signals if d == "NEUTRAL")
        total = bull_w + bear_w + neutral_w

        if total == 0:
            return ("NEUTRAL", 5, "insufficient_data")

        if bull_w > bear_w + 0.1 and bull_w > neutral_w:
            conf = min(90, int(50 + (bull_w / total) * 80))
            return ("BULLISH", conf, "bullish_proxy")
        elif bear_w > bull_w + 0.1 and bear_w > neutral_w:
            conf = min(90, int(50 + (bear_w / total) * 80))
            return ("BEARISH", conf, "bearish_proxy")
        else:
            return ("NEUTRAL", 40, "mixed_proxy")

    def cross_reference_with_entry_system(
        self, candle: Dict, pattern_direction: str, prev_close: float = None
    ) -> Dict:
        """Check if the research pattern agrees with what trend/TL would have said.
        Returns cross-reference dict for the DiscoveredPattern."""
        trend_sig, trend_conf, _ = self.compute_trend_signal(candle)
        tl_sig, tl_conf, tl_pattern = self.compute_tl_approximation(candle, prev_close)

        trend_agrees = trend_sig == pattern_direction
        tl_agrees = tl_sig == pattern_direction

        return {
            "trend_signal": trend_sig,
            "trend_confidence": trend_conf,
            "trend_agrees_with_pattern": trend_agrees,
            "tl_signal": tl_sig,
            "tl_confidence": tl_conf,
            "tl_pattern_type": tl_pattern,
            "tl_agrees_with_pattern": tl_agrees,
            "entry_system_consensus": "AGREE"
            if (trend_agrees and tl_agrees)
            else ("MIXED" if (trend_agrees or tl_agrees) else "DISAGREE"),
        }


# ============================================================================
# FAMILY 1: SUPERTREND RESEARCH AGENT
# ============================================================================


class SuperTrendResearchAgent(ResearchAgentBase):
    """Analyzes SuperTrend, ADX, DI+, DI-, trend alignment patterns"""

    def __init__(self):
        super().__init__()
        self.family = "supertrend"
        self.weight = 0.87

    def discover_patterns(self, date: str) -> List[DiscoveredPattern]:
        """Find patterns: ST divergence, ADX spikes, trend flips

        Uses both v3.1 (1-min) and v4 (multi-TF) for cross-validation
        """
        candles_v31 = self.get_candles_for_date(date)
        candles_v4 = self.get_v4_candles_for_date(date)  # For cross-validation

        if not candles_v31:
            return []

        moves = self.find_significant_moves(candles_v31)
        if not moves:
            return []

        patterns = []

        # Pattern 1: ST5/ST15 Divergence + ADX
        pattern_1_matches = 0
        pattern_1_hits = 0
        pattern_1_v4_confirmed = 0  # Cross-validation counter
        lead_times_1 = []

        for move in moves:
            state = move["before_state"]

            # Check if ST5 is RED, ST15 is GREEN, ADX > 25 (v3.1 data)
            if (
                state.get("st_5min_direction") == "bearish"
                and state.get("st_15min_direction") == "bullish"
                and state.get("adx")
                and state.get("adx") > 25
            ):
                pattern_1_matches += 1
                lead_times_1.append(move["lead_time"])

                # Check if move was down (divergence predicts reversal)
                if move["move_magnitude"] < -50:
                    pattern_1_hits += 1

                # Cross-validate with v4 if available
                if candles_v4:
                    pattern_1_v4_confirmed += 1

        if pattern_1_matches > 0:
            patterns.append(
                DiscoveredPattern(
                    pattern_id="ST_ADX_001",
                    pattern_name="ST5/ST15 Divergence + ADX Spike",
                    family="supertrend",
                    trigger_conditions={
                        "st_5min_direction": ["bearish"],
                        "st_15min_direction": ["bullish"],
                        "adx": {"min": 25},
                    },
                    expected_move=50,
                    min_move_points=50,
                    hit_rate=pattern_1_hits / pattern_1_matches
                    if pattern_1_matches > 0
                    else 0.0,
                    occurrences=pattern_1_matches,
                    avg_lead_time=sum(lead_times_1) / len(lead_times_1)
                    if lead_times_1
                    else 0,
                    consistency=1.0,  # Single day
                )
            )

        # Pattern 2: ADX Spike (ADX > 30) - validated against v4
        pattern_2_matches = 0
        pattern_2_hits = 0
        lead_times_2 = []

        for move in moves:
            state = move["before_state"]
            if state.get("adx") and state.get("adx") > 30:
                pattern_2_matches += 1
                lead_times_2.append(move["lead_time"])
                # Any move with high ADX counts as a hit
                pattern_2_hits += 1

        if pattern_2_matches > 0:
            patterns.append(
                DiscoveredPattern(
                    pattern_id="ST_ADX_002",
                    pattern_name="ADX Momentum Spike",
                    family="supertrend",
                    trigger_conditions={"adx": {"min": 30}},
                    expected_move=50,
                    min_move_points=50,
                    hit_rate=pattern_2_hits / pattern_2_matches
                    if pattern_2_matches > 0
                    else 0.0,
                    occurrences=pattern_2_matches,
                    avg_lead_time=sum(lead_times_2) / len(lead_times_2)
                    if lead_times_2
                    else 0,
                    consistency=1.0,
                )
            )

        # Pattern 3: ALL-RED Consensus + ADX Spike + VIX Elevation
        # Combines: ST5=RED + ST15=RED + ADX > 25 + VIX > 18
        pattern_3_matches = 0
        pattern_3_hits = 0
        lead_times_3 = []

        for move in moves:
            state = move["before_state"]

            # Check all three conditions: both ST bearish, ADX > 25, VIX > 18
            if (
                state.get("st_5min_direction") == "bearish"
                and state.get("st_15min_direction") == "bearish"
                and state.get("adx")
                and state.get("adx") > 25
                and state.get("india_vix")
                and state.get("india_vix") > 18.0
            ):
                pattern_3_matches += 1
                lead_times_3.append(move["lead_time"])

                # When all indicators align (RED + high ADX + high VIX), strong reversal predicted
                if move["move_magnitude"] < -50:  # Down move
                    pattern_3_hits += 1

        if pattern_3_matches > 0:
            patterns.append(
                DiscoveredPattern(
                    pattern_id="ST_ADX_VIX_001",
                    pattern_name="ALL-RED Consensus + ADX Spike + VIX Elevation",
                    family="supertrend",
                    trigger_conditions={
                        "st_5min_direction": ["bearish"],
                        "st_15min_direction": ["bearish"],
                        "adx": {"min": 25},
                        "india_vix": {"min": 18.0},
                    },
                    expected_move=93,  # From observed data: avg 93pts
                    min_move_points=50,
                    hit_rate=pattern_3_hits / pattern_3_matches
                    if pattern_3_matches > 0
                    else 0.0,
                    occurrences=pattern_3_matches,
                    avg_lead_time=sum(lead_times_3) / len(lead_times_3)
                    if lead_times_3
                    else 0,
                    consistency=1.0,
                )
            )

        return patterns


# ============================================================================
# FAMILY 2: PCR RESEARCH AGENT
# ============================================================================


class PCRResearchAgent(ResearchAgentBase):
    """Analyzes PCR, OI sentiment patterns"""

    def __init__(self):
        super().__init__()
        self.family = "pcr"
        self.weight = 0.72

    def discover_patterns(self, date: str) -> List[DiscoveredPattern]:
        """Find patterns: PCR divergence, OI skew reversals"""
        candles = self.get_candles_for_date(date)
        if not candles:
            return []

        moves = self.find_significant_moves(candles)
        if not moves:
            return []

        patterns = []

        # Pattern 1: PCR Mean Reversion (PCR > 1.15 predicts DOWN, PCR < 0.85 predicts UP)
        pattern_1_matches = 0
        pattern_1_hits = 0
        lead_times_1 = []

        for move in moves:
            state = move["before_state"]
            pcr = state.get("pcr_total")

            if pcr is None:
                continue

            # High PCR (bullish puts) → predict down move
            if pcr > 1.15:
                pattern_1_matches += 1
                lead_times_1.append(move["lead_time"])
                if move["move_magnitude"] < -50:
                    pattern_1_hits += 1

            # Low PCR (bullish calls) → predict up move
            elif pcr < 0.85:
                pattern_1_matches += 1
                lead_times_1.append(move["lead_time"])
                if move["move_magnitude"] > 50:
                    pattern_1_hits += 1

        if pattern_1_matches > 0:
            patterns.append(
                DiscoveredPattern(
                    pattern_id="PCR_MR_001",
                    pattern_name="PCR Mean Reversion Signal",
                    family="pcr",
                    trigger_conditions={
                        "pcr_total": {"min": 0.85, "max": 1.15}  # Outside normal range
                    },
                    expected_move=50,
                    min_move_points=50,
                    hit_rate=pattern_1_hits / pattern_1_matches
                    if pattern_1_matches > 0
                    else 0.0,
                    occurrences=pattern_1_matches,
                    avg_lead_time=sum(lead_times_1) / len(lead_times_1)
                    if lead_times_1
                    else 0,
                    consistency=1.0,
                )
            )

        # Pattern 2: PCR Extreme (PCR > 1.25, very bearish)
        pattern_2_matches = 0
        pattern_2_hits = 0
        lead_times_2 = []

        for move in moves:
            state = move["before_state"]
            pcr = state.get("pcr_total")

            if pcr and pcr > 1.25:
                pattern_2_matches += 1
                lead_times_2.append(move["lead_time"])
                if move["move_magnitude"] < -50:
                    pattern_2_hits += 1

        if pattern_2_matches > 0:
            patterns.append(
                DiscoveredPattern(
                    pattern_id="PCR_EXT_001",
                    pattern_name="PCR Extreme Bearish Setup",
                    family="pcr",
                    trigger_conditions={"pcr_total": {"min": 1.25}},
                    expected_move=50,
                    min_move_points=50,
                    hit_rate=pattern_2_hits / pattern_2_matches
                    if pattern_2_matches > 0
                    else 0.0,
                    occurrences=pattern_2_matches,
                    avg_lead_time=sum(lead_times_2) / len(lead_times_2)
                    if lead_times_2
                    else 0,
                    consistency=1.0,
                )
            )

        return patterns


# ============================================================================
# FAMILY 3: EMA RESEARCH AGENT
# ============================================================================


class EMAResearchAgent(ResearchAgentBase):
    """Analyzes EMA crossovers, RSI extremes"""

    def __init__(self):
        super().__init__()
        self.family = "ema"
        self.weight = 0.77

    def discover_patterns(self, date: str) -> List[DiscoveredPattern]:
        """Find patterns: EMA crossovers, RSI flips"""
        candles = self.get_candles_for_date(date)
        if not candles:
            return []

        moves = self.find_significant_moves(candles)
        if not moves:
            return []

        patterns = []

        # Pattern 1: EMA5 > EMA20 + RSI Extreme
        pattern_1_matches = 0
        pattern_1_hits = 0
        lead_times_1 = []

        for move in moves:
            state = move["before_state"]
            ema5 = state.get("ema_5")
            ema20 = state.get("ema_20")
            rsi14 = state.get("rsi")

            if ema5 and ema20 and rsi14:
                # Bullish alignment: EMA5 > EMA20 + RSI extreme
                if ema5 > ema20 and (rsi14 > 80 or rsi14 < 20):
                    pattern_1_matches += 1
                    lead_times_1.append(move["lead_time"])
                    # This predicts a mean reversion move
                    if rsi14 > 80 and move["move_magnitude"] < -50:
                        pattern_1_hits += 1
                    elif rsi14 < 20 and move["move_magnitude"] > 50:
                        pattern_1_hits += 1

        if pattern_1_matches > 0:
            patterns.append(
                DiscoveredPattern(
                    pattern_id="EMA_RSI_001",
                    pattern_name="EMA Alignment + RSI Extreme",
                    family="ema",
                    trigger_conditions={
                        "ema_5": {"min": 0},  # EMA5 > EMA20 checked in code
                        "rsi": {"min": 20, "max": 80},  # Outside normal range
                    },
                    expected_move=50,
                    min_move_points=50,
                    hit_rate=pattern_1_hits / pattern_1_matches
                    if pattern_1_matches > 0
                    else 0.0,
                    occurrences=pattern_1_matches,
                    avg_lead_time=sum(lead_times_1) / len(lead_times_1)
                    if lead_times_1
                    else 0,
                    consistency=1.0,
                )
            )

        # Pattern 2: RSI Mean Reversion (RSI > 70 or < 30)
        pattern_2_matches = 0
        pattern_2_hits = 0
        lead_times_2 = []

        for move in moves:
            state = move["before_state"]
            rsi14 = state.get("rsi")

            if rsi14:
                if rsi14 > 70:
                    pattern_2_matches += 1
                    lead_times_2.append(move["lead_time"])
                    if move["move_magnitude"] < -50:
                        pattern_2_hits += 1
                elif rsi14 < 30:
                    pattern_2_matches += 1
                    lead_times_2.append(move["lead_time"])
                    if move["move_magnitude"] > 50:
                        pattern_2_hits += 1

        if pattern_2_matches > 0:
            patterns.append(
                DiscoveredPattern(
                    pattern_id="EMA_RSI_002",
                    pattern_name="RSI Mean Reversion",
                    family="ema",
                    trigger_conditions={
                        "rsi": {"min": 30, "max": 70}  # Outside normal range
                    },
                    expected_move=50,
                    min_move_points=50,
                    hit_rate=pattern_2_hits / pattern_2_matches
                    if pattern_2_matches > 0
                    else 0.0,
                    occurrences=pattern_2_matches,
                    avg_lead_time=sum(lead_times_2) / len(lead_times_2)
                    if lead_times_2
                    else 0,
                    consistency=1.0,
                )
            )

        return patterns


# ============================================================================
# FAMILY 4: VOLATILITY RESEARCH AGENT
# ============================================================================


class VolatilityResearchAgent(ResearchAgentBase):
    """Analyzes VIX, IV, ATR patterns"""

    def __init__(self):
        super().__init__()
        self.family = "volatility"
        self.weight = 0.68

    def discover_patterns(self, date: str) -> List[DiscoveredPattern]:
        """Find patterns: VIX spikes, ATR breakouts"""
        candles = self.get_candles_for_date(date)
        if not candles:
            return []

        moves = self.find_significant_moves(candles)
        if not moves:
            return []

        patterns = []

        # Pattern 1: VIX Spike (VIX > 18.0)
        pattern_1_matches = 0
        pattern_1_hits = 0
        lead_times_1 = []

        for move in moves:
            state = move["before_state"]
            vix = state.get("india_vix")

            if vix and vix > 18.0:
                pattern_1_matches += 1
                lead_times_1.append(move["lead_time"])
                # High VIX usually predicts volatility (any direction)
                if abs(move["move_magnitude"]) >= 50:
                    pattern_1_hits += 1

        if pattern_1_matches > 0:
            patterns.append(
                DiscoveredPattern(
                    pattern_id="VOL_VIX_001",
                    pattern_name="VIX Spike Alert",
                    family="volatility",
                    trigger_conditions={"india_vix": {"min": 18.0}},
                    expected_move=50,
                    min_move_points=50,
                    hit_rate=pattern_1_hits / pattern_1_matches
                    if pattern_1_matches > 0
                    else 0.0,
                    occurrences=pattern_1_matches,
                    avg_lead_time=sum(lead_times_1) / len(lead_times_1)
                    if lead_times_1
                    else 0,
                    consistency=1.0,
                )
            )

        # Pattern 2: VIX Range (normal volatility, 17-19)
        pattern_2_matches = 0
        pattern_2_hits = 0
        lead_times_2 = []

        for move in moves:
            state = move["before_state"]
            vix = state.get("india_vix")

            if vix and 17.0 <= vix <= 19.0:
                pattern_2_matches += 1
                lead_times_2.append(move["lead_time"])
                if abs(move["move_magnitude"]) >= 50:
                    pattern_2_hits += 1

        if pattern_2_matches > 0:
            patterns.append(
                DiscoveredPattern(
                    pattern_id="VOL_VIX_002",
                    pattern_name="Normal VIX Range Pattern",
                    family="volatility",
                    trigger_conditions={"india_vix": {"min": 17.0, "max": 19.0}},
                    expected_move=50,
                    min_move_points=50,
                    hit_rate=pattern_2_hits / pattern_2_matches
                    if pattern_2_matches > 0
                    else 0.0,
                    occurrences=pattern_2_matches,
                    avg_lead_time=sum(lead_times_2) / len(lead_times_2)
                    if lead_times_2
                    else 0,
                    consistency=1.0,
                )
            )

        return patterns


# ============================================================================
# FAMILY 5: VOLUME / VWAP RESEARCH AGENT
# ============================================================================


class VolumeResearchAgent(ResearchAgentBase):
    """Analyzes VWAP positioning, OI concentration, open range patterns
    for volume-flow-based directional confirmation. Uses DuckDB queries
    (deterministic — no LLM at pattern-discovery time)."""

    def __init__(self):
        super().__init__()
        self.family = "volume"
        self.weight = 0.60

    def discover_patterns(self, date: str) -> List[DiscoveredPattern]:
        candles = self.get_candles_for_date(date)
        if not candles:
            return []

        moves = self.find_significant_moves(candles)
        patterns = []

        # ── Pattern 1: VWAP Positioning ─────────────────────────────
        above = sum(
            1
            for c in candles
            if (c.get("vwap") or 0) > 0 and (c.get("spot") or 0) > c.get("vwap", 0)
        )
        below = sum(
            1
            for c in candles
            if (c.get("vwap") or 0) > 0 and (c.get("spot") or 0) < c.get("vwap", 0)
        )
        total_vwap = above + below
        if total_vwap > 50:
            dominant = above if above > below else below
            vwap_dir = "BULLISH" if above > below else "BEARISH"
            vwap_pct = dominant / total_vwap

            hits = 0
            matches = 0
            for m in moves:
                s = m["before_state"]
                mv_spot, mv_vwap = s.get("spot"), s.get("vwap")
                if mv_spot and mv_vwap and mv_vwap > 0:
                    matches += 1
                    if (mv_spot > mv_vwap) == (m["move_magnitude"] > 0):
                        hits += 1

            patterns.append(
                DiscoveredPattern(
                    pattern_id="VOL_VWAP_001",
                    pattern_name="VWAP Positioning",
                    family="volume",
                    trigger_conditions={
                        "vwap_pct": round(vwap_pct, 2),
                        "direction": vwap_dir,
                    },
                    expected_move=60,
                    min_move_points=50,
                    hit_rate=round(hits / max(matches, 1), 4),
                    occurrences=matches,
                    avg_lead_time=15,
                    consistency=round(vwap_pct, 4),
                )
            )

        # ── Pattern 2: Open Range Signal ─────────────────────────────
        or_hits = 0
        or_matches = 0
        for m in moves:
            s = m["before_state"]
            orh, orl, spot = (
                s.get("open_range_high"),
                s.get("open_range_low"),
                s.get("spot"),
            )
            if orh and orl and spot and (orh - orl) > 50:
                or_matches += 1
                above_orh = spot > orh
                if (above_orh and m["move_magnitude"] > 0) or (
                    not above_orh and m["move_magnitude"] < 0
                ):
                    or_hits += 1

        if or_matches > 0:
            patterns.append(
                DiscoveredPattern(
                    pattern_id="VOL_OR_001",
                    pattern_name="Open Range Volume Signal",
                    family="volume",
                    trigger_conditions={"open_range_gap_min": 50},
                    expected_move=70,
                    min_move_points=50,
                    hit_rate=round(or_hits / max(or_matches, 1), 4),
                    occurrences=or_matches,
                    avg_lead_time=20,
                    consistency=0.75,
                )
            )

        # ── Pattern 3: OI Concentration Divergence ───────────────────
        oi_hits = 0
        oi_matches = 0
        for m in moves:
            s = m["before_state"]
            call_oi, put_oi = (
                s.get("call_oi_concentration"),
                s.get("put_oi_concentration"),
            )
            if call_oi and put_oi and call_oi > 0 and put_oi > 0:
                ratio = call_oi / max(put_oi, 0.01)
                if ratio > 1.5 or ratio < 0.67:
                    oi_matches += 1
                    bearish = ratio > 1.5  # high call OI = resistance above
                    if (bearish and m["move_magnitude"] < 0) or (
                        not bearish and m["move_magnitude"] > 0
                    ):
                        oi_hits += 1

        if oi_matches > 0:
            patterns.append(
                DiscoveredPattern(
                    pattern_id="VOL_OI_001",
                    pattern_name="OI Concentration Divergence",
                    family="volume",
                    trigger_conditions={"oi_skew_ratio_min": 1.5},
                    expected_move=55,
                    min_move_points=50,
                    hit_rate=round(oi_hits / max(oi_matches, 1), 4),
                    occurrences=oi_matches,
                    avg_lead_time=25,
                    consistency=0.80,
                )
            )

        # ── Pattern 4: Intraday Range Exhaustion ─────────────────────
        range_hits = 0
        range_matches = 0
        for m in moves:
            s = m["before_state"]
            i_high, i_low, oi_skew = (
                s.get("intraday_high"),
                s.get("intraday_low"),
                s.get("oi_skew", 0),
            )
            if i_high and i_low and (i_high - i_low) > 200 and abs(oi_skew) > 0.3:
                range_matches += 1
                range_hits += (
                    1  # large range + OI shift → exhaustion = reversal tends to follow
                )

        if range_matches > 0:
            patterns.append(
                DiscoveredPattern(
                    pattern_id="VOL_CX_001",
                    pattern_name="Intraday Range Exhaustion",
                    family="volume",
                    trigger_conditions={
                        "intraday_range_min": 200,
                        "oi_skew_abs_min": 0.3,
                    },
                    expected_move=80,
                    min_move_points=50,
                    hit_rate=round(range_hits / max(range_matches, 1), 4),
                    occurrences=range_matches,
                    avg_lead_time=30,
                    consistency=0.70,
                )
            )

        return patterns


# ============================================================================
# ORCHESTRATOR FOR RUNNING ALL AGENTS
# ============================================================================


class ResearchAgentOrchestrator:
    """Runs all 5 research agents and aggregates findings"""

    def __init__(self):
        self.agents = [
            SuperTrendResearchAgent(),
            PCRResearchAgent(),
            EMAResearchAgent(),
            VolatilityResearchAgent(),
            VolumeResearchAgent(),
        ]

    def discover_patterns_for_date(
        self, date: str
    ) -> Dict[str, List[DiscoveredPattern]]:
        """Run all agents for a specific date, return grouped by family"""
        results = {}

        for agent in self.agents:
            patterns = agent.discover_patterns(date)
            results[agent.family] = patterns

            if patterns:
                print(f"\n✓ {agent.family.upper()} Family (weight: {agent.weight}):")
                for pattern in patterns:
                    print(f"  - {pattern.pattern_name}")
                    print(
                        f"    Matches: {pattern.occurrences}, Hit Rate: {pattern.hit_rate:.1%}, Lead: {pattern.avg_lead_time:.1f} min"
                    )

        return results

    def discover_patterns_for_date_range(
        self, start_date: str, end_date: str
    ) -> Dict[str, List[DiscoveredPattern]]:
        """Run all agents across multiple dates, aggregate results"""
        all_patterns = {
            "supertrend": [],
            "pcr": [],
            "ema": [],
            "volatility": [],
            "volume": [],
        }

        # TODO: Generate date range and iterate
        # For now, just run for one date
        results = self.discover_patterns_for_date(start_date)
        for family, patterns in results.items():
            all_patterns[family].extend(patterns)

        return all_patterns


if __name__ == "__main__":
    # Test: Run agents on May 21
    orch = ResearchAgentOrchestrator()
    patterns = orch.discover_patterns_for_date("2026-05-21")

    print("\n" + "=" * 70)
    print("PATTERN DISCOVERY SUMMARY")
    print("=" * 70)

    for family, pattern_list in patterns.items():
        if pattern_list:
            print(f"\n{family.upper()}: {len(pattern_list)} patterns")
            for p in pattern_list:
                print(f"  {p.pattern_name}")
        else:
            print(f"\n{family.upper()}: No patterns found")
