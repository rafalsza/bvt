import time
import os
import requests
from binance.client import Client
import yaml
from globals import user_data_path
from loguru import logger
from configuration_manager import ConfigurationManager
import threading


class BinanceTickerImporter:
    """Optimized Binance ticker importer with rate limiting."""

    def __init__(self):
        self.client = Client("", "")
        self.creds_file = user_data_path + "creds.yml"
        self.tickers_file = "../tickerlists/tickers_binance_USDT.txt"
        self.time_to_wait = 360  # 6 hours
        self.request_delay = 0.1  # 100ms between requests

        config_file = f"{user_data_path}/config.yml"
        creds_file = f"{user_data_path}/creds.yml"

        self.config_manager = ConfigurationManager(config_file, creds_file)
        self.pair_with = self.config_manager.get_config_value("PAIR_WITH")

        # Load credentials
        try:
            self.keys = yaml.safe_load(open(self.creds_file))
        except Exception as e:
            logger.error(f"Failed to load credentials: {e}")
            self.keys = {}

    def get_binance_symbols(self) -> list:
        """Get Binance symbols with rate limiting and error handling."""
        try:
            # Add delay to respect rate limits
            time.sleep(self.request_delay)

            response = requests.get(
                "https://api.binance.com/api/v3/exchangeInfo", timeout=10
            )

            if response.status_code != 200:
                logger.error(f"Binance API error: {response.status_code}")
                return []

            dataj = response.json()["symbols"]

            ignore_patterns = {
                "UP",
                "DOWN",
                "BEAR",
                "BULL",
                "USD",
                "BUSD",
                "EUR",
                "DAI",
                "TUSD",
                "GBP",
                "WBTC",
                "STETH",
                "CETH",
                "PAX",
                "PEPE",
            }

            filtered_symbols = []
            for item in dataj:
                symbol = item.get("symbol", "")

                if (
                    item.get("status") == "TRADING"
                    and item.get("quoteAsset") == self.pair_with
                    and item.get("isSpotTradingAllowed", False)
                    and not symbol.endswith("USD")
                    and not any(
                        symbol.startswith(pattern) for pattern in ignore_patterns
                    )
                ):

                    filtered_symbols.append(symbol)

            logger.info(f"Retrieved {len(filtered_symbols)} symbols from Binance")
            return filtered_symbols

        except requests.exceptions.Timeout:
            logger.error("Binance API timeout")
            return []
        except requests.exceptions.RequestException as e:
            logger.error(f"Binance API request error: {e}")
            return []
        except Exception as e:
            logger.error(f"Error getting Binance symbols: {e}")
            return []

    def get_crypto_rank(self) -> list:
        """Get CryptoRank data with ranking information"""
        try:
            if (
                "cryptorank" not in self.keys
                or "api_key" not in self.keys["cryptorank"]
            ):
                logger.warning("CryptoRank API key not found")
                return []

            url = "https://api.cryptorank.io/v2/currencies"
            headers = {"X-Api-Key": self.keys["cryptorank"]["api_key"]}
            params = {
                "limit": 500,
                "sortBy": "rank",
                "sortDirection": "ASC",
            }

            time.sleep(self.request_delay)
            response = requests.get(url, headers=headers, params=params, timeout=10)

            if response.status_code != 200:
                logger.error(f"CryptoRank API error: {response.text}")
                return []

            data = response.json()
            if "data" not in data:
                return []

            ranked_symbols = []
            for item in data["data"]:
                symbol = item.get("symbol")
                rank = item.get("rank", 999999)

                if (
                    symbol
                    and not symbol.endswith("USD")
                    and not symbol.startswith("USD")
                ):
                    unwanted_patterns = {
                        "WBTC",
                        "UST",
                        "USDD",
                        "DAI",
                        "STETH",
                        "CETH",
                        "GBP",
                        "PAX",
                    }
                    if not any(pattern in symbol for pattern in unwanted_patterns):
                        ranked_symbols.append((f"{symbol}{self.pair_with}", rank))

            logger.info(
                f"Retrieved {len(ranked_symbols)} ranked symbols from CryptoRank"
            )
            return ranked_symbols

        except Exception as e:
            logger.error(f"Error getting CryptoRank data: {e}")
            return []

    def create_ticker_list(self) -> int:
        """Create ticker list limited to top 100 coins."""
        try:
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                binance_future = executor.submit(self.get_binance_symbols)
                cryptorank_future = executor.submit(self.get_crypto_rank)

                binance_symbols = set(binance_future.result(timeout=30))
                cryptorank_data = cryptorank_future.result(timeout=30)

            available_coins = []
            for symbol, rank in cryptorank_data:
                if symbol in binance_symbols:
                    available_coins.append((symbol, rank))

            available_coins.sort(key=lambda x: x[1])

            top_100_symbols = [symbol for symbol, rank in available_coins[:100]]

            os.makedirs(os.path.dirname(self.tickers_file), exist_ok=True)
            temp_file = f"{self.tickers_file}.tmp"

            with open(temp_file, "w") as f:
                for symbol in top_100_symbols:
                    f.write(f"{symbol}\n")

            os.rename(temp_file, self.tickers_file)

            logger.info(f"Created ticker list with top {len(top_100_symbols)} symbols")
            return len(top_100_symbols)

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

            expected_count = 100
            if len(tickers) > expected_count:
                logger.warning(f"Too many tickers: {len(tickers)} > {expected_count}")
                return False

            if len(tickers) < 50:
                logger.warning(f"Too few tickers: {len(tickers)}")
                return False

            invalid_tickers = [t for t in tickers if not t.endswith(self.pair_with)]
            if invalid_tickers:
                logger.warning(f"Invalid ticker format: {invalid_tickers[:5]}")
                return False

            logger.info(f"Ticker list validation passed: {len(tickers)} tickers")
            return True

        except Exception as e:
            logger.error(f"Error validating ticker list: {e}")
            return False


def do_work():
    logger.info("Starting Binance ticker importer")
    importer = BinanceTickerImporter()

    while True:
        try:
            # Check if main thread is alive
            if not threading.main_thread().is_alive():
                logger.info("Main thread not alive, exiting")
                break

            logger.info("Importing Binance ticker list")

            # Create ticker list
            ticker_count = importer.create_ticker_list()

            if ticker_count > 0:
                # Validate the created list
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
            time.sleep(60)  # Wait 1 minute before retry
            continue

    logger.info("Binance ticker importer stopped")


if __name__ == "__main__":
    do_work()
