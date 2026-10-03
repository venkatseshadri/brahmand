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
