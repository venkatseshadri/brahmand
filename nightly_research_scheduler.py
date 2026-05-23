#!/usr/bin/env python3
"""
Nightly Autonomous Research + Backtest Scheduler
================================================

Runs every night at 11:00 PM (post-market):
  1. Runs all 4 research agents on yesterday's data
  2. Backtests discovered patterns against full historical dataset
  3. Validates patterns (win rate, consistency, lead time)
  4. Auto-approves patterns that meet thresholds
  5. Stores approved patterns in ChromaDB
  6. Sends Telegram summary to user
  7. Next morning (9:15 AM): Entry Agent loads approved patterns

Installation as cron job:
  0 23 * * 1-5 cd /home/trading_ceo/brahmand && python3 nightly_research_scheduler.py >> /tmp/research_scheduler.log 2>&1

Or run manually:
  python3 nightly_research_scheduler.py
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
import json
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("/tmp/research_scheduler.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).parent))

from research_backtest_framework import ResearchBacktestOrchestrator
from research_agents import ResearchAgentOrchestrator
from dotenv import load_dotenv
import os

load_dotenv()

# ============================================================================
# TELEGRAM NOTIFIER
# ============================================================================


def send_telegram_notification(message: str):
    """Send summary to Telegram"""
    try:
        import requests

        telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

        if not telegram_token or not telegram_chat_id:
            logger.warning("Telegram credentials not configured, skipping notification")
            return

        url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
        payload = {
            "chat_id": telegram_chat_id,
            "text": message,
            "parse_mode": "Markdown",
        }

        response = requests.post(url, json=payload)
        if response.status_code == 200:
            logger.info("✓ Telegram notification sent")
        else:
            logger.error(f"Failed to send Telegram: {response.text}")
    except Exception as e:
        logger.error(f"Telegram notification error: {e}")


# ============================================================================
# CHROMA DB INTEGRATION
# ============================================================================


def store_approved_patterns_in_chromadb(
    backtest_results: dict, discovered_patterns: list
):
    """
    Store approved patterns in ChromaDB for Entry Agent to load
    """
    try:
        import chromadb

        # Initialize Chroma
        chroma_client = chromadb.PersistentClient(path="/tmp/chroma_research")
        collection = chroma_client.get_or_create_collection(name="discovered_patterns")

        approved_count = 0

        for pattern in discovered_patterns:
            pattern_id = pattern.get("pattern_id")
            summary = backtest_results.get(pattern_id)

            if not summary or summary.approval_status != "APPROVED":
                continue

            # Create record for ChromaDB
            record = {
                "pattern_id": pattern_id,
                "pattern_name": pattern.get("pattern_name"),
                "family": pattern.get("family"),
                "discovery_date": datetime.now().isoformat(),
                "backtest_results": {
                    "total_matches": summary.total_matches,
                    "win_rate": summary.overall_win_rate,
                    "avg_move_magnitude": summary.avg_move_magnitude,
                    "consistency": summary.consistency_across_days,
                    "weight": summary.recommended_weight,
                    "backtest_period": f"{summary.backtest_period_start} to {summary.backtest_period_end}",
                },
                "entry_agent_config": {
                    "weight": summary.recommended_weight,
                    "active": True,
                    "expires_at": (datetime.now() + timedelta(days=7)).isoformat(),
                },
            }

            # Store in ChromaDB
            collection.upsert(
                ids=[pattern_id],
                documents=[json.dumps(record)],
                metadatas=[
                    {
                        "date": datetime.now().strftime("%Y-%m-%d"),
                        "win_rate": f"{summary.overall_win_rate:.1%}",
                        "family": pattern.get("family"),
                    }
                ],
            )

            approved_count += 1
            logger.info(
                f"✓ Stored pattern: {pattern.get('pattern_name')} (weight={summary.recommended_weight:.2f})"
            )

        logger.info(f"Total patterns stored: {approved_count}")
        return approved_count

    except ImportError:
        logger.warning("ChromaDB not installed, skipping storage")
        return 0
    except Exception as e:
        logger.error(f"ChromaDB storage error: {e}")
        return 0


# ============================================================================
# MARKET REGIME DETECTION
# ============================================================================


def detect_market_regime(date: str) -> str:
    """
    Detect market regime for yesterday (BULLISH, BEARISH, SIDEWAYS)
    Used to understand pattern performance across regimes
    """
    try:
        import duckdb

        db = duckdb.connect(
            "/home/trading_ceo/python-trader/varaha/data/varaha_data.duckdb",
            read_only=True,
        )

        result = db.execute(f"""
            SELECT
                open_price,
                spot as close_price,
                intraday_high as high_price,
                intraday_low as low_price
            FROM market_data
            WHERE date = '{date}' AND index_name = 'NIFTY'
            ORDER BY timestamp
            LIMIT 1
        """).fetchall()

        if not result:
            return "UNKNOWN"

        result2 = db.execute(f"""
            SELECT spot
            FROM market_data
            WHERE date = '{date}' AND index_name = 'NIFTY'
            ORDER BY timestamp DESC
            LIMIT 1
        """).fetchall()

        open_price = result[0][0]
        close_price = result2[0][0] if result2 else result[0][1]
        high = result[0][2]
        low = result[0][3]

        # Simple regime detection
        change_pct = (close_price - open_price) / open_price * 100
        range_pct = (high - low) / open_price * 100

        if abs(change_pct) < 0.3 and range_pct < 1.0:
            return "SIDEWAYS"
        elif change_pct > 0.3:
            return "BULLISH"
        elif change_pct < -0.3:
            return "BEARISH"
        else:
            return "SIDEWAYS"

    except Exception as e:
        logger.error(f"Regime detection error: {e}")
        return "UNKNOWN"


# ============================================================================
# MAIN SCHEDULER
# ============================================================================


def main():
    """
    Main nightly scheduler function
    Runs: Research → Backtest → Validate → Store → Notify
    """

    logger.info("=" * 70)
    logger.info("NIGHTLY RESEARCH + BACKTEST SCHEDULER STARTED")
    logger.info("=" * 70)

    try:
        # Determine date to analyze (yesterday)
        analysis_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        logger.info(f"Analyzing date: {analysis_date}")

        # Detect market regime
        regime = detect_market_regime(analysis_date)
        logger.info(f"Market regime: {regime}")

        # Initialize orchestrator
        orchestrator = ResearchBacktestOrchestrator()

        # Phase 1: Run research agents
        logger.info("\n[PHASE 1] Running research agents...")
        orchestrator.run_research_agents(analysis_date)
        logger.info(f"Discovered {len(orchestrator.discovered_patterns)} patterns")

        # Phase 2: Run backtest
        logger.info("\n[PHASE 2] Backtesting patterns against historical data...")
        orchestrator.run_backtest_phase()

        # Count approved patterns
        approved = [
            summary
            for summary in orchestrator.backtest_results.values()
            if summary.approval_status == "APPROVED"
        ]
        logger.info(f"Approved patterns: {len(approved)}")

        # Phase 3: Store in ChromaDB
        logger.info("\n[PHASE 3] Storing approved patterns...")
        stored_count = store_approved_patterns_in_chromadb(
            orchestrator.backtest_results, orchestrator.discovered_patterns
        )
        logger.info(f"Stored patterns: {stored_count}")

        # Phase 4: Generate and send notification
        logger.info("\n[PHASE 4] Sending notification...")
        summary = orchestrator.generate_telegram_summary()
        logger.info(f"Summary:\n{summary}")
        send_telegram_notification(summary)

        # Phase 5: Log report
        logger.info("\n[REPORT]")
        logger.info(f"Analysis Date: {analysis_date}")
        logger.info(f"Market Regime: {regime}")
        logger.info(f"Patterns Discovered: {len(orchestrator.discovered_patterns)}")
        logger.info(f"Patterns Approved: {len(approved)}")
        logger.info(f"Patterns Stored: {stored_count}")
        logger.info(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("=" * 70)
        logger.info("READY FOR ENTRY AGENT AT 9:15 AM")
        logger.info("=" * 70)

    except Exception as e:
        logger.error(f"FATAL ERROR: {e}", exc_info=True)
        send_telegram_notification(f"❌ Research scheduler failed: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
