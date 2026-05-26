"""Replay session utilities — sandbox paths, env overrides, setup."""

import os
from pathlib import Path

DEFAULT_SANDBOX = Path("/home/trading_ceo/brahmand/data/replays")


def sandbox_root() -> Path:
    return Path(os.environ.get("BRAHMAND_SANDBOX", DEFAULT_SANDBOX))


def sandbox_path(relative: str) -> Path:
    return sandbox_root() / relative


def in_sandbox() -> bool:
    return "BRAHMAND_SANDBOX" in os.environ


def redis_db() -> int:
    return int(os.environ.get("BRAHMAND_REPLAY_REDIS_DB", "1"))
