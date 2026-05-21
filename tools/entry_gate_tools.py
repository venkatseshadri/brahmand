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
