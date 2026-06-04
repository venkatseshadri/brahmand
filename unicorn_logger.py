"""
unicorn_logger.py — Structured debug/troubleshooting logging for UNICORN.

Writes to logs/unicorn_YYYYMMDD.log alongside the existing kickoff/chain logs.
Every decision branch, error condition, and key metric is captured so failure
root-cause is traceable from logs alone — no code-read required.

Usage:
    from unicorn_logger import unicorn_log
    unicorn_log("raw_query", status="ok", elapsed=0.15, families=8)
    unicorn_log("verify", tag="CONTRADICTED", field="adx", claimed=55, raw=38)
    unicorn_log("judge", decision="ENTER", adv_score=3.0, skp_score=1.0, confidence=0.45)

Log file: brahmand/logs/unicorn_YYYYMMDD.log
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
_LOGGER = None

# ── Phase constants (for structured filtering) ─────────────────────────

PHASE_RAW_QUERY = "raw_query"
PHASE_CACHE = "cache"
PHASE_VERIFY = "verify"
PHASE_JUDGE = "judge"
PHASE_DEBATE = "debate"
PHASE_ANOMALY = "anomaly"
PHASE_RESEARCH = "research"

# ── Status constants ────────────────────────────────────────────────────

STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_ERROR = "error"
STATUS_SKIP = "skip"
STATUS_ENTER = "ENTER"
STATUS_FALLBACK = "fallback"
STATUS_CACHE_HIT = "cache_hit"
STATUS_CACHE_MISS = "cache_miss"
STATUS_ANOMALY = "anomaly"


def _ensure_logger():
    global _LOGGER
    if _LOGGER is not None:
        return _LOGGER

    import logging

    today = datetime.now().strftime("%Y%m%d")
    log_path = LOG_DIR / f"unicorn_{today}.log"

    _LOGGER = logging.getLogger("unicorn")
    _LOGGER.setLevel(logging.DEBUG)

    if not _LOGGER.handlers:
        fh = logging.FileHandler(str(log_path))
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(
            logging.Formatter(
                "[%(asctime)s] %(levelname)s %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        _LOGGER.addHandler(fh)

    return _LOGGER


def unicorn_log(
    phase: str,
    status: str = STATUS_OK,
    gate: str = "",
    message: str = "",
    **kwargs,
):
    """Structured UNICORN event log. All kwargs appear in the JSON.

    Args:
        phase: One of PHASE_* constants (raw_query, verify, judge, etc.)
        status: One of STATUS_* constants
        gate: "NOT_UP" or "NOT_DOWN" (if applicable)
        message: Human-readable summary
        **kwargs: Arbitrary structured data (scores, counts, timings, etc.)
    """
    logger = _ensure_logger()
    entry = {
        "phase": phase,
        "status": status,
    }
    if gate:
        entry["gate"] = gate
    if message:
        entry["msg"] = message
    entry.update(kwargs)

    level = (
        logging.WARNING if status in (STATUS_ERROR, STATUS_ANOMALY) else logging.INFO
    )
    logger.log(level, json.dumps(entry, default=str))


# ── Convenience event functions ─────────────────────────────────────────


def log_raw_query(
    status: str = STATUS_OK,
    families: int = 0,
    elapsed: float = 0.0,
    cache_valid: bool = False,
    **kwargs,
):
    """Log raw query completion."""
    unicorn_log(
        PHASE_RAW_QUERY,
        status=status,
        families=families,
        elapsed=round(elapsed, 3),
        cache_valid=cache_valid,
        **kwargs,
    )


def log_cache(
    gate: str,
    hit: bool,
    age: Optional[float] = None,
    signature_match: bool = True,
    **kwargs,
):
    """Log cache load result."""
    unicorn_log(
        PHASE_CACHE,
        gate=gate,
        status=STATUS_CACHE_HIT if hit else STATUS_CACHE_MISS,
        age_sec=round(age, 1) if age is not None else None,
        signature_match=signature_match,
        **kwargs,
    )


def log_verify(
    gate: str,
    role: str,
    raw_score: float,
    normalized_score: float,
    hallucinations: int,
    families: int,
    elapsed: float = 0.0,
    **kwargs,
):
    """Log verification result for one side (Advocate or Skeptic)."""
    unicorn_log(
        PHASE_VERIFY,
        gate=gate,
        status=STATUS_OK,
        role=role,
        raw_score=round(raw_score, 3),
        score=round(normalized_score, 3),
        hallucinations=hallucinations,
        families=families,
        elapsed=round(elapsed, 3),
        **kwargs,
    )


def log_verdict(
    gate: str,
    field: str,
    tag: str,
    claimed=None,
    raw=None,
    **kwargs,
):
    """Log individual verification verdict (per field)."""
    unicorn_log(
        PHASE_VERIFY,
        gate=gate,
        status=tag.lower(),
        field=field,
        tag=tag,
        claimed=claimed,
        raw=raw,
        **kwargs,
    )


def log_judge(
    gate: str,
    decision: str,
    adv_score: float,
    skp_score: float,
    confidence: float,
    hallucinations: int,
    families_covered: int,
    elapsed: float = 0.0,
    **kwargs,
):
    """Log judge decision."""
    unicorn_log(
        PHASE_JUDGE,
        gate=gate,
        status=STATUS_ENTER if decision not in ("NONE", "SKIP") else STATUS_SKIP,
        decision=decision,
        adv_score=round(adv_score, 3),
        skp_score=round(skp_score, 3),
        confidence=round(confidence, 3),
        hallucinations=hallucinations,
        families_covered=families_covered,
        elapsed=round(elapsed, 3),
        **kwargs,
    )


def log_debate(
    gate: str,
    status: str,
    signal: str = "NONE",
    go: bool = False,
    confidence: float = 0.0,
    elapsed: float = 0.0,
    **kwargs,
):
    """Log full debate cycle result."""
    unicorn_log(
        PHASE_DEBATE,
        gate=gate,
        status=status,
        signal=signal,
        go=go,
        confidence=round(confidence, 3),
        elapsed=round(elapsed, 3),
        **kwargs,
    )


def log_anomaly(
    gate: str,
    flags: list,
    fallback_triggered: bool = False,
    **kwargs,
):
    """Log anomaly detection event."""
    unicorn_log(
        PHASE_ANOMALY,
        gate=gate,
        status=STATUS_ANOMALY if flags else STATUS_OK,
        flags=flags,
        fallback_triggered=fallback_triggered,
        **kwargs,
    )


def log_error(
    phase: str,
    error: str,
    gate: str = "",
    exception: Optional[Exception] = None,
    **kwargs,
):
    """Log an error condition."""
    unicorn_log(
        phase,
        gate=gate,
        status=STATUS_ERROR,
        error=error,
        exception=str(exception) if exception else None,
        **kwargs,
    )
