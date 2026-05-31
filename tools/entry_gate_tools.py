"""
Entry Gate Tools — Deterministic EMA + Traffic Light scoring wrapped as CrewAI Tools.

Used by the Entry Agent. 0 LLM, 0 DuckDB — pure Redis + file-based EMA state.
Future: append query_news_sentiment, query_rl_model tools.
"""

import json
import sys
from pathlib import Path
from datetime import datetime

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

# Reach into antariksh for deterministic scoring functions
# (importlib avoids name collision with brahmand/tools/ package)
import importlib.util

_ANTARIKSH_TOOLS = (
    Path(__file__).parent.parent.parent / "antariksh" / "tools" / "entry_tools.py"
)
_spec = importlib.util.spec_from_file_location(
    "entry_tools_antariksh", str(_ANTARIKSH_TOOLS)
)
_entry_tools = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_entry_tools)
_score_trend_redis = _entry_tools.score_trend_redis
_score_traffic_light_redis = _entry_tools.score_traffic_light_redis


class IndexInput(BaseModel):
    index: str = Field(default="NIFTY", description="Index to query: NIFTY or SENSEX")


# ── Tool 1: Trend EMA Scoring ────────────────────────────────────────────


class QueryTrendEMA(BaseTool):
    name: str = "query_trend_ema"
    description: str = (
        "Query EMA alignment scoring for the given index. "
        "Returns BULLISH/BEARISH/NEUTRAL signal, confidence (5-90%), score, "
        "alignment count (e.g. 4/5), ema_source (60min or 1min fallback), "
        "and individual EMA values. "
        "High confidence (80%+): strong trend. Low confidence (40-79%): mixed. "
        "Confidence 5% means no data or Redis unavailable. "
        "Use this to determine the TREND component of the entry gate."
    )
    args_schema: type[BaseModel] = IndexInput

    def _run(self, index: str = "NIFTY") -> str:
        try:
            result = _score_trend_redis(index)
            return json.dumps(
                {
                    "signal": result["signal"],
                    "confidence": result["confidence"],
                    "score": result["score"],
                    "aligned": result.get("key_indicators", {}).get(
                        "ema_aligned",
                        f"{result.get('key_indicators', {}).get('available_count', 0)}",
                    ),
                    "available": result.get("key_indicators", {}).get(
                        "available_count", len(result.get("ema_values", {}))
                    ),
                    "ema_source": result.get("ema_source", "?"),
                    "ema_values": result.get("key_indicators", {}).get(
                        "ema_values", {}
                    ),
                    "ema_status": result.get("ema_status", {}),
                    "method": result.get("_method", "?"),
                },
                indent=2,
                default=str,
            )
        except Exception as e:
            return json.dumps({"error": str(e), "signal": "NEUTRAL", "confidence": 5})


# ── Tool 2: Traffic Light Scoring ────────────────────────────────────────


class QueryTrafficLight(BaseTool):
    name: str = "query_traffic_light"
    description: str = (
        "Query the 7-light traffic light system for the given index. "
        "Aggregates 1-min candles to 6 timeframes (5m,15m,30m,60m,240m,1440m), "
        "matches known patterns, applies gap direction weighting. "
        "Returns signal (BULLISH/BEARISH/NEUTRAL), confidence (5-100%), score, "
        "pattern name (e.g. BULLISH_CONTINUATION, DEAD_CAT_BOUNCE), gap direction, "
        "and story (e.g. '1440m=GREEN | 240m=GREEN | ... | G=4/6 R=2/6'). "
        "STRONG_BEAR_CONTINUATION (6 red) = -9 / 90% — almost certain sell. "
        "MOMENTUM_PEAK (6 green) = +6 / 70% — bullish but exhaustion risk. "
        "Use this to determine the TRAFFIC LIGHT component of the entry gate."
    )
    args_schema: type[BaseModel] = IndexInput

    def _run(self, index: str = "NIFTY") -> str:
        try:
            result = _score_traffic_light_redis(index)
            ki = result.get("key_indicators", {})
            return json.dumps(
                {
                    "signal": result["signal"],
                    "confidence": result["confidence"],
                    "score": result["score"],
                    "pattern": ki.get("pattern", "?"),
                    "story": ki.get("story", "?"),
                    "n_bars": ki.get("n_bars", 0),
                    "gap": ki.get("gap", "unknown"),
                    "gap_boost": ki.get("gap_boost", 0),
                    "gap_conf_adjust": ki.get("gap_conf_adjust", 0),
                    "method": result.get("_method", "?"),
                },
                indent=2,
                default=str,
            )
        except Exception as e:
            return json.dumps({"error": str(e), "signal": "NEUTRAL", "confidence": 5})


# ── Tool 3: Check Active Spreads ─────────────────────────────────────────


class CheckActiveSpreads(BaseTool):
    name: str = "check_active_spreads"
    description: str = (
        "CRITICAL DEDUCTION TOOL: Determine if ANY trade is still OPEN TODAY. "
        "If ANY active trade exists → skip this cycle. The morph system handles "
        "shifting single spreads to dual spreads and vice versa. "
        "Returns: {has_active_trade, active_trade_ids, trade_count, deduction_notes}. "
        "ALL agents MUST call this FIRST: if has_active_trade=true, return go:false (position already open)."
    )
    args_schema: type[BaseModel] = IndexInput

    def _run(self, index: str = "NIFTY") -> str:
        import json
        from order_routing import get_active_trades

        try:
            active_trades = get_active_trades()

            trade_ids = []
            for trade in active_trades:
                if not isinstance(trade, dict):
                    continue
                if trade.get("status") == "ACTIVE" and trade.get("entry_time"):
                    trade_ids.append(trade.get("trade_id", "?"))

            has_active = len(trade_ids) > 0
            result = {
                "has_active_trade": has_active,
                "active_trade_ids": trade_ids,
                "trade_count": len(trade_ids),
                "deduction_notes": (
                    [
                        f"{len(trade_ids)} active trade(s): {', '.join(trade_ids)} — skip entry"
                    ]
                    if has_active
                    else ["No active trades — entry check may proceed"]
                ),
            }
            return json.dumps(result, indent=2)

        except Exception as e:
            return json.dumps(
                {
                    "error": str(e),
                    "has_active_trade": False,
                    "active_trade_ids": [],
                    "trade_count": 0,
                    "deduction_notes": ["Error during position check"],
                }
            )


# ── Tool 4: Evaluate NOT_UP Rejection (Deterministic) ─────────────────────


class EvaluateNotUpRejection(BaseTool):
    name: str = "evaluate_not_up_rejection"
    description: str = (
        "DETERMINISTIC tool: Evaluate if market REJECTS UPSIDE (bearish pressure). "
        "Internally calls query_trend_ema and query_traffic_light, then applies rejection logic. "
        "NO LLM reasoning — pure logic: "
        "- Both BEARISH → go:true, confidence 90% "
        "- One BEARISH + one NEUTRAL → go:true, confidence 60% "
        "- Both NEUTRAL or any BULLISH → go:false "
        "Returns: {go, signal: 'NOT_UP', confidence, trend_signal, traffic_light_signal, reasoning}"
    )
    args_schema: type[BaseModel] = IndexInput

    def _run(self, index: str = "NIFTY") -> str:
        try:
            # Get trend signal
            trend_result = _score_trend_redis(index)
            trend_signal = trend_result.get("signal", "NEUTRAL")
            trend_conf = trend_result.get("confidence", 50)

            # Get traffic light signal
            tl_result = _score_traffic_light_redis(index)
            tl_signal = tl_result.get("signal", "NEUTRAL")
            tl_conf = tl_result.get("confidence", 50)
            tl_pattern = tl_result.get("key_indicators", {}).get("pattern", "?")

            # DETERMINISTIC LOGIC: NOT_UP rejection (market can't go up)
            go = False
            confidence = 0
            reasoning = ""

            if trend_signal == "BEARISH" and tl_signal == "BEARISH":
                # Both BEARISH = strong upside rejection
                go = True
                confidence = round((trend_conf + tl_conf) / 2)
                reasoning = f"Both Trend ({trend_conf}%) and TL ({tl_conf}%) are BEARISH. Strong upside rejection."

            elif (trend_signal == "BEARISH" and tl_signal == "NEUTRAL") or (
                trend_signal == "NEUTRAL" and tl_signal == "BEARISH"
            ):
                # One BEARISH + one NEUTRAL = moderate upside rejection
                go = True
                confidence = round(
                    max(trend_conf if trend_signal == "BEARISH" else tl_conf, 0) * 0.67
                )
                reasoning = f"One BEARISH ({trend_signal if tl_signal == 'NEUTRAL' else tl_signal}) + one NEUTRAL. Moderate upside rejection."

            elif trend_signal == "BULLISH" or tl_signal == "BULLISH":
                # Any BULLISH = no upside rejection
                go = False
                confidence = 0
                reasoning = f"Trend: {trend_signal}({trend_conf}%), TL: {tl_signal}({tl_conf}%). No upside rejection."

            else:
                # Both NEUTRAL = insufficient
                go = False
                confidence = 0
                reasoning = (
                    "Both Trend and TL are NEUTRAL. Insufficient bearish pressure."
                )

            return json.dumps(
                {
                    "go": go,
                    "signal": "NOT_UP",
                    "confidence": confidence,
                    "trend_signal": trend_signal,
                    "trend_confidence": trend_conf,
                    "traffic_light_signal": tl_signal,
                    "traffic_light_confidence": tl_conf,
                    "tl_pattern": tl_pattern,
                    "reasoning": reasoning,
                },
                indent=2,
            )

        except Exception as e:
            return json.dumps(
                {
                    "error": str(e),
                    "go": False,
                    "signal": "NOT_UP",
                    "confidence": 0,
                    "reasoning": f"Evaluation error: {e}",
                }
            )


# ── Tool 5: Evaluate NOT_DOWN Rejection (Deterministic) ───────────────────


class EvaluateNotDownRejection(BaseTool):
    name: str = "evaluate_not_down_rejection"
    description: str = (
        "DETERMINISTIC tool: Evaluate if market REJECTS DOWNSIDE (bullish pressure). "
        "Internally calls query_trend_ema and query_traffic_light, then applies rejection logic. "
        "NO LLM reasoning — pure logic: "
        "- Both BULLISH → go:true, confidence 90% "
        "- One BULLISH + one NEUTRAL → go:true, confidence 60% "
        "- Both NEUTRAL or any BEARISH → go:false "
        "Returns: {go, signal: 'NOT_DOWN', confidence, trend_signal, traffic_light_signal, reasoning}"
    )
    args_schema: type[BaseModel] = IndexInput

    def _run(self, index: str = "NIFTY") -> str:
        try:
            # Get trend signal
            trend_result = _score_trend_redis(index)
            trend_signal = trend_result.get("signal", "NEUTRAL")
            trend_conf = trend_result.get("confidence", 50)

            # Get traffic light signal
            tl_result = _score_traffic_light_redis(index)
            tl_signal = tl_result.get("signal", "NEUTRAL")
            tl_conf = tl_result.get("confidence", 50)
            tl_pattern = tl_result.get("key_indicators", {}).get("pattern", "?")

            # DETERMINISTIC LOGIC: NOT_DOWN rejection (market can't go down)
            go = False
            confidence = 0
            reasoning = ""

            if trend_signal == "BULLISH" and tl_signal == "BULLISH":
                # Both BULLISH = strong downside rejection
                go = True
                confidence = round((trend_conf + tl_conf) / 2)
                reasoning = f"Both Trend ({trend_conf}%) and TL ({tl_conf}%) are BULLISH. Strong downside rejection."

            elif (trend_signal == "BULLISH" and tl_signal == "NEUTRAL") or (
                trend_signal == "NEUTRAL" and tl_signal == "BULLISH"
            ):
                # One BULLISH + one NEUTRAL = moderate downside rejection
                go = True
                confidence = round(
                    max(trend_conf if trend_signal == "BULLISH" else tl_conf, 0) * 0.67
                )
                reasoning = f"One BULLISH ({trend_signal if tl_signal == 'NEUTRAL' else tl_signal}) + one NEUTRAL. Moderate downside rejection."

            elif trend_signal == "BEARISH" or tl_signal == "BEARISH":
                # Any BEARISH = no downside rejection
                go = False
                confidence = 0
                reasoning = f"Trend: {trend_signal}({trend_conf}%), TL: {tl_signal}({tl_conf}%). No downside rejection."

            else:
                # Both NEUTRAL = insufficient
                go = False
                confidence = 0
                reasoning = (
                    "Both Trend and TL are NEUTRAL. Insufficient bullish pressure."
                )

            return json.dumps(
                {
                    "go": go,
                    "signal": "NOT_DOWN",
                    "confidence": confidence,
                    "trend_signal": trend_signal,
                    "trend_confidence": trend_conf,
                    "traffic_light_signal": tl_signal,
                    "traffic_light_confidence": tl_conf,
                    "tl_pattern": tl_pattern,
                    "reasoning": reasoning,
                },
                indent=2,
            )

        except Exception as e:
            return json.dumps(
                {
                    "error": str(e),
                    "go": False,
                    "signal": "NOT_DOWN",
                    "confidence": 0,
                    "reasoning": f"Evaluation error: {e}",
                }
            )
