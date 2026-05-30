"""
Brahmand Test Fixtures & Configuration

Provides:
- Market snapshots (bullish, bearish, neutral, high VIX, low VIX)
- Sample trades (CALL_SPREAD, PUT_SPREAD, IRON_BUTTERFLY)
- Mock tools (DuckDB, order_routing, risk_agent)
- Utility functions
"""

import json
import pytest
from pathlib import Path
from datetime import datetime


# ═══════════════════════════════════════════════════════════════════════════════
# MARKET SNAPSHOTS (Bullish, Bearish, Neutral, High/Low VIX)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def market_snapshot_bearish():
    """Market rejects upside (BEARISH) — Good for CALL_SPREAD"""
    return {
        "spot": 23450,
        "atm_strike": 23400,
        "india_vix": 18.5,  # Elevated, but not extreme
        "adx": 22,  # Sideways
        "ema_20": 23500,
        "ema_50": 23600,
        "ema_100": 23700,
        "supertrend_direction": "bearish",
        "st_15min_direction": "bearish",
        "trend_signal": "BEARISH",
        "traffic_light_signal": "BEARISH",
        "tl_pattern": "STRONG_BEAR_CONTINUATION",
        "expiry_weekly": "26-MAY-2026",
        "session_phase": "preopen",
        "rsi": 35,
        "pcr_total": 1.1,
    }


@pytest.fixture
def market_snapshot_bullish():
    """Market rejects downside (BULLISH) — Good for PUT_SPREAD"""
    return {
        "spot": 23950,
        "atm_strike": 24000,
        "india_vix": 15.2,
        "adx": 20,
        "ema_20": 23900,
        "ema_50": 23800,
        "ema_100": 23600,
        "supertrend_direction": "bullish",
        "st_15min_direction": "bullish",
        "trend_signal": "BULLISH",
        "traffic_light_signal": "BULLISH",
        "tl_pattern": "STRONG_BULL_CONTINUATION",
        "expiry_weekly": "26-MAY-2026",
        "session_phase": "preopen",
        "rsi": 65,
        "pcr_total": 0.9,
    }


@pytest.fixture
def market_snapshot_neutral():
    """Market neutral (sideways) — Good for IRON_BUTTERFLY"""
    return {
        "spot": 23700,
        "atm_strike": 23700,
        "india_vix": 14.8,
        "adx": 18,
        "ema_20": 23700,
        "ema_50": 23700,
        "ema_100": 23600,
        "supertrend_direction": "neutral",
        "st_15min_direction": "neutral",
        "trend_signal": "NEUTRAL",
        "traffic_light_signal": "NEUTRAL",
        "tl_pattern": "CONSOLIDATION",
        "expiry_weekly": "26-MAY-2026",
        "session_phase": "preopen",
        "rsi": 50,
        "pcr_total": 1.0,
    }


@pytest.fixture
def market_snapshot_high_vix():
    """High volatility environment (VIX > 20)"""
    return {
        "spot": 23600,
        "atm_strike": 23600,
        "india_vix": 22.5,
        "adx": 28,  # Trending
        "ema_20": 23500,
        "ema_50": 23400,
        "ema_100": 23300,
        "supertrend_direction": "bearish",
        "st_15min_direction": "bearish",
        "trend_signal": "BEARISH",
        "traffic_light_signal": "BEARISH",
        "tl_pattern": "PANIC_SELL",
        "expiry_weekly": "26-MAY-2026",
        "session_phase": "preopen",
        "rsi": 25,
        "pcr_total": 1.3,
    }


@pytest.fixture
def market_snapshot_low_vix():
    """Low volatility environment (VIX < 15)"""
    return {
        "spot": 23750,
        "atm_strike": 23750,
        "india_vix": 12.3,
        "adx": 16,
        "ema_20": 23700,
        "ema_50": 23750,
        "ema_100": 23800,
        "supertrend_direction": "bullish",
        "st_15min_direction": "neutral",
        "trend_signal": "NEUTRAL",
        "traffic_light_signal": "BULLISH",
        "tl_pattern": "LOW_VOLUME_CONSOLIDATION",
        "expiry_weekly": "26-MAY-2026",
        "session_phase": "preopen",
        "rsi": 55,
        "pcr_total": 0.95,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# SAMPLE TRADES (CALL_SPREAD, PUT_SPREAD, IRON_BUTTERFLY)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def sample_trade_call_spread():
    """CALL_SPREAD: Sell ATM CE, Buy ATM+200 CE"""
    return {
        "trade_id": "TRD-20260523093000",
        "strategy_type": "CALL_SPREAD",
        "entry_gate_signal": "BEARISH",
        "entry_time": "2026-05-23T09:30:00",
        "spot": 23450,
        "atm": 23400,
        "expiry": "26-MAY-2026",
        "wing_width": 200,
        "sl_pct": 0.25,
        "tp_pct": 0.50,
        "vix": 18.5,
        "net_credit": 50.0,
        "legs": [
            {
                "tsym": "NIFTY26MAY26C23400",
                "action": "SELL",
                "type": "CE",
                "strike": 23400,
                "quantity": 65,
                "entry_price": 75.50,
                "current_price": 75.50,
                "sl": 113.25,  # 75.50 * 1.50 (150% = 1 + 0.50 for 50% loss on net_credit)
                "tp": 37.75,  # 75.50 * 0.50 (50% profit)
            },
            {
                "tsym": "NIFTY26MAY26C23600",
                "action": "BUY",
                "type": "CE",
                "strike": 23600,
                "quantity": 65,
                "entry_price": 25.50,
                "current_price": 25.50,
                "sl": 0,
                "tp": 0,  # Hedge, no SL/TP
            },
        ],
        "margin_required": 20000,
        "tsl_activated": False,
        "tsl_level": 0,
        "morph_count": 0,
        "shift_count": 0,
    }


@pytest.fixture
def sample_trade_put_spread():
    """PUT_SPREAD: Sell ATM PE, Buy ATM-200 PE"""
    return {
        "trade_id": "TRD-20260523093001",
        "strategy_type": "PUT_SPREAD",
        "entry_gate_signal": "BULLISH",
        "entry_time": "2026-05-23T09:30:00",
        "spot": 23950,
        "atm": 24000,
        "expiry": "26-MAY-2026",
        "wing_width": 200,
        "sl_pct": 0.25,
        "tp_pct": 0.50,
        "vix": 15.2,
        "net_credit": 52.0,
        "legs": [
            {
                "tsym": "NIFTY26MAY26P24000",
                "action": "SELL",
                "type": "PE",
                "strike": 24000,
                "quantity": 65,
                "entry_price": 80.25,
                "current_price": 80.25,
                "sl": 120.375,  # 80.25 * 1.50
                "tp": 40.125,  # 80.25 * 0.50
            },
            {
                "tsym": "NIFTY26MAY26P23800",
                "action": "BUY",
                "type": "PE",
                "strike": 23800,
                "quantity": 65,
                "entry_price": 28.25,
                "current_price": 28.25,
                "sl": 0,
                "tp": 0,  # Hedge
            },
        ],
        "margin_required": 20800,
        "tsl_activated": False,
        "tsl_level": 0,
        "morph_count": 0,
        "shift_count": 0,
    }


@pytest.fixture
def sample_trade_with_morph(sample_trade_call_spread):
    """CALL_SPREAD with morph executed (signal reversed to BULLISH)"""
    trade = sample_trade_call_spread.copy()
    trade["morph_count"] = 1
    trade["entry_gate_signal_original"] = "BEARISH"
    trade["entry_gate_signal"] = "BULLISH"  # Morphed to opposite
    trade["morph_actions"] = [
        {
            "timestamp": "2026-05-23T10:00:00",
            "action": "MORPH",
            "reason": "Signal reversed from BEARISH to BULLISH",
            "new_legs": [
                {
                    "tsym": "NIFTY26MAY26P23200",
                    "action": "SELL",
                    "type": "PE",
                    "strike": 23200,
                }
            ],
            "cancelled_orders": ["ORD-20260523-0001", "ORD-20260523-0002"],
            "new_orders": ["ORD-20260523-0005"],
        }
    ]
    return trade


@pytest.fixture
def sample_trade_with_shift(sample_trade_call_spread):
    """CALL_SPREAD with shift executed (50% premium decay)"""
    trade = sample_trade_call_spread.copy()
    trade["shift_count"] = 1
    trade["shift_actions"] = [
        {
            "timestamp": "2026-05-23T12:30:00",
            "action": "HEDGE_SHIFT",
            "reason": "Premium decay 50% on hedge leg",
            "old_leg": "NIFTY26MAY26C23600",
            "new_leg": "NIFTY26MAY26C23500",
            "pnl_booked": 0,
        }
    ]
    return trade


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY SIGNALS & DECISIONS
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def entry_decision_bearish():
    """Entry Agent output: Market rejects upside"""
    return {
        "go": True,
        "signal": "NOT_UP",
        "confidence": 90,
        "trend_signal": "BEARISH",
        "traffic_light_signal": "BEARISH",
        "tl_pattern": "STRONG_BEAR_CONTINUATION",
        "reasoning": "Both Trend and Traffic Light are BEARISH with high confidence",
    }


@pytest.fixture
def entry_decision_bullish():
    """Entry Agent output: Market rejects downside"""
    return {
        "go": True,
        "signal": "NOT_DOWN",
        "confidence": 85,
        "trend_signal": "BULLISH",
        "traffic_light_signal": "BULLISH",
        "tl_pattern": "STRONG_BULL_CONTINUATION",
        "reasoning": "Both Trend and Traffic Light are BULLISH",
    }


@pytest.fixture
def entry_decision_no_go():
    """Entry Agent output: No trade opportunity"""
    return {
        "go": False,
        "signal": "NONE",
        "confidence": 0,
        "reasoning": "Market not clearly rejecting either direction",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# STRATEGY DECISIONS (VIX/ADX-based parameter optimization)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def strategy_decision_default():
    """Strategy Agent: Default parameters (moderate VIX, moderate ADX)"""
    return {
        "strategy_type": "CALL_SPREAD",
        "wing_width": 200,
        "sl_pct": 0.25,
        "tp_pct": 0.50,
        "reason": "Default parameters for neutral regime",
    }


@pytest.fixture
def strategy_decision_high_vix():
    """Strategy Agent: High VIX optimization (tighter SL, wider wings)"""
    return {
        "strategy_type": "CALL_SPREAD",
        "wing_width": 250,  # Wider
        "sl_pct": 0.35,  # Tighter SL in high vol
        "tp_pct": 0.50,
        "reason": "VIX > 20: wider wings for protection, tighter SL for volatility",
    }


@pytest.fixture
def strategy_decision_low_vix():
    """Strategy Agent: Low VIX optimization (narrower wings, extended TP)"""
    return {
        "strategy_type": "CALL_SPREAD",
        "wing_width": 150,  # Narrower
        "sl_pct": 0.25,
        "tp_pct": 0.55,  # Extended TP in low vol sideways
        "reason": "VIX < 15, ADX < 20: narrow wings OK, let premium decay fully",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# CONTRACTED SYMBOLS (From DuckDB)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def contracts_call_spread():
    """Resolved CALL_SPREAD contracts from DuckDB"""
    return {
        "contracts": {
            "sell_ce": {
                "tsym": "NIFTY26MAY26C23400",
                "strike": 23400,
                "ltp": 75.50,
                "bid": 74.00,
                "ask": 77.00,
                "option_type": "CE",
            },
            "buy_ce": {
                "tsym": "NIFTY26MAY26C23600",
                "strike": 23600,
                "ltp": 25.50,
                "bid": 25.00,
                "ask": 26.00,
                "option_type": "CE",
            },
        },
        "count": 2,
        "note": "all live",
    }


@pytest.fixture
def contracts_put_spread():
    """Resolved PUT_SPREAD contracts from DuckDB"""
    return {
        "contracts": {
            "sell_pe": {
                "tsym": "NIFTY26MAY26P24000",
                "strike": 24000,
                "ltp": 80.25,
                "bid": 79.00,
                "ask": 81.50,
                "option_type": "PE",
            },
            "buy_pe": {
                "tsym": "NIFTY26MAY26P23800",
                "strike": 23800,
                "ltp": 28.25,
                "bid": 28.00,
                "ask": 28.50,
                "option_type": "PE",
            },
        },
        "count": 2,
        "note": "all live",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# ORDER RESULTS (From order_routing)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def order_result_entry():
    """Order routing: Entry orders placed"""
    return {
        "trade_id": "TRD-20260523093000",
        "entry_orders": [
            "ORD-20260523-0001",
            "ORD-20260523-0002",
        ],
        "status": "FILLED",
        "mode": "PAPER",
    }


@pytest.fixture
def order_result_sl_tp():
    """Order routing: SL/TP orders placed"""
    return {
        "trade_id": "TRD-20260523093000",
        "sl_orders": ["ORD-20260523-0003"],
        "tp_orders": ["ORD-20260523-0004"],
        "status": "FILLED",
        "mode": "PAPER",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# MONITORING EVENTS (Morph, Shift, TSL, Exit)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def monitoring_event_no_action():
    """Morpher/Shifter: No action needed"""
    return {
        "trade_id": "TRD-20260523093000",
        "action": "no_action",
        "reason": "Signal unchanged, no premium decay threshold met",
    }


@pytest.fixture
def monitoring_event_morph():
    """Morpher: Signal reversal detected"""
    return {
        "trade_id": "TRD-20260523093000",
        "action": "MORPH",
        "signal_old": "BEARISH",
        "signal_new": "BULLISH",
        "timestamp": "2026-05-23T10:00:00",
        "new_orders": ["ORD-20260523-0005"],
        "cancelled_orders": ["ORD-20260523-0003", "ORD-20260523-0004"],
    }


@pytest.fixture
def monitoring_event_shift():
    """Shifter: Premium decay threshold met"""
    return {
        "trade_id": "TRD-20260523093000",
        "action": "HEDGE_SHIFT",
        "decay_percent": 50,
        "old_leg": "NIFTY26MAY26C23600",
        "new_leg": "NIFTY26MAY26C23500",
        "timestamp": "2026-05-23T12:30:00",
        "pnl_booked": 0,
        "new_orders": ["ORD-20260523-0006"],
        "cancelled_orders": ["ORD-20260523-0007"],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# EXIT EVENTS
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def exit_event_tp_hit():
    """Trade exited at Take Profit"""
    return {
        "trade_id": "TRD-20260523093000",
        "exit_reason": "TP_HIT",
        "exit_time": "2026-05-23T14:00:00",
        "exit_price_sell_leg": 37.75,  # Hit TP
        "pnl": 50.0,  # 50 * 65 = 3250 per lot (example)
        "exit_orders": ["ORD-20260523-0008", "ORD-20260523-0009"],
    }


@pytest.fixture
def exit_event_sl_hit():
    """Trade exited at Stop Loss"""
    return {
        "trade_id": "TRD-20260523093000",
        "exit_reason": "SL_HIT",
        "exit_time": "2026-05-23T11:30:00",
        "exit_price_sell_leg": 113.25,  # Hit SL
        "pnl": -63.25,  # Loss
        "exit_orders": ["ORD-20260523-0010"],
    }


@pytest.fixture
def exit_event_time():
    """Trade exited at market close"""
    return {
        "trade_id": "TRD-20260523093000",
        "exit_reason": "TIME_EXIT",
        "exit_time": "2026-05-23T15:30:00",
        "exit_price_sell_leg": 60.0,  # Some profit
        "pnl": 15.0,
        "exit_orders": ["ORD-20260523-0011", "ORD-20260523-0012"],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# POSTMORTEM ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def postmortem_analysis_success():
    """Postmortem: Trade executed well"""
    return {
        "trade_id": "TRD-20260523093000",
        "signal_accuracy": True,
        "entry_signal": "BEARISH",
        "market_direction_at_exit": "BEARISH",
        "regime_classification_correct": True,
        "parameters_optimal": True,
        "morphs_count": 0,
        "shifts_count": 1,
        "exit_reason": "TP_HIT",
        "pnl": 50.0,
        "days_held": 0,
        "learning_notes": "Entry signal accurate, CALL_SPREAD profitable in bearish regime",
    }


@pytest.fixture
def postmortem_analysis_loss():
    """Postmortem: Trade executed but took loss"""
    return {
        "trade_id": "TRD-20260523093001",
        "signal_accuracy": False,
        "entry_signal": "BEARISH",
        "market_direction_at_exit": "BULLISH",
        "regime_classification_correct": False,
        "parameters_optimal": False,
        "morphs_count": 1,
        "shifts_count": 0,
        "exit_reason": "SL_HIT",
        "pnl": -100.0,
        "days_held": 0,
        "learning_notes": "Entry signal wrong, market reversed. Need regime validation filter.",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# UTILITY FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def cleanup_ledger():
    """Clean up order_ledger.json after test"""
    yield
    ledger_path = Path(__file__).parent.parent / "data" / "order_ledger.json"
    if ledger_path.exists():
        ledger_path.unlink()


@pytest.fixture
def cleanup_duckdb():
    """Clean up test DuckDB entries"""
    yield
    # TODO: Implement cleanup if using real DuckDB in tests


# ═══════════════════════════════════════════════════════════════════════════════
# PYTEST CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════


def pytest_configure(config):
    """Register custom markers"""
    config.addinivalue_line("markers", "unit: unit test (fast, isolated)")
    config.addinivalue_line(
        "markers", "phase: phase integration test (entry/monitoring/post-trade)"
    )
    config.addinivalue_line(
        "markers", "scenario: scenario test (realistic trading day)"
    )
    config.addinivalue_line("markers", "e2e: end-to-end test (full workflow)")
    config.addinivalue_line("markers", "slow: slow test (> 1 second)")
