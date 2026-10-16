"""Tests for data_provider.py - price filtering, historical buffer, volatility."""
from unittest.mock import MagicMock, patch
from datetime import datetime

import pytest

from data_provider import DataProvider


def _make_config(**overrides):
    config = {
        "TIME_DIFFERENCE": 2,
        "RECHECK_INTERVAL": 2,
        "PAIR_WITH": "USDT",
        "FIATS": ["EUR", "GBP"],
        "CUSTOM_LIST": False,
        "TICKERS_LIST": "",
        "EX_COINS": ["USDC", "DAI"],
        "CHANGE_IN_PRICE": 3.0,
    }
    config.update(overrides)
    return config


@pytest.fixture
def client():
    c = MagicMock()
    c.get_spot_delist_schedule.return_value = []
    return c


@pytest.fixture
def dp(client):
    with patch("data_provider.ExternalSignalManager") as esm:
        provider = DataProvider(client, _make_config())
        provider.external_signal_manager = esm.return_value
        return provider


class TestFiltering:
    def test_pair_with_filter(self, dp):
        prices = [
            {"symbol": "BTCUSDT", "price": "50000"},
            {"symbol": "BTCUSDC", "price": "50001"},
            {"symbol": "ETHBTC", "price": "0.06"},
        ]
        filtered = dp._filter_prices(prices)
        assert set(filtered) == {"BTCUSDT"}
        assert filtered["BTCUSDT"]["price"] == 50000.0

    def test_fiat_exclusion(self, dp):
        prices = [{"symbol": "BTCEUR", "price": "1"}, {"symbol": "BTCUSDT", "price": "1"}]
        # BTCEUR contains fiat EUR and lacks USDT anyway; test a USDT fiat pair
        assert "BTCEUR" not in dp._filter_prices(prices)

    def test_fiat_substring_in_symbol_excluded(self, dp):
        dp.FIATS = ["USDC"]
        prices = [{"symbol": "USDCUSDT", "price": "1"}]
        assert dp._filter_prices(prices) == {}

    def test_custom_list_mode(self, client):
        with patch("data_provider.ExternalSignalManager"):
            provider = DataProvider(
                client, _make_config(CUSTOM_LIST=True, TICKERS_LIST="x.txt")
            )
        provider.tickers = ["BTC", "ETH"]
        assert provider._should_include_symbol("BTCUSDT") is True
        assert provider._should_include_symbol("DOGEUSDT") is False
        assert provider._should_include_symbol("BTCUSDC") is False

    def test_custom_list_full_pair_format(self, client):
        # importer writes full market ids (BTCUSDT) - these must also match
        with patch("data_provider.ExternalSignalManager"):
            provider = DataProvider(
                client, _make_config(CUSTOM_LIST=True, TICKERS_LIST="x.txt")
            )
        provider.tickers = ["BTCUSDT", "ETHUSDT"]
        assert provider._should_include_symbol("BTCUSDT") is True
        assert provider._should_include_symbol("DOGEUSDT") is False

    def test_pinned_symbols_bypass_filters(self, dp):
        # open positions must be priced even outside the ticker list / FIATS
        dp.pinned_symbols = {"SHITCOINUSDT"}
        assert dp._should_include_symbol("SHITCOINUSDT") is True
        dp.FIATS = ["SHIT"]
        assert dp._should_include_symbol("SHITCOINUSDT") is True


class TestHistoricalBuffer:
    def test_initialize_storage_size(self, dp):
        dp.initialize_historical_data()
        assert len(dp.historical_prices) == 4  # TIME_DIFFERENCE * RECHECK_INTERVAL
        assert dp.hsp_head == -1

    def test_ring_buffer_wraps(self, dp):
        dp.initialize_historical_data()
        for i in range(6):
            dp._add_to_historical({"i": i})
        assert dp.hsp_head == 1  # wrapped around twice
        assert all(v is not None for v in dp.historical_prices)

    def test_get_price_adds_to_history(self, dp, client):
        client.get_all_tickers.return_value = [
            {"symbol": "BTCUSDT", "price": "50000"}
        ]
        dp.initialize_historical_data()
        result = dp.get_price()
        assert "BTCUSDT" in result
        assert dp.historical_prices[0] == result

    def test_insufficient_data_flag(self, dp):
        dp.initialize_historical_data()
        assert dp._has_sufficient_data() is False
        dp._add_to_historical({"BTCUSDT": {"price": 1.0, "time": datetime.now()}})
        dp._add_to_historical({"BTCUSDT": {"price": 1.0, "time": datetime.now()}})
        assert dp._has_sufficient_data() is True


class TestVolatilityDetection:
    def _feed_prices(self, dp, *price_snapshots):
        dp.initialize_historical_data()
        for snap in price_snapshots:
            dp._add_to_historical(
                {s: {"price": p, "time": datetime.now()} for s, p in snap.items()}
            )

    def test_detects_pump(self, dp):
        self._feed_prices(dp, {"BTCUSDT": 100.0}, {"BTCUSDT": 105.0})
        signals = dp._detect_volatility()
        assert "BTCUSDT" in signals
        assert signals["BTCUSDT"]["buy_signal"] == "volatility_gain"
        assert signals["BTCUSDT"]["gain"] == pytest.approx(5.0, abs=0.01)

    def test_detects_drop_as_signal(self, dp):
        # change is min/max based so it is unsigned; a drop still flags
        # volatility but reports as a gain magnitude
        self._feed_prices(dp, {"BTCUSDT": 105.0}, {"BTCUSDT": 100.0})
        signals = dp._detect_volatility()
        assert "BTCUSDT" in signals
        assert signals["BTCUSDT"]["buy_signal"] == "volatility_gain"

    def test_below_threshold_no_signal(self, dp):
        self._feed_prices(dp, {"BTCUSDT": 100.0}, {"BTCUSDT": 101.0})
        assert dp._detect_volatility() == {}

    def test_no_history_returns_empty(self, dp):
        dp.initialize_historical_data()
        assert dp._detect_volatility() == {}


class TestPriceChange:
    def test_min_max_based_change(self, dp):
        dp.initialize_historical_data()
        dp._add_to_historical(
            {"BTCUSDT": {"price": 100.0, "time": datetime.now()}}
        )
        dp._add_to_historical(
            {"BTCUSDT": {"price": 90.0, "time": datetime.now()}}
        )
        dp._add_to_historical(
            {"BTCUSDT": {"price": 120.0, "time": datetime.now()}}
        )
        # (max - min) / min * 100 = (120-90)/90 = 33.33%
        assert dp._calculate_price_change("BTCUSDT") == pytest.approx(33.333, abs=0.01)

    def test_single_datapoint_returns_zero(self, dp):
        dp.initialize_historical_data()
        dp._add_to_historical(
            {"BTCUSDT": {"price": 100.0, "time": datetime.now()}}
        )
        assert dp._calculate_price_change("BTCUSDT") == 0.0


class TestDelistedCoins:
    def test_extracts_and_dedupes(self, dp, client):
        client.get_spot_delist_schedule.return_value = [
            {"symbols": ["AAAUSDT", "BBBUSDT"]},
            {"symbols": ["AAAUSDT", "CCCUSDT"]},
        ]
        assert dp.get_delisted_coins() == ["AAAUSDT", "BBBUSDT", "CCCUSDT"]

    def test_empty_schedule(self, dp, client):
        client.get_spot_delist_schedule.return_value = []
        assert dp.get_delisted_coins() == []

    def test_api_error_returns_empty(self, dp, client):
        client.get_spot_delist_schedule.side_effect = Exception("api down")
        assert dp.get_delisted_coins() == []


class TestSymbolPrice:
    def test_returns_cached_price(self, dp):
        dp.initialize_historical_data()
        dp._add_to_historical(
            {"BTCUSDT": {"price": 50000.0, "time": datetime.now()}}
        )
        assert dp.get_symbol_price("BTCUSDT") == 50000.0

    def test_missing_symbol_returns_zero(self, dp, client):
        client.get_all_tickers.return_value = []
        dp.initialize_historical_data()
        assert dp.get_symbol_price("NOPEUSDT") == 0.0
