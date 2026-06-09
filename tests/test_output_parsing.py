"""Regression: CrewAI agent output extraction (the 2026-06-09 zero-trades bug).

Root cause: `TaskOutput.__str__` returns `str(json_dict)`/`str(pydantic)` — a
single-quoted PYTHON repr — when the agent emits structured output. The chain did
`parse_json_output(str(task_output))`, and json.loads rejects single quotes, so
EVERY structured agent output parsed to {} → regime=None → strategy=NONE → no trade.

These tests pin the fix: extract_task_output reads .json_dict/.pydantic directly,
and parse_json_output tolerates single-quoted dicts + braces-in-strings + fences.

Run: python3 -m tests.test_output_parsing   (from brahmand/)  — or: python3 tests/test_output_parsing.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parsing import extract_task_output, parse_json_output


def _ck(name, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    return cond


def main():
    ok = True

    # ── extract_task_output: the actual bug — TaskOutput with json_dict ──
    from crewai.tasks.task_output import TaskOutput
    to = TaskOutput(description="d", agent="regime_agent",
                    json_dict={"regime": "enter", "vix": 15.56, "adx": 57.02})
    got = extract_task_output(to)
    ok &= _ck("json_dict TaskOutput → real dict (was {})",
              got == {"regime": "enter", "vix": 15.56, "adx": 57.02})

    # pydantic-backed TaskOutput
    try:
        from pydantic import BaseModel

        class _S(BaseModel):
            strategy_type: str
            wing_width: int

        to_p = TaskOutput(description="d", agent="strategy_agent",
                          pydantic=_S(strategy_type="IRON_FLY", wing_width=200))
        gp = extract_task_output(to_p)
        ok &= _ck("pydantic TaskOutput → model_dump dict",
                  gp == {"strategy_type": "IRON_FLY", "wing_width": 200})
    except Exception as e:  # pragma: no cover
        ok &= _ck(f"pydantic TaskOutput ({e})", False)

    # raw-only TaskOutput (LLM returned fenced JSON text)
    to_r = TaskOutput(description="d", agent="x",
                      raw='```json\n{"strategy_type": "BULL_CALL"}\n```')
    ok &= _ck("raw-text TaskOutput → parsed",
              extract_task_output(to_r) == {"strategy_type": "BULL_CALL"})

    # None / empty
    ok &= _ck("None task_output → {}", extract_task_output(None) == {})

    # ── parse_json_output hardening ──
    ok &= _ck("single-quoted python repr",
              parse_json_output("{'regime': 'enter', 'vix': 15.56}")
              == {"regime": "enter", "vix": 15.56})
    ok &= _ck("```json fence",
              parse_json_output('```json\n{"a": 1}\n```') == {"a": 1})
    ok &= _ck("brace inside string value (naive scanner failed here)",
              parse_json_output('{"reason": "sideways {tight}", "go": true}')
              == {"reason": "sideways {tight}", "go": True})
    ok &= _ck("prose preceding json",
              parse_json_output('Here is my answer: {"regime": "skip"}')
              == {"regime": "skip"})
    ok &= _ck("nested object",
              parse_json_output('{"a": {"b": {"c": 1}}}') == {"a": {"b": {"c": 1}}})
    ok &= _ck("no json → {}", parse_json_output("no json here") == {})
    ok &= _ck("empty → {}", parse_json_output("") == {})

    print(f"\n{'ALL PASS' if ok else 'FAILURES'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
