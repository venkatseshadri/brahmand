#!/usr/bin/env python3
"""
Unified Broker Manager — abstracts Shoonya + Flattrade
Provides single interface for market data (VIX, NIFTY spot, events)
and trade execution (chooses broker based on strategy).
"""

import sys
import os
import json
import logging
from pathlib import Path
from typing import Dict, Optional, Tuple
from datetime import datetime
import requests

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "python-trader"))
sys.path.insert(0, str(PROJECT_ROOT / "python-trader/Shoonya_oAuthAPI-py"))

try:
    from api_helper import NorenApiPy
except ImportError:
    NorenApiPy = None

logger = logging.getLogger("BrokerManager")

# ============================================================
# BROKER CONFIGS
# ============================================================

class Shoonya:
    """Shoonya broker config and API"""
    NAME = "shoonya"
    CRED_PATH = PROJECT_ROOT / "python-trader/Shoonya_oAuthAPI-py/cred.yml"

    # Well-known exchange tokens for NSE instruments
    TOKENS = {
        "NIFTY50": "99926000",
        "INDIAVIX": "99926009",
        "NIFTY_INDEX": "99926000",
    }

    @staticmethod
    def load_credentials() -> Optional[Dict]:
        """Load Shoonya credentials from cred.yml"""
        try:
            import yaml
            with open(Shoonya.CRED_PATH, 'r') as f:
                creds = yaml.safe_load(f)
                return creds
        except ImportError:
            # Fallback: parse YAML manually (basic)
            try:
                with open(Shoonya.CRED_PATH, 'r') as f:
                    creds = {}
                    for line in f:
                        line = line.strip()
                        if ':' in line and not line.startswith('#'):
                            key, val = line.split(':', 1)
                            creds[key.strip()] = val.strip()
                    return creds if creds else None
            except Exception as e:
                logger.error(f"Shoonya cred load failed: {e}")
                return None

class Flattrade:
    """Flattrade broker config and API"""
    NAME = "flattrade"
    TOKEN_PATH = PROJECT_ROOT / "python-trader/tokens.json"
    OAUTH_SCRIPT = PROJECT_ROOT / "python-trader/get_flattrade_token_auto.py"

    # Well-known exchange tokens for NSE instruments
    TOKENS = {
        "NIFTY50": "99926000",
        "INDIAVIX": "99926009",
        "NIFTY_INDEX": "99926000",
    }

    @staticmethod
    def load_token() -> Optional[str]:
        """Load Flattrade token from tokens.json"""
        try:
            with open(Flattrade.TOKEN_PATH, 'r') as f:
                data = json.load(f)
                return data.get("token")
        except Exception as e:
            logger.error(f"Flattrade token load failed: {e}")
            return None

# ============================================================
# MARKET DATA BRIDGE (UNIFIED)
# ============================================================

class BrokerManager:
    """
    Unified broker interface.
    - Primary data source: Shoonya (has most uptime)
    - Fallback: Flattrade
    - Trade execution: Flattrade (₹0 brokerage)
    - Mock mode: Fixed test values (set ANTARIKSH_MOCK_MODE=1)
    """

    # Mock mode configuration
    MOCK_MODE = os.environ.get("ANTARIKSH_MOCK_MODE", "0") == "1"
    MOCK_VIX = float(os.environ.get("ANTARIKSH_MOCK_VIX", "18.5"))
    MOCK_NIFTY = float(os.environ.get("ANTARIKSH_MOCK_NIFTY", "24500.0"))

    def __init__(self):
        self.shoonya_creds = Shoonya.load_credentials()
        self.flattrade_token = Flattrade.load_token()
        self.last_vix = None
        self.last_nifty = None
        self.shoonya_api = None

        if self.MOCK_MODE:
            logger.info(f"🎭 MOCK MODE: VIX={self.MOCK_VIX}, NIFTY={self.MOCK_NIFTY}")
        else:
            logger.info(f"BrokerManager init: Shoonya={'OK' if self.shoonya_creds else 'FAIL'}, Flattrade={'OK' if self.flattrade_token else 'FAIL'}")

            # Initialize Shoonya API if credentials available
            if self.shoonya_creds:
                self._init_shoonya_api()

    def _init_shoonya_api(self) -> bool:
        """Initialize Shoonya API connection"""
        if not NorenApiPy:
            logger.error("Shoonya API library not available")
            return False

        try:
            self.shoonya_api = NorenApiPy()

            # Inject OAuth header
            ret = self.shoonya_api.injectOAuthHeader(
                self.shoonya_creds.get('Access_token'),
                self.shoonya_creds.get('UID'),
                self.shoonya_creds.get('Account_ID')
            )

            if ret:
                limits = self.shoonya_api.get_limits()
                if limits and limits.get('stat') == 'Ok':
                    logger.info("✅ Shoonya API session established")
                    return True

            logger.error("Shoonya API login failed")
            return False
        except Exception as e:
            logger.error(f"Shoonya API init failed: {e}")
            return False

    def get_vix(self) -> Optional[float]:
        """Get current VIX from primary broker (Shoonya) or mock"""
        if self.MOCK_MODE:
            self.last_vix = self.MOCK_VIX
            logger.info(f"🎭 VIX (mock): {self.MOCK_VIX:.2f}")
            return self.MOCK_VIX

        if not self.shoonya_api:
            logger.warning("VIX: Shoonya API not connected")
            return None

        try:
            # Call Shoonya quote API for INDIAVIX token
            quote = self.shoonya_api.get_quotes("NSE", Shoonya.TOKENS["INDIAVIX"])

            if quote and quote.get('stat') == 'Ok':
                ltp = float(quote.get('lp', 0))
                self.last_vix = ltp
                logger.info(f"VIX: {ltp:.2f}")
                return ltp
            else:
                logger.warning(f"VIX quote failed: {quote}")
                return None
        except Exception as e:
            logger.error(f"VIX fetch failed: {e}")
            return None

    def get_nifty_spot(self) -> Optional[float]:
        """Get current NIFTY spot from primary broker (Shoonya) or mock"""
        if self.MOCK_MODE:
            self.last_nifty = self.MOCK_NIFTY
            logger.info(f"🎭 NIFTY spot (mock): {self.MOCK_NIFTY:.2f}")
            return self.MOCK_NIFTY

        if not self.shoonya_api:
            logger.warning("NIFTY spot: Shoonya API not connected")
            return None

        try:
            # Call Shoonya quote API for NIFTY50 token
            quote = self.shoonya_api.get_quotes("NSE", Shoonya.TOKENS["NIFTY50"])

            if quote and quote.get('stat') == 'Ok':
                ltp = float(quote.get('lp', 0))
                self.last_nifty = ltp
                logger.info(f"NIFTY spot: {ltp:.2f}")
                return ltp
            else:
                logger.warning(f"NIFTY quote failed: {quote}")
                return None
        except Exception as e:
            logger.error(f"NIFTY spot fetch failed: {e}")
            return None

    def get_ltp(self, instrument: str, token: Optional[str] = None) -> Optional[float]:
        """Get LTP for any instrument from Shoonya"""
        if not self.shoonya_api:
            logger.warning(f"LTP {instrument}: Shoonya API not connected")
            return None

        try:
            # Use provided token or lookup from TOKENS dict
            if not token:
                token = Shoonya.TOKENS.get(instrument)
            if not token:
                logger.error(f"LTP {instrument}: token unknown")
                return None

            quote = self.shoonya_api.get_quotes("NSE", token)

            if quote and quote.get('stat') == 'Ok':
                ltp = float(quote.get('lp', 0))
                logger.info(f"LTP {instrument}: {ltp:.2f}")
                return ltp
            else:
                logger.warning(f"LTP {instrument} quote failed: {quote}")
                return None
        except Exception as e:
            logger.error(f"LTP fetch {instrument} failed: {e}")
            return None

    def place_order(self, side: str, instrument: str, qty: int,
                   order_type: str, price: Optional[float] = None) -> Optional[Dict]:
        """
        Place order via Flattrade (₹0 brokerage).
        Fallback to Shoonya if Flattrade fails.
        """
        if not self.flattrade_token:
            logger.warning("Order: Flattrade token unavailable, falling back to Shoonya")
            return self._place_order_shoonya(side, instrument, qty, order_type, price)

        try:
            logger.info(f"TODO: implement Flattrade {side} order for {qty} {instrument}")
            return None
        except Exception as e:
            logger.error(f"Flattrade order failed: {e}, falling back to Shoonya")
            return self._place_order_shoonya(side, instrument, qty, order_type, price)

    def _place_order_shoonya(self, side: str, instrument: str, qty: int,
                            order_type: str, price: Optional[float] = None) -> Optional[Dict]:
        """Place order via Shoonya (fallback)"""
        if not self.shoonya_creds:
            logger.error("Order: both brokers unavailable")
            return None

        try:
            logger.info(f"TODO: implement Shoonya {side} order for {qty} {instrument}")
            return None
        except Exception as e:
            logger.error(f"Shoonya order failed: {e}")
            return None

    def get_position(self, instrument: str) -> Optional[Dict]:
        """Get open position for instrument"""
        try:
            # Primary: Flattrade (execution broker)
            if self.flattrade_token:
                logger.info(f"TODO: get position from Flattrade: {instrument}")
            else:
                logger.info(f"TODO: get position from Shoonya: {instrument}")
            return None
        except Exception as e:
            logger.error(f"Position fetch failed: {e}")
            return None

    def close_position(self, instrument: str, qty: int) -> Optional[Dict]:
        """Close position (exit trade)"""
        try:
            # Use execution broker (Flattrade)
            result = self.place_order("SELL", instrument, qty, "MARKET")
            logger.info(f"Position closed: {instrument} x{qty}")
            return result
        except Exception as e:
            logger.error(f"Position close failed: {e}")
            return None

# ============================================================
# SINGLETON INSTANCE
# ============================================================

_broker_manager = None

def get_broker_manager() -> BrokerManager:
    """Get or create singleton broker manager"""
    global _broker_manager
    if _broker_manager is None:
        _broker_manager = BrokerManager()
    return _broker_manager

# ============================================================
# STANDALONE FUNCTIONS (for backwards compatibility)
# ============================================================

def get_current_vix() -> Optional[float]:
    """Get current VIX"""
    return get_broker_manager().get_vix()

def get_nifty_spot() -> Optional[float]:
    """Get current NIFTY spot"""
    return get_broker_manager().get_nifty_spot()

def place_order(side: str, instrument: str, qty: int, order_type: str,
                price: Optional[float] = None) -> Optional[Dict]:
    """Place order (dual-broker, optimized for brokerage cost)"""
    return get_broker_manager().place_order(side, instrument, qty, order_type, price)
