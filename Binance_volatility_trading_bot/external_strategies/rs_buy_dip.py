# rs_buy_dip.py
from binance.client import Client
import numpy as np
import threading
import os
import warnings
import time
from numpy.typing import NDArray
from loguru import logger
from .w_params import wavetrend_parameters
from .technical_indicators import TechnicalIndicators
from typing import Optional
import signal

warnings.filterwarnings("ignore")

# Configuration
TIME_TO_WAIT = 1  # Minutes to wait between analysis
DEBUG = False
TICKERS = "tickerlists/tickers_binance_USDC.txt"
SIGNAL_NAME = "rs_buy_dip"
SIGNAL_FILE_BUY = "signals/" + SIGNAL_NAME + ".buy"

# Feature flags
CMO_1h = True
WAVETREND_1h = True
MACD_1h = False


class TxColors:
    BUY = "\033[92m"
    WARNING = "\033[93m"
    SELL_LOSS = "\033[91m"
    SELL_PROFIT = "\033[32m"
    DIM = "\033[2m\033[35m"
    DEFAULT = "\033[39m"
    RED = "\033[91m"


class SignalConfig:
    WT_OVERSOLD_THRESHOLD = -75
    CMO_OVERSOLD_THRESHOLD = -50
    WT_MOMENTUM_THRESHOLD = -60
    DEFAULT_WT_N1 = 10
    DEFAULT_WT_N2 = 21


class ImportData:
    def __init__(self):
        self.client = Client("", "")
        self.request_delay = 1

    def get_klines_data(self, symbol: str, interval: str, limit: int = 500) -> Optional[dict]:
        max_retries = 5
        retry_delay = 5
        for attempt in range(max_retries):
            try:
                klines = self.client.get_historical_klines(symbol, interval, limit=limit)
                time.sleep(self.request_delay)
                if not klines:
                    logger.warning(f"No data received for {symbol}")
                    return None
                data = np.array(klines, dtype=float)
                return {
                    "timestamp": data[:, 0],
                    "open": data[:, 1],
                    "high": data[:, 2],
                    "low": data[:, 3],
                    "close": data[:, 4],
                    "volume": data[:, 5],
                }
            except Exception as e:
                if "Too much request weight" in str(e):
                    logger.error(f"Rate limit exceeded for {symbol}, retrying in {retry_delay}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    logger.error(f"Error fetching data for {symbol}: {e}")
                    return None
        logger.error(f"Failed to fetch data for {symbol} after {max_retries} attempts")
        return None

class SignalGenerator:
    def __init__(self):
        self.indicators = TechnicalIndicators()
        self.data_provider = ImportData()

    @logger.catch
    def filter_1h_timeframe(self, symbol: str) -> list:
        try:
            data = self.data_provider.get_klines_data(symbol, "1h", 500)
            if not data:
                return []

            n1, n2 = wavetrend_parameters.get(symbol, (SignalConfig.DEFAULT_WT_N1, SignalConfig.DEFAULT_WT_N2))
            wt1, _ = self.indicators.wavetrend(data["high"], data["low"], data["close"], n1, n2)
            ema_200 = self.indicators.ema(data["close"], 200)
            cmo = self.indicators.cmo(data["close"], 14)
            _, linear_lower, _ = self.indicators.regression_channel(data)

            buy_signals = []
            if self._check_buy_conditions(wt1, linear_lower, ema_200,cmo, data, symbol):
                buy_signals.append(symbol)

            return buy_signals
        except Exception as e:
            logger.error(f"Error in 1h filter for {symbol}: {e}")
            return []

    def _check_buy_conditions(self, wt1: NDArray, linear_lower: NDArray, ema_200: NDArray,cmo: NDArray, data: dict, symbol: str) -> bool:
        try:
            if len(wt1) == 0 or len(ema_200) == 0:
                return False
            wt_oversold = wt1[-1] < SignalConfig.WT_OVERSOLD_THRESHOLD
            below_ema = data["close"][-1] < ema_200[-1]
            below_linear_lower = data["close"][-1] < linear_lower[-1]
            cmo_oversold = cmo[-1] < SignalConfig.CMO_OVERSOLD_THRESHOLD
            buy_signal = wt_oversold and below_ema and below_linear_lower and cmo_oversold
            if buy_signal:
                logger.debug(f"🟢 Buy signal for {symbol}: WT1={wt1[-1]:.2f}")
            return buy_signal
        except Exception as e:
            logger.error(f"Error checking buy conditions for {symbol}: {e}")
            return False

    def filter_15m_timeframe(self, symbol: str) -> bool:
        try:
            data = self.data_provider.get_klines_data(symbol, "15m", 500)
            if not data:
                return False

            _, linear_lower, _ = self.indicators.regression_channel(data)
            current_price = data["close"][-1]

            is_below_lower_band = current_price < linear_lower[-1]

            if is_below_lower_band and DEBUG:
                logger.info(f"15m filter passed (price below lower regression band): {symbol}")
            return is_below_lower_band

        except Exception as e:
            logger.error(f"Error in 15m filter for {symbol}: {e}")
            return False

    def filter_5m_timeframe(self, symbol: str) -> bool:
        try:
            data = self.data_provider.get_klines_data(symbol, interval="5m", limit=100)
            if not data:
                return False
            wt1, _ = self.indicators.wavetrend(data["high"], data["low"], data["close"], SignalConfig.DEFAULT_WT_N1, SignalConfig.DEFAULT_WT_N2)
            logger.info(f"5m filter {symbol} - WT1: {wt1[-1]:.2f}")
            is_oversold = wt1[-1] < SignalConfig.WT_MOMENTUM_THRESHOLD
            return is_oversold
        except Exception as e:
            logger.error(f"Error in 5m filter for {symbol}: {e}")
            return False

    def check_momentum_1m(self, symbol: str) -> bool:
        try:
            data = self.data_provider.get_klines_data(symbol, "1m", 100)
            if not data:
                return False
            cmo_values = self.indicators.cmo(data["close"])
            wt1, _ = self.indicators.wavetrend(data["high"], data["low"], data["close"], SignalConfig.DEFAULT_WT_N1, SignalConfig.DEFAULT_WT_N2)
            if len(cmo_values) == 0 or len(wt1) == 0:
                return False
            current_cmo = cmo_values[-1]
            current_wt1 = wt1[-1]
            logger.info(f"1m momentum {symbol} - CMO: {current_cmo:.2f}, WT1: {current_wt1:.2f}")
            is_oversold = current_cmo < SignalConfig.CMO_OVERSOLD_THRESHOLD and current_wt1 < SignalConfig.WT_MOMENTUM_THRESHOLD
            if is_oversold:
                logger.info(f"Oversold dip found: {symbol}")
            return is_oversold
        except Exception as e:
            logger.error(f"Error in 1m momentum check for {symbol}: {e}")
            return False


class SignalFileManager:
    @staticmethod
    def clear_signal_files():
        for file_path in [SIGNAL_FILE_BUY]:
            if os.path.exists(file_path):
                os.remove(file_path)

    @staticmethod
    def write_buy_signals(signals: list):
        if signals:
            os.makedirs(os.path.dirname(SIGNAL_FILE_BUY), exist_ok=True)
            with open(SIGNAL_FILE_BUY, "a+") as f:
                for signal in signals:
                    f.write(f"{signal}\n")


def analyze_trading_pairs(trading_pairs: list) -> list:
    signal_generator = SignalGenerator()
    file_manager = SignalFileManager()

    file_manager.clear_signal_files()

    all_buy_signals = []

    stage1_buy = []
    for symbol in trading_pairs:
        buy_signals = signal_generator.filter_1h_timeframe(symbol)
        stage1_buy.extend(buy_signals)

    stage2_symbols = [sym for sym in stage1_buy if signal_generator.filter_15m_timeframe(sym)]

    stage3_symbols = [sym for sym in stage2_symbols if signal_generator.filter_5m_timeframe(sym)]

    for sym in stage3_symbols:
        if signal_generator.check_momentum_1m(sym):
            all_buy_signals.append(sym)

    file_manager.write_buy_signals(all_buy_signals)

    if all_buy_signals:
        logger.info(f"{TxColors.BUY}{SIGNAL_NAME}: {all_buy_signals} - Buy Signal Detected{TxColors.DEFAULT}")
    else:
        logger.info(f"{TxColors.DEFAULT}{SIGNAL_NAME}: - not enough signal to buy")

    return all_buy_signals


def load_trading_pairs() -> list:
    try:
        if not os.path.exists(TICKERS):
            logger.warning(f"Tickers file not found: {TICKERS}")
            return []

        with open(TICKERS) as f:
            pairs = f.read().splitlines()

        pairs = [pair.strip() for pair in pairs if pair.strip()]

        return pairs

    except Exception as e:
        logger.error(f"Error loading trading pairs: {e}")
        return []


class SignalHandler:
    def __init__(self):
        self.shutdown = False
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self.shutdown = True


def do_work():
    logger.info(f"{SIGNAL_NAME}: Starting signal analysis")
    signal_handler = SignalHandler()

    while not signal_handler.shutdown:
        try:
            if not threading.main_thread().is_alive():
                logger.info("Main thread not alive, exiting")
                break

            trading_pairs = load_trading_pairs()

            if not trading_pairs:
                logger.warning("No trading pairs loaded, waiting...")
                time.sleep(TIME_TO_WAIT * 60)
                continue

            logger.info(f"{SIGNAL_NAME}: Analyzing {len(trading_pairs)} coins")
            logger.info(f"CMO_1h: {CMO_1h} | WAVETREND_1h: {WAVETREND_1h} | MACD_1h: {MACD_1h}")

            buy_signals = analyze_trading_pairs(trading_pairs)

            logger.info(f"{SIGNAL_NAME}: {len(buy_signals)} coins with Buy Signals")
            logger.info(f"Waiting {TIME_TO_WAIT} minutes for next analysis")

            time.sleep(TIME_TO_WAIT * 60)

        except KeyboardInterrupt:
            logger.info(f"{SIGNAL_NAME}: Received keyboard interrupt, exiting")
            break

        except Exception as e:
            logger.error(f"{SIGNAL_NAME}: Exception in do_work(): {e}")
            time.sleep(60)
            continue

    logger.info(f"{SIGNAL_NAME}: Signal analysis stopped")


if __name__ == "__main__":
    do_work()