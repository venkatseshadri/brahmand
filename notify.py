#!/usr/bin/env python3
"""Telegram notifier — fail-loud alert channel for data_health and the chain.

Reads TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID from the environment or brahmand/.env.
Throttles repeats: the same dedupe_key alerts at most once per throttle_min.
"""

import json
import os
import urllib.request
from datetime import datetime
from pathlib import Path

_ENV_FILE = Path(__file__).parent / ".env"
_STATE_FILE = Path(__file__).parent / "data" / "notify_state.json"


def _env(key: str) -> str:
    val = os.environ.get(key)
    if val:
        return val
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text().splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
    return ""


def _throttled(dedupe_key: str, throttle_min: int) -> bool:
    """True if this key alerted within the last throttle_min minutes."""
    state = {}
    if _STATE_FILE.exists():
        try:
            state = json.loads(_STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            state = {}
    last = state.get(dedupe_key)
    now = datetime.now()
    if last:
        try:
            age_min = (now - datetime.fromisoformat(last)).total_seconds() / 60
            if age_min < throttle_min:
                return True
        except (ValueError, TypeError):
            pass
    state[dedupe_key] = now.isoformat()
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(state))
    return False


def send_telegram(text: str, dedupe_key: str = "", throttle_min: int = 60) -> bool:
    """Send a Telegram message. Returns True only when actually delivered."""
    token = _env("TELEGRAM_BOT_TOKEN")
    chat_id = _env("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False
    if dedupe_key and _throttled(dedupe_key, throttle_min):
        return False
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=json.dumps({"chat_id": chat_id, "text": text}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.load(resp).get("ok", False)
    except Exception:
        return False


if __name__ == "__main__":
    import sys

    msg = " ".join(sys.argv[1:]) or "notify.py test ping"
    print("sent" if send_telegram(msg) else "FAILED (token/chat_id/network)")
