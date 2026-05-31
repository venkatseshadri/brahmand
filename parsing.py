"""JSON output parser — extracts JSON from agent raw output with markdown fences."""

import json
import re


def parse_json_output(raw: str) -> dict:
    """Extract JSON dict from agent raw output (may have markdown fences)."""
    if not raw or not raw.strip():
        return {}
    match = re.search(r"\{(?:[^{}]|\{[^{}]*\})*\}", raw, re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return {}
