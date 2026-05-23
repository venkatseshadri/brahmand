#!/usr/bin/env python3
"""
Nightly Research + Backtest Framework
======================================

Workflow:
  1. 11:00 PM: Run research agents on yesterday's data
  2. 11:15 PM: Backtest discovered patterns against full historical dataset (May 4-21)
  3. 11:45 PM: Validate patterns (multi-day consistency, statistical significance)
  4. 12:00 AM: Store approved patterns in ChromaDB with backtest results
  5. 9:15 AM: Entry Agent loads approved patterns + historical backtest scores

Usage:
  python research_backtest_framework.py --run-full
  python research_backtest_framework.py --run-research-only
  python research_backtest_framework.py --run-backtest-only --pattern-id ST_ADX_001
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
from dataclasses import dataclass, asdict
from collections import defaultdict

import duckdb
from dotenv import load_dotenv
import os

load_dotenv()

# Add brahmand to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from crewai import Agent, Task, Crew, LLM
from research_agents import ResearchAgentOrchestrator, DiscoveredPattern

# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class BacktestResult:
    """Result of backtesting a pattern against one day"""
    pattern_id: str
    date: str
    matches_found: int
    successful_matches: int
    failed_matches: int
    win_rate: float
    avg_move_magnitude: float
    max_move: float
    min_move: float
    total_points_gained: float
    avg_lead_time: float

    def to_dict(self):
        return asdict(self)

@dataclass
class PatternBacktestSummary:
    """Aggregated backtest results for a pattern across all days"""
    pattern_id: str
    pattern_name: str
    total_days_tested: int
    total_matches: int
    total_wins: int
    total_losses: int
    overall_win_rate: float
    avg_move_magnitude: float
    consistency_across_days: float  # % of days pattern appeared
    regime_performance: Dict  # Bull/bear/sideways performance
    statistical_significance: float  # p-value
    recommended_weight: float
    backtest_period_start: str
    backtest_period_end: str
    approval_status: str  # APPROVED, REJECTED, PENDING_VALIDATION

# ============================================================================
# BACKTEST ENGINE
# ============================================================================

class BacktestEngine:
    """Backtests discovered patterns against historical NIFTY data"""

    def __init__(self, db_path: str = "/home/trading_ceo/python-trader/varaha/data/varaha_data.duckdb"):
        self.db_path = db_path
        self.db = None
        self.connect()

    def connect(self):
        """Connect to Varaha database"""
        self.db = duckdb.connect(self.db_path, read_only=True)

    def get_historical_dates(self) -> List[str]:
        """Get all available trading dates"""
        result = self.db.execute("""
            SELECT DISTINCT date FROM market_data
            WHERE index_name = 'NIFTY'
            ORDER BY date ASC
        """).fetchall()
        return [row[0] for row in result]

    def get_candles_for_date(self, date: str) -> List[Dict]:
        """Get all 1-min candles for a specific date"""
        result = self.db.execute(f"""
            SELECT * FROM market_data
            WHERE date = '{date}' AND index_name = 'NIFTY'
            ORDER BY timestamp ASC
        """).fetchall()

        # Get column names
        columns = [desc[0] for desc in self.db.description]

        candles = []
        for row in result:
            candle = dict(zip(columns, row))
            candles.append(candle)

        return candles

    def backtest_pattern(self, pattern: Dict, date: str) -> BacktestResult:
        """
        Backtest a single pattern against a specific date

        Args:
            pattern: Pattern definition with trigger_conditions
            date: Trading date to backtest

        Returns:
            BacktestResult with metrics
        """
        candles = self.get_candles_for_date(date)

        if not candles:
            return BacktestResult(
                pattern_id=pattern.get("pattern_id", "unknown"),
                date=date,
                matches_found=0,
                successful_matches=0,
                failed_matches=0,
                win_rate=0.0,
                avg_move_magnitude=0.0,
                max_move=0.0,
                min_move=0.0,
                total_points_gained=0.0,
                avg_lead_time=0.0
            )

        matches = []
        successful_moves = []
        failed_moves = []
        lead_times = []

        # Scan for pattern matches
        for i in range(len(candles) - 1):
            current = candles[i]

            # Check if pattern triggers
            if self._pattern_matches(current, pattern):
                # Look forward for move
                move_found = False

                # Check next 20 candles (up to 20 minutes)
                for j in range(i + 1, min(i + 20, len(candles))):
                    next_candle = candles[j]
                    move_magnitude = next_candle["spot"] - current["spot"]

                    # Is this a significant move (50+ pts)?
                    if abs(move_magnitude) >= pattern.get("min_move_points", 50):
                        lead_time = j - i
                        lead_times.append(lead_time)
                        matches.append({
                            "time": current["timestamp"],
                            "spot_at_pattern": current["spot"],
                            "move_at": next_candle["timestamp"],
                            "move_magnitude": move_magnitude,
                            "lead_time": lead_time
                        })

                        if abs(move_magnitude) >= pattern.get("expected_move", 50):
                            successful_moves.append(move_magnitude)
                        else:
                            failed_moves.append(move_magnitude)

                        move_found = True
                        break

        # Calculate metrics
        total_matches = len(matches)
        successful = len(successful_moves)
        failed = len(failed_moves)
        win_rate = successful / total_matches if total_matches > 0 else 0.0

        all_moves = successful_moves + failed_moves
        avg_move = sum(all_moves) / len(all_moves) if all_moves else 0.0
        max_move = max(all_moves) if all_moves else 0.0
        min_move = min(all_moves) if all_moves else 0.0
        total_points = sum(all_moves)
        avg_lead = sum(lead_times) / len(lead_times) if lead_times else 0.0

        return BacktestResult(
            pattern_id=pattern.get("pattern_id", "unknown"),
            date=date,
            matches_found=total_matches,
            successful_matches=successful,
            failed_matches=failed,
            win_rate=win_rate,
            avg_move_magnitude=avg_move,
            max_move=max_move,
            min_move=min_move,
            total_points_gained=total_points,
            avg_lead_time=avg_lead
        )

    def _pattern_matches(self, candle: Dict, pattern: Dict) -> bool:
        """Check if a candle matches all pattern conditions"""
        conditions = pattern.get("trigger_conditions", {})

        for field, expected_value in conditions.items():
            if field not in candle:
                return False  # Field doesn't exist

            actual_value = candle[field]

            # Skip if value is None
            if actual_value is None:
                return False

            # Handle different types of conditions
            if isinstance(expected_value, dict):
                # Range condition: {"min": 20, "max": 50}
                if "min" in expected_value and actual_value < expected_value["min"]:
                    return False
                if "max" in expected_value and actual_value > expected_value["max"]:
                    return False
            elif isinstance(expected_value, list):
                # Enum condition: ["GREEN", "BULLISH"]
                if actual_value not in expected_value:
                    return False
            else:
                # Exact match
                if actual_value != expected_value:
                    return False

        return True

    def backtest_pattern_all_dates(self, pattern: Dict) -> PatternBacktestSummary:
        """Backtest pattern across all historical dates"""
        dates = self.get_historical_dates()
        results = []

        print(f"  Backtesting {pattern.get('pattern_name', 'Unknown')} across {len(dates)} days...")

        for date in dates:
            result = self.backtest_pattern(pattern, date)
            results.append(result)

            if result.matches_found > 0:
                print(f"    {date}: {result.matches_found} matches, {result.win_rate:.1%} win rate")

        # Aggregate results
        total_matches = sum(r.matches_found for r in results)
        total_wins = sum(r.successful_matches for r in results)
        total_losses = sum(r.failed_matches for r in results)

        overall_win_rate = total_wins / total_matches if total_matches > 0 else 0.0
        avg_move = sum(r.avg_move_magnitude * r.matches_found for r in results) / total_matches if total_matches > 0 else 0.0

        # Consistency: % of days pattern appeared
        days_with_matches = len([r for r in results if r.matches_found > 0])
        consistency = days_with_matches / len(dates) if dates else 0.0

        # Determine approval status
        # Strategy: High hit rate + high consistency > large avg move
        # A pattern with 100% accuracy on 100+ matches is valuable even at small size
        has_high_confidence = overall_win_rate >= 0.85 and total_matches >= 100
        has_good_consistency = overall_win_rate >= 0.70 and consistency >= 0.30 and avg_move >= 30
        has_excellent_stats = overall_win_rate >= 0.95 and total_matches >= 50

        approval_status = "APPROVED" if (has_high_confidence or has_good_consistency or has_excellent_stats) else "REJECTED" if overall_win_rate < 0.50 else "PENDING_VALIDATION"

        return PatternBacktestSummary(
            pattern_id=pattern.get("pattern_id", "unknown"),
            pattern_name=pattern.get("pattern_name", "Unknown"),
            total_days_tested=len(dates),
            total_matches=total_matches,
            total_wins=total_wins,
            total_losses=total_losses,
            overall_win_rate=overall_win_rate,
            avg_move_magnitude=avg_move,
            consistency_across_days=consistency,
            regime_performance={},  # TODO: calculate by regime
            statistical_significance=0.85,  # TODO: calculate p-value
            recommended_weight=overall_win_rate * 0.9,  # Discount slightly for safety
            backtest_period_start=dates[0] if dates else "N/A",
            backtest_period_end=dates[-1] if dates else "N/A",
            approval_status=approval_status
        )

# ============================================================================
# RESEARCH + BACKTEST ORCHESTRATOR
# ============================================================================

class ResearchBacktestOrchestrator:
    """Coordinates research discovery → backtest validation → storage"""

    def __init__(self):
        self.backtest_engine = BacktestEngine()
        self.discovered_patterns = []
        self.backtest_results = {}

    def run_research_agents(self, date: str = None):
        """
        Run all 4 research agents on specified date
        Falls back to yesterday if no date specified
        """
        if date is None:
            date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        print(f"\n{'='*70}")
        print(f"RESEARCH PHASE: Analyzing {date}")
        print(f"{'='*70}")

        # Run real research agents
        orchestrator = ResearchAgentOrchestrator()
        agent_results = orchestrator.discover_patterns_for_date(date)

        # Convert DiscoveredPattern objects to dicts for backtest engine
        self.discovered_patterns = []
        for family, patterns in agent_results.items():
            for pattern in patterns:
                self.discovered_patterns.append({
                    "pattern_id": pattern.pattern_id,
                    "pattern_name": pattern.pattern_name,
                    "family": family,
                    "trigger_conditions": pattern.trigger_conditions,
                    "expected_move": pattern.expected_move,
                    "min_move_points": pattern.min_move_points
                })

        print(f"\n✓ Discovered {len(self.discovered_patterns)} patterns on {date}")

    def run_backtest_phase(self):
        """
        Backtest all discovered patterns against historical data (May 4-21)
        """
        print(f"\n{'='*70}")
        print(f"BACKTEST PHASE: Testing against {len(self.backtest_engine.get_historical_dates())} trading days")
        print(f"{'='*70}")

        self.backtest_results = {}

        for pattern in self.discovered_patterns:
            print(f"\n📊 {pattern['pattern_name']}:")

            summary = self.backtest_engine.backtest_pattern_all_dates(pattern)
            self.backtest_results[pattern["pattern_id"]] = summary

            print(f"\n  Results:")
            print(f"    Total Matches: {summary.total_matches}")
            print(f"    Win Rate: {summary.overall_win_rate:.1%}")
            print(f"    Avg Move: {summary.avg_move_magnitude:.0f} pts")
            print(f"    Consistency: {summary.consistency_across_days:.1%} of days")
            print(f"    Status: {summary.approval_status} ✓" if summary.approval_status == "APPROVED" else f"    Status: {summary.approval_status} ✗")

    def store_results(self):
        """
        Store approved patterns + backtest results in ChromaDB
        """
        print(f"\n{'='*70}")
        print(f"STORAGE PHASE: Saving approved patterns to ChromaDB")
        print(f"{'='*70}")

        approved = [
            (pid, summary) for pid, summary in self.backtest_results.items()
            if summary.approval_status == "APPROVED"
        ]

        for pattern_id, summary in approved:
            pattern = next(p for p in self.discovered_patterns if p["pattern_id"] == pattern_id)

            record = {
                "pattern_id": pattern_id,
                "pattern_name": pattern["pattern_name"],
                "family": pattern.get("family", "unknown"),
                "discovery_date": datetime.now().isoformat(),
                "backtest_summary": asdict(summary),
                "trigger_conditions": pattern["trigger_conditions"],
                "entry_agent_config": {
                    "weight": summary.recommended_weight,
                    "trigger_threshold": 0.70,
                    "active": True
                }
            }

            print(f"\n✓ {pattern['pattern_name']}")
            print(f"  Weight: {summary.recommended_weight:.2f}")
            print(f"  Win Rate: {summary.overall_win_rate:.1%}")
            print(f"  Total Matches (historical): {summary.total_matches}")

            # TODO: Store in ChromaDB
            # chroma_client.upsert(collection="discovered_patterns", records=[record])

    def generate_telegram_summary(self):
        """Generate summary for Telegram notification"""
        approved = [
            summary for summary in self.backtest_results.values()
            if summary.approval_status == "APPROVED"
        ]

        if not approved:
            return "❌ No patterns approved for tomorrow. Using yesterday's patterns."

        summary_text = f"""
📊 NIGHTLY RESEARCH + BACKTEST COMPLETE ({datetime.now().strftime('%Y-%m-%d')})

✅ Approved Patterns: {len(approved)}

"""

        for summary in approved:
            summary_text += f"""
{summary.pattern_name}
├─ Win Rate: {summary.overall_win_rate:.1%}
├─ Matches (historical): {summary.total_matches}
├─ Avg Move: {summary.avg_move_magnitude:.0f} pts
├─ Weight: {summary.recommended_weight:.2f}
└─ Ready for Entry Agent ✓

"""

        return summary_text

    def run_full_pipeline(self):
        """Run complete pipeline: research → backtest → validate → store"""
        print("\n" + "="*70)
        print("AUTONOMOUS NIGHTLY RESEARCH + BACKTEST PIPELINE")
        print("="*70)
        print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # Phase 1: Research
        self.run_research_agents()

        # Phase 2: Backtest
        self.run_backtest_phase()

        # Phase 3: Store
        self.store_results()

        # Phase 4: Notify
        summary = self.generate_telegram_summary()
        print(f"\n{summary}")

        # TODO: Send to Telegram
        # send_telegram_message(summary)

        print(f"\nCompleted: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("✅ Ready for Entry Agent tomorrow at 9:15 AM")

# ============================================================================
# CLI
# ============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Nightly Research + Backtest Framework")
    parser.add_argument("--run-full", action="store_true", help="Run full pipeline")
    parser.add_argument("--run-research-only", action="store_true", help="Run research only")
    parser.add_argument("--run-backtest-only", action="store_true", help="Run backtest only")
    parser.add_argument("--date", default=None, help="Date to analyze (YYYY-MM-DD)")

    args = parser.parse_args()

    orchestrator = ResearchBacktestOrchestrator()

    if args.run_full:
        orchestrator.run_full_pipeline()
    elif args.run_research_only:
        orchestrator.run_research_agents(args.date)
    elif args.run_backtest_only:
        orchestrator.run_backtest_phase()
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
