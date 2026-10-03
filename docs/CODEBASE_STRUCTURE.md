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
