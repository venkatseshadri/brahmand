"""
Project UNICORN Test Fixtures

Provides frozen raw_data_sample.json output from query_all_families("NIFTY")
for deterministic, reproducible tests without live DuckDB connections.

Also loads .env so live API smoke tests have DEEPSEEK_API_KEY available.
"""

import json
import os
import pytest
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def pytest_configure(config):
    for env_path in (
        Path("/home/trading_ceo/antariksh/.env"),
        Path(__file__).parent.parent.parent / ".env",
    ):
        if not env_path.exists():
            continue
        for line in env_path.read_text().strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip("\"'")
            if key and key not in os.environ:
                os.environ[key] = val


@pytest.fixture(scope="session")
def raw_data_frozen():
    """Frozen query_all_families output — NIFTY, captured 2026-06-03."""
    path = FIXTURES_DIR / "raw_data_sample.json"
    return json.loads(path.read_text())


@pytest.fixture
def raw_data_families(raw_data_frozen):
    """Just the families dict from frozen data."""
    return raw_data_frozen["families"]


@pytest.fixture
def raw_data_trend(raw_data_families):
    return raw_data_families["trend"]


@pytest.fixture
def raw_data_momentum(raw_data_families):
    return raw_data_families["momentum"]


@pytest.fixture
def raw_data_volatility(raw_data_families):
    return raw_data_families["volatility"]


@pytest.fixture
def raw_data_volume(raw_data_families):
    return raw_data_families["volume"]


@pytest.fixture
def raw_data_options(raw_data_families):
    return raw_data_families["options"]


@pytest.fixture
def raw_data_flow(raw_data_families):
    return raw_data_families["flow"]


@pytest.fixture
def raw_data_macro(raw_data_families):
    return raw_data_families["macro"]
