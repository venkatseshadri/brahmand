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
