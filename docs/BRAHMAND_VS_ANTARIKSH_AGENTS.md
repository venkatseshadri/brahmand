# Brahmand vs Antariksh: Two Different Agent Systems

## System Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                      BRAHMAND (Trading)                          │
│            Executes trades, manages positions, learns             │
├──────────────────────────────────────────────────────────────────┤
│ 11 Agents:                                                       │
│  Entry:      NOT_UP, NOT_DOWN, Regime, Strategy, Contract,      │
│              Execution, Order, Risk                              │
│  Monitoring: Morpher, Shifter (+ Risk Agent)                    │
│  Post-Trade: Postmortem                                         │
│                                                                  │
│ INPUT:  Market data (live), DuckDB (snapshots), entry signals   │
│ OUTPUT: Trades executed, positions managed, learning in ChromaDB│
│                                                                  │
│ RUNS:   Market open → close (continuous execution)              │
└──────────────────────────────────────────────────────────────────┘
         ↓ (Writes outcomes to state.db + duckdb)
┌──────────────────────────────────────────────────────────────────┐
│                   ANTARIKSH (Institutional)                      │
│         Reports on trading, oversight, resource auditing         │
├──────────────────────────────────────────────────────────────────┤
│ 6+ Agents:                                                       │
│  Trading Crew:      TA (Trading Agent?) - execution ledger       │
│  Asset Manager Crew: AM (Asset Manager) - broker margins, fees   │
│  Portfolio Mgmt:     PM (Portfolio Manager) - capital allocation │
│  Leadership:         CEO, CTO - strategic decisions              │
│                                                                  │
│ INPUT:  Trading outcomes (from Brahmand), broker state, capital  │
│ OUTPUT: Reports, audits, resource validation, Telegram alerts    │
│                                                                  │
│ RUNS:   End-of-day (ralph_scheduler), on-demand (Telegram)       │
└──────────────────────────────────────────────────────────────────┘
```

---

## Brahmand Agents (11 Total)

| Agent | Phase | Role | Learns? |
|-------|-------|------|---------|
| **NOT_UP** | Entry | Gate for CALL_SPREAD | ❌ |
| **NOT_DOWN** | Entry | Gate for PUT_SPREAD | ❌ |
| **Regime** | Entry | Validate market regime | ❌ |
| **Strategy** | Entry | Pick strategy + parameters | ⚠️ Partial |
| **Contract** | Entry | Resolve option contracts | ❌ |
| **Execution** | Entry | Build trade + route | ❌ |
| **Order** | Entry/Monitoring | Centralized order hub | ❌ |
| **Risk** | Entry/Monitoring | Manage SL/TP | ❌ |
| **Morpher** | Monitoring | Detect signal reversals | ❌ |
| **Shifter** | Monitoring | Premium decay shifts | ❌ |
| **Postmortem** | Post-Trade | Analyze outcomes + learn | ✅ |

---

## Antariksh Agents (6+ Total)

### Asset Manager Crew
| Agent | Role | Responsibility |
|-------|------|---|
| **Asset Manager** | Financial overseer | Monitor broker margins, fees, capital constraints |
| **AM Tools** | Deterministic | Generate margin reports, capital allocation |

### Portfolio Manager
| Agent | Role | Responsibility |
|-------|------|---|
| **Portfolio Manager** | Capital allocator | Decide lot sizes, hedge ratios, leverage per trade |
| **PM Tools** | Deterministic | Wing sizing, margin checks, position limits |

### Trading Accountability
| Agent | Role | Responsibility |
|-------|------|---|
| **TA (Trading Agent?)** | Execution ledger | Generate P&L + broker execution reports for Asset Manager |

### Leadership
| Agent | Role | Responsibility |
|-------|------|---|
| **CEO (Vishnu)** | Strategic | Approval for new strategies, risk escalations |
| **CTO** | Technical | Infrastructure decisions, tool oversight |

---

## Key Difference: WHO DECIDES WHAT

### Brahmand (Trading Execution)
- **Decision:** Which spread to trade? When to morph/shift?
- **Responsibility:** Execute trades, manage risk, learn from outcomes
- **Scope:** NIFTY/SENSEX options (Phase 1), multi-asset (Phase 2)

### Antariksh (Institutional Oversight)
- **Decision:** Is there enough capital? Sufficient margin?
- **Responsibility:** Validate Brahmand's decisions, audit capital usage
- **Scope:** Resource approval, Telegram reporting, CFO-level audits

---

## Data Flow

```
MORNING:
  Brahmand Entry Agents → Execute trade → Write to state.db + duckdb
  ↓
  Antariksh Portfolio Manager → "Check capital for this position?"
  ↓
  Antariksh Asset Manager → "Validate margin requirement?"

DURING DAY:
  Brahmand Monitoring → Morph/shift decisions → Update state.db
  ↓
  (No Antariksh involvement — trusted execution)

END OF DAY:
  Brahmand Postmortem → Analyze outcomes → Write to ChromaDB
  ↓
  Antariksh TA Crew → Generate execution ledger
  ↓
  Antariksh Asset Manager → Audit capital usage + fees
  ↓
  Antariksh Portfolio Manager → Report to CEO
  ↓
  Telegram alert to you (daily summary)
```

---

## Why Separate Systems?

| Concern | Brahmand (Trader) | Antariksh (Overseer) |
|---------|---|---|
| **Speed** | Fast decisions (5-min cycle) | Slower reviews (end-of-day) |
| **Scope** | Tactical (execute trades) | Strategic (capital health) |
| **Autonomy** | Can act independently | Must approve before escalation |
| **Learning** | Learns from market (ChromaDB) | Learns from outcomes (audit trail) |

**Analogy:**
- **Brahmand** = Trader at desk (executes orders, manages risk)
- **Antariksh** = CFO/Compliance (validates capital, audits execution)

---

## For Multi-Asset Expansion (Phase 2)

### Brahmand Changes Needed
1. Add Asset Selector Agent (new)
2. Fix learning feedback loop
3. Support multiple contract types (stocks, futures, crypto)

### Antariksh Changes Needed
1. Portfolio Manager must validate capital across asset classes
   - NIFTY: 15% margin, Reliance: 18%, Crude: 8%, BTC: 25%
2. Asset Manager must track multi-asset fee structures
3. Update daily config for lot sizes per asset class

**Neither system interferes with the other.**

---

## Summary

**Confused agents:**
- ❌ Portfolio Manager, Asset Manager = NOT in Brahmand
- ✅ They're in Antariksh (institutional oversight)

**Brahmand agents (11):**
- ✅ All focused on execution + learning
- ✅ No conflicts (clear role separation)
- ⚠️ Learning feedback loop broken (needs fix before multi-asset)

**The issue you intuited:**
- Brahmand has the trading agents
- Antariksh has the institutional oversight agents
- They SHOULD communicate but currently don't tightly integrate
