"""Unit tests: Contract Agent — resolves option contracts from DuckDB."""

import pytest


@pytest.mark.unit
class TestContractAgent:
    def test_call_spread_contracts_resolved(self, contracts_call_spread):
        c = contracts_call_spread["contracts"]
        assert c["sell_ce"]["option_type"] == "CE"
        assert c["buy_ce"]["option_type"] == "CE"
        assert c["sell_ce"]["strike"] < c["buy_ce"]["strike"]

    def test_put_spread_contracts_resolved(self, contracts_put_spread):
        c = contracts_put_spread["contracts"]
        assert c["sell_pe"]["option_type"] == "PE"
        assert c["buy_pe"]["option_type"] == "PE"
        assert c["sell_pe"]["strike"] > c["buy_pe"]["strike"]
