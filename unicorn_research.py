#!/usr/bin/env python3
"""
unicorn_research.py — Standalone LLM Research Runner

Generates Advocate/Skeptic debate points for a gate using the DeepSeek API
and caches them to disk. Called as a background subprocess from the 5-min
cron execution path when cache is empty/expired.

Writes structured logs to brahmand/logs/unicorn_YYYYMMDD.log — same file
as the execution path, so both 5-min cron and 15-min research are traceable
in one tail -f.

Usage:
    python3 unicorn_research.py --gate NOT_UP
    python3 unicorn_research.py --gate NOT_DOWN
    python3 unicorn_research.py --gate NOT_UP,NOT_DOWN
    python3 unicorn_research.py --all  # both gates

Environment:
    DEEPSEEK_API_KEY  (required)
    DEEPSEEK_BASE_URL (default: https://api.deepseek.com/v1)
    UNICORN_RESEARCH_MODEL (default: deepseek-v4-pro, advocate/judge)
    UNICORN_SKEPTIC_MODEL  (default: deepseek-v4-flash, skeptic)
"""

import json
import os
import sys
import time
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from unicorn_raw_query import UnicornRawQuery
from unicorn_research_cache import save_debate_points, compute_signature
from unicorn_logger import (
    unicorn_log,
    log_error,
    log_cache,
    log_debate,
    PHASE_RESEARCH,
    STATUS_OK,
    STATUS_ERROR,
    STATUS_WARN,
)

RESEARCH_MODEL = os.environ.get("UNICORN_RESEARCH_MODEL", "deepseek-v4-pro")
SKEPTIC_MODEL = os.environ.get("UNICORN_SKEPTIC_MODEL", "deepseek-v4-flash")


def _load_agent_config():
    import yaml

    config_path = Path(__file__).parent / "config" / "unicorn_agents.yaml"
    return yaml.safe_load(config_path.read_text())


def _build_research_prompt(
    agent_config: dict, raw_data_str: str, gate_type: str
) -> str:
    goal = agent_config["goal"].replace("{gate_type}", gate_type)
    backstory = agent_config["backstory"].replace("{gate_type}", gate_type)

    prompt = f"""{backstory}

{goal}

RAW MARKET DATA (7 families):
{raw_data_str}

TASK: Analyze this data and produce your debate points. Every claim
MUST cite a specific value from the raw data in the "evidence" field.
Cite 2-3 points across at least 2 families. Keep each "claim" under 100 characters.

OUTPUT FORMAT — Return EXACTLY this JSON (no markdown, no preamble):
{{
  "recommendation": "ENTER" or "SKIP",
  "gate_type": "{gate_type}",
  "points": [
    {{
      "family": "trend|momentum|volatility|volume|options|flow|macro",
      "claim": "What this data point tells us",
      "evidence": {{"field_name": numeric_value_or_string}}
    }}
  ]
}}
"""
    return prompt


def _parse_llm_json(text: str) -> dict | None:
    raw = (text or "").strip()
    if not raw:
        return None

    # Reasoning models (deepseek-v4-pro) may prepend a <think>...</think> block.
    if "</think>" in raw:
        raw = raw.rsplit("</think>", 1)[-1].strip()

    # Strip markdown code fences (```json ... ```).
    if raw.startswith("```"):
        first_newline = raw.find("\n")
        if first_newline != -1:
            raw = raw[first_newline + 1 :]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Prose before/after the object: isolate the outermost {...} span, then
    # try as-is and with brace-balance repair (handles truncated tails).
    first = raw.find("{")
    last = raw.rfind("}")
    candidates = []
    if first != -1 and last > first:
        candidates.append(raw[first : last + 1])
    if first != -1:
        tail = raw[first:]
        open_count = tail.count("{")
        close_count = tail.count("}")
        if open_count > close_count:
            candidates.append(tail + "}" * (open_count - close_count))

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    return None


def _call_llm(
    prompt: str,
    system_msg: str = "",
    gate: str = "",
    role: str = "",
) -> dict | None:
    try:
        from openai import OpenAI
    except ImportError:
        log_error(
            PHASE_RESEARCH,
            "openai not installed",
            gate=gate,
            message="cannot call LLM for research",
        )
        return None

    api_key = os.environ.get("OMNIROUTE_API_KEY") or os.environ.get("OPENROUTER_API_KEY") or os.environ.get("DEEPSEEK_API_KEY", "")
    base_url = os.environ.get("OMNIROUTE_BASE_URL") or os.environ.get("OPENROUTER_BASE_URL") or os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    if not api_key:
        log_error(PHASE_RESEARCH, "OMNIROUTE_API_KEY or OPENROUTER_API_KEY or DEEPSEEK_API_KEY not set", gate=gate)
        return None

    client = OpenAI(api_key=api_key, base_url=base_url)
    model = SKEPTIC_MODEL if role == "skeptic" else RESEARCH_MODEL

    def _try_parse(msgs):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=msgs,
                temperature=0,
                max_tokens=4096,
                response_format={"type": "json_object"},
            )
        except Exception:
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=msgs,
                    temperature=0,
                    max_tokens=4096,
                )
            except Exception as e:
                log_error(
                    PHASE_RESEARCH, "LLM call failed", gate=gate, role=role, exception=e
                )
                return None, None, 0, ""

        finish = getattr(resp.choices[0], "finish_reason", "") or ""
        text = (resp.choices[0].message.content or "").strip()
        result = _parse_llm_json(text)
        tokens = resp.usage.total_tokens if resp.usage else 0
        return result, finish, tokens, text

    messages = []
    if system_msg:
        messages.append({"role": "system", "content": system_msg})
    messages.append({"role": "user", "content": prompt})

    t0 = time.time()
    result, finish, tokens, text = _try_parse(messages)

    if result is not None:
        unicorn_log(
            PHASE_RESEARCH,
            status=STATUS_OK,
            gate=gate,
            role=role,
            elapsed=round(time.time() - t0, 2),
            points=len(result.get("points", [])),
            tokens_used=tokens,
            model=model,
        )
        return result

    if finish == "length":
        unicorn_log(
            PHASE_RESEARCH,
            status=STATUS_WARN,
            gate=gate,
            role=role,
            message="truncated_by_token_limit_retrying",
            raw_prefix=text[:200],
        )
        messages.append({"role": "assistant", "content": text})
        messages.append(
            {
                "role": "user",
                "content": (
                    "Your response was cut off by the token limit. "
                    "Continue EXACTLY where you left off. Return only the "
                    "remaining JSON — do not restart from the beginning."
                ),
            }
        )
    elif not text:
        unicorn_log(
            PHASE_RESEARCH,
            status=STATUS_WARN,
            gate=gate,
            role=role,
            message="empty_response_retrying",
        )
        messages.append(
            {
                "role": "user",
                "content": (
                    "You must return a JSON object. If you are unsure, "
                    'return: {"recommendation": "SKIP", "points": []}'
                ),
            }
        )
    else:
        unicorn_log(
            PHASE_RESEARCH,
            status=STATUS_WARN,
            gate=gate,
            role=role,
            message="json_parse_failed_retrying",
            raw_prefix=text[:200],
        )
        messages.append({"role": "assistant", "content": text})
        messages.append(
            {
                "role": "user",
                "content": (
                    "Your previous response was not valid JSON. "
                    "Return ONLY raw JSON — no markdown fences, no explanation, "
                    "no trailing text. Just the JSON object."
                ),
            }
        )

    result, finish, tokens, text = _try_parse(messages)

    if result is not None:
        unicorn_log(
            PHASE_RESEARCH,
            status=STATUS_OK,
            gate=gate,
            role=role,
            elapsed=round(time.time() - t0, 2),
            points=len(result.get("points", [])),
            tokens_used=tokens,
            model=model,
        )
        return result

    log_error(
        PHASE_RESEARCH,
        "failed to parse LLM JSON after retry",
        gate=gate,
        role=role,
        raw_prefix=text[:200],
        finish_reason=finish,
    )
    return None


def run_research(gate_type: str) -> bool:
    config = _load_agent_config()

    unicorn_log(
        PHASE_RESEARCH, status=STATUS_OK, gate=gate_type, message="research_start"
    )

    if gate_type not in ("NOT_UP", "NOT_DOWN"):
        log_error(PHASE_RESEARCH, f"unknown gate: {gate_type}", gate=gate_type)
        return False

    agent_cfg = config["unicorn_advocate"]
    skeptic_cfg = config["unicorn_skeptic"]

    # Raw data snapshot for both agents
    raw_query = UnicornRawQuery()
    raw_json = raw_query._run("NIFTY")
    raw_data = json.loads(raw_json)
    sig = compute_signature(raw_data)

    # ── Advocate LLM ──
    prompt = _build_research_prompt(agent_cfg, raw_json, gate_type)
    system_msg = "You are a market analyst generating evidence-based arguments from raw data. Return only valid JSON."

    result = _call_llm(prompt, system_msg, gate=gate_type, role="advocate")
    if not result:
        log_error(PHASE_RESEARCH, "advocate LLM returned no result", gate=gate_type)
        return False

    advocate_pts = result.get("points", [])
    if len(advocate_pts) < 2:
        unicorn_log(
            PHASE_RESEARCH,
            status=STATUS_WARN,
            gate=gate_type,
            message=f"advocate_only_{len(advocate_pts)}_points",
        )
        return False

    # ── Skeptic LLM ──
    skp_prompt = _build_research_prompt(skeptic_cfg, raw_json, gate_type)
    skp_result = _call_llm(skp_prompt, system_msg, gate=gate_type, role="skeptic")
    if not skp_result:
        unicorn_log(
            PHASE_RESEARCH,
            status=STATUS_WARN,
            gate=gate_type,
            message="skeptic_llm_failed_caching_advocate_only",
        )
        skeptic_pts = []
    else:
        skeptic_pts = skp_result.get("points", [])

    # ── Save to cache ──
    ok = save_debate_points(
        gate_type, advocate_pts, skeptic_pts, raw_snapshot_signature=sig
    )
    unicorn_log(
        PHASE_RESEARCH,
        status=STATUS_OK if ok else STATUS_ERROR,
        gate=gate_type,
        advocate_points=len(advocate_pts),
        skeptic_points=len(skeptic_pts),
        cached=ok,
        message="research_complete",
    )
    return ok


def main():
    parser = argparse.ArgumentParser(description="UNICORN LLM Research Runner")
    parser.add_argument("--gate", type=str, default="NOT_UP", help="Gate to research")
    parser.add_argument("--all", action="store_true", help="Research both gates")
    args = parser.parse_args()

    if args.all:
        gates = ["NOT_UP", "NOT_DOWN"]
    elif "," in args.gate:
        gates = [g.strip() for g in args.gate.split(",")]
    else:
        gates = [args.gate]

    overall_ok = True
    for gate in gates:
        start = time.time()
        ok = run_research(gate)
        elapsed = time.time() - start
        unicorn_log(
            PHASE_RESEARCH,
            status=STATUS_OK if ok else STATUS_ERROR,
            gate=gate,
            elapsed=round(elapsed, 2),
            message="gate_complete",
        )
        if not ok:
            overall_ok = False

    sys.exit(0 if overall_ok else 1)


if __name__ == "__main__":
    main()
