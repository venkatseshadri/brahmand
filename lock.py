import os
from pathlib import Path

from logger import get_logger

_log = get_logger("kickoff").info


def acquire_lock(lock_file: Path) -> bool:
    if lock_file.exists():
        pid = lock_file.read_text().strip()
        try:
            os.kill(int(pid), 0)
            _log(f"Already running (PID {pid}) — skipping")
            return False
        except (OSError, ValueError):
            pass
    lock_file.write_text(str(os.getpid()))
    return True


def release_lock(lock_file: Path):
    lock_file.unlink(missing_ok=True)
