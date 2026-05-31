import json
from datetime import datetime
from pathlib import Path


def load_state(state_file: Path) -> dict:
    today = datetime.now().strftime("%Y%m%d")
    if state_file.exists():
        state = json.loads(state_file.read_text())
        if state.get("date") == today:
            return state
    return {
        "date": today,
        "trades_today": 0,
        "active_trade": None,
        "all_trades": [],
        "post_mortem_done": False,
    }


def save_state(state_file: Path, state: dict):
    state_file.write_text(json.dumps(state, indent=2, default=str))


def rollover_if_new_day(state: dict) -> bool:
    today = datetime.now().strftime("%Y%m%d")
    if state.get("date") != today:
        state["date"] = today
        return True
    return False


def activate_trade(state: dict, trade: dict, entry_time: str):
    trade["entry_gate_signal"] = trade.get(
        "entry_gate_signal", trade.get("entry_scores", {}).get("signal", "UNKNOWN")
    )
    trade["monitored_since"] = entry_time
    trade["monitoring_events"] = {
        "tsl_adjustments": [],
        "morph_actions": [],
        "shift_actions": [],
        "mtm_checks": [],
    }

    if state.get("all_trades"):
        prev = state["all_trades"][-1]
        trade["parent_trade_id"] = prev.get("trade_id", "?")
        trade["parent_exit_reason"] = prev.get("exit_reason", "?")
        trade["re_entry_count"] = (
            (prev.get("re_entry_count", 0) + 1) if prev.get("exit_reason") else 0
        )

    state["active_trade"] = trade
    state["trades_today"] += 1
