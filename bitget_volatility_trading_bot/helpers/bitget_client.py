# helpers/bitget_client.py
"""
Bitget exchange adapter exposing the bot's original client interface.

Wraps ccxt.bitget so the rest of the codebase can keep using the same
method names and response shapes it used before the migration.

Internal symbol format stays "BTCUSDT" (which matches Bitget's own spot
market id), responses are normalized to the legacy structures.
"""
import time
from typing import Dict, Any, List, Optional

import ccxt
from loguru import logger


# Semantic error codes (replace the legacy numeric codes)
ERR_AUTH = "AUTH_ERROR"
ERR_INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"
ERR_RATE_LIMIT = "RATE_LIMIT"
ERR_TIMESTAMP = "TIMESTAMP_SYNC"
ERR_BAD_SYMBOL = "BAD_SYMBOL"
ERR_BAD_REQUEST = "BAD_REQUEST"
ERR_EXCHANGE = "EXCHANGE_ERROR"


class BitgetAPIException(Exception):
    """Exchange-side API error, mirrors the original client's exception shape."""

    def __init__(self, message: str, code: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message


class BitgetOrderException(BitgetAPIException):
    """Order-related error, mirrors the original client's exception shape."""

    pass


def _translate_error(e: Exception):
    """Translate ccxt exceptions to BitgetAPIException or builtin errors."""
    if isinstance(e, BitgetAPIException):
        return e
    if isinstance(e, ccxt.InsufficientFunds):
        return BitgetAPIException(str(e), code=ERR_INSUFFICIENT_BALANCE)
    if isinstance(e, (ccxt.AuthenticationError, ccxt.PermissionDenied)):
        return BitgetAPIException(str(e), code=ERR_AUTH)
    if isinstance(e, (ccxt.RateLimitExceeded, ccxt.DDoSProtection)):
        return BitgetAPIException(str(e), code=ERR_RATE_LIMIT)
    if isinstance(e, ccxt.InvalidNonce):
        return BitgetAPIException(str(e), code=ERR_TIMESTAMP)
    if isinstance(e, ccxt.BadSymbol):
        return BitgetAPIException(str(e), code=ERR_BAD_SYMBOL)
    if isinstance(e, ccxt.BadRequest):
        return BitgetAPIException(str(e), code=ERR_BAD_REQUEST)
    if isinstance(e, ccxt.ExchangeError):
        return BitgetAPIException(str(e), code=ERR_EXCHANGE)
    if isinstance(e, ccxt.NetworkError):
        # Main loop handles builtin ConnectionError with retry/backoff
        return ConnectionError(f"Bitget network error: {e}")
    return BitgetAPIException(str(e), code=ERR_EXCHANGE)


class BitgetClient:
    """
    Adapter over ccxt.bitget mimicking the bot's original client interface.

    Symbols are accepted/returned in the concatenated format used by this bot
    (e.g. "BTCUSDT"), which is also Bitget's native spot market id.
    """

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        passphrase: str = "",
        uta: bool = False,
    ):
        config = {
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        }
        if api_key:
            config["apiKey"] = api_key
            config["secret"] = api_secret
            config["password"] = passphrase  # Bitget calls it passphrase
        self.exchange = ccxt.bitget(config)
        self._markets_loaded = False
        # ccxt auto-detects UTA accounts and routes even public calls through
        # UTA endpoints (which only return futures tickers). Force classic
        # spot endpoints for public market data.
        self._pub = {"uta": False}
        # Unified Trading Account mode: private endpoints need {'uta': True}
        self._uta = {"uta": True} if uta else {}

    # ------------------------------------------------------------------
    # symbol helpers
    # ------------------------------------------------------------------
    def _ensure_markets(self):
        if not self._markets_loaded:
            try:
                self.exchange.load_markets()
                self._markets_loaded = True
            except Exception as e:
                raise _translate_error(e)

    def _to_ccxt_symbol(self, symbol: str) -> str:
        """Convert internal "BTCUSDT" to unified "BTC/USDT" via market id lookup."""
        self._ensure_markets()
        markets = self.exchange.markets_by_id.get(symbol)
        market = markets[0] if markets else None
        if market is None:
            # fallback: try treating input as already-unified symbol
            if symbol in self.exchange.markets:
                return symbol
            raise BitgetAPIException(
                f"Unknown Bitget symbol: {symbol}", code=ERR_BAD_SYMBOL
            )
        return market["symbol"]

    def _from_ccxt_symbol(self, unified: str) -> str:
        """Convert unified "BTC/USDT" back to internal "BTCUSDT"."""
        market = self.exchange.markets.get(unified)
        return market["id"] if market else unified.replace("/", "")

    # ------------------------------------------------------------------
    # market data
    # ------------------------------------------------------------------
    def get_all_tickers(self) -> List[Dict[str, str]]:
        """Return [{"symbol": "BTCUSDT", "price": "123.45"}, ...] for all spot pairs."""
        try:
            tickers = self.exchange.fetch_tickers(params=self._pub)
            result = []
            for unified, ticker in tickers.items():
                market = self.exchange.markets.get(unified)
                if market and not market.get("spot"):
                    continue
                price = ticker.get("last") or ticker.get("close")
                if price:
                    result.append(
                        {
                            "symbol": self._from_ccxt_symbol(unified),
                            "price": str(price),
                            "volume": str(ticker.get("quoteVolume") or 0),
                        }
                    )
            return result
        except Exception as e:
            raise _translate_error(e)

    def get_klines(
        self, symbol: str = None, interval: str = None, limit: int = 500, **kwargs
    ) -> List[list]:
        """Return klines in the legacy 12-field format.

        Bitget/ccxt returns [ts, o, h, l, c, base_vol]; we extend it to the
        12-field layout so downstream code indexing 0..5 keeps working.
        """
        try:
            ccxt_symbol = self._to_ccxt_symbol(symbol)
            ohlcv = self.exchange.fetch_ohlcv(
                ccxt_symbol, interval, limit=limit, params=self._pub
            )
            interval_ms = int(self.exchange.parse_timeframe(interval) * 1000)
            return [self._to_legacy_kline(k, interval_ms) for k in ohlcv]
        except Exception as e:
            raise _translate_error(e)

    def get_historical_klines(
        self,
        symbol: str,
        interval: str,
        start_str=None,
        end_str=None,
        limit: int = 500,
        **kwargs,
    ) -> List[list]:
        """Original-client compatible signature; start_str/end_str ignored."""
        try:
            ccxt_symbol = self._to_ccxt_symbol(symbol)
            since = None
            if isinstance(start_str, (int, float)):
                since = int(start_str)
            ohlcv = self.exchange.fetch_ohlcv(
                ccxt_symbol, interval, since=since, limit=limit,
                params=self._pub,
            )
            interval_ms = int(self.exchange.parse_timeframe(interval) * 1000)
            return [self._to_legacy_kline(k, interval_ms) for k in ohlcv]
        except Exception as e:
            raise _translate_error(e)

    @staticmethod
    def _to_legacy_kline(kline: list, interval_ms: int) -> list:
        """Map ccxt [ts, o, h, l, c, vol] to the legacy 12-field layout."""
        open_time = int(kline[0])
        return [
            open_time,                    # 0  open time
            float(kline[1]),              # 1  open
            float(kline[2]),              # 2  high
            float(kline[3]),              # 3  low
            float(kline[4]),              # 4  close
            float(kline[5]),              # 5  base volume
            open_time + interval_ms - 1,  # 6  close time (synthesized)
            0.0,                          # 7  quote volume (not provided)
            0,                            # 8  trade count
            0.0,                          # 9  taker buy base volume
            0.0,                          # 10 taker buy quote volume
            0,                            # 11 ignore
        ]

    def get_symbol_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Return symbol info in the legacy shape, LOT_SIZE filter at index 1."""
        try:
            self._ensure_markets()
            markets = self.exchange.markets_by_id.get(symbol)
            market = markets[0] if markets else None
            if market is None:
                return None

            step_size = self._precision_to_stepsize(market["precision"]["amount"])
            tick_size = self._precision_to_stepsize(market["precision"]["price"])
            min_amount = (market.get("limits", {}).get("amount") or {}).get("min")

            return {
                "symbol": market["id"],
                "status": "TRADING" if market.get("active") else "BREAK",
                "baseAsset": market["base"],
                "quoteAsset": market["quote"],
                "filters": [
                    {
                        "filterType": "PRICE_FILTER",
                        "tickSize": tick_size,
                    },
                    {
                        "filterType": "LOT_SIZE",
                        "stepSize": step_size,
                        "minQty": str(min_amount or step_size),
                    },
                ],
            }
        except BitgetAPIException:
            raise
        except Exception as e:
            raise _translate_error(e)

    @staticmethod
    def _precision_to_stepsize(precision) -> str:
        """Normalize ccxt precision to a decimal string like '0.0001'."""
        if precision is None:
            return "0.00000001"
        precision = float(precision)
        if precision >= 1 and precision == int(precision):
            # DECIMAL_PLACES mode: integer = number of decimal places
            decimals = int(precision)
            return "1" if decimals == 0 else "0." + "0" * (decimals - 1) + "1"
        # TICK_SIZE mode: value is already the step (e.g. 0.0001)
        return f"{precision:.10f}".rstrip("0")

    def get_spot_delist_schedule(self) -> List:
        """Bitget exposes no delist-schedule API; always returns empty."""
        return []

    # ------------------------------------------------------------------
    # account / orders
    # ------------------------------------------------------------------
    def get_account(self) -> Dict[str, Any]:
        """Return account info in the legacy shape (validates credentials)."""
        try:
            balance = self.exchange.fetch_balance(self._uta)
            balances = [
                {
                    "asset": currency,
                    "free": str(amounts.get("free") or 0),
                    "locked": str(amounts.get("used") or 0),
                }
                for currency, amounts in balance.items()
                if isinstance(amounts, dict) and "free" in amounts
            ]
            # Bitget does not expose canTrade/accountType; a successful
            # authenticated call implies spot trading permission.
            return {
                "canTrade": True,
                "accountType": "SPOT",
                "permissions": ["SPOT"],
                "balances": balances,
            }
        except Exception as e:
            raise _translate_error(e)

    def create_order(
        self,
        symbol: str,
        side: str,
        type: str,
        quantity: float = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Place an order; returns a legacy-shaped order response with fills.

        Note: Bitget market BUY orders are sized in quote currency, so the
        base `quantity` is converted to quote cost using the last price.
        """
        try:
            ccxt_symbol = self._to_ccxt_symbol(symbol)
            order_type = type.lower()
            order_side = side.lower()

            price = None
            if order_type == "market" and order_side == "buy":
                # Bitget expects quote-currency cost for market buys;
                # ccxt computes it from amount*price when price is given.
                ticker = self.exchange.fetch_ticker(ccxt_symbol, params=self._pub)
                price = ticker.get("last")

            order = self.exchange.create_order(
                ccxt_symbol, order_type, order_side, quantity, price,
                params=self._uta,
            )
            return self._to_legacy_order(order, ccxt_symbol)

        except BitgetAPIException:
            raise
        except Exception as e:
            translated = _translate_error(e)
            raise BitgetOrderException(translated.message, code=translated.code)

    def _to_legacy_order(self, order: Dict[str, Any], ccxt_symbol: str) -> Dict[str, Any]:
        """Normalize a ccxt order to the legacy response shape used by
        PortfolioManager.extract_order_data (fills/orderId/transactTime)."""
        try:
            if order.get("filled") is None or order.get("average") is None:
                order = self.exchange.fetch_order(
                    order["id"], ccxt_symbol, params=self._uta
                )
        except Exception as e:
            logger.warning(f"Could not fetch order details for fills: {e}")

        avg_price = float(order.get("average") or order.get("price") or 0)
        filled_qty = float(order.get("filled") or order.get("amount") or 0)

        fee = order.get("fee") or {}
        fee_cost = float(fee.get("cost") or 0)
        fee_currency = fee.get("currency") or ""

        fills = []
        if filled_qty > 0 and avg_price > 0:
            fills.append(
                {
                    "price": str(avg_price),
                    "qty": str(filled_qty),
                    "commission": str(fee_cost),
                    "commissionAsset": fee_currency,
                }
            )

        return {
            "symbol": self._from_ccxt_symbol(order.get("symbol", ccxt_symbol)),
            "orderId": order.get("id"),
            "transactTime": order.get("timestamp") or int(time.time() * 1000),
            "fills": fills,
            "status": order.get("status"),
        }
