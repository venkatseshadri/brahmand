# Brahmand MVC — Build Plan
# 2026-05-13

**Architecture:** 3-agent CrewAI Flow (Execution + Risk + Post-Mortem)
**Location:** /home/trading_ceo/brahmand/ (sister to antariksh/)
**Reuses:** antariksh/broker_manager.py, antariksh/telegram_bridge.py, antariksh/event_calendar.py

## Build Order (11 steps, 3 waves)

### Wave 1: Foundation (no agents yet)
| # | File | What |
|---|------|------|
| 1 | `brahmand/schemas.py` | 5 Pydantic models: TradeSignal, RiskLimits, FlowState, ExecutionReport, ResearchNote |
| 2 | `brahmand/config/agents_registry.yaml` | 3 agent blueprints (role, goal, backstory) with {variable} slots |
| 3 | `brahmand/config/tools_registry.yaml` | Tool mappings by market type (NSE_OPTIONS → [order_tool, sl_tool]) |
| 4 | `brahmand/persistence.py` | SQLite state.db init + daily_config.json read/write |
| 5 | `brahmand/factory.py` | AgentFactory + ToolFactory — reads YAML registries → returns CrewAI Agent/Tool |

### Wave 2: Agents (depends on Wave 1)
| # | File | What |
|---|------|------|
| 6 | `brahmand/chromadb_tool.py` | Custom CrewAI Tool wrapping ChromaDB PersistentClient with metadata filtering |
| 7 | `brahmand/agents/execution_agent.py` | Fixed Iron Butterfly (ATM ± 300, 1 lot) via broker_manager.py. Mock mode first. |
| 8 | `brahmand/agents/risk_agent.py` | Validates TradeSignal against RiskLimits. Mock SL (logs only). Writes to state.db. |
| 9 | `brahmand/agents/postmortem_agent.py` | Reads state.db → queries ChromaDB → writes ResearchNote → updates daily_config.json |

### Wave 3: Flow + Tests (depends on Wave 2)
| # | File | What |
|---|------|------|
| 10 | `brahmand/flow.py` | CrewAI Flow[BrahmandState] — @start reads config, @router spawns agents, post-market triggers Post-Mortem |
| 11 | `brahmand/tests/` | 12 test files (conftest.py + per-component tests) |

## Key Decisions (from CONTEXT.md D-01..D-28)
- CrewAI Flow[BrahmandState] with @persist, not Process.hierarchical
- Custom SQLite (state.db) separate from Flow's @persist SQLite
- ChromaDB PersistentClient with MiniLM embeddings (config-driven)
- YAML registries with AgentFactory + ToolFactory patterns
- Mock mode via ANTARIKSH_MOCK_MODE env var
- DeepSeek LLM for agent cognition
- Shoonya primary → Flattrade fallback → yfinance last resort for VIX
- Post-Mortem Agent owns the full Maintenance Window (read → query → write)
