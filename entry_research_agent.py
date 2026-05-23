#!/usr/bin/env python3
"""
Entry Research Agent — Backtest 1-day 1-min data to find predictive indicator patterns.

Analyzes entire trading day to identify:
1. All significant moves (50+ pts NIFTY, 100+ pts SENSEX)
2. Which indicators were aligned BEFORE the move
3. Lead time (how many minutes before move started)
4. Indicator combination effectiveness

Output: JSON report with move timestamps, preceding indicators, and pattern correlations.

Usage:
    python entry_research_agent.py --date 2026-05-21
    python entry_research_agent.py --date 2026-05-21 --min-move 75
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

import duckdb

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from crewai import Agent, Task, Crew, Process, LLM
from crewai.tools import tool
import os


# ============================================================================
# TOOLS: Market Data Analysis
# ============================================================================

@tool
def query_1min_candles_v31(date: str, index: str = "NIFTY", limit: int = None) -> str:
    """Query ALL 1-min candles from Varaha v3.1 DuckDB for a single day.

    Args:
        date: YYYY-MM-DD format
        index: 'NIFTY' or 'SENSEX'
        limit: Optional row limit (None = all rows)

    Returns:
        JSON string with all v3.1 market_data columns
    """
    try:
        db = duckdb.connect(
            "/home/trading_ceo/python-trader/varaha/data/varaha_data.duckdb",
            read_only=True
        )

        # Get schema to understand all available columns
        schema_result = db.execute("""
            SELECT column_name, data_type FROM information_schema.columns
            WHERE table_name='market_data' ORDER BY ordinal_position
        """).fetchall()

        columns = [col[0] for col in schema_result]

        query = f"""
        SELECT * FROM market_data
        WHERE date = '{date}' AND index_name = '{index}'
        ORDER BY timestamp ASC
        {"LIMIT " + str(limit) if limit else ""}
        """

        result = db.execute(query).fetchall()

        if not result:
            return json.dumps({"error": f"No v3.1 data for {date}", "count": 0, "database": "varaha_v3.1"})

        candles = []
        for row in result:
            candle = {}
            for col, val in zip(columns, row):
                if val is None:
                    candle[col] = None
                elif isinstance(val, float):
                    candle[col] = round(val, 4)
                else:
                    candle[col] = val
            candles.append(candle)

        return json.dumps({
            "count": len(candles),
            "date": date,
            "index": index,
            "database": "varaha_v3.1",
            "available_columns": columns,
            "candles": candles,
            "note": "All columns from v3.1 market_data table included"
        })

    except Exception as e:
        return json.dumps({"error": str(e), "database": "varaha_v3.1"})


@tool
def query_1min_candles_v4(date: str, index: str = "NIFTY", limit: int = None) -> str:
    """Query ALL 1-min candles from Varaha v4 DuckDB (multitimeframe aggregator).

    Args:
        date: YYYY-MM-DD format
        index: 'NIFTY' or 'SENSEX'
        limit: Optional row limit (None = all rows)

    Returns:
        JSON string with all v4 market_data_multitf columns
    """
    try:
        db = duckdb.connect(
            "/home/trading_ceo/python-trader/varaha/data/market_data_multitf.duckdb",
            read_only=True
        )

        # List available tables
        tables = db.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()
        table_names = [t[0] for t in tables]

        # Prefer market_data_multitf, fallback to market_data
        target_table = "market_data_multitf" if "market_data_multitf" in table_names else "market_data"

        schema_result = db.execute(f"""
            SELECT column_name, data_type FROM information_schema.columns
            WHERE table_name='{target_table}' ORDER BY ordinal_position
        """).fetchall()

        columns = [col[0] for col in schema_result]

        query = f"""
        SELECT * FROM {target_table}
        WHERE DATE(timestamp) = '{date}' AND index_name = '{index}'
        ORDER BY timestamp ASC
        {"LIMIT " + str(limit) if limit else ""}
        """

        result = db.execute(query).fetchall()

        if not result:
            return json.dumps({"error": f"No v4 data for {date}", "count": 0, "database": "varaha_v4", "tables_available": table_names})

        candles = []
        for row in result:
            candle = {}
            for col, val in zip(columns, row):
                if val is None:
                    candle[col] = None
                elif isinstance(val, float):
                    candle[col] = round(val, 4)
                else:
                    candle[col] = val
            candles.append(candle)

        return json.dumps({
            "count": len(candles),
            "date": date,
            "index": index,
            "database": "varaha_v4",
            "table": target_table,
            "available_columns": columns,
            "candles": candles,
            "note": "All columns from v4 multitimeframe aggregator included"
        })

    except Exception as e:
        return json.dumps({"error": str(e), "database": "varaha_v4"})


@tool
def detect_significant_moves(candles_json: str, min_move_points: int = 50) -> str:
    """Detect all moves >= min_move_points in the candle data.

    Args:
        candles_json: JSON array of candles with spot prices
        min_move_points: Minimum move to track (50 for NIFTY, 100 for SENSEX)

    Returns:
        JSON with move timestamps, magnitudes, and directions
    """
    try:
        candles = json.loads(candles_json) if isinstance(candles_json, str) else candles_json

        if isinstance(candles, dict) and "error" in candles:
            return json.dumps(candles) if isinstance(candles_json, str) else candles_json

        # Handle both dict format (with "candles" key) and direct list format
        candles_list = candles.get("candles", []) if isinstance(candles, dict) else candles

        moves = []
        for i in range(1, len(candles_list)):
            prev_spot = candles_list[i-1].get("spot")
            curr_spot = candles_list[i].get("spot")

            if prev_spot is None or curr_spot is None:
                continue

            move = curr_spot - prev_spot

            if abs(move) >= min_move_points:
                moves.append({
                    "time": candles_list[i].get("time"),
                    "prev_spot": prev_spot,
                    "curr_spot": curr_spot,
                    "move_points": round(move, 1),
                    "direction": "UP" if move > 0 else "DOWN",
                    "magnitude_pct": round((move / prev_spot) * 100, 2)
                })

        return json.dumps({
            "min_move_threshold": min_move_points,
            "significant_moves_found": len(moves),
            "moves": sorted(moves, key=lambda x: abs(x["move_points"]), reverse=True)
        })

    except Exception as e:
        return json.dumps({"error": f"Detection failed: {str(e)}"})


@tool
def correlate_move_with_indicators(candles_json: str, move_time: str, lookback_minutes: int = 15) -> str:
    """For a given move time, find what indicators were aligned BEFORE it.

    Args:
        candles_json: Full candle data
        move_time: Time when significant move was detected
        lookback_minutes: How many minutes before move to examine

    Returns:
        JSON with indicator states during lookback period and at move time
    """
    try:
        candles = json.loads(candles_json)

        if isinstance(candles, dict) and "candles" in candles:
            candles = candles["candles"]

        # Find move index
        move_idx = None
        for i, c in enumerate(candles):
            if c.get("time") == move_time:
                move_idx = i
                break

        if move_idx is None:
            return json.dumps({"error": f"Move time {move_time} not found"})

        # Get lookback period
        start_idx = max(0, move_idx - lookback_minutes)
        lookback_candles = candles[start_idx:move_idx+1]

        # Analyze indicators in lookback period
        analysis = {
            "move_time": move_time,
            "lookback_minutes": lookback_minutes,
            "lookback_period": {
                "start_time": lookback_candles[0].get("time") if lookback_candles else None,
                "end_time": lookback_candles[-1].get("time") if lookback_candles else None,
            },
            "indicator_states": {
                "st15_aligned": None,
                "st60_aligned": None,
                "traffic_light_pattern": [],
                "ema_alignment": None,
                "adx_trend_strength": None,
                "vix_level": None,
                "pcr_sentiment": None,
            },
            "candles_in_lookback": len(lookback_candles),
        }

        # ST15 check: all green or all red in lookback
        st15_values = [c.get("st15") for c in lookback_candles if c.get("st15")]
        if st15_values:
            all_green = all(v == "GREEN" or v == True for v in st15_values)
            all_red = all(v == "RED" or v == False for v in st15_values)
            analysis["indicator_states"]["st15_aligned"] = "GREEN" if all_green else ("RED" if all_red else "MIXED")

        # ST60 check
        st60_values = [c.get("st60") for c in lookback_candles if c.get("st60")]
        if st60_values:
            all_green = all(v == "GREEN" or v == True for v in st60_values)
            all_red = all(v == "RED" or v == False for v in st60_values)
            analysis["indicator_states"]["st60_aligned"] = "GREEN" if all_green else ("RED" if all_red else "MIXED")

        # Traffic light pattern
        tl_values = [c.get("traffic_light") for c in lookback_candles if c.get("traffic_light")]
        if tl_values:
            analysis["indicator_states"]["traffic_light_pattern"] = tl_values[-5:] if len(tl_values) > 5 else tl_values

        # EMA alignment (simplified: all above or all below 20-EMA)
        ema_positions = []
        for c in lookback_candles:
            ema20 = c.get("ema20_15")
            close = c.get("close")
            if ema20 and close:
                ema_positions.append("ABOVE" if close > ema20 else "BELOW")

        if ema_positions:
            consistent = len(set(ema_positions)) == 1
            analysis["indicator_states"]["ema_alignment"] = ema_positions[-1] if ema_positions else None

        # ADX level at move time
        if candles[move_idx].get("adx"):
            adx = candles[move_idx].get("adx")
            analysis["indicator_states"]["adx_trend_strength"] = "STRONG" if adx > 25 else "WEAK" if adx < 20 else "MODERATE"

        # VIX at move time
        if candles[move_idx].get("vix"):
            analysis["indicator_states"]["vix_level"] = round(candles[move_idx].get("vix"), 2)

        # PCR at move time
        if candles[move_idx].get("pcr"):
            pcr = candles[move_idx].get("pcr")
            analysis["indicator_states"]["pcr_sentiment"] = "BEARISH" if pcr > 1.0 else "BULLISH" if pcr < 0.95 else "NEUTRAL"

        return json.dumps(analysis)

    except Exception as e:
        return json.dumps({"error": f"Correlation failed: {str(e)}"})


# ============================================================================
# AGENT DEFINITION
# ============================================================================

def create_entry_research_agent(index: str = "NIFTY", date: str = None, min_move: int = 50) -> Agent:
    """Create the Entry Research Agent with full database access."""

    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    llm = LLM(
        model="deepseek/deepseek-chat",
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
    )

    return Agent(
        role="Entry Research Analyst",
        goal=f"""Analyze {date}'s {index} 1-minute market data from BOTH Varaha v3.1 and v4 DuckDB
        to identify predictive indicator patterns.

Access complete datasets from:
- v3.1 DuckDB: varaha_data.duckdb (all 90+ market_data columns)
- v4 DuckDB: market_data_multitf.duckdb (multitimeframe aggregator data)

Find all significant moves ({min_move}+ points) and correlate them with:
- SuperTrend 15-min & 60-min alignment (all green/red in lookback)
- Traffic light patterns (GGGRRR sequences)
- EMA alignment (5, 9, 20 EMAs relative to price)
- ADX trend strength
- VIX volatility levels
- PCR sentiment (put/call ratio)
- AND any additional v3.1/v4 columns for enhanced pattern discovery

Generate a detailed report showing: WHEN the move occurred → WHAT indicators aligned
BEFORE it → LEAD TIME. Cross-reference v3.1 and v4 data for data quality validation.""",
        backstory=f"""You are a quantitative researcher with access to the COMPLETE 1-minute market dataset.
Your task is to backtest {date}'s {index} data across BOTH databases to find which
indicator combinations predicted moves of {min_move}+ points.

You have full access to:
- Varaha v3.1: Complete market_data with all technical indicators pre-calculated
- Varaha v4: Multi-timeframe aggregator with cross-TF correlations

Think of yourself as an archaeologist with TWO complete catalogs: cross-reference
both to understand patterns from multiple angles. Look for evidence (indicator alignment)
that preceded major price movements. Your goal is to build a comprehensive library
of predictive patterns using ALL available data.""",
        tools=[
            query_1min_candles_v31,
            query_1min_candles_v4,
            detect_significant_moves,
            correlate_move_with_indicators
        ],
        llm=llm,
        verbose=True,
    )


def run_entry_research(date: str = None, index: str = "NIFTY", min_move: int = 50) -> str:
    """Execute entry research analysis for a given day."""

    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    print("\n" + "=" * 80)
    print(f"ENTRY RESEARCH AGENT — {date} {index}")
    print("=" * 80)

    agent = create_entry_research_agent(index, date, min_move)

    task = Task(
        description=f"""Analyze {date}'s complete {index} 1-minute candle data to discover
        predictive indicator patterns for {min_move}+ point moves.

STEP 1: Query all 1-min candles for {date} on {index}
STEP 2: Detect all moves >= {min_move} points (timestamp, magnitude, direction)
STEP 3: For EACH significant move, examine the 15-minute lookback period
STEP 4: For each lookback period, document:
   - ST15 alignment (all GREEN, all RED, or MIXED)
   - ST60 alignment
   - Traffic light pattern (last 5 candles: GGGRRR, etc.)
   - EMA alignment (price above/below 20-EMA)
   - ADX at move time
   - VIX level
   - PCR sentiment (bearish/bullish/neutral)
STEP 5: Identify the TOP 3 most predictive indicator combinations

OUTPUT FORMAT (JSON):
{{
  "date": "{date}",
  "index": "{index}",
  "min_move_threshold": {min_move},
  "analysis_summary": {{
    "total_1min_candles": X,
    "significant_moves_detected": Y,
    "analysis_period": "09:15-15:30",
  }},
  "significant_moves": [
    {{
      "timestamp": "14:05",
      "move_magnitude": 75,
      "direction": "UP",
      "preceding_indicators": {{
        "st15_at_minus_15min": "GREEN",
        "st60": "GREEN",
        "traffic_light_lookback": ["G", "G", "G", "R", "R"],
        "ema_position": "ABOVE 20-EMA",
        "adx": "STRONG",
        "vix": 17.5,
        "pcr": "BEARISH",
      }},
      "lead_time_minutes": 5,
      "indicator_alignment_score": 0.85
    }}
  ],
  "pattern_insights": [
    "When ST15 is consistently GREEN in 15-min lookback AND PCR < 1.0, moves tend to be UP",
    "Traffic light GGGRRR pattern preceded 3 significant moves",
    "ADX < 20 appears before mean-reversion moves",
  ],
  "recommendations": [
    "Monitor ST15 GREEN + PCR < 1.0 for bullish entries",
    "Use traffic light GGGRRR as early warning for reversals",
  ]
}}""",
        expected_output="Detailed JSON report with discovered patterns and recommendations",
        agent=agent,
    )

    crew = Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=True,
    )

    result = crew.kickoff()
    return str(result)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Entry Research Agent")
    parser.add_argument("--date", default=None, help="YYYY-MM-DD format")
    parser.add_argument("--index", default="NIFTY", choices=["NIFTY", "SENSEX"])
    parser.add_argument("--min-move", type=int, default=50, help="Minimum move to track (points)")

    args = parser.parse_args()

    result = run_entry_research(args.date, args.index, args.min_move)
    print("\n" + "=" * 80)
    print("ANALYSIS COMPLETE")
    print("=" * 80)
    print(result)
