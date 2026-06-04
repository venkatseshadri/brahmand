"""
unicorn_verify.py — Deterministic claim verifier for Unicorn debate.

Pure Python. NO LLM. Field-level numeric comparison only.
Corrects C2 from the design doc: verification moves OUT of the Judge LLM.

Every claim an Advocate/Skeptic makes is checked against the raw data
before the Judge LLM ever sees it. This file gets exact-equality tests
because it's deterministic — same input → byte-identical output.
"""

import json

from unicorn_logger import log_verify, log_verdict, log_error

# ── Tolerance per field type ───────────────────────────────────────────

TOLERANCE = {
    "abs_default": 0.5,
    "pct_fields": {"iv_rank", "bb_pct_b", "cmf", "pcr_total", "pcr_atm"},
    "pct_tol": 0.02,
    "direction_fields": {
        "sma_position",
        "st_consensus",
        "st_direction",
        "st_5m_direction",
        "st_15m_direction",
        "candle",
        "rsi_zone",
        "cmf_signal",
        "sentiment",
        "iv_regime",
        "session_phase",
        "color",
    },
}

DEFAULT_WEIGHTS = {
    "trend": 1.0,
    "momentum": 1.0,
    "volatility": 1.0,
    "volume": 1.0,
    "options": 1.0,
    "flow": 1.0,
    "macro": 1.0,
}


def _get_tolerance(field: str) -> float:
    """Return the numeric tolerance for a given field name."""
    if field in TOLERANCE["pct_fields"]:
        return TOLERANCE["pct_tol"]
    return TOLERANCE["abs_default"]


def _is_direction_field(field: str) -> bool:
    """Direction/classification fields are compared by string equality,
    not numeric tolerance."""
    return field in TOLERANCE["direction_fields"]


# Sentinel for "field truly not found" — distinct from found-but-None
_MISSING = object()


def _find_raw_value(raw: dict, family: str, field: str) -> tuple:
    """Search raw data for a field value.

    Tries: raw[family][field], raw[family][timeframes][*][field],
    raw[family][indicators][field].

    Returns (value, path) where path is the lookup path string.
    Returns (_MISSING, None) if truly not found.
    None as value means field exists but has no data (e.g., post-market).
    """
    fam_data = raw.get(family, {})
    if not isinstance(fam_data, dict):
        return _MISSING, None

    # Direct top-level access (use 'in' to detect None vs absent)
    if field in fam_data:
        val = fam_data[field]
        if isinstance(val, dict):
            return _flatten_dict_value(fam_data, field, family), f"{family}.{field}"
        return val, f"{family}.{field}"

    # Search timeframes
    timeframes = fam_data.get("timeframes", {})
    if isinstance(timeframes, dict):
        for tf, tf_data in timeframes.items():
            if isinstance(tf_data, dict) and field in tf_data:
                return tf_data[field], f"{family}.timeframes.{tf}.{field}"

    # Search indicators
    indicators = fam_data.get("indicators", {})
    if isinstance(indicators, dict):
        if field in indicators:
            val = indicators[field]
            if isinstance(val, dict):
                return _flatten_dict_value(
                    indicators, field, family
                ), f"{family}.indicators.{field}"
            return val, f"{family}.indicators.{field}"
        for sub, sub_data in indicators.items():
            if isinstance(sub_data, dict) and field in sub_data:
                return sub_data[field], f"{family}.indicators.{sub}.{field}"

    return _MISSING, None


def _flatten_dict_value(data: dict, key: str, family: str) -> any:
    """If a field value is itself a dict, try to find the most representative
    numeric value (e.g., the lowest TF or the first numeric value)."""
    val = data[key]
    if not isinstance(val, dict):
        return val
    for k in sorted(val.keys()):
        if isinstance(val[k], (int, float)):
            return val[k]
    return list(val.values())[0] if val else None


def _resolve_tf_field(raw: dict, family: str, tf: str, field: str):
    """Direct lookup: raw[family][timeframes][tf][field]."""
    try:
        return raw[family]["timeframes"][tf][field]
    except (KeyError, TypeError):
        return None


def verify_points(
    raw: dict,
    points: list,
    family_weights: dict = None,
) -> dict:
    """Verify a list of claim points against raw data.

    Args:
        raw: dict from unicorn_raw_query (7 families + candles).
        points: list of {family, claim, evidence: {field: value}} dicts.
        family_weights: optional per-family weight dict.

    Returns:
        {score, tags:[], hallucinations:[], families_covered:set}
    """
    weights = family_weights or DEFAULT_WEIGHTS

    tags = []
    hallucinations = []
    families_covered = set()
    score = 0.0

    for i, point in enumerate(points):
        family = point.get("family", "unknown")
        evidence = point.get("evidence", {})
        weight = weights.get(family, 1.0)

        families_covered.add(family)

        field_seen = False
        for field, claimed_val in evidence.items():
            field_seen = True
            raw_val, path = _find_raw_value(raw, family, field)

            if raw_val is _MISSING:
                # Field truly not in raw data
                tag = "UNVERIFIABLE"
                reason = f"field '{field}' not found in raw data for family '{family}'"
                score += 0.5 * weight
                tags.append(
                    {
                        "family": family,
                        "field": field,
                        "tag": tag,
                        "reason": reason,
                        "claimed": claimed_val,
                        "point_index": i,
                    }
                )
                continue

            if raw_val is None:
                # Field exists but has no data — treat as UNVERIFIABLE
                tag = "UNVERIFIABLE"
                reason = f"field '{field}' exists but has no value (None/null) for family '{family}'"
                score += 0.5 * weight
                tags.append(
                    {
                        "family": family,
                        "field": field,
                        "tag": tag,
                        "reason": reason,
                        "claimed": claimed_val,
                        "point_index": i,
                    }
                )
                continue

            if _is_direction_field(field) or isinstance(raw_val, str):
                # String comparison for direction/classification fields
                if str(raw_val).lower() == str(claimed_val).lower():
                    tag = "VERIFIED"
                    score += 1.0 * weight
                else:
                    tag = "CONTRADICTED"
                    hallucinations.append(
                        f"{family}.{field} claimed {claimed_val}, raw={raw_val} → CONTRADICTED"
                    )
                    score += 0.0
            else:
                # Numeric comparison
                try:
                    raw_num = float(raw_val)
                    claimed_num = float(claimed_val)
                    tol = _get_tolerance(field)

                    if abs(claimed_num - raw_num) <= tol:
                        tag = "VERIFIED"
                        score += 1.0 * weight
                    else:
                        tag = "CONTRADICTED"
                        hallucinations.append(
                            f"{family}.{field} claimed {claimed_num}, raw={raw_num} → CONTRADICTED"
                        )
                        score += 0.0
                except (ValueError, TypeError):
                    # Non-numeric comparison — compare as strings
                    if str(raw_val) == str(claimed_val):
                        tag = "VERIFIED"
                        score += 1.0 * weight
                    else:
                        tag = "CONTRADICTED"
                        hallucinations.append(
                            f"{family}.{field} claimed {claimed_val}, raw={raw_val} → CONTRADICTED"
                        )
                        score += 0.0

            tags.append(
                {
                    "family": family,
                    "field": field,
                    "tag": tag,
                    "claimed": claimed_val,
                    "raw": raw_val,
                    "path": path,
                    "point_index": i,
                }
            )

        if not field_seen:
            tags.append(
                {
                    "family": family,
                    "field": "(none)",
                    "tag": "UNVERIFIABLE",
                    "reason": "no evidence fields in point",
                    "point_index": i,
                }
            )
            score += 0.3 * weight

    # Normalize score to 0-1 range based on total possible points
    max_possible = len(points) * 1.0 or 1
    normalized = min(score / max_possible, 1.0)

    for h in hallucinations:
        log_verdict(gate="", field="", tag="CONTRADICTED", message=h)

    return {
        "score": round(normalized, 4),
        "raw_score": round(score, 4),
        "max_possible": max_possible,
        "tags": tags,
        "hallucinations": hallucinations,
        "families_covered": sorted(families_covered),
    }
