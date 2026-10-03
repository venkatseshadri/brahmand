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
