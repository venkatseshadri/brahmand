"""position_research_cache.py — cached LLM position-management research.

Mirror of unicorn_research_cache for the POSITION MANAGER. A slow research cron
(every 15 min) writes a per-trade discretionary assessment (morph/roll/tighten/
hold + the resulting actions + reason); the 1-min run_bridge loads it and applies
it deterministically — zero LLM latency on the hot path.

Safety contract (this is the risk path):
  * Only DISCRETIONARY actions (morph/roll/tighten) are ever cached here.
    Protective triggers — SL, TP, P&L floor, EOD square-off — are NEVER cached;
    run_bridge evaluates those immediately every cycle.
  * The signature buckets regime + position state. A material change invalidates
    the cache even within TTL, so run_bridge falls back to a LIVE deterministic
    recompute. The 15-min cache therefore only applies when conditions are stable.

Keyed by trade_id so each open position has its own assessment.
"""

import json
import os
import time
from pathlib import Path

# Sandbox-aware (matches trade_execution_db / order_routing): under BRAHMAND_SANDBOX
# the cache lives in the sandbox; in prod it's brahmand/data/position_cache.
_BASE = Path(os.environ.get("BRAHMAND_SANDBOX") or (Path(__file__).parent / "data"))
CACHE_DIR = _BASE / "position_cache"
CACHE_TTL = int(os.environ.get("POSITION_CACHE_TTL", 900))  # 15 min

CACHE_DIR.mkdir(parents=True, exist_ok=True)


def cache_path(trade_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(trade_id))
    return CACHE_DIR / f"assessment_{safe}.json"


def save_assessment(trade_id: str, assessment: dict, signature: str = "") -> bool:
    """Persist a per-trade discretionary assessment. `assessment` carries at least
    {"actions": [...], "recommendation": str, "reason": str, "source": str}."""
    cache = {
        "trade_id": trade_id,
        "cached_at": time.time(),
        "cached_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "ttl": CACHE_TTL,
        "signature": signature,
        "assessment": assessment,
    }
    try:
        cpath = cache_path(trade_id)
        tmppath = cpath.with_suffix(cpath.suffix + ".tmp")
        tmppath.write_text(json.dumps(cache, indent=2, default=str))
        os.replace(tmppath, cpath)  # atomic on same filesystem
        return True
    except Exception:
        return False


def load_assessment(
    trade_id: str, max_age_sec: int = None, signature: str = ""
) -> dict | None:
    """Return the cached assessment if fresh AND (when given) signature matches,
    else None. A None return is the signal for run_bridge to recompute live."""
    ttl = max_age_sec if max_age_sec is not None else CACHE_TTL
    cpath = cache_path(trade_id)
    if not cpath.exists():
        return None
    try:
        cache = json.loads(cpath.read_text())
    except (json.JSONDecodeError, OSError):
        return None

    if time.time() - cache.get("cached_at", 0) > ttl:
        return None
    if signature and cache.get("signature") != signature:
        return None
    return cache.get("assessment")


def cache_age_sec(trade_id: str) -> float | None:
    cpath = cache_path(trade_id)
    if not cpath.exists():
        return None
    try:
        cache = json.loads(cpath.read_text())
        return time.time() - cache.get("cached_at", 0)
    except Exception:
        return None


def invalidate(trade_id: str = None):
    """Delete one trade's cache, or all if trade_id is None (e.g. on close)."""
    if trade_id:
        cpath = cache_path(trade_id)
        if cpath.exists():
            cpath.unlink()
    else:
        for cpath in CACHE_DIR.glob("assessment_*.json"):
            cpath.unlink()


def compute_position_signature(trade: dict, spot: float = 0, mtm: float = 0) -> str:
    """Lightweight signature over regime + position state. Buckets spot/MTM so
    minor noise doesn't churn the cache, but a material move (or a regime/leg
    change) flips it → run_bridge recomputes live."""
    try:
        legs = trade.get("legs", []) or []
        leg_sig = ",".join(
            sorted(f"{l.get('type')}:{l.get('action')}:{l.get('strike', '')}" for l in legs)
        )
        spot_bucket = int(float(spot or 0) / 50) * 50
        mtm_bucket = int(float(mtm or 0) / 500) * 500  # ₹500 buckets
        signal = trade.get("entry_gate_signal") or trade.get("entry_signal") or ""
        strategy = trade.get("strategy", "")
        return f"sig:{signal}|strat:{strategy}|legs:{leg_sig}|spot:{spot_bucket}|mtm:{mtm_bucket}"
    except (TypeError, ValueError, KeyError):
        return ""
