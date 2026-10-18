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

    def test_drop_is_blocked_by_min_net_gain(self, dp):
        # unsigned range still trips the detector, but a downward move
        # fails the MIN_NET_GAIN_PCT gate and produces no signal
        self._feed_prices(dp, {"BTCUSDT": 105.0}, {"BTCUSDT": 100.0})
        assert dp._detect_volatility() == {}

    def test_fully_retraced_pump_blocked(self, dp):
        # pump +2.5% then back to start: range trips the trigger but the
        # wave is already over - net ~0% must not produce a signal
        self._feed_prices(
            dp,
            {"BTCUSDT": 100.0},
            {"BTCUSDT": 103.6},
            {"BTCUSDT": 100.0},
        )
        assert dp._detect_volatility() == {}

    def test_v_shape_bounce_passes(self, dp):
        # dip then recovery above start = live bounce, still tradeable
        self._feed_prices(
            dp,
            {"BTCUSDT": 100.0},
            {"BTCUSDT": 97.0},
            {"BTCUSDT": 102.0},
        )
        signals = dp._detect_volatility()
        assert "BTCUSDT" in signals
        assert signals["BTCUSDT"]["buy_signal"] == "volatility_gain"

    def test_near_max_blocks_faded_bounce(self, client):
        # pump +4.5% then retrace -1.9% off the window max: net is still
        # positive (+2.5%) but the bounce already died -> dead-cat entry
        with patch("data_provider.ExternalSignalManager"):
            provider = DataProvider(
                client, _make_config(LAST_NEAR_MAX_PCT=1.5)
            )
            provider.external_signal_manager = MagicMock()
        self._feed_prices(
            provider,
            {"BTCUSDT": 100.0},
            {"BTCUSDT": 104.5},
            {"BTCUSDT": 102.5},
        )
        assert provider._detect_volatility() == {}

    def test_near_max_allows_shallow_retrace(self, client):
        # same shape but last price within 0.5% of the max -> still alive
        with patch("data_provider.ExternalSignalManager"):
            provider = DataProvider(
                client, _make_config(LAST_NEAR_MAX_PCT=1.5)
            )
            provider.external_signal_manager = MagicMock()
        self._feed_prices(
            provider,
            {"BTCUSDT": 100.0},
            {"BTCUSDT": 104.5},
            {"BTCUSDT": 104.0},
        )
        assert "BTCUSDT" in provider._detect_volatility()

    def test_near_max_disabled_by_default(self, dp):
        # without the config key the same faded bounce still signals
        self._feed_prices(
            dp,
            {"BTCUSDT": 100.0},
            {"BTCUSDT": 104.5},
            {"BTCUSDT": 102.5},
        )
        assert "BTCUSDT" in dp._detect_volatility()

    def test_below_threshold_no_signal(self, dp):
        self._feed_prices(dp, {"BTCUSDT": 100.0}, {"BTCUSDT": 101.0})
        assert dp._detect_volatility() == {}

    def test_no_history_returns_empty(self, dp):
        dp.initialize_historical_data()
        assert dp._detect_volatility() == {}

    def _feed_with_volume(self, dp, prices, volumes):
        dp.initialize_historical_data()
        now = datetime.now()
        for snap in prices:
            dp._add_to_historical(
                {
                    s: {"price": p, "volume": volumes[s], "time": now}
                    for s, p in snap.items()
                }
            )

    def test_low_volume_signal_blocked(self, dp):
        dp.COINS_MIN_VOLUME = 100_000_000
        dp.COINS_MAX_VOLUME = 5_000_000_000
        self._feed_with_volume(
            dp,
            [{"BTCUSDT": 100.0}, {"BTCUSDT": 105.0}],
            {"BTCUSDT": 10_000_000},  # thin market - pump is likely fake
        )
        assert dp._detect_volatility() == {}

    def test_high_volume_signal_blocked(self, dp):
        dp.COINS_MIN_VOLUME = 100_000_000
        dp.COINS_MAX_VOLUME = 5_000_000_000
        self._feed_with_volume(
            dp,
            [{"BTCUSDT": 100.0}, {"BTCUSDT": 105.0}],
            {"BTCUSDT": 20_000_000_000},  # mega-cap volume spike
        )
        assert dp._detect_volatility() == {}

    def test_in_range_volume_signal_passes(self, dp):
        dp.COINS_MIN_VOLUME = 100_000_000
        dp.COINS_MAX_VOLUME = 5_000_000_000
        self._feed_with_volume(
            dp,
            [{"BTCUSDT": 100.0}, {"BTCUSDT": 105.0}],
            {"BTCUSDT": 500_000_000},
        )
        assert "BTCUSDT" in dp._detect_volatility()

    def test_missing_volume_still_signals(self, dp):
        # no volume info available -> detector is not blocked
        self._feed_prices(dp, {"BTCUSDT": 100.0}, {"BTCUSDT": 105.0})
        assert "BTCUSDT" in dp._detect_volatility()


class TestMarketFilter:
    def _mk(self, client, **cfg):
        with patch("data_provider.ExternalSignalManager") as esm:
            provider = DataProvider(client, _make_config(**cfg))
            provider.external_signal_manager = esm.return_value
            provider.external_signal_manager.get_external_signals.return_value = {}
            return provider

    def _feed(self, dp, snaps):
        dp.initialize_historical_data()
        now = datetime.now()
        for snap in snaps:
            dp._add_to_historical({s: dict(d, time=now) for s, d in snap.items()})

    def test_btc_24h_downtrend_blocks_signals(self, client):
        dp = self._mk(client, MARKET_FILTER_ENABLED=True)
        self._feed(dp, [
            {"BTCUSDT": {"price": 100.0, "change_24h": -4.0},
             "PUMPUSDT": {"price": 1.0}},
            {"BTCUSDT": {"price": 100.5, "change_24h": -4.1},
             "PUMPUSDT": {"price": 1.1}},
        ])
        assert dp.get_trading_signals() == {}

    def test_btc_window_panic_blocks_signals(self, client):
        dp = self._mk(client, MARKET_FILTER_ENABLED=True)
        self._feed(dp, [
            {"BTCUSDT": {"price": 100.0, "change_24h": 0.5}},
            {"BTCUSDT": {"price": 98.0, "change_24h": 0.5}},
        ])
        assert dp.get_trading_signals() == {}

    def test_healthy_market_allows_signals(self, client):
        dp = self._mk(client, MARKET_FILTER_ENABLED=True)
        self._feed(dp, [
            {"BTCUSDT": {"price": 100.0, "change_24h": 0.5},
             "PUMPUSDT": {"price": 1.0, "volume": 1e9}},
            {"BTCUSDT": {"price": 100.2, "change_24h": 0.6},
             "PUMPUSDT": {"price": 1.1, "volume": 1e9}},
        ])
        signals = dp.get_trading_signals()
        assert "PUMPUSDT" in signals

    def test_filter_disabled_by_default(self, client):
        dp = self._mk(client)
        self._feed(dp, [
            {"BTCUSDT": {"price": 100.0, "change_24h": -9.0},
             "PUMPUSDT": {"price": 1.0, "volume": 1e9}},
            {"BTCUSDT": {"price": 99.0, "change_24h": -9.0},
             "PUMPUSDT": {"price": 1.1, "volume": 1e9}},
        ])
        assert "PUMPUSDT" in dp.get_trading_signals()

    def test_missing_reference_never_blocks(self, client):
        dp = self._mk(client, MARKET_FILTER_ENABLED=True)
        self._feed(dp, [
            {"PUMPUSDT": {"price": 1.0, "volume": 1e9}},
            {"PUMPUSDT": {"price": 1.1, "volume": 1e9}},
        ])
        assert "PUMPUSDT" in dp.get_trading_signals()


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
