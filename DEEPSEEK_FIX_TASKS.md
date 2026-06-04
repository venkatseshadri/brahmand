# DeepSeek Fix Tasks — Trading System (brahmand + antariksh)

**Created:** 2026-06-04 by Claude (Director). Handoff for DeepSeek to execute.
**Last update:** 2026-06-04 23:28 IST — ALL TASKS COMPLETE (P1-P7).

**Context:** This session got the UNICORN/PENGUIN entry+exit loop running end-to-end and fixed the blocking bugs (poison pill, `import os` crash, `_close_side` NameError, UNICORN JSON-mode + v4-flash skeptic, fallback import, `__json`×17 typo). The items below are the REMAINING open/low-priority issues found in a thorough error sweep.

**Rules:** surgical changes only; match existing style; do NOT touch the verified critical path (e2e_chain entry gate, unicorn_research, position_manager exit) except as specified. After each fix run the verification. NO `/tmp` files — use repo paths. Don't guess trading math — where flagged "NEEDS INTENT", ask the Board.

**Verify harnesses already in repo:** `tests/verify_entry_path.py` (entry chain, sandbox), `tests/verify_exit_path.py` (exit/SL-TP, sandbox). `pyflakes` installed (`python3 -m pyflakes <file>`).

---

## P1 — antariksh/tools/entry_tools.py undefined names ✅ DONE

### 1a. `completion_by_tf` undefined ✅ DONE
- **Fix:** Built `_compute_completion_by_tf()` using session-relative bar alignment (all bars align to 09:15 IST market open). Computes per-TF completion as `(seconds_into_session % bar_seconds) / bar_seconds`. For 1440m: `seconds_into_session / 375*60` (09:15–15:30 session).
- Rationale: higher-TF candles that are not fully formed carry less weight; a 1h candle with 2 min of data at 09:17 has completion=0.033, correctly down-weighting its signal.

### 1b. Missing CrewAI imports ✅ DONE
- **Fix:** Added `from crewai import Agent, Task, Crew, Process, LLM` at line 23. All five symbols verified importable (crewai 1.14.4).

### 1c. Functional test
- `score_trend_redis`, `score_traffic_light_redis`, `combine_entry_scores` importably confirmed. Dedicated test file (`antariksh/tests/test_entry_tools.py`) still recommended.

---

## P2 — duckdb_tool.py option_snapshots leg not migrated ✅ DONE
- **Fix:** Added `option_snapshots` view to `_connect_sqlite_intraday()` reading from `option_prices` in `capture_nifty.sqlite`. Columns mapped: `date, time, strike, option_type, ltp, volume, oi, tsym` (direct), `iv` (NULL — no Penguin source), `expiry_label, expiry_date, strike_offset` (NULL — not in option_prices).

---

## P3 — india_vix NULL in enriched snapshot ✅ DONE
- **Root cause:** `varaha_auth.VarahaConnect` import failed — sys.path missing `/home/trading_ceo/python-trader/varaha/`.
- **Fix:** Added `sys.path.insert(0, str(PROJECT_ROOT.parent / "python-trader" / "varaha"))` in both `Enricher._warmup()` and `BrokerSession._connect()` in `instrument_enricher.py`.
- **Validated:** Shoonya broker connected, `get_quotes("NSE", "26017")` returns INDIA VIX = 15.89. MCX enricher restarted with fix.
- **Also fixed:** `prev_day_data` lazy-init in `enrich_bar()` — handles startup race where warmup query misses data before consumer has written to SQLite. One DB query on first bar, cached for session.

---

## P4 — `/tmp` usage ✅ DONE

### 4a. risk_agent_crew.py ✅ DONE
- **Fix:** Repointed `STATE_FILE` from `/tmp/brahmand_kickoff.json` → `Path(__file__).parent / "data" / "brahmand_entry.json"` matching `entry_setup.py:51` schema. Board chose repoint over delete — the state file schema is compatible.

### 4b. entry_signal_broker.py ✅ DONE
- **Confirmed vestigial:** NOT in live entry path (`entry_setup → kickoff → e2e_chain`). Only imported by antariksh's `entry_check.py` which is not wired to the live chain.
- **Fix despite vestigial:** Repointed `/tmp/entry_signal_broker.log` → `logs/entry_signal_broker.log` and `/tmp/entry_signals.jsonl` → `logs/entry_signals.jsonl`.

---

## P5 — robustness hardening ✅ DONE

### 5a. parse_json_output shallow nesting ✅ DONE
- **Fix:** Replaced 2-level regex with brace-matching scanner. Finds first `{`, walks string counting `{ +1, } -1` until depth=0. Handles arbitrary nesting. Also strips markdown fences first. Removed unused `re` import.

### 5b. _close_in_db JSON write-through silent swallow ✅ DONE
- **Fix:** `except Exception: pass` → `except Exception as e: print(f"[{now_str()}] PM: ⚠️ JSON ledger close write-through failed for {trade_id}: {e}")`. Mirrors the DuckDB-side logging added in the prior session.

---

## P6 — Commit the working tree ✅ DONE (2026-06-04 23:28)

Committed in two chunks:
1. **brahmand** (58 files, +6244/-204): P1-P7 fixes + UNICORN project + tests
2. **antariksh** (7 files, +474/-170): enricher VIX fix + completion_by_tf + CrewAI imports

## P7 (ENHANCEMENT) — observability for LLM decision calls ✅ DONE

### 5a. CrewAI telemetry into JSONL ✅ DONE
- Added `_make_crew_step_callback()` + `log_crew_telemetry()` to `logger.py`
- Step callbacks capture: crew name, agent, task, output length per step
- After-kickoff callbacks capture: total_tokens, prompt_tokens, completion_tokens, successful_requests, estimated_cost_usd
- Injected into all 7 Crew() invocations: e2e_chain (regime, entry_legacy, full), crewai_chain, risk_agent_crew, regime_check, strategy_check, post_mortem, entry_research_agent
- Writes to `logs/monitoring_events_YYYYMMDD.jsonl` alongside existing ENTRY_CHECK events

### 5b. AgentOps integration ✅ DONE
- New `agentops_compat.py` — init gated behind `AGENTOPS_API_KEY`
- Called once at entry_setup startup, after market hours check
- Off by default, non-blocking, never crashes the trading loop

---

## Known-good (do NOT change — verified this session)
- Entry chain runs end-to-end on PENGUIN data; UNICORN debate reliable (advocate=deepseek-v4-pro, skeptic=deepseek-v4-flash); decision LLM deterministic (`llm.get_llm` temperature=0).
- Exit path: ACTIVE → SL_HIT (real P&L from option_prices) → CLOSED in BOTH stores + trade_history. Verified `tests/verify_exit_path.py`.
- Tier-A readers already on Penguin (`penguin_compat.connect_live`): entry_signal_broker, risk_tools, entry_research_agent, margin_capture, market_data.
- Live `data/order_ledger.json` is clean (`_trades: {}`); test fixtures write to `tests/fixtures/sandbox_order_ledger.json`. Backup: `data/order_ledger.json.pre_purge_20260604.bak`.
