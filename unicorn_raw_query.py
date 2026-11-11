"""
UnicornRawQuery — CrewAI tool that returns raw market data across 7 families.

Calls the 7 individual query functions from antariksh.tools.entry_tools,
NOT query_all_families (which includes scored traffic_light verdicts).

Returns ~50 raw fields with ZERO verdicts, classifications, or go/no-go tokens.
60-second TTL cache — all agents in a debate cycle see the same frozen snapshot.
"""

import json
import time
from pathlib import Path
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from unicorn_logger import log_raw_query, log_error

FAMILIES = [
    "trend",
    "momentum",
    "volatility",
    "volume",
    "options",
    "flow",
    "macro",
]

FAMILY_FUNCTIONS = {
    "trend": None,
    "momentum": None,
    "volatility": None,
    "volume": None,
    "options": None,
    "flow": None,
    "macro": None,
}

VERDICT_FIELDS = {
    "pattern",
    "confidence",
    "summary",
    "exhaustion",
    "reversal_signal",
}


class QueryInput(BaseModel):
    index: str = Field(default="NIFTY", description="Market index: NIFTY, SENSEX")


def _ensure_imports():
    """Lazy-import family query functions on first use.
    Adds antariksh parent to sys.path for namespace package discovery."""
    if FAMILY_FUNCTIONS["trend"] is not None:
        return

    import sys as _sys

    _projects_root = Path(__file__).parent.parent
    _antariksh_root = _projects_root / "antariksh"
    for p in (str(_projects_root), str(_antariksh_root)):
        if p not in _sys.path:
            _sys.path.insert(0, p)

    from antariksh.tools.entry_tools import (
        query_trend,
        query_momentum,
        query_volatility,
        query_volume,
        query_options,
        query_flow,
        query_macro,
        query_traffic_light,
    )

    FAMILY_FUNCTIONS["trend"] = query_trend
    FAMILY_FUNCTIONS["momentum"] = query_momentum
    FAMILY_FUNCTIONS["volatility"] = query_volatility
    FAMILY_FUNCTIONS["volume"] = query_volume
    FAMILY_FUNCTIONS["options"] = query_options
    FAMILY_FUNCTIONS["flow"] = query_flow
    FAMILY_FUNCTIONS["macro"] = query_macro
    FAMILY_FUNCTIONS["traffic_light"] = query_traffic_light


def _query_all(index: str = "NIFTY") -> dict:
    """Call all 7 families + traffic_light (for candles only).
    Returns raw dict with 'families' key matching query_all_families shape."""
    _ensure_imports()

    families = {}
    for name in FAMILIES:
        fn = FAMILY_FUNCTIONS[name]
        try:
            raw = fn(index)
            families[name] = json.loads(raw)
        except Exception as e:
            families[name] = {"error": str(e)}

    tl_fn = FAMILY_FUNCTIONS.get("traffic_light")
    if tl_fn:
        try:
            raw = tl_fn(index)
            families["traffic_light"] = json.loads(raw)
        except Exception as e:
            families["traffic_light"] = {"error": str(e)}

    return {
        "index": index,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "families": families,
    }


def _build_raw_payload(families: dict) -> dict:
    """Strip verdicts from families and return flat 7-family raw dict.

    The 7 design-document families are passed through as-is (they contain
    no verdict tokens). Traffic_light candle data is extracted and preserved
    under a 'candles' key.
    """
    result = {}

    for name in FAMILIES:
        if name in families:
            result[name] = families[name]

    tl = families.get("traffic_light", {})
    if isinstance(tl, dict) and "error" not in tl:
        result["candles"] = {
            "family": "Candles",
            "index": tl.get("index", ""),
            "timestamp": tl.get("timestamp", ""),
            "candles": tl.get("candles", {}),
        }

    return result


class UnicornRawQuery(BaseTool):
    name: str = "unicorn_raw_query"
    description: str = (
        "Query ALL 7 market data families (trend, momentum, volatility, "
        "volume, options, flow, macro) for raw signal values. Returns ~50 "
        "raw fields with NO verdicts, NO classifications, NO go/no-go. "
        "Use this to build evidence for your entry argument. Cite specific "
        "values from the returned JSON in your claims."
    )
    args_schema: Type[BaseModel] = QueryInput
    _cache_ttl: float = 60.0
    _cache: dict = {}
    _query = staticmethod(_query_all)

    def _run(self, index: str = "NIFTY") -> str:
        cache_key = "raw_data"
        now = time.time()
        entry = self._cache.get(cache_key)

        if entry is not None and (now - entry["ts"]) < self._cache_ttl:
            log_raw_query(
                status="cache_hit",
                families=0,
                elapsed=0,
                cache_valid=True,
                cached_age=round(now - entry["ts"], 2),
            )
            return entry["data"]

        t0 = time.time()
        raw = self._query(index)
        result = _build_raw_payload(raw["families"])

        elapsed = time.time() - t0
        families_found = len([k for k in result if k in FAMILIES])
        errors = [
            k
            for k, v in raw.get("families", {}).items()
            if isinstance(v, dict) and "error" in v
        ]

        log_raw_query(
            status="ok",
            families=families_found,
            elapsed=elapsed,
            cache_valid=False,
            errors=errors,
            index=index,
        )

        output = json.dumps(result, indent=2)
        self._cache[cache_key] = {"ts": now, "data": output}
        return output
