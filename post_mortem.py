#!/usr/bin/env python3
"""
Post-Mortem Agent — midnight research process that runs after market hours.

Analyzes the day's trades and writes insights to ChromaDB.
Triggered independently by cron (e.g., at 15:35 IST), not by kickoff.py.
"""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
load_dotenv()

from state import load_state, save_state
from logger import get_logger, log_exception

_SANDBOX = os.environ.get("BRAHMAND_SANDBOX", "")
if _SANDBOX:
    STATE_DIR = Path(_SANDBOX) / "state"
else:
    STATE_DIR = Path(__file__).parent / "data"
STATE_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = STATE_DIR / "brahmand_kickoff.json"

_log = get_logger("post_mortem").info


def run_pm(state: dict):
    _log("\n=== POST-MORTEM ===")
    state["post_mortem_done"] = True
    try:
        from chromadb_tool import QueryChromaDBTool, StoreResearchNoteTool
        from duckdb_tool import MarketDataQueryTool, OptionSnapshotQueryTool
        from factory import AgentFactory
        from crewai import Task, Crew, Process, LLM
        from persistence import get_today_date_int

        af = AgentFactory()
        pm = af.create_agent(
            "postmortem_agent",
            {
                "today_date_int": get_today_date_int(),
                "chroma_collection": "brahmand_notes",
            },
            tools=[
                QueryChromaDBTool(),
                StoreResearchNoteTool(),
                MarketDataQueryTool(),
                OptionSnapshotQueryTool(),
            ],
        )
        if "DEEPSEEK_API_KEY" in os.environ:
            pm.llm = LLM(
                model="deepseek/deepseek-chat",
                base_url=os.environ.get(
                    "DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"
                ),
                api_key=os.environ["DEEPSEEK_API_KEY"],
                temperature=0,
            )

        trades_summary = json.dumps(state["all_trades"], default=str)[:3000]
        task = Task(
            description=(
                f"POST-MORTEM ANALYSIS for {len(state['all_trades'])} trades today.\n\n"
                "COMPLETE trade data (all agent outputs) included:\n"
                f"{trades_summary}\n\n"
                "ANALYZE EACH TRADE:\n"
                "1. Entry Agent Analysis:\n"
                "   - Was entry_gate_signal accurate? (compare signal vs actual market direction at exit)\n"
                "   - Was confidence level predictive of outcome?\n"
                "   - Trend vs Traffic Light accuracy?\n\n"
                "2. Regime Analysis:\n"
                "   - Did regime_analysis.recommendation match outcome?\n"
                "   - Was VIX level factored correctly?\n"
                "   - ADX trend bias accurate?\n\n"
                "3. Strategy Analysis:\n"
                "   - Were strategy_analysis parameters (wing_width, sl_pct, tp_pct) optimal?\n"
                "   - Did actual premium decay match expectations?\n\n"
                "4. Execution Analysis:\n"
                "   - Net credit sufficient for drawdown? (margin = wing_width - net_credit)\n"
                "   - SL/TP levels appropriate?\n\n"
                "5. Risk Analysis:\n"
                "   - Risk_confirmation: were all orders placed? Any failures?\n"
                "   - Order_ids tracked correctly in order_ledger?\n\n"
                "6. Exit Analysis:\n"
                "   - Exit reason (SL_HIT, TP_HIT, MORPH, TSL, TIME_EXIT)?\n"
                "   - Was the exit reason predictable from earlier analysis?\n"
                "   - PnL: was it within expected range given wing_width and net_credit?\n\n"
                "WRITE ResearchNotes to ChromaDB with:\n"
                "- key insights\n"
                "- what worked (pattern, VIX level, regime match)\n"
                "- what failed (wrong signal, bad timing, parameter miscalibration)\n"
                "- recommendations for tomorrow (parameter adjustments, market regime filters)"
            ),
            expected_output="ResearchNotes JSON with trade analysis summary",
            agent=pm,
        )
        crew = Crew(
            agents=[pm], tasks=[task], process=Process.sequential, verbose=False
        )
        crew.kickoff()
        _log("Post-Mortem complete — ChromaDB updated")
    except Exception as e:
        _log(f"Post-Mortem failed: {e}")


def main():
    state = load_state(STATE_FILE)
    if not state["all_trades"]:
        _log("No trades today — skipping post-mortem")
        return
    if state["post_mortem_done"]:
        _log("Post-mortem already completed for today")
        return
    run_pm(state)
    save_state(STATE_FILE, state)


if __name__ == "__main__":
    main()
