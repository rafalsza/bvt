import time
import os
import requests
from binance.client import Client
from globals import user_data_path
from loguru import logger
from configuration_manager import ConfigurationManager
import threading


class BinanceTickerImporter:
    """Simplified Binance ticker importer with CoinGecko integration."""

    def __init__(self):
        self.client = Client("", "")
        self.tickers_file = "../tickerlists/tickers_binance_USDT.txt"
        self.time_to_wait = 360
        self.request_delay = 1.0
        self.tickers_number = 100

        config_file = f"{user_data_path}/config.yml"
        creds_file = f"{user_data_path}/creds.yml"

        self.config_manager = ConfigurationManager(config_file, creds_file)
        self.pair_with = self.config_manager.get_config_value("PAIR_WITH")

    def get_binance_symbols(self) -> set:
        """Get active Binance trading symbols."""
        try:
            response = requests.get(
                "https://api.binance.com/api/v3/exchangeInfo", timeout=10
            )
            if response.status_code != 200:
                return set()

            symbols = set()
            for item in response.json()["symbols"]:
                if (
                    item.get("status") == "TRADING"
                    and item.get("quoteAsset") == self.pair_with
                    and item.get("isSpotTradingAllowed", False)
                ):
                    symbols.add(item["symbol"])

            return symbols
        except Exception as e:
            logger.error(f"Error getting Binance symbols: {e}")
            return set()

    def get_top_coins_by_volume(self) -> list:
        """Get top coins sorted by 24hr volume, excluding stablecoins."""
        try:
            time.sleep(self.request_delay)
            response = requests.get(
                "https://api.binance.com/api/v3/ticker/24hr", timeout=15
            )

            if response.status_code != 200:
                return []

            # Define stablecoins and unwanted tokens to exclude
            excluded_symbols = {
                "USDCUSDT",
                "FDUSDUSDT",
                "EURUSDT",
                "PAXGUSDT",
                "XUSDUSDT",
                "USD1USDT",
                "DAIUSDT",
                "TUSDUSDT",
                "BUSDUSDT",
                "USTUSDT",
                "USDDUSDT",
                "FRAXUSDT",
                "WBTCUSDT",
                "STETHUSDT",
                "WETHUSDT",  # Wrapped Ethereum variants
            }

            # Filter USDT pairs and exclude stablecoins
            usdt_pairs = []
            for item in response.json():
                symbol = item["symbol"]
                if (
                    symbol.endswith(self.pair_with)
                    and symbol not in excluded_symbols
                    and not self._is_stablecoin(symbol)
                ):
                    usdt_pairs.append(item)

            sorted_pairs = sorted(
                usdt_pairs, key=lambda x: float(x.get("quoteVolume", 0)), reverse=True
            )

            return [(item["symbol"], idx + 1) for idx, item in enumerate(sorted_pairs)]

        except Exception as e:
            logger.error(f"Error getting volume data: {e}")
            return []

    def _is_stablecoin(self, symbol: str) -> bool:
        """Check if symbol is likely a stablecoin based on naming patterns."""
        symbol_base = symbol.replace("USDT", "").upper()

        stablecoin_patterns = [
            "USD",
            "EUR",
            "GBP",
            "JPY",  # Fiat currencies
            "DAI",
            "USDC",
            "USDD",
            "TUSD",
            "BUSD",  # Known stablecoins
            "FRAX",
            "LUSD",
            "SUSD",
            "GUSD",  # More stablecoins
            "PAXG",  # Gold-backed
        ]

        return any(pattern in symbol_base for pattern in stablecoin_patterns)

    def create_ticker_list(self) -> int:
        """Create ticker list from top volume coins with duplicate prevention."""
        try:
            binance_symbols = self.get_binance_symbols()
            volume_data = self.get_top_coins_by_volume()

            if not binance_symbols or not volume_data:
                logger.error("Failed to get required data")
                return 0

            # Prevent duplicates using set
            selected_tickers = []
            seen_symbols = set()

            for symbol, rank in volume_data:
                if (
                    symbol in binance_symbols
                    and symbol not in seen_symbols
                    and len(selected_tickers) < self.tickers_number
                ):
                    selected_tickers.append(symbol)
                    seen_symbols.add(symbol)

            # Write to file
            os.makedirs(os.path.dirname(self.tickers_file), exist_ok=True)
            with open(self.tickers_file, "w") as f:
                for ticker in selected_tickers:
                    f.write(f"{ticker}\n")

            logger.info(
                f"Created ticker list with {len(selected_tickers)} unique symbols"
            )
            return len(selected_tickers)

        except Exception as e:
            logger.error(f"Error creating ticker list: {e}")
            return 0

    def validate_ticker_list(self) -> bool:
        """Validate ticker list quality."""
        try:
            if not os.path.exists(self.tickers_file):
                return False

            with open(self.tickers_file, "r") as f:
                tickers = [line.strip() for line in f if line.strip()]

            min_threshold = max(10, int(self.tickers_number * 0.5))
            max_threshold = int(self.tickers_number * 1.2)

            if len(tickers) < min_threshold:
                logger.warning(
                    f"Too few tickers: {len(tickers)}, expected at least {min_threshold}"
                )
                return False

            if len(tickers) > max_threshold:
                logger.warning(
                    f"Too many tickers: {len(tickers)}, expected at most {max_threshold}"
                )
                return False

            invalid_tickers = [t for t in tickers if not t.endswith(self.pair_with)]
            if invalid_tickers:
                logger.warning(f"Invalid ticker format: {invalid_tickers[:5]}")
                return False

            logger.info(
                f"Ticker list validation passed: {len(tickers)} tickers (target: {self.tickers_number})"
            )
            return True

        except Exception as e:
            logger.error(f"Error validating ticker list: {e}")
            return False


def do_work():
    """Main worker function for ticker import."""
    logger.info("Starting Binance ticker importer")
    importer = BinanceTickerImporter()

    while True:
        try:
            if not threading.main_thread().is_alive():
                logger.info("Main thread not alive, exiting")
                break

            logger.info("Importing Binance ticker list")

            ticker_count = importer.create_ticker_list()

            if ticker_count > 0:
                if importer.validate_ticker_list():
                    logger.info(f"✅ Successfully imported {ticker_count} tickers")
                else:
                    logger.warning("⚠️ Ticker list validation failed")
            else:
                logger.error("❌ Failed to import any tickers")

            logger.info(f"Waiting {importer.time_to_wait} minutes for next import")
            time.sleep(importer.time_to_wait * 60)

        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt, exiting")
            break
        except Exception as e:
            logger.error(f"Exception in ticker import: {e}")
            time.sleep(60)
            continue

    logger.info("Binance ticker importer stopped")


if __name__ == "__main__":
    do_work()
