╔══════════════════════════════════════════════════════════════════════════════╗
║                         PROJECT UNICORN                                     ║
║            Entry Gate: Adversarial LLM Debate Architecture                  ║
║                                                                             ║
║  Extension of: Antarctic • Brahmand • Penguin                              ║
║  Date: 2026-06-01                                                           ║
╚══════════════════════════════════════════════════════════════════════════════╝

══ TABLE OF CONTENTS ═══════════════════════════════════════════════════════════

  1. Problem Statement
  2. Architecture Overview
  3. Raw Data Layer — The 7 Families
  4. Tool Design — unicorn_raw_query
  5. Agent Design — Bull & Bear
  6. Agent Design — Judge
  7. Hallucination Surface Analysis
  8. Integration Plan
  9. Configuration & YAML Blueprints
 10. Testing Strategy
 11. Open Questions


══ 1. PROBLEM STATEMENT ══════════════════════════════════════════════════════════

CURRENT STATE (BRAHMAND)

  Entry gate relies on deterministic Python tools that compute a verdict,
  pass it through a DeepSeek LLM, then run provenance verification to clamp
  hallucinated values. The LLM is a glorified JSON passthrough — it adds no
  reasoning but costs tokens and introduces hallucination risk.

  Data flow:
    tools → compute verdict → LLM passthrough → provenance clamp → gatekeeper

  Problem: The LLM doesn't interpret ambiguous data. It echoes deterministic
  verdicts. Provenance is a band-aid for a system that shouldn't need it.

TARGET STATE (UNICORN)

  Tools return raw data, NOT verdicts. Two adversarial LLMs (Bull + Bear)
  interpret the SAME raw data from OPPOSING biases. A Judge LLM with
  tool access verifies claims and produces the final entry signal.

  Data flow:
    tools → raw data → Bull argues ENTER + Bear argues DON'T → Judge scores → signal

  Why this works:
    • 7 orthogonal data families = ~40 distinct signals. Bull and Bear can't
      fabricate the same hallucination across all 7.
    • Opposing instructions break sycophancy. Each agent MUST argue its bias.
    • Judge has tool access. "Bear says VIX is elevated — let me check." 
      Verifiable claims get weight. Unverifiable get discarded.
    • Deterministic execution follows — contracts, orders, SL/TP unchanged.


══ 2. ARCHITECTURE OVERVIEW ═══════════════════════════════════════════════════════

  ┌─────────────────────────────────────────────────────────────────┐
  │                     ANTARIKSH (Data Layer)                      │
  │  query_trend, query_momentum, query_volatility, query_volume,  │
  │  query_options, query_flow, query_macro → Redis/DuckDB/SQLite  │
  └──────────────────────────┬──────────────────────────────────────┘
                             │
                             ▼
  ┌──────────────────────────────────────────────────────────────────┐
  │              unicorn_raw_query() — Raw Data Tool                  │
  │                                                                   │
  │  Calls all 7 families from antariskh. Returns ~40 flattened raw   │
  │  fields. NO classifications, NO verdicts, NO go/no-go.            │
  │                                                                   │
  │  Output schema:                                                   │
  │  {                                                                │
  │    "trend":      {spot, ema5/20/50, sma_position, adx, di+/-},   │
  │    "momentum":   {rsi, macd, macd_hist, cci, bb_pct_b},          │
  │    "volatility": {atr, atr_pct, hv_20, iv_current, iv_rank},     │
  │    "volume":     {vwap, vwap_position, obv, cmf},                 │
  │    "options":    {pcr_total, pcr_atm, iv_regime, max_pain,       │
  │                   oi_skew, agg_delta/gamma/vega/theta},           │
  │    "flow":       {pcr_change},                                    │
  │    "macro":      {spot, vix, vix_level, gap_pct, session_phase,  │
  │                   prev_day_high/low, pivot_pp/r1/s1}              │
  │  }                                                                │
  └──────────────────────────┬───────────────────────────────────────┘
                             │  (shared raw data, no verdicts)
                             │
              ┌──────────────┴──────────────┐
              ▼                             ▼
  ┌─────────────────────┐       ┌─────────────────────┐
  │     BULL AGENT      │       │     BEAR AGENT      │
  │                     │       │                     │
  │ Role: "You are a    │       │ Role: "You are a    │
  │ bullish entry       │       │ bearish skeptic.    │
  │ advocate. Find      │       │ Find EVERY reason   │
  │ EVERY signal that   │       │ NOT to enter a      │
  │ supports entering   │       │ CALL_SPREAD.        │
  │ a CALL_SPREAD."     │       │                     │
  │                     │       │ Backstory: MUST      │
  │ Backstory: MUST     │       │ argue against.      │
  │ argue for entry.    │       │ Cite specific raw   │
  │ Cite specific raw   │       │ data points.        │─┐
  │ data points.        │─┐     │                     │ │
  │                     │ │     └─────────────────────┘ │
  │ Tools: raw_query    │ │                             │
  └──────────┬──────────┘ │                             │
             │             │                             │
             ▼             │                             │
  bull_argument:           │                             │
  {                        │                             │
    "recommendation":      │                             │
      "ENTER",             │                             │
    "points": [            │   bear_argument:            │
      {                    │   {                         │
        "family": "trend", │     "recommendation":       │
        "claim": "ADX=35  │       "SKIP",               │
         → strong uptrend" │     "points": [             │
        "evidence": {      │       {                     │
          "adx": 35,       │         "family": "vol",    │
          "di_plus": 28    │         "claim": "ATR=18.4  │
        }                  │          → wide range,      │
      },                   │          risk of whipsaw"   │
      ...                  │         "evidence": {       │
    ]                      │           "atr": 18.4       │
  }                        │         }                   │
                           │       },                    │
                           │       ...                   │
                           │     ]                       │
                           │   }                         │
              │             │                             │─┘
              ▼             ▼
  ┌──────────────────────────────────────────────────────────────────────┐
  │                        JUDGE AGENT                                   │
  │                                                                      │
  │ Role: "You are the impartial entry judge. Both sides have presented  │
  │ arguments. Verify EVERY claim by querying raw_data yourself. Score   │
  │ each argument independently. Synthesize into a final decision."      │
  │                                                                      │
  │ Tools: unicorn_raw_query                                             │
  │                                                                      │
  │ Scoring rules:                                                       │
  │   • Verified claim (judge's query matches) → FULL WEIGHT             │
  │   • Unverifiable claim (can't query) → 50% WEIGHT                    │
  │   • Contradicted claim (judge's query differs) → 0% WEIGHT, FLAG    │
  │   • Missing family → penalty on that side                            │
  │                                                                      │
  │ Output:                                                              │
  │ {                                                                    │
  │   "signal":        "NOT_UP",         // NOT_UP or NOT_DOWN or NONE  │
  │   "direction":     "BEARISH",        // from raw data                │
  │   "confidence":    0.72,             // 0-1 weighted                  │
  │   "bull_score":    3.2,              // cumulative weighted score    │
  │   "bear_score":    4.1,              // cumulative weighted score    │
  │   "hallucinations": [                 // detected fabrications        │
  │     "Bear claimed RSI=25 but query returned RSI=41 → 0% weight"     │
  │   ],                                                                 │
  │   "reasoning": "Bear's argument stronger. VIX elevated (19.2) +     │
  │    ATR wide (18.4) + PCR neutral (1.02). Recommendation: SKIP."     │
  │ }                                                                    │
  └──────────────────────────────────────────────────────────────────────┘
                             │
                             ▼
  ┌──────────────────────────────────────────────────────────────────────┐
  │              e2e_chain.run_sequential_crew() (UNCHANGED)             │
  │                                                                      │
  │  signal from judge → strategy_to_execute → contracts → orders        │
  │  All deterministic. No LLM in execution pipeline.                    │
  └──────────────────────────────────────────────────────────────────────┘


══ 3. RAW DATA LAYER — THE 7 FAMILIES ═══════════════════════════════════════════

The raw data tool calls antsariskh's 7-family pipeline. Each family provides
orthogonal signals that cannot be simultaneously fabricated.

  Family       Key Raw Fields                       ~Count  What it detects
  ──────────── ───────────────────────────────────  ──────  ────────────────
  TREND        ema5/20/50, sma_position, adx,       ~12     Directional bias
               di_plus, di_minus, st_direction               + strength

  MOMENTUM     rsi, macd, macd_histogram, cci,      ~8      Overbought/
               bb_pct_b, bb_width                           oversold + speed

  VOLATILITY   atr, atr_pct, hv_20, iv_current,     ~6      Risk environment
               iv_rank, bb_upper/lower

  VOLUME       vwap, vwap_position, obv, cmf,       ~5      Institutional
               cmf_signal, volume                           participation

  OPTIONS      pcr_total, pcr_atm, iv_regime,        ~10    Smart money
               max_pain, oi_skew, agg_greeks                 positioning

  FLOW         pcr_change                            ~1      Momentum shift

  MACRO        spot, vix, vix_level, gap_pct,        ~10    Broad market
               session_phase, pivot levels,                  context
               prev_day_high/low

  TOTAL                                              ~52


══ 4. TOOL DESIGN — unicorn_raw_query ═════════════════════════════════════════

  class UnicornRawQuery(BaseTool):
      name = "unicorn_raw_query"
      description = """
      Query ALL 7 market data families (trend, momentum, volatility,
      volume, options, flow, macro) for raw signal values. Returns ~50
      raw fields with NO verdicts, NO classifications, NO go/no-go.

      Use this to build evidence for your entry argument. Cite specific
      values from the returned JSON in your claims.
      """
      args_schema = QueryInput  # {index: "NIFTY"}
      cache_ttl = 60  # 1min cache — same data for all 3 agents per cycle

  def _run(self, index: str = "NIFTY") -> str:
      from antariskh.tools.entry_tools import query_all_families

      families = query_all_families(index)  # hits Redis/SQLite/DuckDB

      # Flatten into a single ~50-field dict. Strip verdicts.
      # query_all_families already returns raw values — passthrough.
      return json.dumps(families, indent=2)

  Cache note: unicorn_raw_query is called once per debate cycle by
  the Judge. Bull and Bear receive the raw data as injected context
  (see Step B2 in agent design below). If the Judge re-queries for
  claim verification and the value changed (crossed a 1-minute
  boundary), the later query wins — this is not a bug, it's fresher data.


══ 5. AGENT DESIGN — BULL & BEAR ══════════════════════════════════════════════

  Both agents share identical architecture that differs ONLY in role/backstory.

  BULL AGENT (NOT_UP entry advocate)
  ───────────────────────────────────
  Role:       "Bearish Entry Advocate"
  Goal:       "Find EVERY signal in the raw data that supports entering
               a CALL_SPREAD (market rejects upside → bearish pressure).
               Argue forcefully. Cite specific data points."

  Backstory:  "You are the BULLISH CASE for entering a CALL_SPREAD. Your
               job is NOT to be neutral — it is to find every possible
               reason the market is rejecting upside. You MUST produce at
               least 3 evidence points across at least 3 different families.
               Every claim MUST cite a specific value from the raw data.
               If you cannot find 3 points, say so — do not fabricate."

  Instruction to add to backstory:
    "CRITICAL: NEVER invent data. If a value is not in the raw data query,
     say 'no evidence in this family.' The Judge WILL verify your claims
     against the raw data. Fabricated claims receive ZERO weight."

  BEAR AGENT (NOT_UP entry skeptic)
  ───────────────────────────────────
  Role:       "Bearish Entry Skeptic"
  Goal:       "Find EVERY signal in the raw data that argues AGAINST
               entering a CALL_SPREAD. Argue forcefully against entry.
               Cite specific data points."

  Backstory:  "You are the BEARISH CASE against entering a CALL_SPREAD.
               Your job is NOT to be neutral — it is to find every
               possible reason NOT to enter. You MUST produce at least
               3 evidence points across at least 3 different families.
               The Judge WILL verify every claim against the raw data.
               Fabricated claims receive ZERO weight."

  BOTH AGENTS share:
  ──────────────────
  Tools:       unicorn_raw_query (optional — can also receive pre-queried context)
  LLM:         deepseek/deepseek-chat, temperature=0
  Output JSON: {recommendation: "ENTER"|"SKIP", points: [{family, claim, evidence}]}


══ 6. AGENT DESIGN — JUDGE ════════════════════════════════════════════════════

  Role:       "Impartial Entry Judge"
  Goal:       "Verify Bull and Bear claims against raw data. Score each
               side independently. Produce final entry signal."

  Backstory:  "You are the IMPARTIAL JUDGE. Both Bull and Bear have
               presented arguments for entering or skipping a CALL_SPREAD.
               Your job: VERIFY every claim against unicorn_raw_query,
               SCORE each side independently, and SYNTHESIZE a final
               decision.

               SCORING RULES:
               • Verified claim (your query matches claim) → 1.0 × family_weight
               • Unverifiable claim (subjective, can't query) → 0.5 × family_weight
               • Contradicted claim (your query differs) → 0.0 × family_weight
                 AND add to hallucinations list

               WEIGHTS (all 7 families equal for Phase 1):
               trend=1.0, momentum=1.0, volatility=1.0, volume=1.0,
               options=1.0, flow=1.0, macro=1.0

               FINAL DECISION:
               • bull_score > bear_score → signal=NOT_UP (enter CALL_SPREAD)
               • bear_score > bull_score → signal=NONE (skip)
               • bull_score == bear_score → check trend_bias from raw data
                 - ADX>25 + di_plus>di_minus → bullish bias → skip
                 - ADX>25 + di_minus>di_plus → bearish bias → enter
                 - ADX<25 → skip (sideways, no conviction)"

  Tools:       unicorn_raw_query (MUST call to verify claims)
  LLM:         deepseek/deepseek-chat, temperature=0
  Output JSON: {signal, direction, confidence, bull_score, bear_score,
                hallucinations, reasoning}


══ 7. HALLUCINATION SURFACE ANALYSIS ══════════════════════════════════════════

  Scenario                  Can it happen?    Detected by?
  ────────────────────────  ──────────────    ───────────────────────────
  Bull fabricates low VIX   Possible          Bear argues opposite;
    when VIX is actually 22                    Judge queries → contradiction

  Both fabricate same lie   Extremely rare    7 orthogonal families make
    across all families                        this combinatorially hard:
                                               P(fab) = ∏(P(fab_per_family))
                                               ≈ 0.05⁷ = 7.8×10⁻¹⁰

  Judge hallucinates         Possible          Scorecards are auditable.
    scores or signals                          If bull_score + bear_score >
                                               possible max, anomaly flagged.

  Sycophancy (both agree)   Blocked by         Role instructions force
                             design            adversarial positions.
                                               "Your job is NOT to be neutral
                                               — find EVERY reason to..."

  Judge ignores a family    Possible          Minimum-family check: judge
                                               must address all 7 families
                                               or deduct from that side.

  The Judge surface: The Judge is the single point of failure. If the
  Judge hallucinates, the gate is compromised. Mitigation: the Judge's
  output is a scorecard, not just a signal. scorecard_anomaly.json tracks
  unexpected patterns (e.g., Judge scores both sides 0.0 but recommends
  ENTER). A light Python anomaly checker runs post-judge.


══ 8. INTEGRATION PLAN ═══════════════════════════════════════════════════════

  Phase 1 — New files
  ──────────────────
  brahmand/
    unicorn_raw_query.py     Tool class (wraps antariskh query_all_families)
    unicorn_bull_agent.yaml  Agent blueprint
    unicorn_bear_agent.yaml  Agent blueprint
    unicorn_judge_agent.yaml Agent blueprint
    unicorn_debate.py        Debate orchestrator (runs Bull→Bear→Judge crew)

  Phase 2 — Modified files
  ─────────────────────────
  brahmand/
    e2e_chain.py             Replace entry_crew (NOT_UP/NOT_DOWN/regime)
                              with unicorn_debate.run_debate()

  Phase 3 — Deprecated (after validation)
  ───────────────────────────────────────
  brahmand/
    tools/entry_gate_tools.py  EvaluateNotUpRejection, EvaluateNotDownRejection
    verification.py            Provenance functions (no longer needed)
    config/tasks.yaml          not_up_entry_task, not_down_entry_task


══ 9. CONFIGURATION & YAML BLUEPRINTS ═════════════════════════════════════════

  unicorn_bull_agent.yaml → goes in config/agents_registry.yaml as new entry

  unicorn_bear_agent.yaml → goes in config/agents_registry.yaml as new entry

  unicorn_judge_agent.yaml → goes in config/agents_registry.yaml as new entry

  Debate task → goes in config/tasks.yaml or in-code (single-task debate)

  The debate itself is a 3-agent Crew with a single sequence:
    Task: "Evaluate whether to enter a CALL_SPREAD based on raw data"
    Agent sequence: Bull → Bear → Judge
    Context passing: raw_data → Bull → (raw_data + bull_arg) → Bear →
                     (raw_data + bull_arg + bear_arg) → Judge


══ 10. TESTING STRATEGY ═══════════════════════════════════════════════════════

  Unit Tests
  ──────────
  • UnicornRawQuery returns 7 families, no verdicts in output
  • Bull agent produces valid JSON with points array
  • Bear agent produces valid JSON with points array
  • Judge verifies claims correctly (known good seed data)
  • Judge detects contradiction (known bad seed data)
  • Scorecard anomaly checker catches invalid scores

  Integration Tests
  ────────────────
  • Full debate with frozen raw data → deterministic output
  • 1000 simulations with synthetic data → scorecard distribution analysis
  • Regression: e2e_chain still works end-to-end with unicorn gate

  Hallucination Tests (adversarial)
  ─────────────────────────────────
  • Inject fabricated VIX into Bull context → Judge catches it
  • Inject fabricated ADX into Bear context → Judge catches it
  • Both fabricate same claim → minimum conflict triggers skip
  • Judge fabricates score → anomaly checker fires

  Performance
  ────────────
  • Target: 3 LLM calls (Bull + Bear + Judge) per entry cycle
  • With parallel Bull/Bear: 2 rounds ≈ 4-6 seconds at typical latency
  • Cache unicorn_raw_query for 1 minute — same data across all 3 calls


══ 11. OPEN QUESTIONS ═══════════════════════════════════════════════════════════

  Q1: Should Bull/Bear also get the opposite gate's arguments?
      If we run NOT_UP and NOT_DOWN debates sequentially, Bull for
      NOT_UP could see Bear for NOT_DOWN. This creates a 4-agent
      lattice that compounds hallucination detection but adds latency.
      Recommendation: Start with 3-agent debate. Add cross-debate
      awareness in Phase 2.

  Q2: How to handle NOT_DOWN gate?
      NOT_DOWN is the mirror debate — Bull argues FOR PUT_SPREAD entry,
      Bear argues AGAINST. Same architecture, swapped directions.
      Recommendation: Create one UnicornDebate class parameterized by
      gate_type ("NOT_UP"|"NOT_DOWN"). Bull/Bear adapt via gate_type
      injection in the task description.

  Q3: Should unicorn_raw_query return ALL families or let agents choose?
      Return ALL always. The cost of fetching all 7 families is sub-100ms
      (reads from Redis/SQLite/DuckDB). Letting agents choose introduces
      "strategic omission" — an agent can skip a family that doesn't
      support its argument. The Judge detects this as a missing-family
      penalty.

  Q4: What happens when unicorn_raw_query fails (Redis down)?
      Fallback to deterministic entry (what provenance currently does).
      Log the failure. The system degrades gracefully to the current
      Python-only gate.

  Q5: Should the Judge have access to antariksh scoring functions?
      NO. The Judge should verify against RAW data only. If the Judge
      calls score_trend_redis(), it's consuming another LLM's verdict
      (circular). Raw data is the ground truth.
