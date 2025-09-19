# data_provider.py
from datetime import datetime
from typing import Dict, Any, List, Optional
from loguru import logger
from binance.client import Client
from external_signal_manager import ExternalSignalManager


class DataProvider:
    """
    Provides market data and price information for the trading bot.
    """

    def __init__(self, client: Client, config: Dict[str, Any]):
        """
        Initialize data provider with Binance client and configuration.

        Args:
            client: Binance API client
            config: Configuration dictionary
        """
        self.client = client
        self.config = config

        # Historical data storage
        self.historical_prices = []
        self.hsp_head = -1

        # Configuration parameters
        self.TIME_DIFFERENCE = config.get("TIME_DIFFERENCE", 1)
        self.RECHECK_INTERVAL = config.get("RECHECK_INTERVAL", 4)
        self.PAIR_WITH = config.get("PAIR_WITH", "USDT")
        self.FIATS = config.get("FIATS", [])
        self.CUSTOM_LIST = config.get("CUSTOM_LIST", False)
        self.TICKERS_LIST = config.get("TICKERS_LIST", "")
        self.EXCLUDED_COINS = config.get(
            "EX_COINS", ["BUSD", "USDT", "USDC", "DAI", "TUSD"]
        )

        # Load custom tickers if enabled
        self.tickers = []
        if self.CUSTOM_LIST and self.TICKERS_LIST:
            self._load_custom_tickers()
        logger.info(
            f"📊 Data provider initialized - Custom list: {'✅' if self.CUSTOM_LIST else '❌'}"
        )

        self.external_signal_manager = ExternalSignalManager(config)
        if config.get("SIGNALLING_MODULES"):
            self.external_signal_manager.start_signal_modules()

        logger.info("📊 Data provider initialized with external signals")

    def initialize_historical_data(self):
        """
        Initialize historical price data storage.

        Creates empty historical data structure based on configuration parameters.
        """
        try:
            # Calculate required storage size
            storage_size = self.TIME_DIFFERENCE * self.RECHECK_INTERVAL

            # Initialize historical prices array with None values
            self.historical_prices = [None] * storage_size
            self.hsp_head = -1

            logger.info(
                f"📈 Historical data initialized - Storage size: {storage_size}"
            )
            logger.debug(
                f"📈 Time difference: {self.TIME_DIFFERENCE} min, Recheck interval: {self.RECHECK_INTERVAL}"
            )

        except Exception as e:
            logger.error(f"💥 Failed to initialize historical data: {e}")
            raise

    def _load_custom_tickers(self):
        """Load custom ticker list from file."""
        try:
            if self.TICKERS_LIST:
                with open(self.TICKERS_LIST, "r") as file:
                    self.tickers = [line.strip() for line in file if line.strip()]
                logger.info(f"📋 Loaded {len(self.tickers)} custom tickers")
        except FileNotFoundError:
            logger.warning(f"⚠️ Custom ticker file not found: {self.TICKERS_LIST}")
            self.tickers = []
        except Exception as e:
            logger.error(f"💥 Failed to load custom tickers: {e}")
            self.tickers = []

    def get_price(self, add_to_historical: bool = True) -> Dict[str, Dict[str, Any]]:
        """
        Get current prices for all relevant trading pairs.

        Args:
            add_to_historical: Whether to add prices to historical data

        Returns:
            Dict containing price data for filtered symbols
        """
        try:
            logger.debug("📊 Fetching current prices from Binance...")

            # Get all ticker prices from Binance
            all_prices = self.client.get_all_tickers()

            # Filter and process prices
            filtered_prices = self._filter_prices(all_prices)

            # Add to historical data if requested
            if add_to_historical:
                self._add_to_historical(filtered_prices)

            logger.debug(f"📊 Retrieved prices for {len(filtered_prices)} symbols")
            return filtered_prices

        except Exception as e:
            logger.error(f"💥 Failed to get prices: {e}")
            raise

    def _filter_prices(self, all_prices: List[Dict]) -> Dict[str, Dict[str, Any]]:
        """
        Filter prices based on configuration (custom list or pair filtering).

        Args:
            all_prices: List of all ticker prices from Binance

        Returns:
            Dict of filtered prices
        """
        filtered_prices = {}

        for ticker in all_prices:
            symbol = ticker["symbol"]

            # Apply filtering logic
            if self._should_include_symbol(symbol):
                filtered_prices[symbol] = {
                    "price": float(ticker["price"]),
                    "time": datetime.now(),
                }

        return filtered_prices

    def _should_include_symbol(self, symbol: str) -> bool:
        """
        Check if symbol should be included based on configuration.

        Args:
            symbol: Trading pair symbol

        Returns:
            bool: True if symbol should be included
        """
        # Check if symbol contains any excluded fiat pairs
        if any(fiat in symbol for fiat in self.FIATS):
            return False

        if self.CUSTOM_LIST:
            # Use custom ticker list
            base_symbol = symbol.replace(self.PAIR_WITH, "")
            return base_symbol in self.tickers
        else:
            # Use pair filtering
            return self.PAIR_WITH in symbol

    def _add_to_historical(self, prices: Dict[str, Dict[str, Any]]):
        """
        Add current prices to historical data storage.

        Args:
            prices: Current price data to add
        """
        try:
            # Move to next position in circular buffer
            self.hsp_head += 1
            if self.hsp_head >= len(self.historical_prices):
                self.hsp_head = 0

            # Store prices at current position
            self.historical_prices[self.hsp_head] = prices

            logger.debug(
                f"📈 Added prices to historical data at position {self.hsp_head}"
            )

        except Exception as e:
            logger.error(f"💥 Failed to add to historical data: {e}")

    def get_trading_signals(self) -> Dict[str, Dict[str, Any]]:
        """Get trading signals including external signals."""
        try:
            # Get volatility signals
            volatile_coins = self._detect_volatility()

            # Get external signals
            external_signals = self.external_signal_manager.get_external_signals()

            # Combine signals
            all_signals = {**volatile_coins, **external_signals}

            if external_signals:
                logger.info(f"📡 Found {len(external_signals)} external signals")

            return all_signals

        except Exception as e:
            logger.error(f"💥 Error getting trading signals: {e}")
            return {}

    def shutdown(self):
        """Shutdown data provider and stop signal modules."""
        try:
            self.external_signal_manager.stop_all_modules()
            logger.info("📊 Data provider shutdown completed")
        except Exception as e:
            logger.error(f"💥 Error during data provider shutdown: {e}")

    def _has_sufficient_data(self) -> bool:
        """Check if we have sufficient historical data."""
        non_none_count = sum(1 for price in self.historical_prices if price is not None)
        required_count = min(self.TIME_DIFFERENCE * self.RECHECK_INTERVAL, 2)
        return non_none_count >= required_count

    def _detect_volatility(self) -> Dict[str, Dict[str, Any]]:
        """
        Detect volatile coins based on price movement.

        Returns:
            Dict of volatile coins with their signals
        """
        volatile_coins = {}

        try:
            current_prices = self.historical_prices[self.hsp_head]
            if not current_prices:
                return volatile_coins

            for symbol in current_prices:
                try:
                    # Calculate price change over time period
                    price_change = self._calculate_price_change(symbol)

                    # Check if change exceeds threshold
                    change_threshold = self.config.get("CHANGE_IN_PRICE", 3)
                    if abs(price_change) > change_threshold:
                        volatile_coins[symbol] = {
                            "buy_signal": (
                                "volatility_gain"
                                if price_change > 0
                                else "volatility_drop"
                            ),
                            "value": 1,
                            "gain": round(price_change, 3),
                        }

                        logger.info(
                            f"🎯 Volatility detected: {symbol} +{price_change:.3f}%"
                        )

                except Exception as e:
                    logger.debug(f"⚠️ Error analyzing {symbol}: {e}")
                    continue

        except Exception as e:
            logger.error(f"💥 Error in volatility detection: {e}")

        return volatile_coins

    def _calculate_price_change(self, symbol: str) -> float:
        """
        Calculate percentage price change for a symbol over the time period.

        Args:
            symbol: Trading pair symbol

        Returns:
            float: Percentage price change
        """
        try:
            # Find min and max prices over the historical period
            prices = []
            times = []

            for price_data in self.historical_prices:
                if price_data and symbol in price_data:
                    prices.append(float(price_data[symbol]["price"]))
                    times.append(price_data[symbol]["time"])

            if len(prices) < 2:
                return 0.0

            min_price = min(prices)
            max_price = max(prices)

            # Calculate percentage change
            if min_price > 0:
                percentage_change = ((max_price - min_price) / min_price) * 100
                return percentage_change

            return 0.0

        except Exception as e:
            logger.debug(f"⚠️ Error calculating price change for {symbol}: {e}")
            return 0.0

    def get_historical_data_status(self) -> Dict[str, Any]:
        """
        Get status information about historical data.

        Returns:
            Dict with historical data status
        """
        non_none_count = sum(1 for price in self.historical_prices if price is not None)

        return {
            "total_slots": len(self.historical_prices),
            "filled_slots": non_none_count,
            "current_position": self.hsp_head,
            "data_ready": self._has_sufficient_data(),
            "oldest_data": self._get_oldest_data_time(),
            "newest_data": self._get_newest_data_time(),
        }

    def _get_oldest_data_time(self) -> Optional[str]:
        """Get timestamp of oldest data."""
        for price_data in self.historical_prices:
            if price_data:
                # Get first symbol's time
                first_symbol = next(iter(price_data))
                return price_data[first_symbol]["time"].strftime("%Y-%m-%d %H:%M:%S")
        return None

    def _get_newest_data_time(self) -> Optional[str]:
        """Get timestamp of newest data."""
        if self.hsp_head >= 0 and self.historical_prices[self.hsp_head]:
            price_data = self.historical_prices[self.hsp_head]
            first_symbol = next(iter(price_data))
            return price_data[first_symbol]["time"].strftime("%Y-%m-%d %H:%M:%S")
        return None

    def get_symbol_price(self, symbol: str) -> float:
        """Get single symbol price from cached data."""
        try:
            if self.hsp_head >= 0 and self.historical_prices[self.hsp_head]:
                latest_prices = self.historical_prices[self.hsp_head]
                if symbol in latest_prices:
                    return float(latest_prices[symbol]["price"])

            # Fallback - update cache if empty
            if not self._has_sufficient_data():
                logger.debug(f"📊 Updating price cache for {symbol}")
                self.get_price()
                if self.hsp_head >= 0 and self.historical_prices[self.hsp_head]:
                    latest_prices = self.historical_prices[self.hsp_head]
                    if symbol in latest_prices:
                        return float(latest_prices[symbol]["price"])

            logger.warning(f"⚠️ Price not found for {symbol}")
            return 0.0

        except Exception as e:
            logger.error(f"💥 Error getting price for {symbol}: {e}")
            return 0.0

    def get_current_prices(self) -> Dict[str, float]:
        try:
            if self.hsp_head >= 0 and self.historical_prices[self.hsp_head]:
                latest_prices = self.historical_prices[self.hsp_head]
                return {
                    symbol: float(data["price"])
                    for symbol, data in latest_prices.items()
                }
            else:

                price_data = self.get_price()
                return {
                    symbol: float(data["price"]) for symbol, data in price_data.items()
                }
        except Exception as e:
            logger.error(f"💥 Error getting current prices: {e}")
            return {}

    def get_delisted_coins(self) -> List[str]:
        """
        Retrieve a list of coins that are scheduled for delisting from Binance spot trading.

        Returns:
            List[str]: List of trading pair symbols that are scheduled for delisting
        """
        try:
            delist_schedule = self.client.get_spot_delist_schedule()
            if not delist_schedule:
                return []

            # Extract all symbols from the delist schedule
            delisted_coins = []
            for entry in delist_schedule:
                if (
                    isinstance(entry, dict)
                    and "symbols" in entry
                    and isinstance(entry["symbols"], list)
                ):
                    delisted_coins.extend(entry["symbols"])

            # Remove duplicates while preserving order
            seen = set()
            unique_coins = [
                coin for coin in delisted_coins if not (coin in seen or seen.add(coin))
            ]

            if unique_coins:
                logger.debug(
                    f"Found {len(unique_coins)} coins scheduled for delisting: {', '.join(unique_coins)}"
                )
            return unique_coins

        except Exception as e:
            logger.error(f"❌ Error fetching delisted coins: {e}")
            return []
