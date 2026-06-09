"""Agent output parsing — robustly extract a JSON dict from CrewAI outputs.

CrewAI's `TaskOutput.__str__` returns `str(json_dict)` / `str(pydantic)` when the
agent produced structured output — i.e. a PYTHON repr with single quotes
(`{'regime': 'enter'}`), which `json.loads` cannot parse. The old extraction
`parse_json_output(str(task_output))` therefore silently returned `{}` whenever the
agent emitted structured output, cascading to regime=None → strategy=NONE → no trade.

Fix: `extract_task_output` reads the structured fields DIRECTLY and only falls back
to text parsing; `parse_json_output` is string-aware and tolerates single-quoted
python-repr dicts.
"""

import ast
import json


def _iter_json_objects(s: str):
    """Yield each top-level balanced {...} substring, string-aware.

    Tracks single- and double-quoted strings (with escapes) so braces inside
    string values don't corrupt the depth count — the failure mode of the old
    naive scanner.
    """
    depth = 0
    start = -1
    in_str = False
    esc = False
    quote = ""
    for i, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote:
                in_str = False
            continue
        if ch in ('"', "'"):
            in_str = True
            quote = ch
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start != -1:
                    yield s[start : i + 1]
                    start = -1


def parse_json_output(raw: str) -> dict:
    """Extract a JSON dict from agent raw text (markdown fences, prose, or a
    single-quoted python-repr dict). Returns {} only if nothing dict-like parses."""
    if not raw or not str(raw).strip():
        return {}

    raw = str(raw).strip()

    # Strip a leading ```/```json fence and trailing ```
    if raw.startswith("```"):
        first_nl = raw.find("\n")
        if first_nl != -1:
            raw = raw[first_nl + 1 :]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()

    # Try each balanced {...} block: strict JSON first, then python-literal
    # (handles the single-quoted str(json_dict) / str(pydantic) repr).
    for candidate in _iter_json_objects(raw):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            try:
                val = ast.literal_eval(candidate)
                if isinstance(val, dict):
                    return val
            except (ValueError, SyntaxError):
                continue
    return {}


def extract_task_output(task_output) -> dict:
    """Robustly get a dict from a CrewAI TaskOutput (or anything str-able).

    Prefers the STRUCTURED fields — `.json_dict` is already a dict, `.pydantic`
    dumps to one — because `str(TaskOutput)` yields a single-quoted python repr
    that json.loads rejects. Falls back to parsing `.raw` / str()."""
    if task_output is None:
        return {}

    json_dict = getattr(task_output, "json_dict", None)
    if isinstance(json_dict, dict):
        return json_dict

    pydantic = getattr(task_output, "pydantic", None)
    if pydantic is not None:
        try:
            return pydantic.model_dump()
        except Exception:
            try:
                return dict(pydantic)
            except Exception:
                pass

    raw = getattr(task_output, "raw", None)
    return parse_json_output(raw if raw is not None else str(task_output))
