"""
Regime Check — Pre-trade market classification using DuckDB.

Runs Regime Agent via AgentFactory + query_market_data tool.
No dependency on other agents. Output: {"regime", "confidence", "recommendation"}
"""

import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
load_dotenv()


def run_regime_check() -> dict:
    """Run Regime Agent to classify current market. Returns regime dict."""
    from factory import AgentFactory
    from duckdb_tool import MarketDataQueryTool
    from crewai import Agent, Task, Crew, Process, LLM
    from duckdb_tool import get_latest_market_snapshot

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        snap = get_latest_market_snapshot()
        vix = float(snap.get("india_vix", 0))
        adx = float(snap.get("adx", 0) or 0)
        regime_type = "sideways" if (adx and adx < 25) else "trending"
        return _fallback_regime(vix, regime_type)

    llm = LLM(
        model="deepseek/deepseek-chat",
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        api_key=api_key,
        temperature=0,
    )

    af = AgentFactory()
    agent = af.create_agent("regime_agent", {}, tools=[MarketDataQueryTool()])
    agent.llm = llm

    snap = get_latest_market_snapshot()
    snap_json = json.dumps(
        {
            k: snap.get(k, "")
            for k in [
                "spot",
                "india_vix",
                "adx",
                "supertrend_direction",
                "iv_current",
                "iv_rank",
                "iv_regime",
                "rsi",
                "pcr_total",
                "sentiment",
                "structure_type",
                "session_phase",
                "atm_strike",
            ]
        },
        indent=2,
    )

    task = Task(
        description=f"""Classify NIFTY market regime from these indicators:
{snap_json}

Output JSON: {{'regime': 'sideways'|'trending_bullish'|'trending_bearish',
'confidence': 0-1, 'recommendation': 'enter'|'skip'|'caution', 'reason': '...'}}""",
        expected_output="MarketRegime JSON with regime, confidence, recommendation",
        agent=agent,
    )

    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)
    result = crew.kickoff()

    try:
        raw = str(result)
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(raw[start:end])
    except (json.JSONDecodeError, ValueError):
        pass

    vix = float(snap.get("india_vix", 0))
    return _fallback_regime(vix, "unknown")


def _fallback_regime(vix: float, reason: str = "api_down") -> dict:
    """Fallback classification when LLM is unavailable."""
    if vix > 18:
        return {
            "regime": "trending",
            "confidence": 0.5,
            "recommendation": "caution",
            "reason": f"fallback_{reason}_vix>18",
        }
    return {
        "regime": "unknown",
        "confidence": 0.3,
        "recommendation": "enter",
        "reason": f"fallback_{reason}",
    }
