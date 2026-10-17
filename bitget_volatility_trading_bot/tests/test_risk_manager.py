"""Tests for risk_manager.py - signal validation, cooloff, session limits."""
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from risk_manager import RiskManager


def _make_config(**overrides):
    config = {
        "SESSION_TPSL_OVERRIDE": False,
        "SESSION_TAKE_PROFIT": 5.0,
        "SESSION_STOP_LOSS": -2.0,
        "TRADE_SLOTS": 3,
        "TRADE_TOTAL": 300.0,
        "TIME_DIFFERENCE": 5,
        "COOLOFF_MULTIPLIER_LOSS": 2,
        "COOLOFF_MULTIPLIER_SMALL_PROFIT": 1.5,
    }
    config.update(overrides)
    return config


@pytest.fixture
def portfolio():
    pm = MagicMock()
    pm.get_portfolio_summary.return_value = {
        "active_positions": 0,
        "positions": [],
        "total_current_value": 0.0,
        "unrealized_pnl_pct": 0.0,
    }
    return pm


@pytest.fixture
def data_provider():
    dp = MagicMock()
    dp.get_delisted_coins.return_value = []
    return dp


@pytest.fixture
def rm(portfolio, data_provider, tmp_path):
    return RiskManager(
        _make_config(COOLOFF_FILE=str(tmp_path / "cooloffs.json")),
        portfolio_manager=portfolio,
        data_provider=data_provider,
    )


class TestValidateSignals:
    def test_empty_signals_returns_empty(self, rm):
        assert rm.validate_signals({}) == {}

    def test_buy_signal_validated_when_slots_free(self, rm):
        signals = {"BTCUSDT": {"buy_signal": "volatility_gain", "value": 1}}
        result = rm.validate_signals(signals)
        assert "BTCUSDT" in result

    def test_slot_reservation_limits_buys(self, rm):
        signals = {
            f"COIN{i}USDT": {"buy_signal": "x"}
            for i in range(5)  # 5 signals, only 3 slots
        }
        result = rm.validate_signals(signals)
        assert len(result) == 3

    def test_sell_signals_dont_consume_slots(self, rm, portfolio):
        portfolio.get_portfolio_summary.return_value["active_positions"] = 3
        signals = {"BTCUSDT": {"sell_signal": "x"}}
        result = rm.validate_signals(signals)
        assert "BTCUSDT" in result

    def test_invalid_signal_skipped(self, rm):
        signals = {"BTCUSDT": "not-a-dict", "ETHUSDT": {"buy_signal": "x"}}
        result = rm.validate_signals(signals)
        assert "BTCUSDT" not in result
        assert "ETHUSDT" in result

    def test_cooloff_blocks_buy(self, rm):
        rm.set_cooloff_period("BTCUSDT", minutes=10)
        signals = {"BTCUSDT": {"buy_signal": "x"}}
        assert rm.validate_signals(signals) == {}

    def test_delisted_coin_blocked(self, rm, data_provider):
        data_provider.get_delisted_coins.return_value = ["DELISTUSDT"]
        signals = {"DELISTUSDT": {"buy_signal": "x"}}
        assert rm.validate_signals(signals) == {}


class TestSessionLimits:
    def test_override_disabled_always_continues(self, rm):
        assert rm.check_session_limits(999.0) == "CONTINUE"

    def test_take_profit_hit(self, portfolio, data_provider):
        rm = RiskManager(
            _make_config(SESSION_TPSL_OVERRIDE=True),
            portfolio_manager=portfolio,
            data_provider=data_provider,
        )
        assert rm.check_session_limits(6.0) == "TAKE_PROFIT_HIT"
        assert rm.check_session_limits(0.0) == "CONTINUE"

    def test_stop_loss_hit(self, portfolio, data_provider):
        rm = RiskManager(
            _make_config(SESSION_TPSL_OVERRIDE=True),
            portfolio_manager=portfolio,
            data_provider=data_provider,
        )
        assert rm.check_session_limits(-3.0) == "STOP_LOSS_HIT"


class TestPositionSize:
    def test_normal_calculation(self, rm):
        assert rm.calculate_position_size(50.0, 1000.0) == pytest.approx(6.0)

    def test_capped_by_available_capital(self, rm):
        # TRADE_TOTAL=300 but only 100 available
        assert rm.calculate_position_size(10.0, 100.0) == pytest.approx(10.0)

    def test_invalid_inputs_return_zero(self, rm):
        assert rm.calculate_position_size(0.0, 100.0) == 0.0
        assert rm.calculate_position_size(50.0, -5.0) == 0.0


class TestCooloff:
    def test_cooloff_blocks_then_expires(self, rm):
        rm.set_cooloff_period("BTCUSDT", minutes=10)
        assert rm._check_cooloff_period("BTCUSDT") is False
        rm.position_cooloff["BTCUSDT"] = datetime.now() - timedelta(minutes=1)
        assert rm._check_cooloff_period("BTCUSDT") is True


class TestDailyLossLimit:
    def _stats(self, losses, pnl):
        return {"losing_trades": losses, "realized_pnl": pnl}

    def test_disabled_by_default(self, rm, portfolio):
        assert rm._check_daily_symbol_loss_limit("BTCUSDT") is True
        portfolio.db_interface.get_symbol_day_stats.assert_not_called()

    def test_blocks_after_n_losses(self, rm, portfolio):
        rm.config["MAX_LOSSES_PER_SYMBOL_PER_DAY"] = 3
        portfolio.db_interface.get_symbol_day_stats.return_value = self._stats(
            3, -10.0
        )
        assert rm._check_daily_symbol_loss_limit("UMXMUSDT") is False
        portfolio.db_interface.get_symbol_day_stats.return_value = self._stats(
            2, -10.0
        )
        assert rm._check_daily_symbol_loss_limit("UMXMUSDT") is True

    def test_blocks_on_pnl_floor(self, rm, portfolio):
        # TRADE_TOTAL=300 in fixture -> -4% floor = -12 USDT
        rm.config["SYMBOL_DAILY_LOSS_LIMIT_PCT"] = 4.0
        portfolio.db_interface.get_symbol_day_stats.return_value = self._stats(
            1, -13.0
        )
        assert rm._check_daily_symbol_loss_limit("UMXMUSDT") is False
        portfolio.db_interface.get_symbol_day_stats.return_value = self._stats(
            1, -10.0
        )
        assert rm._check_daily_symbol_loss_limit("UMXMUSDT") is True

    def test_blocks_buy_in_validate_signals(self, rm, portfolio):
        rm.config["MAX_LOSSES_PER_SYMBOL_PER_DAY"] = 1
        portfolio.db_interface.get_symbol_day_stats.return_value = self._stats(
            1, -5.0
        )
        assert rm.validate_signals({"UMXMUSDT": {"buy_signal": "x"}}) == {}

    def test_does_not_block_sells(self, rm, portfolio):
        rm.config["MAX_LOSSES_PER_SYMBOL_PER_DAY"] = 1
        portfolio.db_interface.get_symbol_day_stats.return_value = self._stats(
            9, -99.0
        )
        portfolio.get_portfolio_summary.return_value["active_positions"] = 1
        signals = {"UMXMUSDT": {"sell_signal": "x"}}
        assert "UMXMUSDT" in rm.validate_signals(signals)

    def test_adaptive_cooloff_multipliers(self, rm):
        rm.set_adaptive_cooloff("A", "LOSS")
        rm.set_adaptive_cooloff("B", "SMALL_PROFIT")
        rm.set_adaptive_cooloff("C", "PROFIT")
        remaining = {
            k: (v - datetime.now()).total_seconds() / 60
            for k, v in rm.position_cooloff.items()
        }
        assert remaining["A"] == pytest.approx(10, abs=0.1)  # 5 * 2
        # int() truncation in set_adaptive_cooloff: 5 * 1.5 -> 7
        assert remaining["B"] == pytest.approx(7, abs=0.1)
        assert remaining["C"] == pytest.approx(5, abs=0.1)


class TestSessionStats:
    def test_profit_loss_tracking(self, rm):
        rm.update_session_profit(5.0)
        rm.update_session_profit(-2.0)
        rm.update_session_profit(1.0)
        assert rm.session_profit == pytest.approx(6.0)
        assert rm.session_loss == pytest.approx(2.0)

    def test_reset_clears_state(self, rm):
        rm.update_session_profit(5.0)
        rm.set_cooloff_period("BTCUSDT", 10)
        rm.reset_session_stats()
        assert rm.session_profit == 0
        assert rm.position_cooloff == {}

    def test_risk_metrics_shape(self, rm):
        rm.update_session_profit(3.0)
        metrics = rm.get_risk_metrics()
        assert metrics["session_profit"] == 3.0
        assert metrics["net_session_profit"] == 3.0
        assert "active_cooloffs" in metrics


class TestPortfolioRiskAssessment:
    def test_low_risk_normal_portfolio(self, rm, portfolio):
        portfolio.get_portfolio_summary.return_value = {
            "active_positions": 5,
            "positions": [],
            "total_current_value": 100.0,
            "unrealized_pnl_pct": 2.0,
        }
        assert rm.assess_portfolio_risk()["risk_level"] == "LOW"

    def test_concentration_risk_few_positions(self, rm, portfolio):
        portfolio.get_portfolio_summary.return_value = {
            "active_positions": 1,
            "positions": [],
            "total_current_value": 100.0,
            "unrealized_pnl_pct": 0.0,
        }
        result = rm.assess_portfolio_risk()
        assert result["concentration_risk"] is True
        assert result["risk_level"] == "MEDIUM"
