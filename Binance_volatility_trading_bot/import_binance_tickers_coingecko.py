import time
import os
import requests
from globals import user_data_path
from loguru import logger
from configuration_manager import ConfigurationManager
import threading


class BinanceTickerImporter:
    """CoinGecko + Binance ticker importer with market cap ranking."""

    def __init__(self):
        config_file = f"{user_data_path}/config.yml"
        creds_file = f"{user_data_path}/creds.yml"
        self.config_manager = ConfigurationManager(config_file, creds_file)
        self.pair_with = self.config_manager.get_config_value("PAIR_WITH")
        self.tickers_file = f"tickerlists/tickers_binance_{self.pair_with}.txt"
        self.time_to_wait = 360
        self.request_delay = 1.0
        self.tickers_number = 100

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

            logger.info(f"Retrieved {len(symbols)} Binance symbols")
            return symbols
        except Exception as e:
            logger.error(f"Error getting Binance symbols: {e}")
            return set()

    def get_coingecko_top_coins(self, limit: int = 500) -> list:
        try:
            all_coins = []
            pages_needed = (limit + 249) // 250  # CoinGecko max 250 per page
            max_retries = 3

            for page in range(1, pages_needed + 1):
                per_page = min(250, limit - (page - 1) * 250)

                url = "https://api.coingecko.com/api/v3/coins/markets"
                params = {
                    "vs_currency": "usd",
                    "order": "market_cap_desc",
                    "per_page": per_page,
                    "page": page,
                    "sparkline": "false",
                }

                logger.debug(f"Fetching CoinGecko page {page}/{pages_needed}")
                time.sleep(self.request_delay)

                for attempt in range(max_retries):
                    try:
                        response = requests.get(url, params=params, timeout=30)
                        response.raise_for_status()
                        page_data = response.json()
                        break
                    except requests.exceptions.Timeout:
                        logger.warning(
                            f"Timeout waiting for CoinGecko API response, retry {attempt + 1}/{max_retries}"
                        )
                        time.sleep(2**attempt)
                        if attempt == max_retries - 1:
                            logger.error(
                                "Max retries reached for CoinGecko page, skipping"
                            )
                            page_data = []
                    except Exception as e:
                        logger.error(f"Error fetching CoinGecko data: {e}")
                        return []

                # Process coins and create ranked list
                for coin in page_data:
                    symbol = coin.get("symbol", "").upper()
                    rank = coin.get("market_cap_rank", 999999)

                    if symbol and not self._is_stablecoin(symbol):
                        binance_symbol = f"{symbol}{self.pair_with}"
                        all_coins.append((binance_symbol, rank))

                if len(all_coins) >= limit:
                    break

            logger.info(f"Retrieved {len(all_coins)} ranked coins from CoinGecko")
            return all_coins

        except Exception as e:
            logger.error(f"Error getting CoinGecko data: {e}")
            return []

    def _is_stablecoin(self, symbol: str) -> bool:
        """Filter out stablecoins and unwanted tokens."""
        excluded_patterns = {
            "USDC",
            "FDUSD",
            "DAI",
            "TUSD",
            "BUSD",
            "USDD",
            "EUR",
            "GBP",
            "JPY",
            "PAXG",
            "XUSD",
            "USD1",
            "WBTC",
            "WETH",
            "STETH",
            "WBETH",
            "BNSOL",
        }

        return any(pattern in symbol for pattern in excluded_patterns)

    def create_ticker_list(self) -> int:
        """Create ticker list from CoinGecko market cap ranking."""
        try:
            # Get data from both sources
            binance_symbols = self.get_binance_symbols()
            coingecko_coins = self.get_coingecko_top_coins(self.tickers_number * 3)

            if not binance_symbols or not coingecko_coins:
                logger.error("Failed to get required data")
                return 0

            # Filter coins available on Binance and prevent duplicates
            selected_tickers = []
            seen_symbols = set()

            # Sort by market cap rank (lower rank = higher market cap)
            coingecko_coins.sort(key=lambda x: x[1])

            for symbol, rank in coingecko_coins:
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
                f"Created ticker list with {len(selected_tickers)} coins (CoinGecko market cap ranking)"
            )
            return len(selected_tickers)

        except Exception as e:
            logger.error(f"Error creating ticker list: {e}")
            return 0


def do_work():
    """Main worker function for ticker import with CoinGecko integration."""
    logger.info("Starting CoinGecko + Binance ticker importer")
    importer = BinanceTickerImporter()

    while True:
        try:
            if not threading.main_thread().is_alive():
                logger.info("Main thread not alive, exiting")
                break

            logger.info("Importing ticker list from CoinGecko market cap ranking")

            ticker_count = importer.create_ticker_list()

            if ticker_count > 0:
                logger.success(
                    f"✅ Successfully imported {ticker_count} tickers (CoinGecko ranked)"
                )
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

    logger.info("CoinGecko + Binance ticker importer stopped")


if __name__ == "__main__":
    do_work()
