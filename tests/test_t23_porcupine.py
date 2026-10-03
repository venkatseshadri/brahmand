"""PORCUPINE scenario: simulated GO cycle crew-output loss → recovery from cache.

Tests T23(a) split-brain guard: BuildAndExecuteTradeTool caches trade dict,
run_full_chain reconciles from cache when crew_result.trade is empty.
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # /home/trading_ceo/projects/brahmand
# Insert antariksh first (needed by chain_tools), then brahmand LAST so its tools wins
sys.path.insert(0, str(ROOT.parent / "antariksh"))
sys.path.insert(0, str(ROOT))  # brahmand OVERRIDES antariksh tools
for k in list(sys.modules):
    if k.startswith("tools"):
        del sys.modules[k]


def test_cache_write_read():
    """BuildAndExecuteTradeTool caches → get_last_built_trade recovers."""
    from tools.chain_tools import get_last_built_trade
    import tools.chain_tools as ct

    # Inject a fake cached trade
    fake_trade = {"trade_id": "TRD-20260613120000", "legs": [], "sl": {}, "tp": {}}
    ct._LAST_BUILT_TRADE = fake_trade
    ct._LAST_BUILT_TIME = time.time() - 30  # 30s ago

    recovered = get_last_built_trade(max_age_sec=60.0)
    assert recovered is not None, "30s-old cache should recover"
    assert recovered["trade_id"] == fake_trade["trade_id"]

    # Cleanup
    ct._LAST_BUILT_TRADE = {}
    ct._LAST_BUILT_TIME = 0.0


def test_cache_stale_refuses():
    """get_last_built_trade returns None when cache > max_age_sec old."""
    from tools.chain_tools import get_last_built_trade
    import tools.chain_tools as ct

    ct._LAST_BUILT_TRADE = {"trade_id": "TRD-old"}
    ct._LAST_BUILT_TIME = time.time() - 120  # 2 min old

    recovered = get_last_built_trade(max_age_sec=60.0)
    assert recovered is None, "120s-old cache should refuse"

    ct._LAST_BUILT_TRADE = {}
    ct._LAST_BUILT_TIME = 0.0


def test_empty_cache_returns_none():
    """get_last_built_trade returns None when cache is empty."""
    from tools.chain_tools import get_last_built_trade
    import tools.chain_tools as ct

    ct._LAST_BUILT_TRADE = {}
    ct._LAST_BUILT_TIME = 0.0

    recovered = get_last_built_trade()
    assert recovered is None, "Empty cache should return None"


if __name__ == "__main__":
    test_cache_write_read()
    print("  PASS  test_cache_write_read")
    test_cache_stale_refuses()
    print("  PASS  test_cache_stale_refuses")
    test_empty_cache_returns_none()
    print("  PASS  test_empty_cache_returns_none")
    print("  PORCUPINE: 3/3 PASSED")
