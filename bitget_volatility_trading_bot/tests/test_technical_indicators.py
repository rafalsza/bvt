"""Tests for external_strategies/technical_indicators.py - pure math, no mocks."""
import numpy as np
import pytest

from external_strategies.technical_indicators import TechnicalIndicators as TI


class TestEma:
    def test_constant_series_returns_constant(self):
        data = np.full(20, 42.0)
        result = TI.ema(data, 10)
        np.testing.assert_allclose(result, 42.0)

    def test_ema_first_value_is_seed(self):
        data = np.array([1.0, 2.0, 3.0])
        result = TI.ema(data, 2)
        assert result[0] == 1.0
        # alpha = 2/3: ema[1] = 2/3*2 + 1/3*1 = 5/3
        assert result[1] == pytest.approx(5 / 3)

    def test_ema_reacts_faster_than_sma(self):
        data = np.concatenate([np.full(10, 10.0), np.full(10, 20.0)])
        ema = TI.ema(data, 5)
        # after the jump, EMA should already exceed 19 by the last point
        assert ema[-1] > 19.0


class TestSma:
    def test_head_is_nan(self):
        data = np.arange(10.0)
        result = TI.sma(data, 4)
        assert np.all(np.isnan(result[:3]))
        assert not np.isnan(result[3])

    def test_values_correct(self):
        data = np.arange(1.0, 6.0)  # 1..5
        result = TI.sma(data, 2)
        np.testing.assert_allclose(result[1:], [1.5, 2.5, 3.5, 4.5])


class TestHlc3:
    def test_typical_price(self):
        h = np.array([10.0])
        l = np.array([8.0])
        c = np.array([9.0])
        assert TI.hlc3(h, l, c)[0] == pytest.approx(9.0)


class TestCmo:
    def test_monotonic_rise_is_100(self):
        data = np.arange(30.0)  # strictly increasing
        result = TI.cmo(data, 14)
        np.testing.assert_allclose(result[~np.isnan(result)], 100.0)

    def test_monotonic_fall_is_minus_100(self):
        data = np.arange(30.0)[::-1]
        result = TI.cmo(data, 14)
        np.testing.assert_allclose(result[~np.isnan(result)], -100.0)

    def test_flat_series_is_zero(self):
        data = np.full(30, 5.0)
        result = TI.cmo(data, 14)
        np.testing.assert_allclose(result[~np.isnan(result)], 0.0)

    def test_short_series_all_nan(self):
        data = np.arange(5.0)
        result = TI.cmo(data, 14)
        assert np.all(np.isnan(result))


class TestRegressionChannel:
    def test_perfect_line_has_zero_width_channel(self):
        x = np.arange(50, dtype=float)
        data = {"close": 2 * x + 5}
        mid, lower, upper = TI.regression_channel(data)
        np.testing.assert_allclose(mid, 2 * x + 5, atol=1e-6)
        np.testing.assert_allclose(upper - mid, np.zeros(50), atol=1e-6)

    def test_bad_input_returns_empty_arrays(self):
        mid, lower, upper = TI.regression_channel({"no_close": []})
        assert len(mid) == 0 and len(lower) == 0 and len(upper) == 0


class TestWavetrend:
    def test_output_shapes(self):
        rng = np.random.default_rng(42)
        n = 100
        close = 100 + np.cumsum(rng.normal(0, 1, n))
        high = close + 1
        low = close - 1
        wt1, wt2 = TI.wavetrend(high, low, close)
        assert wt1.shape == (n,)
        assert wt2.shape == (n,)
        # wt2 is SMA(4) of wt1 -> first 3 entries NaN
        assert np.all(np.isnan(wt2[:3]))

    def test_flat_input_does_not_divide_by_zero(self):
        close = np.full(60, 10.0)
        wt1, wt2 = TI.wavetrend(close, close, close)
        assert len(wt1) == 60
        assert np.all(np.isfinite(wt1))
