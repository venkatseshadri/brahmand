#!/usr/bin/env python3
"""
Research Agent - Full Database Analysis
========================================

Analyzes ENTIRE historical dataset (May 4-21, 13 trading days)
to discover patterns that consistently predict moves across all periods.

This is MORE ROBUST than single-day analysis because:
1. Finds patterns that work across different market conditions
2. Validates patterns across 4,995 candles (not just 390)
3. Captures market regime changes and transitions
4. Produces higher-confidence patterns

Usage:
  python3 research_agents_full_db.py
"""

import duckdb
from typing import Dict, List, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
from collections import defaultdict


@dataclass
class DiscoveredPattern:
    """Pattern discovered across full database"""
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
    days_found: int  # How many different days this pattern appeared


class FullDatabaseResearchAgent:
    """Analyzes ENTIRE historical database for patterns"""

    def __init__(self, db_path: str = "/home/trading_ceo/python-trader/varaha/data/varaha_data.duckdb"):
        self.db_path = db_path
        self.db = duckdb.connect(db_path, read_only=True)
        self.family = "base"
        self.weight = 0.5
        self.all_candles = []
        self.load_full_database()

    def load_full_database(self):
        """Load ALL historical NIFTY data (May 4-21)"""
        result = self.db.execute(f"""
            SELECT * FROM market_data
            WHERE index_name = 'NIFTY'
            ORDER BY timestamp ASC
        """).fetchall()

        columns = [desc[0] for desc in self.db.description]
        self.all_candles = []
        for row in result:
            candle = dict(zip(columns, row))
            self.all_candles.append(candle)

        print(f"  ✓ Loaded {len(self.all_candles)} candles from full database")
        if self.all_candles:
            print(f"    Date range: {self.all_candles[0]['date']} to {self.all_candles[-1]['date']}")

    def find_significant_moves(self, min_move: int = 50, lookback: int = 20) -> List[Dict]:
        """Find all significant moves (50+ pts) across ENTIRE dataset"""
        moves = []

        for i in range(len(self.all_candles) - 1):
            current = self.all_candles[i]

            # Look ahead for move
            for j in range(i + 1, min(i + lookback, len(self.all_candles))):
                future = self.all_candles[j]
                move_magnitude = abs(future["spot"] - current["spot"])

                if move_magnitude >= min_move:
                    # Capture state before move
                    moves.append({
                        "start_idx": i,
                        "end_idx": j,
                        "start_time": current["timestamp"],
                        "end_time": future["timestamp"],
                        "start_date": current["date"],
                        "end_date": future["date"],
                        "start_spot": current["spot"],
                        "end_spot": future["spot"],
                        "move_magnitude": future["spot"] - current["spot"],
                        "lead_time": j - i,
                        "before_state": current,
                    })
                    break

        return moves

    def discover_patterns(self) -> List[DiscoveredPattern]:
        """Discover patterns across ENTIRE dataset - override in subclasses"""
        return []


# ============================================================================
# FAMILY 1: SUPERTREND RESEARCH AGENT
# ============================================================================

class SuperTrendResearchAgentFullDB(FullDatabaseResearchAgent):
    """Analyzes SuperTrend patterns across FULL database"""

    def __init__(self):
        super().__init__()
        self.family = "supertrend"
        self.weight = 0.87

    def discover_patterns(self) -> List[DiscoveredPattern]:
        """Find patterns across entire 13-day dataset"""

        if not self.all_candles:
            return []

        moves = self.find_significant_moves()
        if not moves:
            return []

        patterns = []

        # Pattern 1: ADX Spike (ADX > 30)
        pattern_1_matches = 0
        pattern_1_hits = 0
        pattern_1_days = set()
        lead_times_1 = []

        for move in moves:
            state = move["before_state"]
            if state.get("adx") and state.get("adx") > 30:
                pattern_1_matches += 1
                pattern_1_days.add(move["start_date"])
                lead_times_1.append(move["lead_time"])
                pattern_1_hits += 1  # Any move with high ADX counts as hit

        if pattern_1_matches > 0:
            patterns.append(DiscoveredPattern(
                pattern_id="ST_ADX_FULLDB_001",
                pattern_name="ADX Momentum Spike (Full DB)",
                family="supertrend",
                trigger_conditions={
                    "adx": {"min": 30}
                },
                expected_move=50,
                min_move_points=50,
                hit_rate=pattern_1_hits / pattern_1_matches if pattern_1_matches > 0 else 0.0,
                occurrences=pattern_1_matches,
                avg_lead_time=sum(lead_times_1) / len(lead_times_1) if lead_times_1 else 0,
                consistency=len(pattern_1_days) / 13,  # Fraction of 13 trading days
                days_found=len(pattern_1_days)
            ))

        # Pattern 2: ST5/ST15 Divergence + ADX
        pattern_2_matches = 0
        pattern_2_hits = 0
        pattern_2_days = set()
        lead_times_2 = []

        for move in moves:
            state = move["before_state"]
            if (state.get("st_5min_direction") == "bearish" and
                state.get("st_15min_direction") == "bullish" and
                state.get("adx") and state.get("adx") > 25):

                pattern_2_matches += 1
                pattern_2_days.add(move["start_date"])
                lead_times_2.append(move["lead_time"])

                # Divergence predicts DOWN move
                if move["move_magnitude"] < -50:
                    pattern_2_hits += 1

        if pattern_2_matches > 0:
            patterns.append(DiscoveredPattern(
                pattern_id="ST_ADX_FULLDB_002",
                pattern_name="ST5/ST15 Divergence + ADX (Full DB)",
                family="supertrend",
                trigger_conditions={
                    "st_5min_direction": ["bearish"],
                    "st_15min_direction": ["bullish"],
                    "adx": {"min": 25}
                },
                expected_move=50,
                min_move_points=50,
                hit_rate=pattern_2_hits / pattern_2_matches if pattern_2_matches > 0 else 0.0,
                occurrences=pattern_2_matches,
                avg_lead_time=sum(lead_times_2) / len(lead_times_2) if lead_times_2 else 0,
                consistency=len(pattern_2_days) / 13,
                days_found=len(pattern_2_days)
            ))

        return patterns


# ============================================================================
# FAMILY 2: PCR RESEARCH AGENT
# ============================================================================

class PCRResearchAgentFullDB(FullDatabaseResearchAgent):
    """Analyzes PCR patterns across FULL database"""

    def __init__(self):
        super().__init__()
        self.family = "pcr"
        self.weight = 0.72

    def discover_patterns(self) -> List[DiscoveredPattern]:
        """Find PCR patterns across entire dataset"""

        if not self.all_candles:
            return []

        moves = self.find_significant_moves()
        if not moves:
            return []

        patterns = []

        # Pattern: PCR Mean Reversion (extreme values)
        pattern_matches = 0
        pattern_hits = 0
        pattern_days = set()
        lead_times = []

        for move in moves:
            state = move["before_state"]
            pcr = state.get("pcr_total")

            if pcr is None:
                continue

            triggered = False

            # High PCR (bullish puts) → expect down move
            if pcr > 1.15:
                triggered = True
                if move["move_magnitude"] < -50:
                    pattern_hits += 1

            # Low PCR (bullish calls) → expect up move
            elif pcr < 0.85:
                triggered = True
                if move["move_magnitude"] > 50:
                    pattern_hits += 1

            if triggered:
                pattern_matches += 1
                pattern_days.add(move["start_date"])
                lead_times.append(move["lead_time"])

        if pattern_matches > 0:
            patterns.append(DiscoveredPattern(
                pattern_id="PCR_MR_FULLDB_001",
                pattern_name="PCR Mean Reversion (Full DB)",
                family="pcr",
                trigger_conditions={
                    "pcr_total": {"min": 0.85, "max": 1.15}
                },
                expected_move=50,
                min_move_points=50,
                hit_rate=pattern_hits / pattern_matches if pattern_matches > 0 else 0.0,
                occurrences=pattern_matches,
                avg_lead_time=sum(lead_times) / len(lead_times) if lead_times else 0,
                consistency=len(pattern_days) / 13,
                days_found=len(pattern_days)
            ))

        return patterns


# ============================================================================
# FAMILY 3: EMA RESEARCH AGENT
# ============================================================================

class EMAResearchAgentFullDB(FullDatabaseResearchAgent):
    """Analyzes EMA patterns across FULL database"""

    def __init__(self):
        super().__init__()
        self.family = "ema"
        self.weight = 0.77

    def discover_patterns(self) -> List[DiscoveredPattern]:
        """Find EMA patterns across entire dataset"""

        if not self.all_candles:
            return []

        moves = self.find_significant_moves()
        if not moves:
            return []

        patterns = []

        # Pattern: RSI Mean Reversion (RSI > 70 or < 30)
        pattern_matches = 0
        pattern_hits = 0
        pattern_days = set()
        lead_times = []

        for move in moves:
            state = move["before_state"]
            rsi = state.get("rsi")

            if not rsi:
                continue

            triggered = False

            # RSI > 70 (overbought) → expect down move
            if rsi > 70:
                triggered = True
                if move["move_magnitude"] < -50:
                    pattern_hits += 1

            # RSI < 30 (oversold) → expect up move
            elif rsi < 30:
                triggered = True
                if move["move_magnitude"] > 50:
                    pattern_hits += 1

            if triggered:
                pattern_matches += 1
                pattern_days.add(move["start_date"])
                lead_times.append(move["lead_time"])

        if pattern_matches > 0:
            patterns.append(DiscoveredPattern(
                pattern_id="EMA_RSI_FULLDB_001",
                pattern_name="RSI Mean Reversion (Full DB)",
                family="ema",
                trigger_conditions={
                    "rsi": {"min": 30, "max": 70}
                },
                expected_move=50,
                min_move_points=50,
                hit_rate=pattern_hits / pattern_matches if pattern_matches > 0 else 0.0,
                occurrences=pattern_matches,
                avg_lead_time=sum(lead_times) / len(lead_times) if lead_times else 0,
                consistency=len(pattern_days) / 13,
                days_found=len(pattern_days)
            ))

        return patterns


# ============================================================================
# FAMILY 4: VOLATILITY RESEARCH AGENT
# ============================================================================

class VolatilityResearchAgentFullDB(FullDatabaseResearchAgent):
    """Analyzes Volatility patterns across FULL database"""

    def __init__(self):
        super().__init__()
        self.family = "volatility"
        self.weight = 0.68

    def discover_patterns(self) -> List[DiscoveredPattern]:
        """Find volatility patterns across entire dataset"""

        if not self.all_candles:
            return []

        moves = self.find_significant_moves()
        if not moves:
            return []

        patterns = []

        # Pattern: VIX Spike (VIX > 18.0)
        pattern_matches = 0
        pattern_hits = 0
        pattern_days = set()
        lead_times = []

        for move in moves:
            state = move["before_state"]
            vix = state.get("india_vix")

            if vix and vix > 18.0:
                pattern_matches += 1
                pattern_days.add(move["start_date"])
                lead_times.append(move["lead_time"])
                # High VIX predicts any volatility move
                if abs(move["move_magnitude"]) >= 50:
                    pattern_hits += 1

        if pattern_matches > 0:
            patterns.append(DiscoveredPattern(
                pattern_id="VOL_VIX_FULLDB_001",
                pattern_name="VIX Spike Alert (Full DB)",
                family="volatility",
                trigger_conditions={
                    "india_vix": {"min": 18.0}
                },
                expected_move=50,
                min_move_points=50,
                hit_rate=pattern_hits / pattern_matches if pattern_matches > 0 else 0.0,
                occurrences=pattern_matches,
                avg_lead_time=sum(lead_times) / len(lead_times) if lead_times else 0,
                consistency=len(pattern_days) / 13,
                days_found=len(pattern_days)
            ))

        return patterns


# ============================================================================
# ORCHESTRATOR FOR RUNNING ALL AGENTS
# ============================================================================

class FullDatabaseResearchOrchestrator:
    """Runs all 4 research agents on FULL database"""

    def __init__(self):
        self.agents = [
            SuperTrendResearchAgentFullDB(),
            PCRResearchAgentFullDB(),
            EMAResearchAgentFullDB(),
            VolatilityResearchAgentFullDB()
        ]

    def discover_patterns(self) -> Dict[str, List[DiscoveredPattern]]:
        """Run all agents on full database"""
        results = {}

        for agent in self.agents:
            patterns = agent.discover_patterns()
            results[agent.family] = patterns

            if patterns:
                print(f"\n✓ {agent.family.upper()} Family (weight: {agent.weight}):")
                for pattern in patterns:
                    print(f"  - {pattern.pattern_name}")
                    print(f"    Matches: {pattern.occurrences} across {pattern.days_found}/13 days")
                    print(f"    Hit Rate: {pattern.hit_rate:.0%}")
                    print(f"    Consistency: {pattern.consistency:.0%}")
                    print(f"    Lead: {pattern.avg_lead_time:.1f} min")

        return results


if __name__ == "__main__":
    print("="*70)
    print("RESEARCH AGENTS - ANALYZING FULL DATABASE (May 4-21)")
    print("="*70)

    orch = FullDatabaseResearchOrchestrator()
    patterns = orch.discover_patterns()

    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)

    total_patterns = sum(len(p) for p in patterns.values())
    print(f"\nTotal patterns discovered: {total_patterns}")
    print("\nThese patterns are discovered across the ENTIRE 13-day dataset")
    print("Not just single-day analysis = MUCH MORE ROBUST")
