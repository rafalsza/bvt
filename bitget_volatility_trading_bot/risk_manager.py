# risk_manager.py
from datetime import datetime, timedelta
from typing import Dict, Any
from loguru import logger


class RiskManager:
    """Manages risk parameters and session limits for trading operations."""

    def __init__(
        self, config: Dict[str, Any], portfolio_manager=None, data_provider=None
    ):
        """Initialize risk manager with configuration."""
        self.config = config
        self.portfolio_manager = portfolio_manager
        self.data_provider = data_provider
        self.session_profit = 0
        self.session_loss = 0

        self.SESSION_TPSL_OVERRIDE = config.get("SESSION_TPSL_OVERRIDE")
        self.SESSION_TAKE_PROFIT = config.get("SESSION_TAKE_PROFIT")
        self.SESSION_STOP_LOSS = config.get("SESSION_STOP_LOSS")
        self.TRADE_SLOTS = config.get("TRADE_SLOTS")
        self.TRADE_TOTAL = float(config.get("TRADE_TOTAL"))
        self.TIME_DIFFERENCE = config.get("TIME_DIFFERENCE")

        # Cooloff tracking
        self.position_cooloff = {}
        self.last_trade_times = {}

        logger.info("⚖️ Risk manager initialized")

    def validate_signals(self, signals: Dict[str, Any]) -> Dict[str, Any]:
        if not signals:
            logger.debug("⚖️ No signals to validate")
            return {}

        validated = {}

        try:
            logger.info(f"⚖️ Validating {len(signals)} signals")
            portfolio_summary = self.portfolio_manager.get_portfolio_summary()
            slots_used = portfolio_summary.get("active_positions", 0)
            max_slots = self.TRADE_SLOTS

            for coin, signal in signals.items():
                if not isinstance(signal, dict) or not coin:
                    logger.warning(
                        f"⚠️ Invalid signal for {coin}: missing or invalid data"
                    )
                    continue

                signal_type = signal.get("signal_type", "buy")
                is_sell = "sell_signal" in signal or signal_type == "sell"

                if is_sell:
                    if self._passes_all_risk_checks(coin, is_sell, portfolio_summary):
                        validated[coin] = signal
                        logger.debug(f"⚖️ Sell signal validated for {coin}")
                else:
                    available_slots = max_slots - slots_used
                    if available_slots <= 0:
                        logger.warning(
                            "⚠️ No trade slots left during validation, stopping validation process"
                        )
                        break

                    if self._passes_all_risk_checks(coin, is_sell, portfolio_summary):
                        validated[coin] = signal
                        slots_used += 1
                        logger.debug(f"⚖️ Signal validated and slot reserved for {coin}")
                    else:
                        logger.debug(f"⚖️ Signal for {coin} did not pass risk checks")

            logger.debug(f"⚖️ Validated {len(validated)} out of {len(signals)} signals")
            return validated

        except Exception as e:
            logger.error(f"💥 Error validating signals: {e}")
            return {}

    def _passes_all_risk_checks(
        self, coin: str, is_sell: bool, portfolio_summary: Dict[str, Any]
    ) -> bool:
        """
        Check if coin passes all risk validation checks.

        Args:
            coin: Trading pair symbol
            is_sell: Whether the signal is a sell
            portfolio_summary: Portfolio summary data

        Returns:
            bool: True if all checks pass
        """
        risk_checks = [
            self._check_position_size_limit(coin, portfolio_summary),
            self._check_cooloff_period(coin),
            self._check_session_limits(),
            self.check_delisting(coin),
        ]

        if not is_sell:
            risk_checks.append(self._check_trade_slots(portfolio_summary))

        return all(risk_checks)

    def check_session_limits(self, current_profit: float) -> str:
        """
        Check if session limits have been reached.

        Args:
            current_profit: Current session profit percentage

        Returns:
            str: Session status ('CONTINUE', 'TAKE_PROFIT_HIT', 'STOP_LOSS_HIT')
        """
        try:
            if not self.SESSION_TPSL_OVERRIDE:
                return "CONTINUE"

            if current_profit >= self.SESSION_TAKE_PROFIT:
                logger.warning(f"🎯 Session take profit hit: {current_profit:.2f}%")
                return "TAKE_PROFIT_HIT"
            elif current_profit <= self.SESSION_STOP_LOSS:
                logger.warning(f"🛑 Session stop loss hit: {current_profit:.2f}%")
                return "STOP_LOSS_HIT"

            return "CONTINUE"

        except Exception as e:
            logger.error(f"💥 Error checking session limits: {e}")
            return "CONTINUE"

    def calculate_position_size(
        self, coin_price: float, available_capital: float
    ) -> float:
        """Calculate position size with guaranteed float types."""
        try:
            if coin_price <= 0.0:
                logger.warning(f"⚠️ Invalid coin price: {coin_price}")
                return 0.0

            if available_capital <= 0.0:
                logger.warning(f"⚠️ Invalid available capital: {available_capital}")
                return 0.0

            trade_amount = min(self.TRADE_TOTAL, available_capital)
            position_size = trade_amount / coin_price

            logger.debug(
                f"💰 Position size calculated: {position_size:.8f} for price {coin_price}"
            )
            return position_size

        except Exception as e:
            logger.error(f"💥 Error calculating position size: {e}")
            return 0.0

    def _check_position_size_limit(
        self, coin: str, portfolio_summary: Dict[str, Any]
    ) -> bool:
        """
        Check if position size is within acceptable limits.

        Args:
            coin: Trading pair symbol

        Returns:
            bool: True if position size is acceptable
        """
        try:
            if not self.portfolio_manager:
                return False
            max_per_coin = self.TRADE_TOTAL / self.TRADE_SLOTS
            for position in portfolio_summary.get("positions", []):
                if position["symbol"] == coin and position["value"] >= max_per_coin:
                    logger.warning(
                        f"⚠️ Position size limit exceeded for {coin}: {position['value']} >= {max_per_coin}"
                    )
                    return False
            return True
        except Exception as e:
            logger.error(f"💥 Error checking position size limit for {coin}: {e}")
            return False

    def _check_cooloff_period(self, coin: str) -> bool:
        """
        Check if coin is in cooloff period.

        Args:
            coin: Trading pair symbol

        Returns:
            bool: True if coin is not in cooloff period
        """
        try:
            current_time = datetime.now()

            if coin in self.position_cooloff:
                cooloff_end = self.position_cooloff[coin]
                if current_time < cooloff_end:
                    remaining = cooloff_end - current_time
                    logger.debug(
                        f"⏰ {coin} in cooloff for {remaining.total_seconds():.0f} seconds"
                    )
                    return False

            return True

        except Exception as e:
            logger.error(f"💥 Error checking cooloff period for {coin}: {e}")
            return False

    def _check_session_limits(self) -> bool:
        """
        Check if session limits allow new trades.

        Returns:
            bool: True if session limits allow trading
        """
        try:
            if not self.SESSION_TPSL_OVERRIDE:
                return True

            # Check if we're close to session limits
            current_profit = self.session_profit - self.session_loss

            # Don't open new positions if close to stop loss
            if current_profit <= (self.SESSION_STOP_LOSS * 0.8):
                logger.warning(f"⚠️ Close to session stop loss: {current_profit:.2f}%")
                return False

            # Don't open new positions if take profit is very close
            if current_profit >= (self.SESSION_TAKE_PROFIT * 0.9):
                logger.warning(f"⚠️ Close to session take profit: {current_profit:.2f}%")
                return False

            return True

        except Exception as e:
            logger.error(f"💥 Error checking session limits: {e}")
            return True

    def _check_trade_slots(self, portfolio_summary: Dict[str, Any]) -> bool:
        """Check if there are available trade slots using portfolio data."""
        try:
            if not self.portfolio_manager:
                return False

            active_positions = portfolio_summary.get("active_positions", 0)

            available_slots = self.TRADE_SLOTS - active_positions

            if available_slots <= 0:
                logger.warning(
                    f"⚠️ No trade slots available: {active_positions}/{self.TRADE_SLOTS}"
                )
                return False

            logger.debug(
                f"📊 Available trade slots: {available_slots}/{self.TRADE_SLOTS}"
            )
            return True

        except Exception as e:
            logger.error(f"💥 Error checking trade slots: {e}")
            return False

    def check_delisting(self, coin: str) -> bool:
        """
        Check if a coin is scheduled for delisting.

        Args:
            coin (str): The trading pair symbol to check

        Returns:
            bool: True if the coin is scheduled for delisting, False otherwise
        """
        delisted_coins = self.data_provider.get_delisted_coins()
        is_delisted = coin in delisted_coins

        if is_delisted:
            logger.debug(f"⚠️ Coin {coin} is scheduled for delisting")

        return not is_delisted

    def set_cooloff_period(self, coin: str, minutes: int = None):
        """
        Set cooloff period for a coin.

        Args:
            coin: Trading pair symbol
            minutes: Cooloff period in minutes (default: TIME_DIFFERENCE)
        """
        try:
            if minutes is None:
                minutes = self.TIME_DIFFERENCE

            cooloff_end = datetime.now() + timedelta(minutes=minutes)
            self.position_cooloff[coin] = cooloff_end

            logger.debug(f"⏰ Cooloff set for {coin}: {minutes} minutes")

        except Exception as e:
            logger.error(f"💥 Error setting cooloff for {coin}: {e}")

    def set_adaptive_cooloff(self, coin: str, trade_result: str):
        """
        Set adaptive cooloff period based on trade result.

        Args:
            coin: Trading pair symbol
            trade_result: Result of the trade ("LOSS", "SMALL_PROFIT", "PROFIT", etc.)
        """
        try:
            base_cooloff = self.TIME_DIFFERENCE
            loss_multiplier = self.config.get("COOLOFF_MULTIPLIER_LOSS", 2)
            small_profit_multiplier = self.config.get(
                "COOLOFF_MULTIPLIER_SMALL_PROFIT", 1.5
            )

            if trade_result == "LOSS":
                cooloff_minutes = base_cooloff * loss_multiplier
            elif trade_result == "SMALL_PROFIT":
                cooloff_minutes = base_cooloff * small_profit_multiplier
            else:
                cooloff_minutes = base_cooloff

            self.set_cooloff_period(coin, int(cooloff_minutes))

            logger.info(
                f"🎯 Adaptive cooloff set for {coin}: {cooloff_minutes} minutes (result: {trade_result})"
            )

        except Exception as e:
            logger.error(f"💥 Error setting adaptive cooloff for {coin}: {e}")

    def update_session_profit(self, profit: float):
        """
        Update session profit tracking.

        Args:
            profit: Profit/loss amount to add
        """
        try:
            if profit > 0:
                self.session_profit += profit
            else:
                self.session_loss += abs(profit)

            logger.debug(
                f"💰 Session updated - Profit: {self.session_profit:.2f}, Loss: {self.session_loss:.2f}"
            )

        except Exception as e:
            logger.error(f"💥 Error updating session profit: {e}")

    def get_risk_metrics(self) -> Dict[str, Any]:
        """
        Get current risk metrics and status.

        Returns:
            Dict: Risk metrics and status
        """
        try:
            current_profit = self.session_profit - self.session_loss

            return {
                "session_profit": self.session_profit,
                "session_loss": self.session_loss,
                "net_session_profit": current_profit,
                "session_tpsl_override": self.SESSION_TPSL_OVERRIDE,
                "session_take_profit": self.SESSION_TAKE_PROFIT,
                "session_stop_loss": self.SESSION_STOP_LOSS,
                "active_cooloffs": len(self.position_cooloff),
                "cooloff_coins": list(self.position_cooloff.keys()),
            }

        except Exception as e:
            logger.error(f"💥 Error getting risk metrics: {e}")
            return {}

    def reset_session_stats(self):
        """Reset session statistics."""
        try:
            self.session_profit = 0
            self.session_loss = 0
            self.position_cooloff.clear()
            self.last_trade_times.clear()

            logger.info("⚖️ Session statistics reset")

        except Exception as e:
            logger.error(f"💥 Error resetting session stats: {e}")

    def assess_portfolio_risk(self) -> Dict[str, Any]:
        """Assess current portfolio risk using portfolio summary."""
        try:
            portfolio_summary = self.portfolio_manager.get_portfolio_summary()

            risk_assessment = {
                "risk_level": "LOW",
                "concentration_risk": False,
                "exposure_risk": False,
                "performance_risk": False,
            }

            # Check concentration risk
            min_positions = self.config.get("MIN_POSITIONS_CONCENTRATION", 3)
            if portfolio_summary["active_positions"] < min_positions:
                risk_assessment["concentration_risk"] = True
                risk_assessment["risk_level"] = "MEDIUM"

            # Check exposure risk
            max_exposure = self.config.get("MAX_PORTFOLIO_VALUE", self.TRADE_TOTAL * 2)
            if portfolio_summary["total_current_value"] > max_exposure:
                risk_assessment["exposure_risk"] = True
                risk_assessment["risk_level"] = "HIGH"

            # Check performance risk
            performance_threshold = self.config.get("PERFORMANCE_RISK_THRESHOLD", -15)
            if portfolio_summary["unrealized_pnl_pct"] < -performance_threshold:
                risk_assessment["performance_risk"] = True
                risk_assessment["risk_level"] = "HIGH"

            return risk_assessment

        except Exception as e:
            logger.error(f"💥 Error assessing portfolio risk: {e}")
            return {"risk_level": "UNKNOWN"}
