# Open Tasks — for Deepseek (build) / Claude (validate)

Created 2026-05-25. Context: risk-flow correctness was just fixed and committed as
`f84504f` (real CLOSE_SIDE/CLOSE_ALL + hedge square-off, live-MTM floor, signature
bugs, ledger-as-source-of-truth, `status != 'CLOSED'` visibility fix, LLM-down SL/TP
fallback, risk_monitor deprecation). Paper lifecycle test `tests/e2e/test_paper_lifecycle.py`
= 15/15; concurrency `tests/unit/test_tedb_concurrent_writes.py` = 60/60.

These tasks are what remains. Ordered by what blocks a real trade.

## STANDING RULES (do not violate)
- **Do NOT turn the RISK agent into a deterministic module.** SL/TP placement and
  exit strategy must stay owned by the LLM agent so it can learn. Deterministic code
  is a *fallback only* (LLM-down path). This has been reverted twice — see the warning
  block in `risk_agent_crew.py`.
- Use **real data** only. No invented numbers, no fake P&L. Every claim traceable to a
  source (log line, DB row, broker response).
- Backtest is reversible; **live is not** — never auto-flip `LIVE_MODE`.

---

## P0 — Blocks real money

### P0.1 Live broker order path is a stub
`order_agent.py` — `place_order`, `modify_order`, `cancel_order`, `place_legs` all have
LIVE branches that return `{"error": "LIVE mode not yet implemented"}` and never call
the broker (`# TODO: Call Shoonya API`).
- **Build:** wire real Shoonya `api.place_order` / modify / cancel for the LIVE branch;
  capture real order_id, status (PENDING→FILLED/REJECTED), and fill price; write them
  back to the ledger + `trade_execution.duckdb`.
- **Validate (Claude):** with a single MINI/MICRO lot, place → confirm broker order_id
  echoes in logs + ledger; cancel → confirm cancelled at broker. No mock values.

### P0.2 Live hedge-close + OCO + fill reconciliation
Today resting SL/TP orders are placed only for the SELL legs. In live mode, if the
broker fills the SL, the long hedge is orphaned and the sibling (TP) order still rests.
The deterministic monitor closes the whole side, but the broker-fill path does not.
- **Build:**
  1. **Hedge close on fill:** when an SL/TP order fills at the broker, square off the
     paired hedge leg of the same type.
  2. **OCO:** cancel the sibling SL/TP order when one fills (so a dead stop can't
     re-open a naked leg).
  3. **Fill reconciliation:** each 1-min cycle, poll broker order status and update the
     ledger so the system knows a resting order filled.
- **Validate (Claude):** invariant "PUT SL hit ⇒ zero put-side position (short AND
  hedge)" must hold via *broker fills*, not just monitor-computed LTP. Extend
  `tests/e2e/test_paper_lifecycle.py` with a broker-fill simulation.

---

## P1 — Blocks a trustworthy run

### P1.1 Morph/shift agents have no tools to execute
In `risk_agent_crew.py`, the MORPHER agent has `tools=[PatternQueryTool()]` and the
SHIFTER agent has `tools=[]`. Their task prompts tell them to call
`detect_morph` / `execute_morph` / `detect_theta_decay`, but those are plain module
functions never registered as CrewAI tools. So in the live LLM path, morph/roll
**cannot execute** — only the deterministic fallback does.
- **Build:** register `detect_morph`, `execute_morph`, `detect_theta_decay`,
  `execute_roll` as CrewAI tools and attach to the right agents. Keep the agents as the
  *deciders* (do not hard-code the decision — see standing rule).
- **Validate (Claude):** force a signal change in paper → confirm the morpher agent
  actually calls execute_morph and legs change; confirm decision is the LLM's, not a
  hard rule.

### P1.2 Entry decisioning unvalidated (hallucination surface)
The 6-agent entry chain (Deepseek) decides the trade. There is no conformance harness
checking consistency / no-hallucination / no-fake-P&L. Spec already exists:
`docs/AGENT_CONFORMANCE_HARNESS_SPEC.md`. Known issues to fix first (from
`deepseek_nifty_backtest_validation`): NOT_UP/NOT_DOWN logic, TP/SL params,
`combine_entry_scores`.
- **Build:** implement the conformance harness per spec; fix the 3 known issues.
- **Validate (Claude):** harness runs green on a replay; spot-check that agent outputs
  match source data.

### P1.3 Detector unvalidated against live data
`position_manager.run()` (P1–P7) reads live LTPs from `varaha_data.duckdb` and decides
*when* to fire ROLL/TIGHTEN/MORPH/CLOSE. The *executor* is now tested; the *detector
firing at correct thresholds on real ticks* is not.
- **Build:** a replay/sim that feeds recorded ticks and asserts each P-rule fires at the
  right boundary.
- **Validate (Claude):** thresholds (SL_PCT, TP_PCT, DECAY_PCT, FLOOR, HEDGE_GAP) trigger
  exactly at the documented levels; no double-fire, correct dedup.

---

## P2 — Data / research

### P2.1 60-min EMA not available in backtest
Root cause = three code issues (functions defined but never called; fallback can't fire
without a 60-min file; buffer truncated to 200 bars) PLUS a hard data blocker (~13 CSVs
≈ 12 days — cannot seed EMA-100/200 on 60-min). **Decision pending from user:**
(a) accept 1-min basis with an explicit flag, or (b) source more 2024 data. Deepseek
should implement whichever the user picks — do not silently choose.

### P2.2 python-trader pipeline fixes uncommitted (separate repo)
Lock-path crash-loop fixes in `python-trader/varaha/`: `watchdog_capture.sh`,
`validate_pipeline.sh`, `run_data_capture_with_v4.sh` are on disk but uncommitted in the
python-trader repo. Commit them there (NOT in brahmand). See
`data_pipeline_instability_blocker` for context.

---

## Definition of done for "real trade ready"
1. P0.1 + P0.2 complete and validated with 1 MINI/MICRO lot.
2. At least one **clean end-to-end paper day**: entry → position → monitor → exit, with
   the audit log (`logs/monitoring_events_*.jsonl`) showing every ENTRY_CHECK / TRADE_OPEN
   / SL / TP / MORPH / SHIFT / CLOSE — no crashes, no hallucinated numbers.
3. Pipeline stays up the full session (P2.2 deployed).
