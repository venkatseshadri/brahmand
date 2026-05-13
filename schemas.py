"""
Brahmand Pydantic Schemas — Universal Agent Communication Contract.

All inter-agent data is validated through these Pydantic v2 BaseModel classes.
Invalid data raises ValidationError on construction — no silent failures.
"""

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class TradeSignal(BaseModel):
    """Produced by Execution Agent. Consumed by Risk Agent and state.db."""

    market: str = Field(
        default="NSE_OPTIONS",
        description="Market identifier — NSE_OPTIONS, MCX_FUTURES, etc.",
    )
    ticker: str = Field(
        default="NIFTY", description="Underlying ticker — NIFTY, BANKNIFTY"
    )
    action: str = Field(
        default="BUY",
        pattern="^(BUY|SELL)$",
        description="Order direction — BUY or SELL",
    )
    strategy_type: str = Field(default="IRON_BUTTERFLY", description="Strategy name")
    size: int = Field(default=1, ge=1, le=4, description="Number of lots (1-4)")
    strikes: Dict[str, int] = Field(
        default_factory=lambda: {"atm": 0, "ce_wing": 0, "pe_wing": 0},
        description="Strike prices — {atm, ce_wing, pe_wing}",
    )
    sl_level: float = Field(default=3500.0, ge=0, description="Stop-loss in ₹")
    tp_level: float = Field(default=1000.0, ge=0, description="Take-profit in ₹")
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0, description="Execution confidence 0-1"
    )
    meta_data: Dict = Field(
        default_factory=dict, description="Extra context — VIX, ADX, event flags"
    )


class RiskLimits(BaseModel):
    """Enforced by Risk Agent. Seeded from risk_limits.yaml at startup."""

    max_drawdown: float = Field(default=4500.0, description="Daily max loss in ₹")
    max_lots: int = Field(default=1, ge=1, description="Maximum lots per trade")
    sl_enabled: bool = Field(default=True, description="Stop-loss active")
    tp_enabled: bool = Field(default=True, description="Take-profit active")
    margin_cap: float = Field(default=500000.0, description="Maximum margin usage in ₹")
    hard_exit: str = Field(default="14:30", description="Hard exit time IST (HH:MM)")
    entry_window_start: str = Field(default="10:30", description="Entry window open")
    entry_window_end: str = Field(default="11:30", description="Entry window close")
    vix_max: float = Field(default=20.0, description="VIX ceiling — skip if above")

    @classmethod
    def from_yaml(cls, data: dict) -> "RiskLimits":
        """Construct RiskLimits from parsed YAML dict."""
        limits = data.get("risk_limits", data)
        return cls(**limits)


class FlowState(BaseModel):
    """Persisted by CrewAI Flow @persist (optional). Tracks full session state."""

    active_trades: List[Dict] = Field(
        default_factory=list, description="Current open positions"
    )
    daily_pnl: float = Field(default=0.0, description="Running daily P&L")
    agent_decisions: List[Dict] = Field(
        default_factory=list,
        description="All agent decisions made this session",
    )
    market_context: Dict = Field(
        default_factory=dict, description="VIX, NIFTY spot, regime snapshot"
    )
    phase: str = Field(
        default="pre_market",
        description="Session phase — pre_market | market_hours | post_market",
    )
    daily_config_loaded: bool = Field(
        default=False, description="daily_config.json read successfully"
    )
    timestamp: Optional[str] = Field(default=None, description="ISO timestamp")


class ExecutionReport(BaseModel):
    """Produced by Execution Agent. Written to state.db execution_reports table."""

    order_id: str = Field(
        default_factory=lambda: f"SIM-{datetime.now().strftime('%H%M%S')}-001",
        description="Broker order ID or SIM-{time}-{seq}",
    )
    status: str = Field(
        default="PENDING",
        pattern="^(FILLED|CANCELLED|REJECTED|PENDING|MOCK)$",
        description="Order status",
    )
    fill_price: float = Field(default=0.0, description="Fill price or 0 for mock")
    timestamp: str = Field(
        default_factory=lambda: datetime.now().isoformat(),
        description="ISO timestamp of execution",
    )
    agent_version: str = Field(
        default="brahmand-v1", description="Agent version for audit trail"
    )
    error: Optional[str] = Field(
        default=None, description="Error message if status is REJECTED"
    )


class ResearchNote(BaseModel):
    """Produced by Post-Mortem Agent. Stored in ChromaDB research_notes collection."""

    observation: str = Field(
        ..., description="What was observed — specific, actionable"
    )
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence in this observation"
    )
    source: str = Field(
        ...,
        pattern="^(chromadb_query|new_insight|sl_breach|pnl_event)$",
        description="Source of this observation",
    )
    suggested_action: str = Field(
        ..., description="What should change for next session"
    )
    context_date: int = Field(
        ...,
        description="Date as YYYYMMDD integer — required for ChromaDB date filtering",
    )
    metadata: Dict = Field(
        default_factory=dict,
        description="Filterable tags — strategy, ticker, pnl, vix, etc.",
    )


__all__ = [
    "TradeSignal",
    "RiskLimits",
    "FlowState",
    "ExecutionReport",
    "ResearchNote",
]
