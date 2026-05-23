#!/usr/bin/env python3
"""
Entry Signal Broker
===================

Runs during market hours (9:15 AM - 3:30 PM) to:
1. Load latest NIFTY 1-min candle every minute
2. Call Entry Agent's entry_check() method
3. Publish entry signals to Telegram
4. Log all signals for analysis

Usage:
  python3 entry_signal_broker.py --live    # Real-time trading
  python3 entry_signal_broker.py --backtest 2026-05-21  # Test on historical data
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
import logging
import json
import os
import argparse
import time
from typing import Dict, Optional

import duckdb
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))

from entry_agent import EntryAgent, EntrySignal

load_dotenv()

# ============================================================================
# LOGGING SETUP
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/tmp/entry_signal_broker.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ============================================================================
# TELEGRAM NOTIFICATIONS
# ============================================================================

def send_telegram_signal(signal: EntrySignal, market_context: Dict):
    """Send entry signal to Telegram"""
    try:
        import requests

        telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

        if not telegram_token or not telegram_chat_id:
            return

        message = f"""
🟢 ENTRY SIGNAL GENERATED

⏰ Time: {signal.timestamp}
🎯 Direction: {signal.direction}
📊 Confidence: {signal.confidence:.0%}
🚦 Traffic Light: {signal.traffic_light}

Market Context:
├─ SPOT: {market_context.get('spot', 'N/A')}
├─ ADX: {market_context.get('adx', 'N/A')}
├─ PCR: {market_context.get('pcr_total', 'N/A'):.2f}
├─ VIX: {market_context.get('india_vix', 'N/A'):.1f}
└─ Patterns: {', '.join(signal.matching_patterns)}

Entry Rules:
├─ Target: {signal.target_points}+ pts
├─ Position Size: {signal.recommended_size:.0%}
└─ Stop: Previous support/resistance

Ready to execute ✓
"""

        url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
        payload = {
            "chat_id": telegram_chat_id,
            "text": message,
            "parse_mode": "Markdown"
        }

        response = requests.post(url, json=payload)
        if response.status_code == 200:
            logger.info("✓ Signal sent to Telegram")
        else:
            logger.warning(f"Telegram send failed: {response.text}")

    except Exception as e:
        logger.error(f"Telegram error: {e}")


# ============================================================================
# MARKET DATA ACCESS
# ============================================================================

class MarketDataFeed:
    """Access real-time or historical market data"""

    def __init__(self, db_path: str = "/home/trading_ceo/python-trader/varaha/data/varaha_data.duckdb"):
        self.db_path = db_path
        self.db = duckdb.connect(db_path, read_only=True)

    def get_latest_candle(self, index_name: str = "NIFTY") -> Optional[Dict]:
        """Get the most recent 1-min candle"""
        try:
            result = self.db.execute(f"""
                SELECT * FROM market_data
                WHERE index_name = '{index_name}'
                ORDER BY timestamp DESC
                LIMIT 1
            """).fetchall()

            if not result:
                return None

            columns = [desc[0] for desc in self.db.description]
            candle = dict(zip(columns, result[0]))
            return candle

        except Exception as e:
            logger.error(f"Error fetching latest candle: {e}")
            return None

    def get_candle_at_time(self, timestamp: str, index_name: str = "NIFTY") -> Optional[Dict]:
        """Get candle at specific timestamp"""
        try:
            result = self.db.execute(f"""
                SELECT * FROM market_data
                WHERE index_name = '{index_name}'
                  AND timestamp <= '{timestamp}'
                ORDER BY timestamp DESC
                LIMIT 1
            """).fetchall()

            if not result:
                return None

            columns = [desc[0] for desc in self.db.description]
            candle = dict(zip(columns, result[0]))
            return candle

        except Exception as e:
            logger.error(f"Error fetching candle at {timestamp}: {e}")
            return None

    def get_candles_for_date(self, date: str, index_name: str = "NIFTY") -> list:
        """Get all candles for a specific date"""
        try:
            result = self.db.execute(f"""
                SELECT * FROM market_data
                WHERE index_name = '{index_name}'
                  AND date = '{date}'
                ORDER BY timestamp ASC
            """).fetchall()

            columns = [desc[0] for desc in self.db.description]
            candles = [dict(zip(columns, row)) for row in result]
            return candles

        except Exception as e:
            logger.error(f"Error fetching candles for {date}: {e}")
            return []


# ============================================================================
# ENTRY SIGNAL BROKER
# ============================================================================

class EntrySignalBroker:
    """Main broker that monitors and publishes entry signals"""

    def __init__(self):
        self.entry_agent = EntryAgent()
        self.market_feed = MarketDataFeed()
        self.last_signal_timestamp = None
        self.signals_generated = 0
        self.signals_file = "/tmp/entry_signals.jsonl"

        logger.info("="*70)
        logger.info("ENTRY SIGNAL BROKER INITIALIZED")
        logger.info("="*70)
        logger.info(f"Patterns loaded: {len(self.entry_agent.patterns)}")
        for pattern in self.entry_agent.patterns:
            logger.info(f"  - {pattern['pattern_name']} ({pattern['family']})")

    def check_market_hours(self) -> bool:
        """Check if current time is within trading hours (9:15 AM - 3:30 PM)"""
        now = datetime.now()

        # Skip weekends
        if now.weekday() >= 5:
            return False

        # Check time: 9:15 AM to 3:30 PM
        market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
        market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)

        return market_open <= now <= market_close

    def run_live(self):
        """Run broker continuously during market hours"""
        logger.info("\n🟢 STARTING LIVE SIGNAL MONITORING")
        logger.info("Hours: 9:15 AM - 3:30 PM IST")
        logger.info("Signals will be published to Telegram\n")

        last_checked_timestamp = None

        while True:
            try:
                # Check market hours
                if not self.check_market_hours():
                    time.sleep(60)  # Check again in 1 minute
                    continue

                # Get latest candle
                candle = self.market_feed.get_latest_candle()
                if not candle:
                    logger.warning("⚠ No market data available")
                    time.sleep(60)
                    continue

                # Avoid duplicate checks for same candle
                current_timestamp = candle.get("timestamp")
                if current_timestamp == last_checked_timestamp:
                    time.sleep(10)  # Wait before checking again
                    continue

                last_checked_timestamp = current_timestamp

                # Check entry signal
                signal = self.entry_agent.entry_check(candle)

                # Log every check
                logger.info(f"📊 {current_timestamp}")
                logger.info(f"   Market: SPOT={candle.get('spot')}, "
                           f"ADX={candle.get('adx'):.1f}, "
                           f"PCR={candle.get('pcr_total', 0):.2f}, "
                           f"VIX={candle.get('india_vix', 0):.1f}")
                logger.info(f"   Confidence: {signal.confidence:.0%}, TL: {signal.traffic_light}")

                # Publish signal if entry triggered
                if signal.entry:
                    self.signals_generated += 1
                    logger.info(f"   🟢 ENTRY SIGNAL #{self.signals_generated} ✓")
                    logger.info(f"      Direction: {signal.direction}")
                    logger.info(f"      Patterns: {', '.join(signal.matching_patterns)}")
                    logger.info(f"      Target: {signal.target_points}+ pts")
                    logger.info(f"      Size: {signal.recommended_size:.0%}")

                    # Save signal to file
                    self._save_signal(signal, candle)

                    # Send to Telegram
                    send_telegram_signal(signal, candle)

                # Sleep before next check
                time.sleep(60)

            except KeyboardInterrupt:
                logger.info("\n🛑 Broker stopped by user")
                break
            except Exception as e:
                logger.error(f"Error in main loop: {e}", exc_info=True)
                time.sleep(60)

    def run_backtest(self, date: str):
        """Backtest signals on historical data for a specific date"""
        logger.info(f"\n📅 BACKTESTING SIGNALS FOR {date}")
        logger.info("="*70 + "\n")

        candles = self.market_feed.get_candles_for_date(date)
        if not candles:
            logger.error(f"No data available for {date}")
            return

        logger.info(f"Processing {len(candles)} candles for {date}\n")

        signals_on_date = 0

        for candle in candles:
            signal = self.entry_agent.entry_check(candle)

            if signal.entry:
                signals_on_date += 1
                logger.info(f"🟢 SIGNAL #{signals_on_date}: {candle['timestamp']}")
                logger.info(f"   Confidence: {signal.confidence:.0%}, TL: {signal.traffic_light}")
                logger.info(f"   Direction: {signal.direction}, Target: {signal.target_points}+ pts")
                logger.info(f"   Patterns: {', '.join(signal.matching_patterns)}")
                logger.info(f"   Position Size: {signal.recommended_size:.0%}")
                logger.info("")

        logger.info("="*70)
        logger.info(f"BACKTEST SUMMARY FOR {date}")
        logger.info(f"Total signals: {signals_on_date}")
        logger.info(f"Candles processed: {len(candles)}")
        logger.info(f"Signal frequency: 1 per {len(candles)//max(1, signals_on_date)} candles")

    def run_test_mode(self):
        """Test mode: simulate with recent market data"""
        logger.info("\n🟡 RUNNING IN TEST MODE")
        logger.info("Using recent market data to simulate signals\n")

        # Get yesterday's date
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        self.run_backtest(yesterday)

    def _save_signal(self, signal: EntrySignal, market_context: Dict):
        """Save signal to JSONL file for analysis"""
        try:
            signal_record = {
                "timestamp": signal.timestamp,
                "confidence": signal.confidence,
                "traffic_light": signal.traffic_light,
                "direction": signal.direction,
                "patterns": signal.matching_patterns,
                "target_points": signal.target_points,
                "position_size": signal.recommended_size,
                "market_context": {
                    "spot": market_context.get("spot"),
                    "adx": market_context.get("adx"),
                    "pcr_total": market_context.get("pcr_total"),
                    "india_vix": market_context.get("india_vix")
                }
            }

            with open(self.signals_file, 'a') as f:
                f.write(json.dumps(signal_record) + "\n")

        except Exception as e:
            logger.error(f"Error saving signal: {e}")


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Entry Signal Broker")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run live signal monitoring (9:15 AM - 3:30 PM)"
    )
    parser.add_argument(
        "--backtest",
        type=str,
        help="Backtest on specific date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Test mode: simulate with recent data"
    )

    args = parser.parse_args()

    broker = EntrySignalBroker()

    if args.live:
        broker.run_live()
    elif args.backtest:
        broker.run_backtest(args.backtest)
    elif args.test:
        broker.run_test_mode()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
