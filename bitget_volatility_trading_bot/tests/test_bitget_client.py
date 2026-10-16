"""Tests for the Bitget CCXT adapter (helpers/bitget_client.py).

All exchange calls are mocked - no network access required.
"""
import pytest
from unittest.mock import MagicMock

import ccxt

from helpers.bitget_client import (
    BitgetClient,
    BitgetAPIException,
    BitgetOrderException,
    ERR_AUTH,
    ERR_BAD_SYMBOL,
    ERR_INSUFFICIENT_BALANCE,
    ERR_RATE_LIMIT,
    ERR_TIMESTAMP,
    ERR_EXCHANGE,
)


def _make_client(uta=False):
    """Create a BitgetClient with a mocked underlying ccxt exchange."""
    client = BitgetClient.__new__(BitgetClient)
    client.exchange = MagicMock()
    client._markets_loaded = True
    client._pub = {"uta": False}
    client._uta = {"uta": True} if uta else {}
    return client


def _setup_markets(client):
    """Give the client two spot markets and one futures market."""
    spot_btc = {
        "id": "BTCUSDT",
        "symbol": "BTC/USDT",
        "base": "BTC",
        "quote": "USDT",
        "spot": True,
        "active": True,
        "precision": {"amount": 0.0001, "price": 0.01},
        "limits": {"amount": {"min": 0.0001}},
    }
    spot_eth = {
        "id": "ETHUSDT",
        "symbol": "ETH/USDT",
        "base": "ETH",
        "quote": "USDT",
        "spot": True,
        "active": True,
        "precision": {"amount": 1, "price": 0.001},
        "limits": {"amount": {"min": 1}},
    }
    futures_btc = {
        "id": "BTCUSDT_UMCBL",
        "symbol": "BTC/USDT:USDT",
        "base": "BTC",
        "quote": "USDT",
        "spot": False,
        "active": True,
    }
    client.exchange.markets = {
        "BTC/USDT": spot_btc,
        "ETH/USDT": spot_eth,
        "BTC/USDT:USDT": futures_btc,
    }
    client.exchange.markets_by_id = {
        "BTCUSDT": [spot_btc],
        "ETHUSDT": [spot_eth],
        "BTCUSDT_UMCBL": [futures_btc],
    }
    return client


class TestSymbolMapping:
    def test_to_ccxt_symbol_via_market_id(self):
        client = _setup_markets(_make_client())
        assert client._to_ccxt_symbol("BTCUSDT") == "BTC/USDT"

    def test_to_ccxt_symbol_unknown_raises(self):
        client = _setup_markets(_make_client())
        with pytest.raises(BitgetAPIException) as exc:
            client._to_ccxt_symbol("NOTREALUSDT")
        assert exc.value.code == ERR_BAD_SYMBOL

    def test_from_ccxt_symbol_roundtrip(self):
        client = _setup_markets(_make_client())
        assert client._from_ccxt_symbol("BTC/USDT") == "BTCUSDT"


class TestGetAllTickers:
    def test_filters_to_spot_markets_only(self):
        client = _setup_markets(_make_client())
        client.exchange.fetch_tickers.return_value = {
            "BTC/USDT": {"last": 50000.0},
            "ETH/USDT": {"last": 3000.0},
            "BTC/USDT:USDT": {"last": 50001.0},  # futures ticker - excluded
        }

        tickers = client.get_all_tickers()

        client.exchange.fetch_tickers.assert_called_once_with(params={"uta": False})
        symbols = {t["symbol"] for t in tickers}
        assert symbols == {"BTCUSDT", "ETHUSDT"}
        assert all(isinstance(t["price"], str) for t in tickers)

    def test_skips_tickers_without_price(self):
        client = _setup_markets(_make_client())
        client.exchange.fetch_tickers.return_value = {
            "BTC/USDT": {"last": 50000.0},
            "ETH/USDT": {"last": None, "close": None},
        }
        tickers = client.get_all_tickers()
        assert [t["symbol"] for t in tickers] == ["BTCUSDT"]


class TestKlines:
    def test_kline_returns_12_field_layout(self):
        client = _setup_markets(_make_client())
        client.exchange.fetch_ohlcv.return_value = [
            [1700000000000, 100.0, 110.0, 90.0, 105.0, 12.5]
        ]
        client.exchange.parse_timeframe.return_value = 60

        klines = client.get_klines("BTCUSDT", "1m", limit=1)

        assert len(klines) == 1
        k = klines[0]
        assert len(k) == 12
        assert k[0] == 1700000000000          # open time
        assert k[1] == 100.0                  # open
        assert k[2] == 110.0                  # high
        assert k[3] == 90.0                   # low
        assert k[4] == 105.0                  # close
        assert k[5] == 12.5                   # volume
        assert k[6] == 1700000000000 + 59999  # synthesized close time
        # public market data must go through classic spot endpoints
        _, kwargs = client.exchange.fetch_ohlcv.call_args
        assert kwargs["params"] == {"uta": False}

    def test_historical_klines_passes_since_timestamp(self):
        client = _setup_markets(_make_client())
        client.exchange.fetch_ohlcv.return_value = []
        client.exchange.parse_timeframe.return_value = 3600

        client.get_historical_klines("BTCUSDT", "1h", start_str=1699999999000)

        _, kwargs = client.exchange.fetch_ohlcv.call_args
        assert kwargs["since"] == 1699999999000
        assert kwargs["params"] == {"uta": False}


class TestSymbolInfo:
    def test_returns_legacy_filters_shape(self):
        client = _setup_markets(_make_client())
        info = client.get_symbol_info("BTCUSDT")

        assert info["symbol"] == "BTCUSDT"
        assert info["status"] == "TRADING"
        assert info["baseAsset"] == "BTC"
        assert info["quoteAsset"] == "USDT"
        # LOT_SIZE filter must be at index 1 (downstream code depends on it)
        assert info["filters"][1]["filterType"] == "LOT_SIZE"
        assert info["filters"][1]["stepSize"] == "0.0001"
        assert info["filters"][0]["filterType"] == "PRICE_FILTER"

    def test_unknown_symbol_returns_none(self):
        client = _setup_markets(_make_client())
        assert client.get_symbol_info("FAKEUSDT") is None

    def test_precision_in_decimal_places_mode(self):
        client = _setup_markets(_make_client())
        info = client.get_symbol_info("ETHUSDT")  # precision.amount == 1
        # integer precision = number of decimals -> '0.1'
        assert info["filters"][1]["stepSize"] == "0.1"


class TestAccountAndOrders:
    def test_get_account_returns_cantrade_and_balances(self):
        client = _make_client(uta=True)
        client.exchange.fetch_balance.return_value = {
            "USDT": {"free": 100.5, "used": 0.0, "total": 100.5},
            "BTC": {"free": 0.001, "used": 0.0, "total": 0.001},
            "info": {"some": "raw"},
        }

        account = client.get_account()

        client.exchange.fetch_balance.assert_called_once_with({"uta": True})
        assert account["canTrade"] is True
        assert account["accountType"] == "SPOT"
        assert len(account["balances"]) == 2
        usdt = next(b for b in account["balances"] if b["asset"] == "USDT")
        assert usdt["free"] == "100.5"

    def test_market_buy_converts_to_quote_cost(self):
        """Bitget market BUY takes size in quote currency; adapter must fetch
        last price and pass it to ccxt so it computes the quote cost."""
        client = _setup_markets(_make_client(uta=True))
        client.exchange.fetch_ticker.return_value = {"last": 50000.0}
        client.exchange.create_order.return_value = {
            "id": "123",
            "symbol": "BTC/USDT",
            "status": "closed",
            "filled": 0.002,
            "average": 50000.0,
            "timestamp": 1700000000000,
            "fee": {"cost": 0.0000015, "currency": "BTC"},
        }

        result = client.create_order("BTCUSDT", "BUY", "MARKET", quantity=0.002)

        args, kwargs = client.exchange.create_order.call_args
        assert args[:4] == ("BTC/USDT", "market", "buy", 0.002)
        assert args[4] == 50000.0  # price hint for quote-cost conversion
        assert kwargs["params"] == {"uta": True}

        assert result["symbol"] == "BTCUSDT"
        assert result["orderId"] == "123"
        assert result["fills"][0]["price"] == "50000.0"
        assert result["fills"][0]["qty"] == "0.002"
        assert result["fills"][0]["commissionAsset"] == "BTC"

    def test_order_response_fetches_details_when_incomplete(self):
        """When create_order response lacks fills, adapter fetches the order."""
        client = _setup_markets(_make_client(uta=True))
        client.exchange.create_order.return_value = {
            "id": "9",
            "symbol": "BTC/USDT",
            "status": "open",
            "filled": None,
            "average": None,
        }
        client.exchange.fetch_order.return_value = {
            "id": "9",
            "symbol": "BTC/USDT",
            "status": "closed",
            "filled": 1.0,
            "average": 3000.0,
            "timestamp": 1700000000000,
            "fee": {"cost": 0.1, "currency": "USDT"},
        }

        result = client.create_order("BTCUSDT", "SELL", "MARKET", quantity=1.0)

        client.exchange.fetch_order.assert_called_once_with(
            "9", "BTC/USDT", params={"uta": True}
        )
        assert result["fills"][0]["qty"] == "1.0"

    def test_order_error_wrapped_as_order_exception(self):
        client = _setup_markets(_make_client())
        client.exchange.create_order.side_effect = ccxt.InsufficientFunds("nope")

        with pytest.raises(BitgetOrderException) as exc:
            client.create_order("BTCUSDT", "BUY", "MARKET", quantity=1.0)
        assert exc.value.code == ERR_INSUFFICIENT_BALANCE

    def test_delist_schedule_always_empty(self):
        client = _make_client()
        assert client.get_spot_delist_schedule() == []


class TestErrorTranslation:
    @pytest.mark.parametrize(
        "ccxt_exc,expected_code",
        [
            (ccxt.InsufficientFunds("x"), ERR_INSUFFICIENT_BALANCE),
            (ccxt.AuthenticationError("x"), ERR_AUTH),
            (ccxt.PermissionDenied("x"), ERR_AUTH),
            (ccxt.RateLimitExceeded("x"), ERR_RATE_LIMIT),
            (ccxt.InvalidNonce("x"), ERR_TIMESTAMP),
            (ccxt.BadSymbol("x"), ERR_BAD_SYMBOL),
            (ccxt.ExchangeError("x"), ERR_EXCHANGE),
        ],
    )
    def test_ccxt_errors_map_to_semantic_codes(self, ccxt_exc, expected_code):
        client = _make_client()
        client.exchange.fetch_balance.side_effect = ccxt_exc
        with pytest.raises(BitgetAPIException) as exc:
            client.get_account()
        assert exc.value.code == expected_code

    def test_network_error_becomes_connection_error(self):
        client = _make_client()
        client.exchange.fetch_balance.side_effect = ccxt.NetworkError("timeout")
        with pytest.raises(ConnectionError):
            client.get_account()
