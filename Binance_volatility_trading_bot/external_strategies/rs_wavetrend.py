# rs_wavetrend.py
from binance.client import Client
import numpy as np
import threading
import os
import warnings
import time
from numpy.typing import NDArray
from loguru import logger
from .w_params import wavetrend_parameters
from typing import Optional
import signal

warnings.filterwarnings("ignore")

# Configuration
TIME_TO_WAIT = 1  # Minutes to wait between analysis
DEBUG = False
TICKERS = "tickerlists/tickers_binance_USDC.txt"
SIGNAL_NAME = "rs_signals_wavetrend"
SIGNAL_FILE_BUY = "signals/" + SIGNAL_NAME + ".buy"
SIGNAL_FILE_SELL = "signals/" + SIGNAL_NAME + ".sell"

# Feature flags
CMO_1h = True
WAVETREND_1h = True
MACD_1h = False

# Global lists for filtering
filtered_pairs1 = []
filtered_pairs2 = []
filtered_pairs3 = []
filtered_pairs_sell = []
selected_pair_buy = []
selected_pair_sell = []


class TxColors:
    """Color constants for console output."""

    BUY = "\033[92m"
    WARNING = "\033[93m"
    SELL_LOSS = "\033[91m"
    SELL_PROFIT = "\033[32m"
    DIM = "\033[2m\033[35m"
    DEFAULT = "\033[39m"
    RED = "\033[91m"


class SignalConfig:
    """Configuration for signal generation."""

    # WaveTrend thresholds
    WT_OVERSOLD_THRESHOLD = -75
    WT_OVERBOUGHT_THRESHOLD = 60

    # CMO thresholds
    CMO_OVERSOLD_THRESHOLD = -50
    # WaveTrend momentum
    WT_MOMENTUM_THRESHOLD = -60

    # Default WaveTrend parameters
    DEFAULT_WT_N1 = 10
    DEFAULT_WT_N2 = 21


class TechnicalIndicators:
    """Technical analysis indicators implemented with numpy."""

    @staticmethod
    def ema(data: NDArray, period: int) -> NDArray:
        alpha = 2.0 / (period + 1.0)
        ema_values = np.zeros_like(data)
        ema_values[0] = data[0]

        for i in range(1, len(data)):
            ema_values[i] = alpha * data[i] + (1 - alpha) * ema_values[i - 1]

        return ema_values

    @staticmethod
    def sma(data: NDArray, period: int) -> NDArray:
        sma_values = np.full(len(data), np.nan)

        for i in range(period - 1, len(data)):
            sma_values[i] = np.mean(data[i - period + 1 : i + 1])

        return sma_values

    @staticmethod
    def hlc3(high: NDArray, low: NDArray, close: NDArray) -> NDArray:
        """Calculate HLC3 (typical price)."""
        return (high + low + close) / 3.0

    @staticmethod
    def cmo(data: NDArray, period: int = 14) -> NDArray:
        """
        Calculate Chande Momentum Oscillator.

        Args:
            data: Price data array
            period: CMO period

        Returns:
            CMO values array
        """
        if len(data) < period + 1:
            return np.full(len(data), np.nan)

        changes = np.diff(data)
        gains = np.where(changes > 0, changes, 0)
        losses = np.where(changes < 0, -changes, 0)

        cmo_values = np.full(len(data), np.nan)

        for i in range(period, len(data)):
            sum_gains = float(np.sum(gains[i - period : i]))
            sum_losses = float(np.sum(losses[i - period : i]))

            if sum_gains + sum_losses != 0:
                cmo_values[i] = (
                    100 * (sum_gains - sum_losses) / (sum_gains + sum_losses)
                )
            else:
                cmo_values[i] = 0

        return cmo_values


class DataProvider:
    """Handles data fetching and processing."""

    def __init__(self):
        self.client = Client("", "")
        self.request_delay = 1

    def get_klines_data(
        self, symbol: str, interval: str, limit: int = 500
    ) -> Optional[dict]:
        max_retries = 5
        retry_delay = 5
        for attempt in range(max_retries):
            try:
                klines = self.client.get_historical_klines(
                    symbol, interval, limit=limit
                )
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
                    logger.error(
                        f"Rate limit exceeded for {symbol}, retrying in {retry_delay}s (attempt {attempt + 1}/{max_retries})"
                    )
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    logger.error(f"Error fetching data for {symbol}: {e}")
                    return None
        logger.error(f"Failed to fetch data for {symbol} after {max_retries} attempts")
        return None


class WaveTrendAnalyzer:
    """WaveTrend indicator analysis."""

    def __init__(self):
        self.indicators = TechnicalIndicators()
        self.data_provider = DataProvider()

    def calculate_wavetrend(
        self, high: NDArray, low: NDArray, close: NDArray, n1: int = 10, n2: int = 21
    ) -> tuple:
        try:
            ap = self.indicators.hlc3(high, low, close)
            esa = self.indicators.ema(ap, n1)
            d = self.indicators.ema(np.abs(ap - esa), n1)
            d = np.where((d == 0) | np.isnan(d), 1e-10, d)
            ci = (ap - esa) / (0.015 * d)
            wt1 = self.indicators.ema(ci, n2)
            wt2 = self.indicators.sma(wt1, 4)

            return wt1, wt2

        except Exception as e:
            logger.error(f"Error calculating WaveTrend: {e}")
            return np.array([]), np.array([])


class SignalGenerator:
    """Main signal generation logic."""

    def __init__(self):
        self.wavetrend_analyzer = WaveTrendAnalyzer()
        self.indicators = TechnicalIndicators()
        self.data_provider = DataProvider()

    @logger.catch
    def filter_1h_timeframe(self, symbol: str) -> tuple:
        try:
            data = self.data_provider.get_klines_data(symbol, "1h", 500)
            if not data:
                return [], []

            # Get WaveTrend parameters for this symbol
            n1, n2 = wavetrend_parameters.get(
                symbol, (SignalConfig.DEFAULT_WT_N1, SignalConfig.DEFAULT_WT_N2)
            )

            # Calculate WaveTrend
            wt1, _ = self.wavetrend_analyzer.calculate_wavetrend(
                data["high"], data["low"], data["close"], 10, 21
            )

            # Calculate EMA200
            ema_200 = self.indicators.ema(data["close"], 200)

            buy_signals = []
            sell_signals = []

            if self._check_buy_conditions(wt1, ema_200, data, symbol):
                buy_signals.append(symbol)

            if self._check_sell_conditions(wt1, symbol):
                sell_signals.append(symbol)

            return buy_signals, sell_signals

        except Exception as e:
            logger.error(f"Error in 1h filter for {symbol}: {e}")
            return [], []

    def _check_buy_conditions(
        self,
        wt1: NDArray,
        ema_200: NDArray,
        data: dict,
        symbol: str,
    ) -> bool:
        """Check buy conditions"""
        try:
            if len(wt1) == 0 or len(ema_200) == 0:
                return False

            wt_oversold = wt1[-1] < SignalConfig.WT_OVERSOLD_THRESHOLD
            below_ema = data["close"][-1] < ema_200[-1]

            buy_signal = wt_oversold and below_ema

            if buy_signal:
                logger.debug(f"🟢 Buy signal for {symbol}: WT1={wt1[-1]:.2f}")

            return buy_signal

        except Exception as e:
            logger.error(f"Error checking buy conditions for {symbol}: {e}")
            return False

    def _check_sell_conditions(self, wt1: NDArray, symbol: str) -> bool:
        """Check sell conditions"""
        try:
            if len(wt1) == 0:
                return False

            # Basic WaveTrend overbought condition
            sell_signal = bool(wt1[-1] > SignalConfig.WT_OVERBOUGHT_THRESHOLD)

            if sell_signal:
                logger.debug(f"🔴 Sell signal for {symbol}: WT1={wt1[-1]:.2f}")

            return sell_signal

        except Exception as e:
            logger.error(f"Error checking sell conditions for {symbol}: {e}")
            return False

    def filter_15m_timeframe(self, symbol: str) -> bool:
        """
        Filter on 15m timeframe using trend analysis.

        Args:
            symbol: Trading pair symbol

        Returns:
            bool: True if passes filter
        """
        try:
            klines = self.data_provider.client.get_klines(symbol=symbol, interval="15m")
            if not klines:
                return False

            close_prices = np.array([float(entry[4]) for entry in klines])

            # Linear regression analysis
            y_values = np.arange(len(close_prices))
            trend_line = np.poly1d(np.polyfit(y_values, close_prices, 1))(y_values)
            lower_band = trend_line * 0.99

            # Check if current price is below trend
            current_price = close_prices[-1]
            is_below_trend = current_price < lower_band[-1]

            if is_below_trend and DEBUG:
                logger.info(f"15m filter passed: {symbol}")

            return is_below_trend

        except Exception as e:
            logger.error(f"Error in 15m filter for {symbol}: {e}")
            return False

    def filter_5m_timeframe(self, symbol: str) -> bool:
        """
        Filter on 5m timeframe using trend analysis.

        Args:
            symbol: Trading pair symbol

        Returns:
            bool: True if passes filter
        """
        try:
            data = self.data_provider.get_klines_data(
                symbol=symbol, interval="5m", limit=100
            )
            if not data:
                return False

            wt1, _ = self.wavetrend_analyzer.calculate_wavetrend(
                data["high"],
                data["low"],
                data["close"],
                SignalConfig.DEFAULT_WT_N1,
                SignalConfig.DEFAULT_WT_N2,
            )

            logger.info(f"5m filter {symbol} - WT1: {wt1[-1]:.2f}")

            # Check oversold conditions
            is_oversold = wt1[-1] < SignalConfig.WT_MOMENTUM_THRESHOLD

            return is_oversold

        except Exception as e:
            logger.error(f"Error in 5m filter for {symbol}: {e}")
            return False

    def check_momentum_1m(self, symbol: str) -> bool:
        """
        Check momentum on 1m timeframe using CMO and WaveTrend.

        Args:
            symbol: Trading pair symbol

        Returns:
            bool: True if momentum conditions are met
        """
        try:
            data = self.data_provider.get_klines_data(symbol, "1m", 100)
            if not data:
                return False

            # Calculate CMO
            cmo_values = self.indicators.cmo(data["close"])

            # Calculate WaveTrend
            wt1, _ = self.wavetrend_analyzer.calculate_wavetrend(
                data["high"],
                data["low"],
                data["close"],
                SignalConfig.DEFAULT_WT_N1,
                SignalConfig.DEFAULT_WT_N2,
            )

            if len(cmo_values) == 0 or len(wt1) == 0:
                return False

            current_cmo = cmo_values[-1]
            current_wt1 = wt1[-1]

            logger.info(
                f"1m momentum {symbol} - CMO: {current_cmo:.2f}, WT1: {current_wt1:.2f}"
            )

            # Check oversold conditions
            is_oversold = (
                current_cmo < SignalConfig.CMO_OVERSOLD_THRESHOLD
                and current_wt1 < SignalConfig.WT_MOMENTUM_THRESHOLD
            )

            if is_oversold:
                logger.info(f"Oversold dip found: {symbol}")

            return is_oversold

        except Exception as e:
            logger.error(f"Error in 1m momentum check for {symbol}: {e}")
            return False


class SignalFileManager:
    """Manages signal file operations."""

    @staticmethod
    def clear_signal_files():
        """Remove existing signal files."""
        for file_path in [SIGNAL_FILE_BUY, SIGNAL_FILE_SELL]:
            if os.path.exists(file_path):
                os.remove(file_path)

    @staticmethod
    def write_buy_signals(signals: list):
        """Write buy signals to file."""
        if signals:
            os.makedirs(os.path.dirname(SIGNAL_FILE_BUY), exist_ok=True)
            with open(SIGNAL_FILE_BUY, "a+") as f:
                for sig in signals:
                    f.write(f"{sig}\n")

    @staticmethod
    def write_sell_signals(signals: list):
        """Write sell signals to file."""
        if signals:
            os.makedirs(os.path.dirname(SIGNAL_FILE_SELL), exist_ok=True)
            with open(SIGNAL_FILE_SELL, "a+") as f:
                for sig in signals:
                    f.write(f"{sig}\n")


def analyze_trading_pairs(trading_pairs: list) -> tuple:
    signal_generator = SignalGenerator()
    file_manager = SignalFileManager()

    # Clear existing signal files
    file_manager.clear_signal_files()

    # Initialize signal lists
    all_buy_signals = []
    all_sell_signals = []

    # Stage 1: 1h timeframe analysis
    stage1_buy = []
    stage1_sell = []

    for symbol in trading_pairs:
        buy_signals, sell_signals = signal_generator.filter_1h_timeframe(symbol)
        stage1_buy.extend(buy_signals)
        stage1_sell.extend(sell_signals)

    # Stage 2: 15m timeframe analysis
    stage2_symbols = []
    for symbol in stage1_buy:
        if signal_generator.filter_15m_timeframe(symbol):
            stage2_symbols.append(symbol)

    # Stage 3: 5m timeframe analysis
    stage3_symbols = []
    for symbol in stage2_symbols:
        if signal_generator.filter_5m_timeframe(symbol):
            stage3_symbols.append(symbol)

    # Stage 4: 1m momentum analysis
    for symbol in stage3_symbols:
        if signal_generator.check_momentum_1m(symbol):
            all_buy_signals.append(symbol)

    # Add sell signals from stage 1
    all_sell_signals.extend(stage1_sell)

    # Write signals to files
    file_manager.write_buy_signals(all_buy_signals)
    file_manager.write_sell_signals(all_sell_signals)

    # Log results
    if all_buy_signals:
        logger.info(
            f"{TxColors.BUY}{SIGNAL_NAME}: {all_buy_signals} - Buy Signal Detected{TxColors.DEFAULT}"
        )

    if all_sell_signals:
        logger.info(
            f"{TxColors.RED}{SIGNAL_NAME}: {all_sell_signals} - Sell Signal Detected{TxColors.DEFAULT}"
        )
    else:
        logger.info(f"{TxColors.DEFAULT}{SIGNAL_NAME}: - not enough signal to buy")

    return all_buy_signals, all_sell_signals


def load_trading_pairs() -> list:
    """Load trading pairs from file."""
    try:
        if not os.path.exists(TICKERS):
            logger.warning(f"Tickers file not found: {TICKERS}")
            return []

        with open(TICKERS) as f:
            pairs = f.read().splitlines()

        # Filter out empty lines
        pairs = [pair.strip() for pair in pairs if pair.strip()]

        return pairs

    except Exception as e:
        logger.error(f"Error loading trading pairs: {e}")
        return []


class SignalHandler:
    """Handle graceful shutdown."""

    def __init__(self):
        self.shutdown = False
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self.shutdown = True


def do_work():
    """Main work function that runs the signal analysis loop."""
    logger.info(f"{SIGNAL_NAME}: Starting signal analysis")
    signal_handler = SignalHandler()

    while not signal_handler.shutdown:
        try:
            # Check if main thread is still alive
            if not threading.main_thread().is_alive():
                logger.info("Main thread not alive, exiting")
                break

            # Load trading pairs
            trading_pairs = load_trading_pairs()

            if not trading_pairs:
                logger.warning("No trading pairs loaded, waiting...")
                time.sleep(TIME_TO_WAIT * 60)
                continue

            logger.info(f"{SIGNAL_NAME}: Analyzing {len(trading_pairs)} coins")
            logger.info(
                f"CMO_1h: {CMO_1h} | WAVETREND_1h: {WAVETREND_1h} | MACD_1h: {MACD_1h}"
            )

            # Analyze trading pairs
            buy_signals, sell_signals = analyze_trading_pairs(trading_pairs)

            logger.info(f"{SIGNAL_NAME}: {len(buy_signals)} coins with Buy Signals")
            logger.info(f"{SIGNAL_NAME}: {len(sell_signals)} coins with Sell Signals")
            logger.info(f"Waiting {TIME_TO_WAIT} minutes for next analysis")

            # Wait before next analysis
            time.sleep(TIME_TO_WAIT * 60)

        except KeyboardInterrupt:
            logger.info(f"{SIGNAL_NAME}: Received keyboard interrupt, exiting")
            break

        except Exception as e:
            logger.error(f"{SIGNAL_NAME}: Exception in do_work(): {e}")
            time.sleep(60)  # Wait 1 minute before retrying
            continue

    logger.info(f"{SIGNAL_NAME}: Signal analysis stopped")


if __name__ == "__main__":
    do_work()
