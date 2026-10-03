# Technology Stack

**Analysis Date:** 2026-10-03

## Languages

**Primary:**
- Python >=3.12 - Core logic, execution chain, agents, analytics, risk management (`pyproject.toml`, `e2e_chain.py`, `factory.py`)

**Secondary:**
- Bash - Automation and scripts (`pull_all.sh`)
- YAML - Agent and tool configurations (`config/agents_registry.yaml`, `config/tasks.yaml`, `config/tools_registry.yaml`)

## Runtime

**Environment:**
- Python 3.12+ runtime via Linux shell

**Package Manager:**
- pip / pip-tools (via pyproject.toml)
- Lockfile: Not detected (relying on `pyproject.toml`)

## Frameworks

**Core:**
- CrewAI - Multi-agent orchestration, agent chaining, task definitions (`e2e_chain.py`, `factory.py`)
- Pydantic - Data validation and schemas (`schemas.py`)

**Testing:**
- Pytest - Test runner and assertions (`.pytest_cache`, `tests/`)

**Build/Dev:**
- Ruff - Linting and formatting (`pyproject.toml`, `.ruff_cache`)

## Key Dependencies

**Critical:**
- `crewai` - Core multi-agent chain orchestration (`factory.py`, `e2e_chain.py`)
- `duckdb` - Fast embedded analytical SQL engine for historical snapshots and research (`duckdb_tool.py`, `research_backtest_framework.py`)
- `chromadb` - Vector database used for position research caching and semantic similarity search (`chromadb_tool.py`)
- `sqlite3` (built-in) - Persistence engine for states, execution reports, and decision traces (`persistence.py`, `state.py`)
- `redis` - Option timeseries streaming and caching (`tools/record_option_timeseries.py`)

**Infrastructure:**
- `pyyaml` - Parsing agent, tool, and task blueprints (`factory.py`)
- `python-dotenv` - Environment variable loading (`.env`, `e2e_chain.py`)
- `requests` - External broker/HTTP APIs communication (`broker_manager.py`)

## Configuration

**Environment:**
- Configured via `.env` file at repository root
- Key configs required: `DEEPSEEK_API_KEY`, `TRADE_MODE`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `CAPTURE_SQLITE`

**Build:**
- `pyproject.toml` - Project metadata and Ruff configurations

## Platform Requirements

**Development:**
- Python 3.12+, Linux/UNIX environment, access to Redis, SQLite, and local filesystem DuckDB stores

**Production:**
- Automated cron/daemon jobs (`cron/`, `entry_setup.py`, `kickoff.py`) running against real-time/historical option data sources

---

*Stack analysis: 2026-10-03*
# External Integrations

**Analysis Date:** 2026-10-03

## APIs & External Services

**LLM Inference Providers:**
- DeepSeek / OpenAI-compatible API - Used for powering CrewAI Agents (Entry Agent, Regime Agent, Strategy Agent, Unicorn Debates)
  - SDK/Client: `crewai`, `litellm` / `llm.py`
  - Auth: `DEEPSEEK_API_KEY`

**Notifications & Messaging:**
- Telegram - Real-time alerts, entry notifications, risk events
  - SDK/Client: `requests` (`notify.py`)
  - Auth: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`

**Broker APIs:**
- Live & Paper Trading Execution APIs - For placing, modifying, and canceling option orders
  - SDK/Client: `broker_manager.py`, `order_routing.py`
  - Auth: `LIVE_KEY`, `TRADE_MODE`

## Data Storage

**Databases:**
- DuckDB (Embedded OLAP)
  - Connection: Local disk DuckDB files (e.g. `data/`, `duckdb_tool.py`)
  - Client: `duckdb` Python client
- SQLite3 (Transactional state)
  - Connection: `state.db` / `persistence.py`
  - Client: Standard library `sqlite3`
- ChromaDB (Vector Store)
  - Connection: `data/chroma`
  - Client: `chromadb` (`chromadb_tool.py`)

**File Storage:**
- Local filesystem only (`data/`, `logs/`, `config/`)

**Caching:**
- Redis: Option timeseries streaming and fast lookup (`tools/record_option_timeseries.py`)
- Disk Caches: JSON/SQLite cache directories (`data/unicorn_cache`, `data/position_cache`, `data/ema_state`)

## Authentication & Identity

**Auth Provider:**
- Custom API key-based authentication via environment variables (`.env`)

## Monitoring & Observability

**Error Tracking:**
- Local persistent logging framework (`logger.py`, `unicorn_logger.py`, `logs/`)

**Logs:**
- Multi-channel structured logging via standard library and custom callbacks (`logger.py`, `data_health.py`)

## CI/CD & Deployment

**Hosting:**
- Self-hosted Linux instance running trading pipelines and cron schedulers

**CI Pipeline:**
- Not detected / local testing via `pytest`

## Environment Configuration

**Required env vars:**
- `DEEPSEEK_API_KEY`: API key for LLM reasoning steps
- `TRADE_MODE`: Trading execution mode (`paper`, `live`, `backtest`)
- `TELEGRAM_BOT_TOKEN`: Bot token for status alerts
- `TELEGRAM_CHAT_ID`: Destination chat id for alerts
- `CAPTURE_SQLITE`: Path to target SQLite capture database (optional)

**Secrets location:**
- `.env` file at root directory

## Webhooks & Callbacks

**Incoming:**
- None (Polling and cron based architecture)

**Outgoing:**
- Telegram Bot Webhooks/API calls (`notify.py`)

---

*Integration audit: 2026-10-03*
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
# Codebase Structure

**Analysis Date:** 2026-10-03

## Directory Layout

```
/home/trading_ceo/projects/brahmand/
├── archives/          # Deprecated code/data archives
├── backtest/          # Integration layer to sherpa testing engine
├── config/            # YAML configurations for Agents, Tasks, and Tools
├── cron/              # Scheduler definitions and automation triggers
├── data/              # Ephemeral caches, DuckDB indices, ChromaDB logic
├── docs/              # System map, implementation references, architecture details
├── graphify-out/      # Agent system graph representations
├── locks/             # File-based mutex locks ensuring atomicity of chain runs
├── logs/              # Persisted output logs split by component
├── tests/             # Pytest harness (unit, integration, scenarios)
├── tools/             # Script utilities and CrewAI custom Tool implementations
└── *.py               # Core orchestrator and agent modules
```

## Directory Purposes

**`config/`:**
- Purpose: Configures CrewAI logic externally.
- Contains: `agents_registry.yaml`, `tasks.yaml`, `tools_registry.yaml`.
- Key files: `agents_registry.yaml`

**`data/`:**
- Purpose: Runtime cache and index persistence.
- Contains: Embedded databases, JSON caches, embeddings.
- Key files: `chroma/`, `unicorn_cache/`, `position_cache/`

**`tools/`:**
- Purpose: Both standalone diagnostic CLI tools, and integrated external functionality exposed to CrewAI agents.
- Contains: Python scripts with standalone `if __name__ == '__main__':` and shared classes.
- Key files: `entry_check_tool.py`, `replay_session.py`, `monitor_tools.py`

## Key File Locations

**Entry Points:**
- `entry_setup.py`: Primary initialization script that secures locks and checks global status before executing.
- `kickoff.py`: The direct E2E chain starter logic.
- `e2e_chain.py`: End-to-end multi-agent Crew definition.

**Configuration:**
- `.env`: API credentials, environment modes.
- `pyproject.toml`: Dependency spec and build constraints.

**Core Logic:**
- `unicorn_*.py` (`unicorn_judge.py`, `unicorn_verify.py`): Implementation of the adversarial "Unicorn" evaluation framework.
- `contract_builder.py`: Maps market intent to tradable option symbols.
- `order_routing.py`: Direct interactions with broker mechanics and order updates.
- `broker_manager.py`: Abstraction mapping custom execution to actual HTTP-level broker calls.

**Testing:**
- `tests/e2e/`: Full simulation end to end traces.
- `tests/unicorn/`: Specific gating tests for the adversarial logic.

## Naming Conventions

**Files:**
- `{feature}_agent.py`: Agent logic (e.g. `entry_agent.py`, `risk_agent.py?`)
- `unicorn_{feature}.py`: Adversarial gate logic (e.g., `unicorn_debate.py`, `unicorn_judge.py`)
- Snake case for all python modules.

**Directories:**
- Generic lowcase namespaces, primarily grouping by function (`locks/`, `data/`)

## Where to Add New Code

**New Feature (LLM Agent):**
- Primary code: Create configurations in `config/agents_registry.yaml` and `config/tasks.yaml`. If custom behavior is required, subclass in the root directory (e.g., `my_new_agent.py`)
- Tests: `tests/unit/test_my_new_agent.py`

**New Component/Module (Execution Logic):**
- Implementation: Placed in the root directory if it alters the execution chain directly, otherwise as a helper in `tools/`.

**Utilities:**
- Shared helpers: `tools/` if for direct execution scripting, or generic modules like `parsing.py` at the root.

## Special Directories

**`locks/`:**
- Purpose: To prevent duplicate entries when cron jobs overlap.
- Generated: Yes (dynamically on script run).
- Committed: No (contents .gitignored).

**`data/`:**
- Purpose: Holds SQLite state databases and caches.
- Generated: Yes.
- Committed: No.

---

*Structure analysis: 2026-10-03*
