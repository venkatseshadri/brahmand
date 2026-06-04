"""JSON output parser — extracts JSON from agent raw output with markdown fences."""

import json


def parse_json_output(raw: str) -> dict:
    """Extract JSON dict from agent raw output (may have markdown fences).

    Uses a brace-matching scanner that handles arbitrary nesting depth,
    unlike the previous regex which was limited to 2 levels.
    """
    if not raw or not raw.strip():
        return {}

    raw = raw.strip()

    if raw.startswith("```"):
        first_nl = raw.find("\n")
        if first_nl != -1:
            raw = raw[first_nl + 1 :]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()

    start = raw.find("{")
    if start == -1:
        return {}

    depth = 0
    for i in range(start, len(raw)):
        ch = raw[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = raw[start : i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    return {}

    return {}
