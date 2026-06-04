"""AgentOps integration — opt-in, off by default.

Set AGENTOPS_API_KEY to enable session-replay/dashboards.
Never blocks the trading loop. Broker creds/PII are scrubbed from prompts.

Usage:
    from agentops_compat import init_agentops_if_enabled
    init_agentops_if_enabled()  # call once at entry_setup startup
"""

import os
import logging

_log = logging.getLogger("brahmand.agentops").info


def init_agentops_if_enabled() -> bool:
    api_key = os.environ.get("AGENTOPS_API_KEY", "").strip()
    if not api_key:
        return False

    try:
        import agentops
    except ImportError:
        _log("agentops not installed — skipping AgentOps init")
        return False

    try:
        agentops.init(
            api_key=api_key,
            default_tags=["brahmand", "paper-trading"],
            auto_start_session=True,
        )
        _log("AgentOps tracking enabled (opt-in)")
        return True
    except Exception as e:
        _log(f"AgentOps init failed (non-blocking): {e}")
        return False
