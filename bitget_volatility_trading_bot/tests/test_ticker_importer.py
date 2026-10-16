"""Tests for import_bitget_tickers_coingecko.py - network calls mocked."""
from unittest.mock import MagicMock, patch

import pytest

from import_bitget_tickers_coingecko import BitgetTickerImporter


@pytest.fixture
def importer(tmp_path):
    """Importer instance without touching user config files."""
    imp = BitgetTickerImporter.__new__(BitgetTickerImporter)
    imp.pair_with = "USDT"
    imp.tickers_file = str(tmp_path / "tickers.txt")
    imp.tickers_number = 3
    imp.request_delay = 0
    return imp


class TestStablecoinFilter:
    @pytest.mark.parametrize(
        "symbol",
        ["USDCUSDT", "FDUSDUSDT", "WBTCUSDT", "STETHUSDT", "PAXGUSDT", "EURUSDT"],
    )
    def test_excluded_symbols(self, importer, symbol):
        assert importer._is_stablecoin(symbol) is True

    @pytest.mark.parametrize("symbol", ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    def test_regular_coins_pass(self, importer, symbol):
        assert importer._is_stablecoin(symbol) is False


class TestGetBitgetSymbols:
    def _mock_response(self, symbols):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"data": symbols}
        return resp

    def test_filters_online_usdt_pairs(self, importer):
        resp = self._mock_response(
            [
                {"symbol": "BTCUSDT", "status": "online", "quoteCoin": "USDT"},
                {"symbol": "BTCUSDC", "status": "online", "quoteCoin": "USDC"},
                {"symbol": "OLDUSDT", "status": "offline", "quoteCoin": "USDT"},
            ]
        )
        with patch("import_bitget_tickers_coingecko.requests.get", return_value=resp):
            assert importer.get_bitget_symbols() == {"BTCUSDT"}

    def test_non_200_returns_empty(self, importer):
        resp = MagicMock(status_code=500)
        with patch("import_bitget_tickers_coingecko.requests.get", return_value=resp):
            assert importer.get_bitget_symbols() == set()

    def test_network_error_returns_empty(self, importer):
        with patch(
            "import_bitget_tickers_coingecko.requests.get",
            side_effect=Exception("down"),
        ):
            assert importer.get_bitget_symbols() == set()


class TestCreateTickerList:
    def test_ranked_selection_and_dedup(self, importer):
        importer.get_bitget_symbols = lambda: {"BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"}
        # (symbol, market_cap_rank) - lower rank = better
        importer.get_coingecko_top_coins = lambda n: [
            ("SOLUSDT", 3),
            ("BTCUSDT", 1),
            ("ETHUSDT", 2),
            ("XRPUSDT", 4),
        ]
        count = importer.create_ticker_list()
        assert count == 3  # tickers_number
        with open(importer.tickers_file) as f:
            lines = [l.strip() for l in f]
        assert lines == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]  # sorted by rank

    def test_empty_source_data_returns_zero(self, importer):
        importer.get_bitget_symbols = lambda: set()
        importer.get_coingecko_top_coins = lambda n: [("BTCUSDT", 1)]
        assert importer.create_ticker_list() == 0
