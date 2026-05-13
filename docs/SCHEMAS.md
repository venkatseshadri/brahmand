# Brahmand — Schema Documentation

## Overview

All inter-agent communication uses Pydantic v2 BaseModel. These schemas form the "universal language" contract — every agent produces and consumes these exact structures. Validation is automatic on construction.

**Location:** `brahmand/schemas.py`

---

## 1. TradeSignal

**Producer:** Execution Agent  
**Consumer:** Risk Agent, state.db  

```python
from pydantic import BaseModel, Field
from typing import Dict

class TradeSignal(BaseModel):
    market: str = Field(..., description="Market identifier — NSE_OPTIONS, MCX_FUTURES, etc.")
    ticker: str = Field(..., description="Underlying — NIFTY, BANKNIFTY")
    action: str = Field(..., pattern="^(BUY|SELL)$", description="Order direction")
    strategy_type: str = Field(default="IRON_BUTTERFLY", description="Strategy name")
    size: int = Field(ge=1, le=4, description="Number of lots")
    strikes: Dict[str, int] = Field(..., description="{atm, ce_wing, pe_wing} — strike prices")
    sl_level: float = Field(ge=0, description="Stop-loss level in ₹")
    tp_level: float = Field(ge=0, description="Take-profit level in ₹")
    confidence: float = Field(ge=0, le=1, description="Execution confidence 0-1")
    meta_data: Dict = Field(default_factory=dict, description="Greeks, ADX, VIX, event flags")
```

**Example:**
```json
{
  "market": "NSE_OPTIONS",
  "ticker": "NIFTY",
  "action": "BUY",
  "strategy_type": "IRON_BUTTERFLY",
  "size": 1,
  "strikes": {"atm": 23600, "ce_wing": 23300, "pe_wing": 23900},
  "sl_level": 3500.0,
  "tp_level": 1000.0,
  "confidence": 1.0,
  "meta_data": {"vix": 18.5, "adx": 22.3, "event_day": false}
}
```

---

## 2. RiskLimits

**Loaded from:** `antariksh/config/antariksh_rules.yaml`  
**Used by:** Risk Agent  

```python
class RiskLimits(BaseModel):
    max_drawdown: float = Field(default=4500.0, description="Daily max loss in ₹")
    max_lots: int = Field(default=1, ge=1, description="Maximum lots per trade")
    sl_enabled: bool = Field(default=True, description="Stop-loss enabled")
    tp_enabled: bool = Field(default=True, description="Take-profit enabled")
    margin_cap: float = Field(default=500000.0, description="Maximum margin usage in ₹")
    hard_exit: str = Field(default="14:30", description="Hard exit time IST")
    entry_window_start: str = Field(default="10:30", description="Entry window open")
    entry_window_end: str = Field(default="11:30", description="Entry window close")
    vix_max: float = Field(default=20.0, description="VIX ceiling — skip trade if above")
```

---

## 3. FlowState

**Persisted to:** `@persist` (CrewAI SQLiteFlowPersistence)  
**Used by:** Flow orchestrator, Post-Mortem Agent  

```python
from datetime import datetime
from typing import List, Dict, Optional

class FlowState(BaseModel):
    active_trades: List[Dict] = Field(default_factory=list, description="Current open positions")
    daily_pnl: float = Field(default=0.0, description="Running daily P&L")
    agent_decisions: List[Dict] = Field(default_factory=list, description="All agent decisions today")
    market_context: Dict = Field(default_factory=dict, description="VIX, NIFTY spot, regime")
    phase: str = Field(default="pre_market", description="pre_market | market_hours | post_market")
    daily_config_loaded: bool = Field(default=False, description="daily_config.json read successfully")
    timestamp: Optional[str] = Field(default=None)
```

---

## 4. ExecutionReport

**Producer:** Execution Agent  
**Written to:** state.db execution_reports table  

```python
class ExecutionReport(BaseModel):
    order_id: str = Field(..., description="Broker order ID or SIM-{tsym}-{seq}")
    status: str = Field(..., pattern="^(FILLED|CANCELLED|REJECTED|PENDING|MOCK)$")
    fill_price: float = Field(default=0.0)
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    agent_version: str = Field(default="brahmand-v1", description="Agent version tracking")
    error: Optional[str] = Field(default=None, description="Error message if REJECTED")
```

---

## 5. ResearchNote

**Producer:** Post-Mortem Agent  
**Stored in:** ChromaDB `research_notes` collection  

```python
class ResearchNote(BaseModel):
    observation: str = Field(..., description="What was observed — specific, actionable")
    confidence: float = Field(ge=0, le=1, description="Confidence in this observation")
    source: str = Field(..., pattern="^(chromadb_query|new_insight|sl_breach|pnl_event)$")
    suggested_action: str = Field(..., description="What should change tomorrow")
    context_date: int = Field(..., description="Date as YYYYMMDD integer for ChromaDB metadata filtering")
    metadata: Dict = Field(default_factory=dict, description="strategy, ticker, pnl, vix for filtering")
```

**Example:**
```json
{
  "observation": "SL hit at 09:45 — entry was 2 min after open during high volatility. Entry delay would have saved ₹3,500.",
  "confidence": 0.85,
  "source": "sl_breach",
  "suggested_action": "Delay entry to 10:00 if VIX > 17 or first 5-min candle range > 50 pts",
  "context_date": 20260513,
  "metadata": {"strategy": "IRON_BUTTERFLY", "ticker": "NIFTY", "pnl": -3500}
}
```

---

## Schema Validation Rules

- All schemas use `Field()` validators — invalid data raises `ValidationError` immediately
- `pattern=` enforces allowed enum values (BUY/SELL, FILLED/CANCELLED/REJECTED/MOCK/PENDING)
- `ge=/le=` enforce numeric ranges (confidence 0-1, size 1-4 lots)
- `default_factory=list/dict` ensures mutable defaults don't leak between instances
- All schemas are JSON-serializable via `.model_dump()` and `.model_dump_json()`
