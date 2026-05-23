#!/usr/bin/env python3
"""
Entry Agent
===========

Loads approved patterns from ChromaDB and generates real-time trading signals.
Runs during market hours (9:15 AM - 3:30 PM) to check every 1-min candle.

Usage:
  agent = EntryAgent()
  signal = agent.entry_check(current_candle)
"""

import json
import duckdb
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
import chromadb


@dataclass
class EntrySignal:
    """Entry signal with confidence and metadata"""
    entry: bool  # True = ENTRY, False = NO ENTRY
    confidence: float  # 0.0 to 1.0
    traffic_light: str  # "GREEN", "YELLOW", "RED"
    direction: str  # "LONG", "SHORT", or "NEUTRAL"
    matching_patterns: List[str]  # Pattern names that triggered
    target_points: int  # Expected move magnitude
    recommended_size: float  # Position size scaled by confidence
    timestamp: str


class EntryAgent:
    """
    Loads patterns from ChromaDB and generates entry signals based on real-time market data.

    Confidence = Weighted vote from all patterns
    Signal = Entry if confidence > 0.70
    """

    def __init__(self, chroma_path: str = "/tmp/chroma_research"):
        """Initialize Entry Agent and load approved patterns from ChromaDB"""

        self.chroma_path = chroma_path
        self.patterns = []
        self.family_weights = {
            "supertrend": 0.87,
            "pcr": 0.72,
            "ema": 0.77,
            "volatility": 0.68
        }

        self.load_patterns_from_chromadb()
        self.log(f"✓ Entry Agent initialized with {len(self.patterns)} patterns")

    def load_patterns_from_chromadb(self):
        """Load approved patterns from ChromaDB"""
        try:
            client = chromadb.PersistentClient(path=self.chroma_path)
            collection = client.get_or_create_collection(name="discovered_patterns")

            results = collection.get()

            for pattern_id, document, metadata in zip(
                results.get('ids', []),
                results.get('documents', []),
                results.get('metadatas', [])
            ):
                try:
                    # Parse pattern data
                    pattern_data = json.loads(document) if isinstance(document, str) else document

                    pattern = {
                        "pattern_id": pattern_id,
                        "pattern_name": pattern_data.get("pattern_name", pattern_id),
                        "family": pattern_data.get("family", "unknown"),
                        "weight": self.family_weights.get(
                            pattern_data.get("family"),
                            0.5
                        ),
                        "trigger_conditions": pattern_data.get("trigger_conditions", {}),
                        "expected_move": pattern_data.get("expected_move", 50),
                        "backtest_results": pattern_data.get("backtest_results", {}),
                        "active": pattern_data.get("entry_agent_config", {}).get("active", True),
                    }

                    if pattern["active"]:
                        self.patterns.append(pattern)

                except Exception as e:
                    self.log(f"⚠ Error loading pattern {pattern_id}: {e}")

        except Exception as e:
            self.log(f"✗ ChromaDB load error: {e}")
            self.patterns = []

    def entry_check(self, current_candle: Dict) -> EntrySignal:
        """
        Main entry check method called every 1-minute candle.

        Args:
            current_candle: Market data dict with indicators (spot, adx, pcr_total, india_vix, etc.)

        Returns:
            EntrySignal with confidence, direction, and entry/no-entry decision
        """

        if not self.patterns:
            return EntrySignal(
                entry=False,
                confidence=0.0,
                traffic_light="RED",
                direction="NEUTRAL",
                matching_patterns=[],
                target_points=0,
                recommended_size=0.0,
                timestamp=current_candle.get("timestamp", "")
            )

        # Step 1: Check which patterns match current candle state
        matching_patterns = []
        pattern_scores = {}

        for pattern in self.patterns:
            if self._pattern_matches(current_candle, pattern):
                matching_patterns.append(pattern["pattern_name"])
                pattern_scores[pattern["pattern_id"]] = 1.0

        # Step 2: Calculate weighted confidence
        confidence = self._calculate_confidence(pattern_scores)

        # Step 3: Determine traffic light status
        traffic_light = self._get_traffic_light(confidence)

        # Step 4: Generate entry signal
        entry = confidence > 0.70
        direction = self._determine_direction(matching_patterns)
        target_points = self._calculate_target(matching_patterns)
        recommended_size = self._scale_position_size(confidence)

        return EntrySignal(
            entry=entry,
            confidence=confidence,
            traffic_light=traffic_light,
            direction=direction,
            matching_patterns=matching_patterns,
            target_points=target_points,
            recommended_size=recommended_size,
            timestamp=current_candle.get("timestamp", "")
        )

    def _pattern_matches(self, candle: Dict, pattern: Dict) -> bool:
        """Check if current candle state matches pattern trigger conditions"""

        conditions = pattern.get("trigger_conditions", {})

        for field, expected_value in conditions.items():
            if field not in candle:
                return False

            actual_value = candle[field]

            # Skip if value is None or missing
            if actual_value is None:
                return False

            # Handle different condition types
            if isinstance(expected_value, dict):
                # Range condition: {"min": 30, "max": 50}
                if "min" in expected_value and actual_value < expected_value["min"]:
                    return False
                if "max" in expected_value and actual_value > expected_value["max"]:
                    return False
            elif isinstance(expected_value, list):
                # Enum condition: ["GREEN", "RED"]
                if actual_value not in expected_value:
                    return False
            else:
                # Exact match
                if actual_value != expected_value:
                    return False

        return True

    def _calculate_confidence(self, pattern_scores: Dict) -> float:
        """
        Calculate weighted confidence score from matching patterns.

        Formula:
        Confidence = sum(pattern_score × family_weight) / max_possible_weight

        Where:
        - pattern_score: 1.0 if pattern matches, 0.0 if not
        - family_weight: Pre-assigned weight for SuperTrend (0.87), PCR (0.72), EMA (0.77), Vol (0.68)
        """

        if not pattern_scores:
            return 0.0

        total_score = 0.0
        max_possible = 0.0

        # Sum weighted scores for all patterns
        for pattern in self.patterns:
            family_weight = pattern["weight"]
            pattern_score = pattern_scores.get(pattern["pattern_id"], 0.0)

            total_score += pattern_score * family_weight
            max_possible += family_weight

        # Normalize to 0-1 range
        if max_possible > 0:
            confidence = min(1.0, total_score / max_possible)
        else:
            confidence = 0.0

        return confidence

    def _get_traffic_light(self, confidence: float) -> str:
        """Map confidence score to traffic light color"""
        if confidence >= 0.85:
            return "GREEN"
        elif confidence >= 0.70:
            return "YELLOW"
        else:
            return "RED"

    def _determine_direction(self, matching_patterns: List[str]) -> str:
        """
        Determine trade direction from matching patterns.

        For now: patterns with PCR/VIX extremes = SHORT, ADX = directional
        This would be refined based on actual pattern characteristics.
        """

        if not matching_patterns:
            return "NEUTRAL"

        # Simple heuristic: check pattern names
        pcr_patterns = [p for p in matching_patterns if "PCR" in p.upper()]
        vix_patterns = [p for p in matching_patterns if "VIX" in p.upper()]

        # PCR > 1.15 = bearish = SHORT
        # PCR < 0.85 = bullish = LONG
        if pcr_patterns:
            return "SHORT" if "1.15" in str(pcr_patterns) else "LONG"

        # High VIX + other signals = contrarian direction
        if vix_patterns:
            return "NEUTRAL"  # Requires additional context

        return "NEUTRAL"

    def _calculate_target(self, matching_patterns: List[str]) -> int:
        """
        Calculate target points based on matched patterns.
        Uses backtest results from pattern history.
        """

        if not matching_patterns:
            return 0

        # Use first matched pattern's expected move
        for pattern in self.patterns:
            if pattern["pattern_name"] in matching_patterns:
                return pattern.get("expected_move", 50)

        return 50  # Default

    def _scale_position_size(self, confidence: float) -> float:
        """
        Scale position size by confidence.

        1.0 confidence → 1.0x size (full position)
        0.70 confidence → 0.5x size (half position)
        <0.70 → 0.0x size (no trade)
        """

        if confidence < 0.70:
            return 0.0

        # Linear scaling: 0.70 → 0.5, 0.85 → 1.0
        if confidence >= 0.85:
            return 1.0
        else:
            # Scale between 0.5 and 1.0
            return 0.5 + (confidence - 0.70) / (0.85 - 0.70) * 0.5

    def log(self, message: str):
        """Log message with timestamp"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {message}")


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

if __name__ == "__main__":
    # Initialize Entry Agent (loads patterns from ChromaDB)
    agent = EntryAgent()

    # Example market data (what we'd get from a 1-min candle)
    example_candles = [
        {
            "timestamp": "2026-05-22 09:20:00",
            "spot": 23680,
            "adx": 35,
            "pcr_total": 1.18,
            "india_vix": 18.2,
            "st_5min_direction": "bearish",
            "st_15min_direction": "bullish",
        },
        {
            "timestamp": "2026-05-22 09:21:00",
            "spot": 23675,
            "adx": 28,
            "pcr_total": 0.92,
            "india_vix": 17.8,
            "st_5min_direction": "bullish",
            "st_15min_direction": "bullish",
        },
        {
            "timestamp": "2026-05-22 09:22:00",
            "spot": 23670,
            "adx": 22,
            "pcr_total": 0.88,
            "india_vix": 17.2,
            "st_5min_direction": "bearish",
            "st_15min_direction": "bearish",
        },
    ]

    print("\n" + "="*70)
    print("ENTRY AGENT LIVE SIGNAL TEST")
    print("="*70 + "\n")

    for candle in example_candles:
        signal = agent.entry_check(candle)

        print(f"📊 {candle['timestamp']}")
        print(f"   Market: SPOT={candle['spot']}, ADX={candle['adx']}, "
              f"PCR={candle['pcr_total']:.2f}, VIX={candle['india_vix']:.1f}")
        print(f"   ├─ Patterns matched: {signal.matching_patterns if signal.matching_patterns else 'None'}")
        print(f"   ├─ Confidence: {signal.confidence:.2%}")
        print(f"   ├─ Traffic Light: {signal.traffic_light}")
        print(f"   ├─ Entry: {'YES ✓' if signal.entry else 'NO ✗'}")
        if signal.entry:
            print(f"   ├─ Direction: {signal.direction}")
            print(f"   ├─ Target: {signal.target_points}+ pts")
            print(f"   └─ Position Size: {signal.recommended_size:.1%}")
        print()
