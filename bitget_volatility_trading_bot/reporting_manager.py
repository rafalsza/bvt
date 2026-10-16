# reporting_manager.py
from datetime import datetime
from typing import Dict, Any
from loguru import logger
import sqlalchemy as db


class ReportingManager:
    """Manages reporting and statistics for the trading bot."""

    def __init__(self, config: Dict[str, Any], db_interface):
        """Initialize reporting manager."""
        self.config = config
        self.db_interface = db_interface
        self.session_start_time = None
        self.session_stats = {}

        logger.info("📈 Reporting manager initialized")

    def initialize_session_stats(self):
        """Initialize session statistics."""
        try:
            self.session_start_time = datetime.now()
            self.session_stats = {
                "trades_executed": 0,
                "profit_total": 0,
                "wins": 0,
                "losses": 0,
                "start_time": self.session_start_time,
                "session_profit": 0,
            }
            logger.info("📈 Session statistics initialized")
        except Exception as e:
            logger.error(f"💥 Failed to initialize session stats: {e}")

    def generate_balance_report(
        self, portfolio_status: Dict[str, Any], current_prices: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Generate comprehensive balance report.

        Args:
            portfolio_status: Current portfolio status

        Returns:
            Dict with balance report data
        """
        try:
            if portfolio_status is None:
                logger.warning("⚠️ No portfolio_status provided, using empty data")
                portfolio_status = {
                    "active_positions": 0,
                    "total_current_value": 0,
                    "unrealized_pnl_pct": 0,
                    "unrealized_pnl": 0,
                }
            # Get portfolio statistics from database
            db_stats = self.db_interface.get_portfolio_statistics()
            db_positions = self.db_interface.get_open_positions()

            # Calculate session profit
            session_profit = self._calculate_session_profit()
            bot_profit = self.db_interface.get_total_bot_profit()

            total_exposure = portfolio_status.get("total_current_value", 0)
            unrealized_pnl_pct = portfolio_status.get("unrealized_pnl_pct", 0)
            unrealized_pnl_dollars = portfolio_status.get("unrealized_pnl", 0)

            # Generate report
            report = {
                "timestamp": datetime.now().isoformat(),
                "positions": len(db_positions),
                "total_exposure": total_exposure,
                "unrealized_pnl": unrealized_pnl_pct,
                "unrealized_pnl_dollars": unrealized_pnl_dollars,
                "positions_data": db_positions,
                "session_profit": session_profit,
                "bot_profit": bot_profit,
                "total_trades": db_stats.get("total_trades", 0),
                "winning_trades": db_stats.get("winning_trades", 0),
                "losing_trades": db_stats.get("losing_trades", 0),
                "win_rate": db_stats.get("win_rate", 0),
                "total_realized_pnl": db_stats.get("total_realized_pnl", 0),
                "best_trade": db_stats.get("best_trade", 0),
                "worst_trade": db_stats.get("worst_trade", 0),
            }

            logger.debug("📊 Balance report generated")
            return report

        except Exception as e:
            logger.error(f"💥 Error generating balance report: {e}")
            return {
                "timestamp": datetime.now().isoformat(),
                "positions": 0,
                "total_exposure": 0,
                "unrealized_pnl": 0,
                "session_profit": 0,
                "bot_profit": 0,
                "error": str(e),
            }

    def _calculate_session_profit(self) -> float:
        """
        Calculate profit/loss for current session.

        Returns:
            float: Session profit percentage
        """
        try:
            if not self.session_start_time:
                return 0.0

            # Get trades from current session
            session_query = db.text(
                """
                SELECT COALESCE(SUM(profit_dollars), 0) as session_profit
                FROM transactions 
                WHERE closed = 1 
                AND sell_time >= :session_start
            """
            )

            result = self.db_interface.connection.execute(
                session_query, {"session_start": self.session_start_time}
            ).fetchone()

            session_profit_dollars = float(result[0] if result else 0)

            # Calculate percentage based on initial capital
            initial_capital = self.config.get("TRADE_TOTAL", 100) * self.config.get(
                "TRADE_SLOTS", 5
            )
            if initial_capital > 0:
                session_profit_percentage = (
                    session_profit_dollars / initial_capital
                ) * 100
            else:
                session_profit_percentage = 0

            logger.debug(
                f"💰 Session profit calculated: {session_profit_percentage:.2f}%"
            )
            return session_profit_percentage

        except Exception as e:
            logger.error(f"💥 Error calculating session profit: {e}")
            return 0.0

    def log_error(self, error_message: str):
        """
        Log error to file and database.

        Args:
            error_message: Error message to log
        """
        try:
            # Log to file
            error_log_file = "logs/error.log"
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            with open(error_log_file, "a") as f:
                f.write(f"{timestamp} - {error_message}\n")

            logger.debug("📝 Error logged to file")

        except Exception as e:
            logger.error(f"💥 Failed to log error: {e}")

    def generate_final_report(self):
        """Generate final report when bot shuts down."""
        try:
            final_stats = self.db_interface.get_portfolio_statistics()
            session_profit = self._calculate_session_profit()

            report = {
                "session_duration": (
                    str(datetime.now() - self.session_start_time)
                    if self.session_start_time
                    else "Unknown"
                ),
                "session_profit": session_profit,
                "total_trades": final_stats.get("total_trades", 0),
                "win_rate": final_stats.get("win_rate", 0),
                "total_realized_pnl": final_stats.get("total_realized_pnl", 0),
            }

            logger.info(
                f"📊 Final Report - Session Profit: {session_profit:.2f}%, Total Trades: {report['total_trades']}"
            )

            # Save to file
            with open("logs/final_report.json", "w") as f:
                import json

                json.dump(report, f, indent=2, default=str)

        except Exception as e:
            logger.error(f"💥 Error generating final report: {e}")

    def update_session_stats(self, trade_result: Dict[str, Any]):
        """
        Update session statistics with new trade result.

        Args:
            trade_result: Result of completed trade
        """
        try:
            self.session_stats["trades_executed"] += 1

            profit = trade_result.get("profit", 0)
            if profit > 0:
                self.session_stats["wins"] += 1
            else:
                self.session_stats["losses"] += 1

            self.session_stats["profit_total"] += profit

            logger.debug("📊 Session stats updated")

        except Exception as e:
            logger.error(f"💥 Error updating session stats: {e}")
