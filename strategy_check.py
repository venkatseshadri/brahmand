"""
Strategy Check — Strategy selection based on Regime Agent output.

Depends on: Regime Agent (receives regime dict as input)
No dependency on: Execution, Risk, Post-Mortem

Output: {"strategy_type", "wing_width", "sl_pct", "tp_pct", "entry_delay", "reason"}
"""

import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
load_dotenv()


def run_strategy_check(regime: dict) -> dict:
    """Given regime classification, select strategy and parameters."""
    from factory import AgentFactory
    from duckdb_tool import MarketDataQueryTool, get_latest_market_snapshot
    from crewai import Agent, Task, Crew, Process, LLM

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    regime_type = regime.get("regime", "unknown")
    vix = float(get_latest_market_snapshot().get("india_vix", 18))

    if not api_key:
        return _fallback_strategy(regime_type, vix)

    llm = LLM(
        model="deepseek/deepseek-chat",
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        api_key=api_key,
    )

    af = AgentFactory()
    agent = af.create_agent("strategy_agent", {}, tools=[MarketDataQueryTool()])
    agent.llm = llm

    regime_json = json.dumps(regime, indent=2)

    task = Task(
        description=f"""Based on this regime classification, select strategy and parameters:

REGIME: {regime_json}
VIX: {vix}

Rules:
- Sideways → IRON_BUTTERFLY, wing_width=200
- Trending → CREDIT_SPREAD, wing_width=100
- VIX > 18 → sl_pct=0.35, wing_width=100
- VIX <= 18 → sl_pct=0.25, wing_width=200
- Strong trend → tp_pct=0.40 (book faster)
- Normal → tp_pct=0.50

Output JSON: {{'strategy_type', 'wing_width', 'sl_pct', 'tp_pct', 'entry_delay', 'reason'}}""",
        expected_output="StrategySpec JSON",
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

    return _fallback_strategy(regime_type, vix)


def _fallback_strategy(regime_type: str, vix: float) -> dict:
    """Fallback strategy when LLM is down."""
    if vix > 18:
        return {
            "strategy_type": "IRON_BUTTERFLY",
            "wing_width": 200,
            "sl_pct": 0.35,
            "tp_pct": 0.45,
            "entry_delay": 15,
            "reason": f"fallback_vix>{vix:.1f}",
        }
    return {
        "strategy_type": "IRON_BUTTERFLY",
        "wing_width": 200,
        "sl_pct": 0.25,
        "tp_pct": 0.50,
        "entry_delay": 5,
        "reason": f"fallback_{regime_type}",
    }
