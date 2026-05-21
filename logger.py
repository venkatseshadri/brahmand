"""
Brahmand structured logger — dual file+console output with daily rotation.

Log files:
  logs/kickoff_YYYYMMDD.log   — scheduler + chain operational events
  logs/chain_YYYYMMDD.log     — agent-by-agent chain results only
  logs/error_YYYYMMDD.log     — errors + stack traces only

Usage:
    from logger import get_logger
    log = get_logger("kickoff")
    log.info("message")
    log.agent("Entry", {"go": true, "signal": "BEARISH"})
    log.chain_summary(...)
"""

import logging
import json
import sys
from datetime import datetime
from pathlib import Path

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

_AGENT_LEVEL = 25  # between INFO (20) and WARNING (30)
_CHAIN_LEVEL = 26  # between AGENT and WARNING

logging.addLevelName(_AGENT_LEVEL, "AGENT")
logging.addLevelName(_CHAIN_LEVEL, "CHAIN")


def _agent_method(self, message, *args, **kwargs):
    if self.isEnabledFor(_AGENT_LEVEL):
        self._log(_AGENT_LEVEL, message, args, **kwargs)


def _chain_method(self, message, *args, **kwargs):
    if self.isEnabledFor(_CHAIN_LEVEL):
        self._log(_CHAIN_LEVEL, message, args, **kwargs)


logging.Logger.agent = _agent_method
logging.Logger.chain = _chain_method


class DailyRotatingFileHandler(logging.FileHandler):
    """File handler that rotates daily — filename includes YYYYMMDD."""

    def __init__(self, base_name: str, mode="a"):
        self._base_name = base_name
        self._today = None
        self._mode = mode
        self._dir = LOG_DIR
        path = self._today_path()
        super().__init__(path, mode=mode, encoding="utf-8")

    def _today_str(self):
        return datetime.now().strftime("%Y%m%d")

    def _today_path(self):
        self._today = self._today_str()
        return str(self._dir / f"{self._base_name}_{self._today}.log")

    def emit(self, record):
        today = self._today_str()
        if today != self._today:
            self.close()
            self.baseFilename = self._today_path()
            self._open()
        if not self.stream or self.stream.closed:
            self._open()
        super().emit(record)


class _AgentFilter(logging.Filter):
    """Only pass AGENT and CHAIN level records (for chain-only log)."""

    def filter(self, record):
        return record.levelno in (_AGENT_LEVEL, _CHAIN_LEVEL)


class _ErrorFilter(logging.Filter):
    """Only pass WARNING and above (for error log)."""

    def filter(self, record):
        return record.levelno >= logging.WARNING


class _BraidFormatter(logging.Formatter):
    """Structured log line: TS | LEVEL | module | message."""

    def format(self, record):
        ts = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        level = record.levelname
        module = getattr(record, "module_name", record.name)
        msg = super().format(record)
        return f"{ts} | {level:<6s} | {module:<12s} | {msg}"


# ── Singleton setup ────────────────────────────────────────────────────────
_loggers: dict[str, logging.Logger] = {}


def _suppress_crewai_verbose():
    """Reduce CrewAI's own logging to WARNING to cut noise."""
    for name in ("crewai", "litellm", "httpx", "httpcore", "openai"):
        logging.getLogger(name).setLevel(logging.WARNING)


_suppress_crewai_verbose()


def get_logger(name: str, to_console: bool = True) -> logging.Logger:
    """Get or create a named logger with dual file+console output.

    Args:
        name: Module name (e.g. "kickoff", "chain", "monitor")
        to_console: Also emit to stdout (default True)
    """
    if name in _loggers:
        return _loggers[name]

    logger = logging.getLogger(f"brahmand.{name}")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    # Clear existing handlers
    logger.handlers.clear()

    formatter = _BraidFormatter("%(message)s")

    # Console handler
    if to_console:
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.DEBUG)
        ch.setFormatter(formatter)
        logger.addHandler(ch)

    # Daily file handler
    fh = DailyRotatingFileHandler("kickoff")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    # Chain-only daily file (AGENT + CHAIN levels only)
    cfh = DailyRotatingFileHandler("chain")
    cfh.setLevel(_AGENT_LEVEL)
    cfh.addFilter(_AgentFilter())
    cfh.setFormatter(formatter)
    logger.addHandler(cfh)

    # Error daily file (WARNING+ only)
    efh = DailyRotatingFileHandler("error")
    efh.setLevel(logging.WARNING)
    efh.addFilter(_ErrorFilter())
    efh.setFormatter(formatter)
    logger.addHandler(efh)

    _loggers[name] = logger
    return logger


def agent_log(logger: logging.Logger, agent_name: str, data: dict | str):
    """Log an agent's output in structured form."""
    if isinstance(data, dict):
        payload = json.dumps(data, default=str)
        logger.agent(f"{agent_name} | {payload}")
    else:
        logger.agent(f"{agent_name} | {data}")


def chain_summary(logger: logging.Logger, summary: dict):
    """Log chain completion summary."""
    payload = json.dumps(summary, default=str)
    logger.chain(f"CHAIN_COMPLETE | {payload}")


def log_exception(logger: logging.Logger, error: Exception, context: str = ""):
    """Log exception with traceback."""
    import traceback

    tb = traceback.format_exc()
    if context:
        logger.error(f"{context}: {error}\n{tb}")
    else:
        logger.error(f"{error}\n{tb}")
