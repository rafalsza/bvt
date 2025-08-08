# Standard library imports
import time
import sys
from pathlib import Path
from datetime import datetime

# Third-party imports
from colorama import init, Fore, Style
from loguru import logger

# Binance API imports
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceOrderException
from requests.exceptions import ReadTimeout, ConnectionError, RequestException

# Local imports
from configuration_manager import (
    ConfigurationManager,
    ConfigurationError,
    CredentialsError,
    ConfigurationFileNotFoundError,
    CredentialsFileNotFoundError,
    IncompleteCredentialsError,
)
from data_provider import DataProvider
from risk_manager import RiskManager
from portfolio_manager import PortfolioManager
from reporting_manager import ReportingManager
from notification_manager import NotificationManager
from trading_engine import TradingEngine
from helpers.db_interface import DbInterface
from helpers.handle_creds import test_api_key
from globals import user_data_path

# Initialize colorama for colored console output
init(autoreset=True)


# Custom exceptions for better error handling
class APIPermissionError(Exception):
    """Raised when API key lacks required permissions."""

    pass


class APIConnectionError(Exception):
    """Raised when API connection fails."""

    pass


class TradingBotError(Exception):
    """Base exception for trading bot errors."""

    pass


class BinanceVolatilityBot:
    """
    Main trading bot class for Binance volatility-based cryptocurrency trading.

    This bot monitors cryptocurrency price movements and executes trades
    based on volatility patterns and external signals using a modular architecture.
    """

    def __init__(self):
        """
        Initialize the Binance Volatility Bot with all necessary components.

        Sets up configuration, API client, database interface, and all trading modules
        in the correct order to ensure proper dependency injection.
        """
        # Configure Loguru logging
        self._setup_logging()

        logger.info("🚀 Initializing Binance Volatility Bot...")

        try:
            # Initialize configuration manager with proper file paths
            config_file = f"{user_data_path}/config.yml"
            creds_file = f"{user_data_path}/creds.yml"
            self.config_manager = ConfigurationManager(config_file, creds_file)

            # Validate configuration
            self.config_manager.validate_configuration()

            self.config = self.config_manager.get_trading_config()
            self.script_config = self.config_manager.get_script_options()
            logger.success("✅ Configuration loaded and validated successfully")

            # Initialize Binance API client with credentials
            api_key, api_secret = self.config_manager.get_api_credentials()
            self.client = Client(api_key, api_secret)
            logger.info("🔑 Binance API client initialized")

            # Initialize database interface
            self.db_interface = DbInterface(
                self.config_manager.get_db_filename(), self.config
            )
            logger.info(
                f"💾 Database interface initialized: {self.config_manager.get_db_filename()}"
            )

            # Initialize core trading components
            self._initialize_trading_components()

            logger.success("🎯 All components initialized successfully")

            self.shutdown_requested = False
            self.trading_paused = False
            self.start_time = datetime.now()

        except (ConfigurationFileNotFoundError, CredentialsFileNotFoundError) as e:
            logger.error(f"📁 Configuration file missing: {e}")
            print(f"{Fore.RED}Configuration Error: {e}{Style.RESET_ALL}")
            raise

        except IncompleteCredentialsError as e:
            logger.error(f"🔐 Incomplete credentials: {e}")
            print(f"{Fore.RED}Credentials Error: {e}{Style.RESET_ALL}")
            raise

        except (ConfigurationError, CredentialsError) as e:
            logger.error(f"⚙️ Configuration error: {e}")
            print(f"{Fore.RED}Configuration Error: {e}{Style.RESET_ALL}")
            raise

        except Exception as e:
            logger.exception(f"💥 Failed to initialize bot: {e}")
            raise

    def _setup_logging(self):
        """
        Configure Loguru logging with multiple outputs and formatting.
        """
        # Remove default handler
        logger.remove()

        # Create logs directory if it doesn't exist
        Path("logs").mkdir(exist_ok=True)

        # Console output with colors and icons
        logger.add(
            sys.stdout,
            level="INFO",
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>",
            colorize=True,
        )

        # Debug log file with detailed information
        logger.add(
            "logs/trading_bot_debug.log",
            level="DEBUG",
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
            rotation="10 MB",
            retention="7 days",
            compression="zip",
        )

        # Error log file for critical issues
        logger.add(
            "logs/trading_bot_errors.log",
            level="ERROR",
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message} | {extra}",
            rotation="5 MB",
            retention="30 days",
            compression="zip",
        )

        # Trading operations log
        logger.add(
            "logs/trading_operations.log",
            level="INFO",
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
            filter=lambda record: "trade" in record["message"].lower()
            or "buy" in record["message"].lower()
            or "sell" in record["message"].lower(),
            rotation="1 day",
            retention="30 days",
        )

    def _initialize_trading_components(self):
        """
        Initialize all trading-related components with proper dependency injection.

        Creates instances of data provider, risk manager, portfolio manager,
        reporting manager, notification manager, and trading engine.
        """
        try:
            logger.debug("🔧 Initializing trading components...")

            # Data provider for market data and price information
            self.data_provider = DataProvider(self.client, self.config)
            logger.debug("📊 Data provider initialized")

            # Portfolio management for trade execution and position tracking
            self.portfolio_manager = PortfolioManager(
                self.client,
                self.config,
                self.script_config,
                self.db_interface,
                self.data_provider,
            )
            logger.debug("💼 Portfolio manager initialized")

            # Risk management for position sizing and limits
            self.risk_manager = RiskManager(self.config, self.portfolio_manager)
            logger.debug("⚖️ Risk manager initialized")

            # Reporting for performance tracking and analytics
            self.reporting_manager = ReportingManager(self.config, self.db_interface)
            logger.debug("📈 Reporting manager initialized")

            # Notification system for alerts and updates
            self.notification_manager = NotificationManager(
                self.script_config,
                self.db_interface,
                self.portfolio_manager,
                self.data_provider,
                self.reporting_manager,
                self.config_manager,
                bot_instance=self,
            )
            logger.debug("🔔 Notification manager initialized")
            self.portfolio_manager.notification_manager = self.notification_manager

            # Main trading engine that coordinates all components
            self.trading_engine = TradingEngine(
                self.config,
                self.data_provider,
                self.risk_manager,
                self.portfolio_manager,
            )
            logger.debug("🏭 Trading engine initialized")

            logger.success("✅ All trading components initialized successfully")

        except Exception as e:
            logger.exception(f"❌ Failed to initialize trading components: {e}")
            raise

    @logger.catch
    def run(self):
        """
        Main execution loop for the trading bot.

        Handles initialization, main trading loop, error recovery,
        and graceful shutdown procedures.
        """
        logger.info(
            f"{Fore.GREEN}🚀 Starting Binance Volatility Bot...{Style.RESET_ALL}"
        )
        logger.info("🎬 Starting main trading loop")

        try:
            # Initialize all components and verify connections
            self._initialize_components()

            # Send startup notification
            self.notification_manager.send_bot_startup_notification()

            # Main trading loop
            while self.trading_engine.is_running and not self.shutdown_requested:
                try:
                    # Check shutdown flag at start of each cycle
                    if self.shutdown_requested:
                        logger.info("🛑 Shutdown requested - breaking main loop")
                        break

                    if not getattr(self, "trading_paused", False):
                        self._execute_trading_cycle()
                    else:
                        logger.debug("⏸️ Trading paused - skipping cycle")

                    # Generate and process reports
                    self._process_reports()

                    # Check session limits and trading rules
                    if self._check_session_limits():
                        break

                    # Check shutdown flag before sleep
                    if self.shutdown_requested:
                        logger.info("🛑 Shutdown requested - skipping sleep")
                        break

                    # Wait before next cycle
                    cycle_interval = self.config.get("cycle_interval", 60)
                    logger.debug(
                        f"⏱️ Waiting {cycle_interval} seconds before next cycle"
                    )

                    for _ in range(cycle_interval):
                        if self.shutdown_requested:
                            logger.info("🛑 Shutdown requested during sleep - breaking")
                            break
                        time.sleep(1)

                except BinanceAPIException as e:
                    self._handle_binance_api_error(e)

                except (ConnectionError, RequestException) as e:
                    self._handle_network_error(e)

                except Exception as e:
                    self._handle_general_error(e)

        except KeyboardInterrupt:
            logger.warning("⏹️ Received keyboard interrupt - initiating shutdown")
            self.trading_engine.is_running = False
            self.shutdown_requested = True

        except SystemExit:
            logger.info("🛑 System exit requested - initiating shutdown")
            self.shutdown_requested = True
            raise

        except Exception as e:
            logger.critical(f"💥 Critical error in main loop: {e}")
            self._handle_critical_error(e)
            raise

        finally:
            self._cleanup()

    @logger.catch
    def _execute_trading_cycle(self):
        """
        Execute a single trading cycle including signal detection and trade execution.

        Raises:
            BinanceAPIException: When Binance API calls fail
            ConnectionError: When network connectivity issues occur
        """
        try:
            logger.debug("🔄 Executing trading cycle")
            self._update_positions_details()
            self.trading_engine.execute_trading_cycle()

        except BinanceAPIException as e:
            logger.error(f"🔴 Binance API error during trading cycle: {e}")
            raise

        except Exception as e:
            logger.error(f"💥 Error in trading cycle execution: {e}")
            raise

    def _update_positions_details(self):
        """Update current prices for all open positions."""
        try:
            if self.portfolio_manager.has_open_positions():
                logger.debug("💰 Updating position prices...")
                self.portfolio_manager.update_open_positions_details()
                logger.debug("✅ Position prices updated")
            else:
                logger.debug("📊 No open positions to update")
        except Exception as e:
            logger.error(f"💥 Error updating position prices: {e}")

    def _process_reports(self):
        """Generate portfolio reports and send notifications."""
        try:
            portfolio_summary = self.portfolio_manager.get_portfolio_summary()
            current_prices = self.data_provider.get_price()

            # Generate report using summary
            balance_report = self.reporting_manager.generate_balance_report(
                portfolio_summary, current_prices
            )
            # Log portfolio manager data
            logger.info(
                f"📊 Portfolio: {portfolio_summary.get('active_positions', 0)} positions, "
                f"P&L: {portfolio_summary.get('unrealized_pnl_pct', 0):.2f}%, "
                f"Win Rate: {balance_report.get('win_rate', 0):.1f}%"
            )

            # Send notifications
            self.notification_manager.send_balance_update(balance_report)

        except Exception as e:
            logger.error(f"📈 Error processing reports: {e}")

    def _check_session_limits(self) -> bool:
        """
        Check if session limits have been reached.

        Returns:
            bool: True if session should be terminated, False otherwise
        """
        try:
            # Get current session profit from latest report
            portfolio_status = self.portfolio_manager.get_portfolio_status()
            current_prices = self.data_provider.get_price()
            report = self.reporting_manager.generate_balance_report(
                portfolio_status, current_prices
            )

            # Check session limits
            session_status = self.risk_manager.check_session_limits(
                report.get("session_profit", 0)
            )

            if session_status != "CONTINUE":
                self._handle_session_limit(session_status)
                return True

            return False

        except Exception as e:
            logger.error(f"⚖️ Error checking session limits: {e}")
            return False

    def _initialize_components(self):
        """
        Initialize and verify all bot components.

        Tests API connectivity, loads historical data, and prepares
        all systems for trading operations.

        Raises:
            APIConnectionError: When API connection fails
            Exception: When component initialization fails
        """
        try:
            logger.info("🔧 Initializing bot components...")

            # Test API connection first
            self._test_api_connection()

            # Initialize data provider with historical data
            self.data_provider.initialize_historical_data()
            logger.info("📊 Historical data initialized")

            # Seed initial prices
            self.data_provider.get_price(add_to_historical=True)

            # Load existing open positions
            self.portfolio_manager.load_open_positions()
            logger.info("💼 Open positions loaded")

            # Initialize session statistics
            self.reporting_manager.initialize_session_stats()

            logger.success("✅ All components initialized successfully")

        except Exception as e:
            logger.exception(f"💥 Component initialization failed: {e}")
            raise

    def _test_api_connection(self):
        """
        Test connection to Binance API and verify credentials.

        Raises:
            BinanceAPIException: When Binance API returns an error
            APIConnectionError: When network connection fails
            APIPermissionError: When API key lacks trading permissions
            ValueError: When API response format is invalid
        """
        try:
            logger.info("🔍 Testing Binance API connection...")
            success, message = test_api_key(self.client, BinanceAPIException)
            if not success:
                raise APIConnectionError(f"API key validation failed: {message}")

            # Get account info for additional permission checks
            account_info = self.client.get_account()

            # Validate response structure
            if not account_info or not isinstance(account_info, dict):
                raise ValueError("Invalid API response - check API configuration")

            # Check trading permissions
            can_trade = account_info.get("canTrade", False)
            if not can_trade:
                permissions = account_info.get("permissions", [])
                raise APIPermissionError(
                    f"API key lacks trading permissions. "
                    f"Current permissions: {permissions}. "
                    f"Please enable SPOT trading in your Binance API settings."
                )

            # Check account status
            account_status = account_info.get("accountType")
            if account_status != "SPOT":
                raise APIPermissionError(
                    f"Account type '{account_status}' not supported for spot trading"
                )

            logger.success(f"🔗 API connection successful - {message}")
            logger.info(f"Account type: {account_status}, Trading enabled: {can_trade}")

        except BinanceAPIException as e:
            error_msg = f"Binance API error [{getattr(e, 'code', 'Unknown')}]: {e}"
            logger.error(f"🔴 {error_msg}")
            raise APIConnectionError(error_msg) from e

        except (APIPermissionError, ValueError):
            # Re-raise our custom exceptions
            raise

        except (ConnectionError, RequestException) as e:
            error_msg = f"Network error: {type(e).__name__} - {e}"
            logger.error(f"🌐 {error_msg}")
            raise APIConnectionError(error_msg) from e

        except Exception as e:
            error_msg = f"Unexpected API test failure: {type(e).__name__} - {e}"
            logger.exception(f"💥 {error_msg}")
            raise APIConnectionError(error_msg) from e

    def _handle_session_limit(self, session_status: str):
        """
        Handle session limit events (take profit or stop loss).

        Args:
            session_status (str): Type of session limit reached
        """
        message = f"Session limit reached: {session_status}"
        logger.warning(f"⚠️ {message}")

        try:
            # Close all positions
            self.portfolio_manager.sell_all_positions(
                f"Session limit: {session_status}"
            )
            logger.info(f"💰 All positions closed due to: {session_status}")

            # Send notification
            self.notification_manager.send_session_limit_notification(session_status)

            logger.success("✅ Session limit handling completed")

        except Exception as e:
            logger.exception(f"💥 Error handling session limit: {e}")

    def _handle_binance_api_error(self, exception: BinanceAPIException):
        """
        Handle Binance API specific errors with appropriate recovery strategies.

        Args:
            exception (BinanceAPIException): The Binance API exception
        """
        error_code = getattr(exception, "code", "Unknown")
        error_msg = f"Binance API Error [{error_code}]: {str(exception)}"

        logger.error(f"🔴 {error_msg}")

        # Log error for analysis
        self.reporting_manager.log_error(error_msg)

        # Send error notification
        self.notification_manager.send_error_notification(error_msg)

        # Handle specific error codes
        if error_code in [-1021, -1022]:  # Timestamp errors
            logger.warning("⏰ Timestamp synchronization issue detected")
            time.sleep(5)  # Wait before retry

        elif error_code == -2010:  # Insufficient balance
            logger.error("💸 Insufficient balance - stopping trading")
            self.trading_engine.is_running = False

        elif error_code in [-1003, -1015]:  # Rate limiting
            logger.warning("🚦 Rate limit exceeded - implementing backoff")
            time.sleep(60)  # Wait 1 minute before continuing

        else:
            # For other API errors, continue but log for investigation
            logger.warning("⚠️ Continuing operation despite API error")

    def _handle_network_error(self, exception: Exception):
        """
        Handle network-related errors with retry logic.

        Args:
            exception (Exception): Network-related exception
        """
        error_msg = f"Network Error: {type(exception).__name__} - {str(exception)}"
        logger.error(f"🌐 {error_msg}")

        # Log error
        self.reporting_manager.log_error(error_msg)

        # Implement exponential backoff for network errors
        retry_delay = 30  # Start with 30 seconds
        max_retries = 3

        for attempt in range(max_retries):
            logger.info(
                f"🔄 Retrying connection in {retry_delay} seconds (attempt {attempt + 1}/{max_retries})"
            )
            time.sleep(retry_delay)

            try:
                # Test connection
                self._test_api_connection()
                logger.success("✅ Connection restored successfully")
                return

            except BinanceAPIException as e:
                logger.warning(
                    f"⚠️ Retry attempt {attempt + 1} failed with API error: {e}"
                )
                retry_delay *= 2  # Exponential backoff

            except (ConnectionError, ReadTimeout, RequestException) as e:
                logger.warning(
                    f"🌐 Retry attempt {attempt + 1} failed with network error: {e}"
                )
                retry_delay *= 2  # Exponential backoff

        # If all retries failed, stop the bot
        logger.error("💥 All connection retry attempts failed - stopping bot")
        self.trading_engine.is_running = False

    def _handle_general_error(self, exception: Exception):
        """
        Handle general exceptions that don't fall into specific categories.

        Args:
            exception (Exception): The general exception
        """
        error_msg = f"General Error: {type(exception).__name__} - {str(exception)}"
        logger.exception(f"💥 {error_msg}")

        # Log error with full traceback
        self.reporting_manager.log_error(error_msg)

        # Send error notification
        self.notification_manager.send_error_notification(error_msg)

        # Continue operation for general errors unless they're critical
        logger.info("🔄 Continuing operation after general error")

    def _handle_critical_error(self, exception: Exception):
        """
        Handle critical errors that require immediate bot shutdown.

        Args:
            exception (Exception): The critical exception
        """
        error_msg = f"Critical Error: {type(exception).__name__} - {str(exception)}"
        logger.critical(f"🚨 CRITICAL: {error_msg}")

        # Log critical error
        self.reporting_manager.log_error(f"CRITICAL: {error_msg}")

        # Send urgent notification
        self.notification_manager.send_critical_error_notification(error_msg)

        # Force stop trading engine
        self.trading_engine.is_running = False

    def _cleanup(self):
        """Perform cleanup operations before bot shutdown."""
        try:
            logger.info(
                f"{Fore.CYAN}🧹 Performing cleanup operations...{Style.RESET_ALL}"
            )
            logger.info("🧹 Starting cleanup operations")

            # Stop external signal modules
            if hasattr(self.data_provider, "shutdown"):
                self.data_provider.shutdown()

            # Save current portfolio state
            self.portfolio_manager.save_current_state()
            logger.info("💾 Portfolio state saved")

            # Generate final trading report
            self.reporting_manager.generate_final_report()
            logger.info("📊 Final report generated")

            # Close database connections
            if hasattr(self.db_interface, "close"):
                self.db_interface.close()
                logger.info("🔌 Database connections closed")

            logger.success("✅ Bot shutdown completed successfully")
            logger.success("✅ Cleanup completed successfully")

        except Exception as e:
            logger.exception(f"💥 Error during cleanup: {e}")


if __name__ == "__main__":
    try:
        bot = BinanceVolatilityBot()
        bot.run()

    except KeyboardInterrupt:
        logger.warning("⏹️ Bot startup interrupted by user")

    except Exception as e:
        logger.critical(f"💥 Bot startup failed: {e}")
