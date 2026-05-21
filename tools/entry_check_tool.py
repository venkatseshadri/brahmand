"""
Entry Check Tool — Regime Agent queries the deterministic entry gate signal
Fallback chain: /home/trading_ceo/antariksh/logs/entry_check_latest.json → DuckDB
"""

from crewai.tools import BaseTool
from pathlib import Path
import json
import re
from datetime import datetime


class EntryCheckTool(BaseTool):
    name: str = "query_entry_check"
    description: str = (
        "Get the deterministic entry gate signal from Redis indicators (or fallback to DuckDB). "
        "Returns: {signal: BULLISH/BEARISH/NEUTRAL, confidence: 0-100, timestamp, source}"
    )

    def _run(self, index: str = "NIFTY") -> dict:
        """
        Query entry check with fallback chain:
        1. /home/trading_ceo/antariksh/logs/entry_check_latest.json (updated by entry_check every 5 min)
        2. DuckDB direct query
        """

        # ── Attempt 1: Read from persistent file (freshest) ──
        try:
            result = self._read_from_persistent_file(index)
            if result:
                result["source"] = "persistent_file (Redis via entry_check)"
                return result
        except Exception as e:
            pass  # Fall through to next strategy

        # ── Attempt 2: Query DuckDB directly (fallback) ──
        try:
            result = self._query_duckdb(index)
            if result:
                result["source"] = "duckdb (fallback)"
                return result
        except Exception as e:
            pass

        # ── All strategies failed ──
        return {
            "error": "Entry check unavailable — all fallbacks failed",
            "signal": "NEUTRAL",
            "confidence": 0,
            "source": "error",
            "recommendation": "skip",
        }

    def _read_from_persistent_file(self, index: str) -> dict | None:
        """
        Read from /home/trading_ceo/antariksh/logs/entry_check_latest.json
        Risk: Potential race condition if file is being written
        Mitigation: Try 3 times with small delays
        """
        p = Path("/home/trading_ceo/antariksh/logs/entry_check_latest.json")
        if not p.exists():
            return None

        for attempt in range(3):
            try:
                content = p.read_text()
                data = json.loads(content)

                # Validate structure
                if all(k in data for k in ["signal", "confidence", "timestamp"]):
                    return {
                        "signal": data.get("signal"),
                        "confidence": data.get("confidence"),
                        "timestamp": data.get("timestamp"),
                        "trend_signal": data.get("trend_signal"),
                        "traffic_light_signal": data.get("traffic_light_signal"),
                        "reasoning": data.get("reasoning"),
                    }
            except json.JSONDecodeError:
                # File might be mid-write, wait and retry
                import time

                if attempt < 2:
                    time.sleep(0.1)
                continue
            except Exception:
                continue

        return None

    def _read_from_log_file(self, index: str) -> dict | None:
        """
        Read from the latest entry_check log file
        Safer than JSON file (append-only, no locking issues)

        Log format expected:
        [HH:MM:SS] entry_check.py | signal | confidence | trend_signal | traffic_light
        """
        log_dir = Path("/home/trading_ceo/antariksh/logs")
        if not log_dir.exists():
            return None

        # Find latest entry_check log for today
        today = datetime.now().strftime("%Y%m%d")
        log_file = log_dir / f"entry_check_{today}.log"

        if not log_file.exists():
            return None

        try:
            lines = log_file.read_text().strip().split("\n")
            if not lines:
                return None

            # Read last line (most recent entry)
            last_line = lines[-1]

            # Parse log format: "[HH:MM:SS] | 🟢 GO | BULLISH 75% | T:BULLISH(5%) | TL:BULLISH(80%)"
            # Extract signal and confidence
            match = re.search(r"(BULLISH|BEARISH|NEUTRAL)\s+(\d+)%", last_line)
            if match:
                signal = match.group(1)
                confidence = int(match.group(2))

                # Extract trend signal
                trend_match = re.search(r"T:(\w+)\((\d+)%\)", last_line)
                trend_signal = trend_match.group(1) if trend_match else "UNKNOWN"

                # Extract traffic light signal
                tl_match = re.search(r"TL:(\w+)\((\d+)%\)", last_line)
                tl_signal = tl_match.group(1) if tl_match else "UNKNOWN"

                return {
                    "signal": signal,
                    "confidence": confidence,
                    "timestamp": datetime.now().isoformat(),  # Approximate
                    "trend_signal": trend_signal,
                    "traffic_light_signal": tl_signal,
                    "reasoning": f"Read from log (last entry at {last_line[:20]}...)",
                }
        except Exception as e:
            return None

        return None

    def _query_duckdb(self, index: str) -> dict | None:
        """
        Fallback: Query DuckDB directly for latest indicators

        This extracts the core trend/traffic light logic from Redis
        and runs it against DuckDB data.
        """
        try:
            from duckdb_tool import _connect
            import sys
            from pathlib import Path

            # Add antariksh to path to import entry_tools
            sys.path.insert(0, str(Path(__file__).parent.parent.parent / "antariksh"))

            con = _connect()

            # Get latest bar from DuckDB
            row = con.execute(
                "SELECT spot, ema_20, adx, supertrend_direction "
                "FROM ohlcv_1min WHERE index_name = ? "
                "ORDER BY timestamp DESC LIMIT 1",
                (index,),
            ).fetchone()

            if not row:
                return None

            spot, ema_20, adx, st_direction = row

            # Simple heuristic: if ADX > 25 + ST agreement = trending
            if adx and adx > 25 and st_direction:
                signal = "BULLISH" if st_direction.lower() == "bullish" else "BEARISH"
                confidence = min(int(adx / 30 * 100), 95)
            elif adx and adx < 20:
                signal = "NEUTRAL"
                confidence = 50
            else:
                signal = "NEUTRAL"
                confidence = 40

            return {
                "signal": signal,
                "confidence": confidence,
                "timestamp": datetime.now().isoformat(),
                "trend_signal": signal,
                "traffic_light_signal": "UNKNOWN",
                "reasoning": f"DuckDB fallback: ADX={adx:.1f}, ST={st_direction}",
            }

        except Exception as e:
            return None
