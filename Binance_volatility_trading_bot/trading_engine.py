# trading_engine.py
from typing import Dict, Any
from loguru import logger
from datetime import datetime


class TradingEngine:
    """Main trading engine that coordinates all trading operations."""

    def __init__(
        self, config: Dict[str, Any], data_provider, risk_manager, portfolio_manager
    ):
        """Initialize trading engine with all components."""
        self.config = config
        self.data_provider = data_provider
        self.risk_manager = risk_manager
        self.portfolio_manager = portfolio_manager
        self.is_running = True

        logger.info("🏭 Trading engine initialized")

    def execute_trading_cycle(self):
        """Execute a single trading cycle with proper signal handling."""
        try:
            logger.debug("🔄 Executing trading cycle")

            # Get trading signals from data provider
            signals = self.data_provider.get_trading_signals()

            if not signals:
                logger.debug("📊 No trading signals detected")
                return

            logger.info(f"📊 Found {len(signals)} potential signals")

            # Validate signals through risk manager
            validated_signals = self.risk_manager.validate_signals(signals)

            if not validated_signals:
                logger.debug("⚖️ No signals passed risk validation")
                return

            logger.info(f"⚖️ {len(validated_signals)} signals validated")

            # Execute trades for validated signals
            self._execute_validated_signals(validated_signals)

        except Exception as e:
            logger.error(f"💥 Error in trading cycle: {e}")
            self.handle_error(e)

    def _execute_validated_signals(self, validated_signals: Dict[str, Any]):
        """
        Execute trades for validated signals.

        Args:
            validated_signals: Dictionary of validated trading signals
        """
        try:
            for symbol, signal in validated_signals.items():
                try:
                    # Add symbol to signal data
                    signal["symbol"] = symbol

                    # Determine action based on signal type
                    action = self._determine_action(signal)

                    # Check if trade should be executed based on portfolio status
                    if not self._should_execute_trade():
                        logger.warning(
                            f"⏸️  Trade execution blocked for {symbol} - portfolio conditions not met"
                        )
                        continue

                    if action == "BUY":
                        self._execute_buy_signal(symbol, signal)
                    elif action == "SELL":
                        self._execute_sell_signal(symbol, signal)
                    else:
                        logger.warning(f"⚠️ Unknown action for {symbol}: {action}")

                except Exception as e:
                    logger.error(f"💥 Failed to execute signal for {symbol}: {e}")
                    continue

        except Exception as e:
            logger.error(f"💥 Error executing validated signals: {e}")

    def _determine_action(self, signal: Dict[str, Any]) -> str:
        """
        Determine trading action from signal.

        Args:
            signal: Trading signal data

        Returns:
            str: Trading action ('BUY', 'SELL', or 'UNKNOWN')
        """
        # Check if action is explicitly defined
        if "action" in signal:
            return signal["action"].upper()

        # Check for buy signal indicators
        if signal.get("buy_signal"):
            return "BUY"

        # Check for sell signal indicators
        if signal.get("sell_signal"):
            return "SELL"

        # Default to BUY for volatility signals (most common case)
        if signal.get("buy_signal") or signal.get("gain"):
            return "BUY"

        logger.warning(f"⚠️ Could not determine action from signal: {signal}")
        return "UNKNOWN"

    def _execute_buy_signal(self, symbol: str, signal: Dict[str, Any]):
        """
        Execute buy order for a signal.

        Args:
            symbol: Trading pair symbol
            signal: Trading signal data
        """
        try:
            # Check if we already have this position
            current_positions = self.portfolio_manager.coins_bought
            if symbol in current_positions:
                logger.warning(f"⚠️ Already have position in {symbol}, skipping buy")
                return

            # Execute buy order
            self.portfolio_manager.execute_buy(signal)
            logger.info(f"🟢 Buy signal executed for {symbol}")

            # Set cooloff period for this symbol
            self.risk_manager.set_adaptive_cooloff(symbol, "NORMAL")

            # Update risk manager with trade info
            self.risk_manager.last_trade_times[symbol] = datetime.now()

        except Exception as e:
            logger.error(f"💥 Failed to execute buy for {symbol}: {e}")

    def _execute_sell_signal(self, symbol: str, signal: Dict[str, Any]):
        """Execute sell order with result tracking."""
        try:
            # Check if we have this position
            current_positions = self.portfolio_manager.coins_bought
            if symbol not in current_positions:
                logger.warning(f"⚠️ No position found for {symbol}, skipping sell")
                return

            # Determine sell reason
            sell_reason = signal.get("sell_reason", "External signal")

            # Execute sell order
            sell_result = self.portfolio_manager.execute_sell(symbol, sell_reason)

            if sell_result and sell_result.get("success"):
                logger.info(f"🔴 Sell signal executed for {symbol}")

                # Determine trade result based on P&L
                profit_pct = sell_result.get("profit_pct", 0)
                if profit_pct < -5:
                    trade_result = "LOSS"
                elif profit_pct < 2:
                    trade_result = "SMALL_PROFIT"
                else:
                    trade_result = "PROFIT"

                # Set adaptive cooloff based on result
                self.risk_manager.set_adaptive_cooloff(symbol, trade_result)

                # Update session profit tracking
                profit = sell_result.get("profit", 0)
                self.risk_manager.update_session_profit(profit)

        except Exception as e:
            logger.error(f"💥 Failed to execute sell for {symbol}: {e}")

    def handle_error(self, exception: Exception):
        """
        Handle trading engine errors with appropriate recovery strategies.

        Args:
            exception: The exception that occurred
        """
        error_type = type(exception).__name__
        error_message = str(exception)

        logger.error(f"🏭 Trading Engine Error: {error_type} - {error_message}")

        # Handle specific error types
        if isinstance(exception, ConnectionError):
            logger.warning("🌐 Connection error detected - continuing with next cycle")

        elif isinstance(exception, ValueError):
            logger.warning("📊 Data validation error - continuing with next cycle")

        elif "BinanceAPI" in error_type:
            logger.warning("🔴 Binance API error - implementing backoff")
            # Could add backoff logic here

        else:
            logger.warning("⚠️ General error - continuing operation")

        # For critical errors, stop the engine
        critical_errors = ["BinanceAPIException", "AuthenticationError"]
        if any(critical in error_type for critical in critical_errors):
            logger.critical("🚨 Critical error detected - stopping trading engine")
            self.is_running = False

    def stop(self):
        """Stop the trading engine gracefully."""
        try:
            logger.info("🛑 Stopping trading engine...")
            self.is_running = False

            # Perform any cleanup operations here
            logger.info("🛑 Trading engine stopped")

        except Exception as e:
            logger.error(f"💥 Error stopping trading engine: {e}")

    def get_engine_status(self) -> Dict[str, Any]:
        """
        Get current status of the trading engine.

        Returns:
            Dict: Engine status information
        """
        try:
            return {
                "is_running": self.is_running,
                "components_initialized": all(
                    [
                        self.data_provider is not None,
                        self.risk_manager is not None,
                        self.portfolio_manager is not None,
                    ]
                ),
                "last_cycle_time": getattr(self, "last_cycle_time", None),
            }

        except Exception as e:
            logger.error(f"💥 Error getting engine status: {e}")
            return {"is_running": False, "error": str(e)}

    def force_sell_all(self, reason: str = "Force sell all"):
        """
        Force sell all positions (emergency function).

        Args:
            reason: Reason for force selling
        """
        try:
            logger.warning(f"🚨 Force selling all positions: {reason}")
            self.portfolio_manager.sell_all_positions(reason)
            logger.info("🚨 All positions force sold")

        except Exception as e:
            logger.error(f"💥 Error force selling all positions: {e}")

    def _should_execute_trade(self) -> bool:
        """Check if trade should be executed based on portfolio status."""
        try:
            portfolio_summary = self.portfolio_manager.get_portfolio_summary()

            # Check available slots
            if portfolio_summary["available_slots"] <= 0:
                logger.warning(
                    f"⚠️ No available trade slots ({portfolio_summary['active_positions']}/{self.config.get('TRADE_SLOTS')})"
                )
                return False

            # Check portfolio exposure
            max_exposure = self.config.get("MAX_PORTFOLIO_EXPOSURE", 10000)
            if portfolio_summary["total_current_value"] >= max_exposure:
                logger.warning(
                    f"⚠️ Portfolio exposure limit reached: {portfolio_summary['total_current_value']:.2f}"
                )
                return False

            # Check unrealized P&L
            if (
                portfolio_summary["unrealized_pnl_pct"] < -20
            ):  # Stop trading if down 20%
                logger.warning(
                    f"⚠️ Portfolio down {portfolio_summary['unrealized_pnl_pct']:.2f}% - pausing trades"
                )
                return False

            return True

        except Exception as e:
            logger.error(f"💥 Error checking trade conditions: {e}")
            return False
