<!-- refreshed: 2026-10-03 -->
# Architecture

**Analysis Date:** 2026-10-03

## System Overview

```text
┌─────────────────────────────────────────────────────────────┐
│                    Entry Gate Pre-flight                     │
│               `entry_setup.py`, `kickoff.py`                 │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│                  E2E Agent Chain Orchestrator                │
│                        `e2e_chain.py`                        │
├──────────────────┬──────────────────┬───────────────────────┤
│  Entry Agent     │  Regime Agent    │  Strategy Agent       │
│  (GO/NO-GO)      │  (Market Env)    │  (Select Spread/TP)   │
│ `entry_agent.py` │ `research_*`     │ `canonical_strategy.py`│
└────────┬─────────┴────────┬─────────┴──────────┬────────────┘
         │                  │                     │
         ▼                  ▼                     ▼
┌─────────────────────────────────────────────────────────────┐
│                 Execution & Risk Pipeline                    │
│     `contract_builder.py`, `order_routing.py`,               │
│     `risk_monitor.py`                                        │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│                 Persistence & Analytics                      │
│ `persistence.py`, `duckdb_tool.py`, `chromadb_tool.py`       │
└─────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| Setup / Entry | Validates pre-flight conditions, locks, system state, handles entry gate decisions | `entry_setup.py` |
| Chain Orchestrator | Hooks together CrewAI agents and Python execution pipelines into an end-to-end flow | `e2e_chain.py` |
| Agent Factory | Dynamically builds CrewAI configurations from YAML blueprints | `factory.py` |
| Unicorn Judge | Handles adversarial evaluation/debate logic for complex gate decisions (Project UNICORN) | `unicorn_judge.py` |
| Contract Builder | Maps LLM strategy intent to actual TSym (Option) symbols via DuckDB | `contract_builder.py` |
| Execution / Order | Broker integration, routing orders, status updates | `order_routing.py` |
| Market Data | Ingests market state, caches latest snapshots | `market_data.py` |
| Logging / Tracing| Writes detailed agent logs, decision trails, and errors | `logger.py`, `unicorn_logger.py`|

## Pattern Overview

**Overall:** Linear CrewAI Sequential Chain + Python Deterministic Pipeline

**Key Characteristics:**
- **Hybrid LLM/Code:** Orchestrates non-deterministic LLM agents for complex heuristics (Entry, Regime, Strategy) and switches to deterministic Python logic for irreversible actions (Contract selection, Execution, Risk).
- **Adversarial Debating:** Uses Project Unicorn modules (`unicorn_debate.py`, `unicorn_judge.py`) to pit multiple models/prompts against each other before committing to a decision.
- **Factory Pattern:** Dynamically assembles instances. YAML blueprints (`config/`) manage prompts and tool assignments.

## Layers

**Agent Orchestration Layer:**
- Purpose: LLM-based decisioning, market sentiment interpretation, and strategy selection.
- Location: `e2e_chain.py`, `entry_agent.py`, `factory.py`, `unicorn_judge.py`
- Contains: CrewAI chains, Tasks, adversarial prompts.
- Depends on: Data layer (DuckDB), Configurations (YAML)
- Used by: Pipeline runner (`kickoff.py`, `entry_setup.py`)

**Execution / Protocol Layer:**
- Purpose: Converts abstract agent intents into strictly typed, irreversible broker-level actions.
- Location: `order_routing.py`, `contract_builder.py`, `risk_monitor.py`
- Contains: Trading constraints, limit order calculations, risk boundaries.
- Depends on: Broker configurations, Market data, Agent Intents.
- Used by: Orchestration Layer end-stage.

**Data & Persistence Layer:**
- Purpose: Store execution traces, option chain history, and context embeddings.
- Location: `persistence.py`, `duckdb_tool.py`, `chromadb_tool.py`, `market_data.py`
- Contains: DuckDB wrappers, SQLite state updates, Redis streaming readers.
- Depends on: Local disk paths, Market streams.
- Used by: Execution Layer, Agent Layer (via Tools).

## Data Flow

### Primary Request Path

1. Scheduler triggers `entry_setup.py` (`sys.argv`)
2. `entry_setup.py` runs state checks and invokes `kickoff.py#run_entry_pipeline()`
3. `e2e_chain.py` launches the Entry Crew (Agent 1: Entry, Agent 2: Regime, Agent 3: Strategy).
4. `e2e_chain.py` extracts output (`parsing.py`), translates to symbols (`contract_builder.py`).
5. Trade execution connects to Broker (`order_routing.py`) and writes result to state (`persistence.py`).

## Key Abstractions

**Agent & Tool Factories:**
- Purpose: Decouples LLM definitions from runtime python code.
- Examples: `factory.py`
- Pattern: Factory Method (reading from YAML).

**Unicorn Verifier/Judge:**
- Purpose: Evaluates opposing points of view on data anomaly detection or entry signaling.
- Examples: `unicorn_verify.py`, `unicorn_judge.py`, `unicorn_debate.py`
- Pattern: Adversarial LLM verification.

## Entry Points

**`entry_setup.py`:**
- Location: `/home/trading_ceo/projects/brahmand/entry_setup.py`
- Triggers: Cron/User execution
- Responsibilities: Market check -> State lock -> Kickoff trigger.

**`kickoff.py`:**
- Location: `/home/trading_ceo/projects/brahmand/kickoff.py`
- Triggers: Directly or via `entry_setup.py`
- Responsibilities: Wraps the monolithic Crew invocation.

## Architectural Constraints

- **Threading:** Primarily single-threaded event loop blocking on API responses. Heavy analysis done locally on DuckDB in bulk synchronous queries.
- **Global state:** File locks (`locks/`) and SQLite state tracking ensure only one monolithic entry is evaluated and processed at a time.
- **Cost control:** Separation of LLM/Adversarial layers (DeepSeek) and deterministic functions limits LLM hallucination in final trade steps.

## Anti-Patterns

### Unchecked Agent Memory Overflows

**What happens:** Using large `DuckDB` table dumps directly inside an LLM context query.
**Why it's wrong:** Exhausts token limits, creates extreme latency, impacts adversarial reasoning quality.
**Do this instead:** Use `chromadb_tool.py` or aggregate wrappers like `duckdb_tool.py` returning strict subsets/sums.

### Mixing LLM output with API endpoints

**What happens:** Executing options orders by passing unmodified JSON from CrewAI outputs to the Broker.
**Why it's wrong:** Exposes the broker to hallucinated TSym attributes.
**Do this instead:** Extract intents from LLM (`parsing.py`), rely locally on `contract_builder.py` to match exact market realities before generating order dicts.

## Error Handling

**Strategy:** Deterministic Fallback & Hard Aborts

**Patterns:**
- LLM response parsing fails → `fallback.py#deterministic_fallback` generates default/safe 'sideways' regimes rather than halting the workflow violently, or issues a strict NO-GO.
- Order failures → `log_exception()` stores to `logs/`, cancels side-effects, does not retry aggressively to avoid broker spam.

## Cross-Cutting Concerns

**Logging:** Multi-level JSON tracing output through `logger.py` and `unicorn_logger.py` (which separates specific gating phases like `PHASE_CACHE`, `PHASE_DEBATE`).
**Validation:** Handled implicitly by strict schema casting (`schemas.py`, Pydantic).
**Authentication:** Implicit through env-bound configuration across modules; no cross-network RPC needing complex auth mapping.

---

*Architecture analysis: 2026-10-03*
