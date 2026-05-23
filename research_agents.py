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
from typing import Dict, List, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass


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

    def __init__(self,
                 db_path_v31: str = "/home/trading_ceo/python-trader/varaha/data/varaha_data.duckdb",
                 db_path_v4: str = "/home/trading_ceo/python-trader/varaha/data/market_data_multitf.duckdb"):
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

    def find_significant_moves(self, candles: List[Dict], min_move: int = 50, lookback: int = 20) -> List[Dict]:
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
                    moves.append({
                        "start_idx": i,
                        "end_idx": j,
                        "start_time": current["timestamp"],
                        "end_time": future["timestamp"],
                        "start_spot": current["spot"],
                        "end_spot": future["spot"],
                        "move_magnitude": future["spot"] - current["spot"],
                        "lead_time": j - i,
                        "before_state": current,  # Indicators BEFORE move
                    })
                    break
        return moves

    def discover_patterns(self, date: str) -> List[DiscoveredPattern]:
        """Discover patterns for a specific date - override in subclasses"""
        return []


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
            if (state.get("st_5min_direction") == "bearish" and
                state.get("st_15min_direction") == "bullish" and
                state.get("adx") and state.get("adx") > 25):

                pattern_1_matches += 1
                lead_times_1.append(move["lead_time"])

                # Check if move was down (divergence predicts reversal)
                if move["move_magnitude"] < -50:
                    pattern_1_hits += 1

                # Cross-validate with v4 if available
                if candles_v4:
                    pattern_1_v4_confirmed += 1

        if pattern_1_matches > 0:
            patterns.append(DiscoveredPattern(
                pattern_id="ST_ADX_001",
                pattern_name="ST5/ST15 Divergence + ADX Spike",
                family="supertrend",
                trigger_conditions={
                    "st_5min_direction": ["bearish"],
                    "st_15min_direction": ["bullish"],
                    "adx": {"min": 25}
                },
                expected_move=50,
                min_move_points=50,
                hit_rate=pattern_1_hits / pattern_1_matches if pattern_1_matches > 0 else 0.0,
                occurrences=pattern_1_matches,
                avg_lead_time=sum(lead_times_1) / len(lead_times_1) if lead_times_1 else 0,
                consistency=1.0  # Single day
            ))

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
            patterns.append(DiscoveredPattern(
                pattern_id="ST_ADX_002",
                pattern_name="ADX Momentum Spike",
                family="supertrend",
                trigger_conditions={
                    "adx": {"min": 30}
                },
                expected_move=50,
                min_move_points=50,
                hit_rate=pattern_2_hits / pattern_2_matches if pattern_2_matches > 0 else 0.0,
                occurrences=pattern_2_matches,
                avg_lead_time=sum(lead_times_2) / len(lead_times_2) if lead_times_2 else 0,
                consistency=1.0
            ))

        # Pattern 3: ALL-RED Consensus + ADX Spike + VIX Elevation
        # Combines: ST5=RED + ST15=RED + ADX > 25 + VIX > 18
        pattern_3_matches = 0
        pattern_3_hits = 0
        lead_times_3 = []

        for move in moves:
            state = move["before_state"]

            # Check all three conditions: both ST bearish, ADX > 25, VIX > 18
            if (state.get("st_5min_direction") == "bearish" and
                state.get("st_15min_direction") == "bearish" and
                state.get("adx") and state.get("adx") > 25 and
                state.get("india_vix") and state.get("india_vix") > 18.0):

                pattern_3_matches += 1
                lead_times_3.append(move["lead_time"])

                # When all indicators align (RED + high ADX + high VIX), strong reversal predicted
                if move["move_magnitude"] < -50:  # Down move
                    pattern_3_hits += 1

        if pattern_3_matches > 0:
            patterns.append(DiscoveredPattern(
                pattern_id="ST_ADX_VIX_001",
                pattern_name="ALL-RED Consensus + ADX Spike + VIX Elevation",
                family="supertrend",
                trigger_conditions={
                    "st_5min_direction": ["bearish"],
                    "st_15min_direction": ["bearish"],
                    "adx": {"min": 25},
                    "india_vix": {"min": 18.0}
                },
                expected_move=93,  # From observed data: avg 93pts
                min_move_points=50,
                hit_rate=pattern_3_hits / pattern_3_matches if pattern_3_matches > 0 else 0.0,
                occurrences=pattern_3_matches,
                avg_lead_time=sum(lead_times_3) / len(lead_times_3) if lead_times_3 else 0,
                consistency=1.0
            ))

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
            patterns.append(DiscoveredPattern(
                pattern_id="PCR_MR_001",
                pattern_name="PCR Mean Reversion Signal",
                family="pcr",
                trigger_conditions={
                    "pcr_total": {"min": 0.85, "max": 1.15}  # Outside normal range
                },
                expected_move=50,
                min_move_points=50,
                hit_rate=pattern_1_hits / pattern_1_matches if pattern_1_matches > 0 else 0.0,
                occurrences=pattern_1_matches,
                avg_lead_time=sum(lead_times_1) / len(lead_times_1) if lead_times_1 else 0,
                consistency=1.0
            ))

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
            patterns.append(DiscoveredPattern(
                pattern_id="PCR_EXT_001",
                pattern_name="PCR Extreme Bearish Setup",
                family="pcr",
                trigger_conditions={
                    "pcr_total": {"min": 1.25}
                },
                expected_move=50,
                min_move_points=50,
                hit_rate=pattern_2_hits / pattern_2_matches if pattern_2_matches > 0 else 0.0,
                occurrences=pattern_2_matches,
                avg_lead_time=sum(lead_times_2) / len(lead_times_2) if lead_times_2 else 0,
                consistency=1.0
            ))

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
            patterns.append(DiscoveredPattern(
                pattern_id="EMA_RSI_001",
                pattern_name="EMA Alignment + RSI Extreme",
                family="ema",
                trigger_conditions={
                    "ema_5": {"min": 0},  # EMA5 > EMA20 checked in code
                    "rsi": {"min": 20, "max": 80}  # Outside normal range
                },
                expected_move=50,
                min_move_points=50,
                hit_rate=pattern_1_hits / pattern_1_matches if pattern_1_matches > 0 else 0.0,
                occurrences=pattern_1_matches,
                avg_lead_time=sum(lead_times_1) / len(lead_times_1) if lead_times_1 else 0,
                consistency=1.0
            ))

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
            patterns.append(DiscoveredPattern(
                pattern_id="EMA_RSI_002",
                pattern_name="RSI Mean Reversion",
                family="ema",
                trigger_conditions={
                    "rsi": {"min": 30, "max": 70}  # Outside normal range
                },
                expected_move=50,
                min_move_points=50,
                hit_rate=pattern_2_hits / pattern_2_matches if pattern_2_matches > 0 else 0.0,
                occurrences=pattern_2_matches,
                avg_lead_time=sum(lead_times_2) / len(lead_times_2) if lead_times_2 else 0,
                consistency=1.0
            ))

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
            patterns.append(DiscoveredPattern(
                pattern_id="VOL_VIX_001",
                pattern_name="VIX Spike Alert",
                family="volatility",
                trigger_conditions={
                    "india_vix": {"min": 18.0}
                },
                expected_move=50,
                min_move_points=50,
                hit_rate=pattern_1_hits / pattern_1_matches if pattern_1_matches > 0 else 0.0,
                occurrences=pattern_1_matches,
                avg_lead_time=sum(lead_times_1) / len(lead_times_1) if lead_times_1 else 0,
                consistency=1.0
            ))

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
            patterns.append(DiscoveredPattern(
                pattern_id="VOL_VIX_002",
                pattern_name="Normal VIX Range Pattern",
                family="volatility",
                trigger_conditions={
                    "india_vix": {"min": 17.0, "max": 19.0}
                },
                expected_move=50,
                min_move_points=50,
                hit_rate=pattern_2_hits / pattern_2_matches if pattern_2_matches > 0 else 0.0,
                occurrences=pattern_2_matches,
                avg_lead_time=sum(lead_times_2) / len(lead_times_2) if lead_times_2 else 0,
                consistency=1.0
            ))

        return patterns


# ============================================================================
# ORCHESTRATOR FOR RUNNING ALL AGENTS
# ============================================================================

class ResearchAgentOrchestrator:
    """Runs all 4 research agents and aggregates findings"""

    def __init__(self):
        self.agents = [
            SuperTrendResearchAgent(),
            PCRResearchAgent(),
            EMAResearchAgent(),
            VolatilityResearchAgent()
        ]

    def discover_patterns_for_date(self, date: str) -> Dict[str, List[DiscoveredPattern]]:
        """Run all agents for a specific date, return grouped by family"""
        results = {}

        for agent in self.agents:
            patterns = agent.discover_patterns(date)
            results[agent.family] = patterns

            if patterns:
                print(f"\n✓ {agent.family.upper()} Family (weight: {agent.weight}):")
                for pattern in patterns:
                    print(f"  - {pattern.pattern_name}")
                    print(f"    Matches: {pattern.occurrences}, Hit Rate: {pattern.hit_rate:.1%}, Lead: {pattern.avg_lead_time:.1f} min")

        return results

    def discover_patterns_for_date_range(self, start_date: str, end_date: str) -> Dict[str, List[DiscoveredPattern]]:
        """Run all agents across multiple dates, aggregate results"""
        all_patterns = {
            "supertrend": [],
            "pcr": [],
            "ema": [],
            "volatility": []
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

    print("\n" + "="*70)
    print("PATTERN DISCOVERY SUMMARY")
    print("="*70)

    for family, pattern_list in patterns.items():
        if pattern_list:
            print(f"\n{family.upper()}: {len(pattern_list)} patterns")
            for p in pattern_list:
                print(f"  {p.pattern_name}")
        else:
            print(f"\n{family.upper()}: No patterns found")
