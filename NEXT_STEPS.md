# Brahmand — Status & Next Steps

**Last updated:** 2026-05-13 23:00
**Phase:** 01-dress-rehearsal (Brahmand MVC)
**Architecture:** 3-agent CrewAI circadian rhythm (Execution + Risk + Post-Mortem)
**Autonomous test:** Scheduled for tomorrow 11:00-12:00 IST (Mon/Wed/Fri cron)
**Repo:** https://github.com/venkatseshadri/brahmand (private)

---

## What's Built (Wave 1+2 Complete)

### Foundation (Wave 1)
| File | Lines | Purpose |
|------|-------|---------|
| `schemas.py` | 120 | 5 Pydantic v2 models (TradeSignal, RiskLimits, FlowState, ExecutionReport, ResearchNote) |
| `persistence.py` | 198 | Custom SQLite state.db — 3 tables (execution_reports, research_notes, daily_configs) |
| `factory.py` | 90 | AgentFactory + ToolFactory from YAML registries |
| `broker_manager.py` | 317 | Shoonya primary + Flattrade fallback (copied from antariksh) |
| `config/agents_registry.yaml` | 77 | 3 agent blueprints with {variable} slots |
| `config/tools_registry.yaml` | 33 | Market→tool mappings (NSE_OPTIONS, MCX, NASDAQ) |
| `config/risk_limits.yaml` | 11 | Self-contained risk params (SL 4500, TP 1000, VIX 20) |

### Agents (Wave 2)
| Component | Status | Verdict |
|-----------|--------|---------|
| **Execution Agent** | ✅ Tested | 4-leg Iron Butterfly (WINGS_FIRST), 65 lot size, SIM mode. Writes to state.db. |
| **Risk Agent** | ✅ Tested | SELL legs: SL = premium × 1.25, TP = premium × 0.50. BUY skipped. Writes to state.db. |
| **Post-Mortem Agent** | ✅ Tested | Reads state.db → queries ChromaDB (past patterns) + DuckDB (market data) → writes ResearchNotes + daily_config.json |
| `chromadb_tool.py` | 218 | Semantic memory (MiniLM embeddings, metadata filtering, 2 collections) |
| `duckdb_tool.py` | 202 | Market data cross-reference (2,252 snapshots, 83K option records) |
| `tools/execution_tools.py` | 621 | ExecuteTradeTool, ModifyOrderTool, CancelOrderTool (copied) |
| `tools/risk_tools.py` | 606 | MonitorPnLGreeksTool, TSLEngineTool (copied) |

### Data Flow (Verified End-to-End)

```
Market Hours:
  Execution Agent ──writes──→ state.db (execution_reports)
  Risk Agent      ──writes──→ state.db (risk decisions)

Post-Market (Post-Mortem):
  state.db         ──reads──→ Post-Mortem
  ChromaDB         ──query──→ Post-Mortem (past patterns)
  DuckDB           ──query──→ Post-Mortem (VIX, ADX, IV rank, sentiment)
  Post-Mortem      ──writes──→ ChromaDB (ResearchNotes)
  Post-Mortem      ──writes──→ daily_config.json (tomorrow's params)
```

### Post-Mortem Proven Capabilities
- Detects duplicate orders (same leg submitted twice)
- Detects missing wing legs (naked straddle vs iron butterfly)
- Detects post-market entries (executed after 15:30 IST)
- Cross-references VIX at entry time against 52w high
- Compares IV rank to determine if premiums were expensive
- Analyzes market structure (LL/HH trending vs sideways)
- Compares multi-day regime shifts (May 6 bullish → May 12 bearish)
- Generates daily_config.json with concrete rule changes

---

## Next Steps (Tomorrow)

### 1. Flow Orchestrator — `brahmand/flow.py`
Close the circadian rhythm loop:

```
@start:  Read daily_config.json → populate agent variables
         Spawn Execution Agent + Risk Agent
         Run market-hours crew
Post-market: Read state.db → trigger Post-Mortem Agent
         Post-Mortem writes daily_config.json for tomorrow
```

### 2. Feedback Loop — Execution Agent
- Read `daily_config.json` at start:
  - Entry window timing (preferred_entry_start, preferred_entry_end)
  - VIX threshold for rejection
  - IV rank threshold for rejection
  - Wing width setting
  - Mandatory wing leg validation (never naked straddle)

### 3. Feedback Loop — Risk Agent
- Read `daily_config.json` at start:
  - Stop-loss percentage (stop_loss_pct)
  - Take-profit percentage (stop_loss_pct → tp implied)
  - VIX-adjusted wing/exit rules
  - Block post-market execution flag
  - Max positions per ticker

### 4. Dedup Fix
- Execution Agent: check state.db for existing open orders with same order_id before submitting
- Prevent double-submission bug found by Post-Mortem

### 5. Telegram Two-Message Protocol
- 09:30 AM pre-flight status (VIX, ADX, event check, daily config loaded)
- 14:35 PM daily summary (P&L, trades executed, SL/TP status)

### 6. Tests
- Per-agent unit tests (Execution output validation, Risk rejection cases)
- Integration test: Execution → Risk → Post-Mortem full circadian loop
- Mock mode: verify no broker API calls when ANTARIKSH_MOCK_MODE=1

---

## Deferred (Phase 2+)
- Live broker order placement (real Shoonya/Flattrade orders)
- WebSocket LTP feed for TSL
- Regime Agent (ADX/SuperTrend)
- Strategy Architect (Iron Butterfly vs Credit Spread selection)
- Portfolio Manager + Margin Agent
- Multi-market expansion
- Full autonomy (A2A protocol, dynamic agent spawning)
