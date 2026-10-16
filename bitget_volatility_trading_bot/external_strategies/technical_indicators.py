# technical_indicators.py
from numpy.typing import NDArray
import numpy as np
from sklearn.linear_model import LinearRegression
from loguru import logger

class TechnicalIndicators:
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
        return (high + low + close) / 3.0

    @staticmethod
    def cmo(data: NDArray, period: int = 14) -> NDArray:
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
                cmo_values[i] = 100 * (sum_gains - sum_losses) / (sum_gains + sum_losses)
            else:
                cmo_values[i] = 0
        return cmo_values

    @staticmethod
    def regression_channel(data):
        try:
            y = data["close"]
            X = np.arange(len(y)).reshape(-1, 1)
            model = LinearRegression()
            model.fit(X, y)
            linear_regression = model.predict(X)
            residuals = y - linear_regression
            std = np.std(residuals)
            linear_upper = linear_regression + 2 * std
            linear_lower = linear_regression - 2 * std
            return linear_regression, linear_lower, linear_upper
        except Exception as e:
            logger.error(f"Regression channel calculation error: {e}")
            return np.array([]), np.array([]), np.array([])

    @staticmethod
    def wavetrend(high: NDArray, low: NDArray, close: NDArray, n1: int = 10, n2: int = 21) -> tuple:
        try:
            ap = TechnicalIndicators.hlc3(high, low, close)
            esa = TechnicalIndicators.ema(ap, n1)
            d = TechnicalIndicators.ema(np.abs(ap - esa), n1)
            d = np.where((d == 0) | np.isnan(d), 1e-10, d)
            ci = (ap - esa) / (0.015 * d)
            wt1 = TechnicalIndicators.ema(ci, n2)
            wt2 = TechnicalIndicators.sma(wt1, 4)
            return wt1, wt2
        except Exception as e:
            logger.error(f"Error calculating WaveTrend: {e}")
            return np.array([]), np.array([])