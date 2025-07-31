# notification_manager.py
import telebot
from typing import Dict, Any
from loguru import logger
from prettytable import PrettyTable
from datetime import datetime


class NotificationManager:
    """
    Manages notifications via Telegram for trading bot events.
    """

    def __init__(
        self,
        config: Dict[str, Any],
        db_interface=None,
        portfolio_manager=None,
        data_provider=None,
        reporting_manager=None,
        config_manager=None,
        bot_instance=None,
    ):
        """
        Initialize notification manager with Telegram configuration.

        Args:
            config (Dict[str, Any]): Configuration dictionary
        """
        self.config = config
        self.db_interface = db_interface
        self.portfolio_manager = portfolio_manager
        self.data_provider = data_provider
        self.reporting_manager = reporting_manager
        self.config_manager = config_manager

        # Telegram configuration
        self.telegram_enabled = config.get("MSG_TELEGRAM", False)
        self.telegram_bot_token, self.telegram_chat_id = (
            config_manager.get_telegram_credentials()
        )

        self.pair_with = config_manager.get_config_value("PAIR_WITH")

        self.bot = None
        self.bot_instance = bot_instance
        self.command_handlers_registered = False

        if self.telegram_enabled:
            self.bot = telebot.TeleBot(self.telegram_bot_token)
            self._setup_command_handlers()
            self._start_polling()

        logger.success(
            f"📱 Notification manager initialized - Telegram: {'✅' if self.telegram_enabled else '❌'}"
        )

    def _send_telegram_message(
        self, message: str, parse_mode: str = "Markdown", urgent: bool = False
    ):
        """
        Send message via pyTelegramBotAPI.

        Args:
            message (str): Message to send
            urgent (bool): Whether this is an urgent message
        """
        if not self.telegram_enabled or not self.bot:
            return

        try:
            self.bot.send_message(
                chat_id=self.telegram_chat_id,
                text=message,
                parse_mode=parse_mode,
                disable_web_page_preview=True,
                disable_notification=not urgent,
            )

        except telebot.apihelper.ApiException as e:
            logger.error(f"❌ Telegram API error: {e}")
            raise
        except Exception as e:
            logger.error(f"❌ Failed to send Telegram message: {e}")
            raise

    def send_trade_notification(self, trade_data: Dict[str, Any]):
        """
        Send trade notification via Telegram.

        Args:
            trade_data (Dict[str, Any]): Trade information
        """
        if not self.telegram_enabled:
            logger.debug(
                "📱 Telegram notifications disabled - skipping trade notification"
            )
            return

        try:
            message = self._format_trade_message(trade_data)
            self._send_telegram_message(message)
            logger.info(
                f"📱 Trade notification sent: {trade_data.get('symbol', 'Unknown')}"
            )

        except Exception as e:
            logger.error(f"❌ Failed to send trade notification: {e}")

    def send_balance_update(self, balance_data: Dict[str, Any]):
        """Send balance update as separate messages."""
        try:
            if not self.telegram_enabled:
                return

            summary_message = self._format_summary_message(balance_data)
            self._send_telegram_message(summary_message)

            total_positions = balance_data.get("positions", 0)
            if total_positions > 0:
                table_message = self._format_positions_table(balance_data)
                self._send_telegram_message(
                    f"<pre>{table_message}</pre>", parse_mode="HTML"
                )

        except Exception as e:
            logger.error(f"💥 Error sending balance update: {e}")

    def send_session_limit_notification(self, session_status: str):
        """
        Send session limit notification via Telegram.

        Args:
            session_status (str): Session limit status
        """
        if not self.telegram_enabled:
            return

        try:
            message = self._format_session_limit_message(session_status)
            self._send_telegram_message(message, urgent=True)
            logger.warning(f"📱 Session limit notification sent: {session_status}")

        except Exception as e:
            logger.error(f"❌ Failed to send session limit notification: {e}")

    def send_error_notification(self, error_message: str):
        """
        Send error notification via Telegram.

        Args:
            error_message (str): Error message
        """
        if not self.telegram_enabled:
            return

        try:
            message = self._format_error_message(error_message)
            self._send_telegram_message(message, urgent=True)
            logger.error("📱 Error notification sent")

        except Exception as e:
            logger.error(f"❌ Failed to send error notification: {e}")

    def send_critical_error_notification(self, error_message: str):
        """
        Send critical error notification via Telegram.

        Args:
            error_message (str): Critical error message
        """
        if not self.telegram_enabled:
            return

        try:
            message = self._format_critical_error_message(error_message)
            self._send_telegram_message(message, urgent=True)
            logger.critical("📱 Critical error notification sent")

        except Exception as e:
            logger.error(f"❌ Failed to send critical error notification: {e}")

    def send_bot_startup_notification(self):
        """Send bot startup notification."""
        if not self.telegram_enabled:
            return

        try:
            message = (
                "🚀 *Binance Volatility Bot Started*\n\n"
                f"• Mode: {'🧪 TEST' if self.config.get('TEST_MODE') else '💰 LIVE'}\n"
                f"• Time: {self._get_current_time()}\n"
                f"• Status: Ready for trading"
            )

            self._send_telegram_message(message)
            logger.info("📱 Bot startup notification sent")

        except Exception as e:
            logger.error(f"❌ Failed to send startup notification: {e}")

    def send_bot_shutdown_notification(self):
        """Send bot shutdown notification."""
        if not self.telegram_enabled:
            return

        try:
            message = (
                "⏹️ *Binance Volatility Bot Stopped*\n\n"
                f"• Time: {self._get_current_time()}\n"
                f"• Status: Bot has been shut down"
            )

            self._send_telegram_message(message)
            logger.info("📱 Bot shutdown notification sent")

        except Exception as e:
            logger.error(f"❌ Failed to send shutdown notification: {e}")

    def _format_trade_message(self, trade_data: Dict[str, Any]) -> str:
        """Format trade data into Telegram message."""
        symbol = trade_data.get("symbol", "Unknown")
        side = trade_data.get("side", "Unknown")
        quantity = trade_data.get("quantity", 0)
        price = trade_data.get("price", 0)
        total = trade_data.get("total", 0)
        profit = trade_data.get("profit", 0)
        profit_pct = trade_data.get("profit_pct", 0)
        reason_buy = trade_data.get("signal", "")
        reason_sell = trade_data.get("reason", "")
        reason = reason_buy if side.upper() == "BUY" else reason_sell

        side_emoji = "🟢" if side.upper() == "BUY" else "🔴"
        profit_emoji = "📈" if profit >= 0 else "📉"

        message = (
            f"{side_emoji} *{side.upper()} Order Executed*\n\n"
            f"• Symbol: `{symbol}`\n"
            f"• Quantity: `{quantity:.8f}`\n"
            f"• Price: `{price:.8f}`\n"
            f"• Total: `{total:.8f} {self.pair_with}`\n"
            f"• Reason: `{reason}`\n"
        )

        if side.upper() == "SELL":
            message += (
                f"• Profit/Loss: `{profit_emoji} {profit:.2f} {self.pair_with}`\n"
                f"• Profit/Loss %: `{profit_emoji} {profit_pct:.2f}%`\n"
            )

        message += f"• Time: {self._get_current_time()}"

        return message

    def _format_summary_message(self, balance_data: Dict[str, Any]) -> str:
        """Format summary without positions table."""
        session_profit = balance_data.get("session_profit", 0)
        unrealized_pnl = balance_data.get("unrealized_pnl", 0)
        total_positions = balance_data.get("positions", 0)
        exposure = balance_data.get("total_exposure", 0)

        # Trading statistics
        total_trades = balance_data.get("total_trades", 0)
        win_rate = balance_data.get("win_rate", 0)
        total_realized_pnl = balance_data.get("total_realized_pnl", 0)
        best_trade = balance_data.get("best_trade", 0)
        worst_trade = balance_data.get("worst_trade", 0)
        bot_profit = balance_data.get("bot_profit", None)

        profit_emoji = "📈" if session_profit >= 0 else "📉"
        unrealized_emoji = "🟢" if unrealized_pnl >= 0 else "🔴"
        bot_profit_emoji = (
            "🤖💰" if bot_profit is not None and bot_profit >= 0 else "🤖📉"
        )

        message = (
            f"{profit_emoji} *Portfolio Update*\n\n"
            f"💼 *Current Portfolio*\n"
            f"• Open Positions: `{total_positions}`\n"
            f"• Total Exposure: `{exposure:.2f} {self.pair_with}`\n"
            f"• Unrealized P&L: `{unrealized_emoji} {unrealized_pnl:.2f}%`\n\n"
            f"📊 *Session Stats*\n"
            f"• Session P&L: `{session_profit:.2f}%`\n"
            f"• Total Realized: `{total_realized_pnl:.2f} {self.pair_with}`\n\n"
            f"📈 *Trading History*\n"
            f"• Total Trades: `{total_trades}`\n"
            f"• Win Rate: `{win_rate:.1f}%`\n"
            f"• Best Trade: `{best_trade:.2f} {self.pair_with}`\n"
            f"• Worst Trade: `{worst_trade:.2f} {self.pair_with}`\n\n"
            f"🤖 *Bot Profit*\n"
        )

        if bot_profit is not None:
            message += f"• Bot Total Profit: `{bot_profit_emoji} {bot_profit:.2f} {self.pair_with}`\n"
        else:
            message += "• Bot Total Profit: `N/A`\n"

        return message

    def _format_positions_table(self, balance_data: Dict[str, Any]) -> str:
        """Format positions as comprehensive table with all trading metrics using PrettyTable."""
        try:
            positions = self._get_positions_data(balance_data)

            table = PrettyTable()
            table.field_names = [
                "Symbol",
                "Volume",
                "Bought At",
                "Now At",
                "TP %",
                "SL %",
                "Change %",
                "Profit $",
                "Time Held",
            ]

            table.padding_width = 1
            table.border = True
            table.junction_char = "+"
            table.horizontal_char = "-"
            table.vertical_char = "|"
            table.align["Symbol"] = "l"
            table.align["Volume"] = "r"
            table.align["Bought At"] = "r"
            table.align["Now At"] = "r"
            table.align["TP %"] = "r"
            table.align["SL %"] = "r"
            table.align["Change %"] = "l"
            table.align["Profit $"] = "l"
            table.align["Time Held"] = "l"

            for symbol, pos in positions.items():
                volume = float(pos.get("volume", 0))
                bought_at = float(pos.get("bought_at", 0))
                now_at = float(pos.get("now_at", 0))
                tp_pct = float(pos.get("tp_perc", 0))
                sl_pct = float(pos.get("sl_perc", 0))
                change_pct = float(pos.get("change_perc", 0))
                profit_dollars = float(pos.get("profit_dollars", 0))
                time_held = self.calculate_time_held(pos)

                profit_emoji = "🟢" if profit_dollars >= 0 else "🔴"
                profit_str = f"{profit_emoji}{profit_dollars:+.2f}$".rjust(1)
                change_emoji = "🟢" if change_pct >= 0 else "🔴"
                change_str = f"{change_emoji}{change_pct:+.2f}%".rjust(1)

                table.add_row(
                    [
                        symbol[:15],
                        f"{volume:.4f}",
                        f"{bought_at:.5f}",
                        f"{now_at:.5f}",
                        f"{tp_pct:+.2f}%",
                        f"{sl_pct:.2f}%",
                        change_str,
                        profit_str,
                        time_held[:20],
                    ]
                )

            table.sortby = "Profit $"
            table.reversesort = True

            return str(table)

        except (KeyError, ValueError, TypeError) as e:
            logger.error(f"💥 Error formatting comprehensive positions table: {e}")
            return f"❌ Error generating positions table: {str(e)}"

    def _get_positions_data(self, balance_data: Dict[str, Any]) -> Dict[str, Any]:
        """Get positions data from various sources."""
        try:
            positions = balance_data.get("positions_data", {})
            if isinstance(positions, dict) and positions:
                return positions

            return {}

        except Exception as e:
            logger.error(f"💥 Error getting positions data: {e}")
            return {}

    @staticmethod
    def calculate_time_held(position: Dict[str, Any]) -> str:
        """Calculate time held for position, formatted as 'Xd HH:MM:SS' if over 24h."""
        try:
            from datetime import datetime, timedelta

            buy_time_str = position.get("time", "") or position.get("buy_time", "")

            if not buy_time_str:
                return "N/A"

            try:
                if "T" in buy_time_str:
                    buy_time = datetime.fromisoformat(
                        buy_time_str.replace("Z", "+00:00")
                    )
                else:
                    buy_time = datetime.strptime(buy_time_str[:19], "%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError) as e:
                logger.error(f"💥 Error parsing buy_time: {e}")
                return "N/A"

            now = datetime.now(buy_time.tzinfo) if buy_time.tzinfo else datetime.now()
            time_diff = now - buy_time

            days = time_diff.days
            hours, remainder = divmod(time_diff.seconds, 3600)
            minutes, seconds = divmod(remainder, 60)

            if days > 0:
                return f"{days} days, {hours}:{minutes:02d}:{seconds:02d}"
            else:
                return f"{hours}:{minutes:02d}:{seconds:02d}"

        except Exception as e:
            logger.error(f"💥 Error calculating time held: {e}")
            return "N/A"

    def _format_session_limit_message(self, session_status: str) -> str:
        """Format session limit message."""
        if "TAKE_PROFIT" in session_status:
            emoji = "🎯"
            title = "Take Profit Hit"
        else:
            emoji = "🛑"
            title = "Stop Loss Hit"

        message = (
            f"{emoji} *{title}*\n\n"
            f"• Status: `{session_status}`\n"
            f"• Action: All positions closed\n"
            f"• Time: {self._get_current_time()}"
        )

        return message

    def _format_error_message(self, error_message: str) -> str:
        """Format error message."""
        message = (
            f"⚠️ *Trading Bot Error*\n\n"
            f"• Error: `{error_message[:500]}...`\n"
            f"• Time: {self._get_current_time()}\n"
            f"• Status: Bot continuing operation"
        )

        return message

    def _format_critical_error_message(self, error_message: str) -> str:
        """Format critical error message."""
        message = (
            f"🚨 *CRITICAL ERROR*\n\n"
            f"• Error: `{error_message[:500]}...`\n"
            f"• Time: {self._get_current_time()}\n"
            f"• Status: Bot stopped"
        )

        return message

    def _get_current_time(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def send_portfolio_summary_notification(self):
        """Send detailed portfolio summary via Telegram."""
        try:
            if not self.telegram_enabled:
                return

            # Get comprehensive portfolio data
            portfolio_summary = self.portfolio_manager.get_portfolio_summary()

            message = (
                f"📊 *Portfolio Summary*\n\n"
                f"• Active Positions: `{portfolio_summary['active_positions']}`\n"
                f"• Total Invested: `{portfolio_summary['total_invested']:.2f} USDT`\n"
                f"• Current Value: `{portfolio_summary['total_current_value']:.2f} USDT`\n"
                f"• Unrealized P&L: `{portfolio_summary['unrealized_pnl']:.2f} USDT` "
                f"({portfolio_summary['unrealized_pnl_pct']:.2f}%)\n"
                f"• Available Slots: `{portfolio_summary['available_slots']}`\n\n"
                f"📈 *Trading Stats*\n"
                f"• Total Trades: `{portfolio_summary['total_trades']}`\n"
                f"• Win Rate: `{portfolio_summary['win_rate']:.1f}%`\n"
                f"• Realized P&L: `{portfolio_summary['total_realized_pnl']:.2f} USDT`"
            )

            self._send_telegram_message(message)
            logger.info("📱 Portfolio summary notification sent")

        except Exception as e:
            logger.error(f"❌ Failed to send portfolio summary: {e}")

    def _setup_command_handlers(self):
        """Setup Telegram command handlers."""
        if self.command_handlers_registered:
            return

        @self.bot.message_handler(commands=["stop", "shutdown"])
        def handle_stop(message):
            self._handle_stop_command(message)

        @self.bot.message_handler(commands=["status"])
        def handle_status(message):
            self._handle_status_command(message)

        @self.bot.message_handler(commands=["positions"])
        def handle_positions(message):
            self._handle_positions_command(message)

        @self.bot.message_handler(commands=["help"])
        def handle_help(message):
            self._handle_help_command(message)

        @self.bot.message_handler(commands=["pause"])
        def handle_pause(message):
            self._handle_pause_command(message)

        @self.bot.message_handler(commands=["resume"])
        def handle_resume(message):
            self._handle_resume_command(message)

        @self.bot.message_handler(commands=["sell"])
        def handle_sell(message):
            self._handle_sell_command(message)

        @self.bot.message_handler(commands=["changetp"])
        def handle_change_tp(message):
            self._handle_change_tp_command(message)

        @self.bot.message_handler(commands=["changetpglobal"])
        def handle_change_tp_global(message):
            self._handle_change_tp_global_command(message)

        @self.bot.message_handler(commands=["changesl"])
        def handle_change_sl(message):
            self._handle_change_sl_command(message)

        @self.bot.message_handler(commands=["changeslglobal"])
        def handle_change_sl_global(message):
            self._handle_change_sl_global_command(message)

        self.command_handlers_registered = True
        logger.info("📱 Telegram command handlers registered")

    def _start_polling(self):
        """Start Telegram bot polling in separate thread."""
        import threading

        def polling_worker():
            """Worker thread for Telegram polling."""
            try:
                logger.info("📱 Starting Telegram bot polling...")
                self.bot.polling(none_stop=True, interval=1, timeout=10)
            except Exception as e:
                logger.error(f"💥 Telegram polling error: {e}")

        polling_thread = threading.Thread(target=polling_worker, daemon=True)
        polling_thread.start()

    def _verify_authorized_user(self, message) -> bool:
        """Verify if user is authorized to control bot."""
        chat_id = str(message.chat.id)
        authorized_chat_id = str(self.telegram_chat_id)

        if chat_id != authorized_chat_id:
            self.bot.reply_to(message, "❌ Unauthorized access denied")
            logger.warning(f"🚨 Unauthorized command attempt from chat_id: {chat_id}")
            return False

        return True

    def _handle_stop_command(self, message):
        """Handle stop/shutdown command."""
        try:
            if not self._verify_authorized_user(message):
                return

            logger.info("🛑 STOP command received from Telegram")

            # Send confirmation
            self.bot.reply_to(
                message,
                "🛑 *Bot Shutdown Initiated*\n\n Shutting down bot safely...\n All positions will be preserved.",
                parse_mode="Markdown",
            )

            # Trigger bot shutdown
            if self.bot_instance:
                self.bot_instance.shutdown_requested = True
                logger.info("✅ Shutdown flag set")

        except Exception as e:
            logger.error(f"💥 Error handling stop command: {e}")
            self.bot.reply_to(message, f"❌ Error: {str(e)}")

    def _handle_status_command(self, message):
        """Handle status command."""
        try:
            if not self._verify_authorized_user(message):
                return

            if self.bot_instance:
                status = (
                    "🟢 Running"
                    if not getattr(self.bot_instance, "shutdown_requested", False)
                    else "🔴 Shutting down"
                )

                # Get portfolio stats
                portfolio_summary = (
                    self.portfolio_manager.get_portfolio_summary()
                    if self.portfolio_manager
                    else {}
                )
                positions = portfolio_summary.get("active_positions", 0)
                unrealized_pnl = portfolio_summary.get("unrealized_pnl_pct", 0)

                uptime = self._get_uptime()

                status_message = f"""📊 *Bot Status Report*

    🤖 *System Status*
    • Status: {status}
    • Uptime: `{uptime}`
    • Mode: {'🧪 TEST' if self.config.get('TEST_MODE') else '💰 LIVE'}

    💼 *Portfolio*
    • Open Positions: `{positions}`
    • Unrealized P&L: `{unrealized_pnl:+.2f}%`

    🕐 *Last Update*
    • Time: `{self._get_current_time()}`

    Use /help for available commands"""

                self.bot.reply_to(message, status_message, parse_mode="Markdown")

        except Exception as e:
            logger.error(f"💥 Error handling status command: {e}")
            self.bot.reply_to(message, f"❌ Error getting status: {str(e)}")

    def _handle_positions_command(self, message):
        """Handle positions command."""
        try:
            if not self._verify_authorized_user(message):
                return

            if self.portfolio_manager:
                # Get portfolio data
                portfolio_summary = self.portfolio_manager.get_portfolio_summary()
                current_prices = self.data_provider.get_price()

                # Create balance data for table
                balance_data = {
                    "positions": portfolio_summary.get("active_positions", 0),
                    "total_exposure": portfolio_summary.get("total_current_value", 0),
                    "unrealized_pnl": portfolio_summary.get("unrealized_pnl_pct", 0),
                    "positions_data": portfolio_summary.get("positions_data", {}),
                }

                balance_report = self.reporting_manager.generate_balance_report(
                    portfolio_summary, current_prices
                )

                # Send positions table
                if balance_data["positions"] > 0:
                    table_message = self._format_positions_table(balance_report)
                    self.bot.reply_to(
                        message,
                        f"📋 *Current Positions*\n\n<pre>{table_message}</pre>",
                        parse_mode="HTML",
                    )
                else:
                    self.bot.reply_to(
                        message,
                        "📋 *No Open Positions*\n\nBot is currently not holding any positions.",
                    )

        except Exception as e:
            logger.error(f"💥 Error handling positions command: {e}")
            self.bot.reply_to(message, f"❌ Error getting positions: {str(e)}")

    def _handle_help_command(self, message):
        """Handle help command."""
        try:
            if not self._verify_authorized_user(message):
                return

            mode = "🧪 TEST" if self.config.get("TEST_MODE") else "💰 LIVE"

            help_text = f"""🤖 *Binance Volatility Bot Commands*

    🛑 *Control Commands*
    /stop - Shutdown bot safely
    /pause - Pause trading operations
    /resume - Resume trading operations
    
    💰  *Trading Commands*
    /sell SYMBOL - Sell a specific coin (e.g. /sell BTCUSDT)
    /changetp SYMBOL TP% - Change take profit for a coin (e.g. /changetp BTCUSDT 15)
    /changetpglobal TP% - Change global take profit for all new trades (e.g. /changetpglobal 12.5)
    /changesl SYMBOL SL% - Change stop loss for a coin (e.g. /changesl BTCUSDT 10)
    /changeslglobal SL% - Change global stop loss for all new trades (e.g. /changeslglobal 10)

    📊 *Information Commands*
    /status - Show bot status & stats
    /positions - Show current positions table
    /help - Show this help message

    ⚠️ *Security Notice*
    Only authorized chat can control this bot.
    All commands are logged for security.

    🔗 *Bot Info*
    • Mode: {mode}
    • Version: Binance Volatility Bot v2.0"""

            self.bot.reply_to(
                message,
                help_text,
                parse_mode="Markdown",
            )

        except Exception as e:
            logger.error(f"💥 Error handling help command: {e}")

    def _handle_pause_command(self, message):
        """Handle pause command."""
        try:
            if not self._verify_authorized_user(message):
                return

            if self.bot_instance:
                self.bot_instance.trading_paused = True
                self.bot.reply_to(
                    message,
                    "⏸️ *Trading Paused*\n\n"
                    "Bot will stop opening new positions.\n"
                    "Existing positions remain active.\n\n"
                    "Use /resume to continue trading.",
                    parse_mode="Markdown",
                )
                logger.info("⏸️ Trading paused via Telegram command")

        except Exception as e:
            logger.error(f"💥 Error handling pause command: {e}")

    def _handle_resume_command(self, message):
        """Handle resume command."""
        try:
            if not self._verify_authorized_user(message):
                return

            if self.bot_instance:
                self.bot_instance.trading_paused = False
                self.bot.reply_to(
                    message,
                    "▶️ *Trading Resumed*\n\n Bot will continue normal trading operations.",
                    parse_mode="Markdown",
                )
                logger.info("▶️ Trading resumed via Telegram command")

        except Exception as e:
            logger.error(f"💥 Error handling resume command: {e}")

    def _handle_sell_command(self, message):
        """Handle /sell SYMBOL command from Telegram."""
        try:
            if not self._verify_authorized_user(message):
                return

            parts = message.text.strip().split()
            if len(parts) < 2:
                self.bot.reply_to(
                    message, "❌ Usage: /sell SYMBOL (e.g. /sell BTCUSDT)"
                )
                return

            symbol = parts[1].upper()

            # Check if the bot currently holds this coin
            if (
                not self.portfolio_manager
                or symbol not in self.portfolio_manager.coins_bought
            ):
                self.bot.reply_to(message, f"❌ No open position for {symbol}.")
                return

            # Trigger the sell logic
            result = self.portfolio_manager.execute_sell(symbol, "Manual sell")

            if result:
                self.bot.reply_to(message, f"✅ Sell order for {symbol} executed.")
                logger.info(f"🟠 Manual sell command executed for {symbol}")
            else:
                self.bot.reply_to(message, f"⚠️ Failed to execute sell for {symbol}.")
                logger.warning(f"⚠️ Manual sell command failed for {symbol}")

        except Exception as e:
            logger.error(f"💥 Error handling sell command: {e}")
            self.bot.reply_to(message, f"❌ Error executing sell: {str(e)}")

    def _handle_change_tp_global_command(self, message):
        """Handle /changetpglobal TP% command from Telegram."""
        try:
            if not self._verify_authorized_user(message):
                return

            parts = message.text.strip().split()
            if len(parts) != 2:
                self.bot.reply_to(
                    message, "❌ Usage: /changetpglobal TP% (e.g. /changetpglobal 12.5)"
                )
                return

            try:
                new_tp = float(parts[1])
            except ValueError:
                self.bot.reply_to(
                    message, "❌ TP% must be a number (e.g. 12.5 for 12.5%)."
                )
                return

            if hasattr(self.bot_instance, "TAKE_PROFIT"):
                self.bot_instance.TAKE_PROFIT = new_tp

            try:
                self.config_manager.set_take_profit(new_tp)
                self.bot.reply_to(
                    message,
                    f"✅ Global Take Profit updated to {new_tp:.2f}% (config.yaml updated)",
                )
            except Exception as e:
                self.bot.reply_to(
                    message,
                    f"⚠️ TAKE_PROFIT changed in memory, but failed to update config.yaml: {e}",
                )

        except Exception as e:
            logger.error(f"💥 Error handling changetpglobal command: {e}")
            self.bot.reply_to(message, f"❌ Error changing global TP: {str(e)}")

    def _handle_change_tp_command(self, message):
        """Handle /changetp SYMBOL TP% command from Telegram."""
        try:
            if not self._verify_authorized_user(message):
                return

            parts = message.text.strip().split()
            if len(parts) != 3:
                self.bot.reply_to(
                    message,
                    "❌ Usage: /changetp SYMBOL TP% (e.g. /changetp BTCUSDT 15)",
                )
                return

            symbol = parts[1].upper()
            try:
                new_tp = float(parts[2])
            except ValueError:
                self.bot.reply_to(message, "❌ TP% must be a number (e.g. 15 for 15%).")
                return

            # Check if the bot currently holds this coin
            if (
                not self.portfolio_manager
                or symbol not in self.portfolio_manager.coins_bought
            ):
                self.bot.reply_to(message, f"❌ No open position for {symbol}.")
                return

            # Update TP in the position
            self.portfolio_manager.update_tp_in_memory_and_json(symbol, new_tp)
            self.portfolio_manager.update_tp_in_db(symbol, new_tp)

            # If you want to persist this change, also update in DB if needed:
            if hasattr(self.portfolio_manager, "save_current_state"):
                self.portfolio_manager.save_current_state()

            self.bot.reply_to(
                message, f"✅ Take Profit for {symbol} updated to {new_tp:.2f}%"
            )
            logger.info(f"🟢 TP for {symbol} changed to {new_tp:.2f}% via Telegram")

        except Exception as e:
            logger.error(f"💥 Error handling changetp command: {e}")
            self.bot.reply_to(message, f"❌ Error changing TP: {str(e)}")

    def _handle_change_sl_global_command(self, message):
        """Handle /changeslglobal SL% command from Telegram."""
        try:
            if not self._verify_authorized_user(message):
                return

            parts = message.text.strip().split()
            if len(parts) != 2:
                self.bot.reply_to(
                    message, "❌ Usage: /changeslglobal SL% (e.g. /changeslglobal 12.5)"
                )
                return

            try:
                new_sl = float(parts[1])
            except ValueError:
                self.bot.reply_to(
                    message, "❌ SL% must be a number (e.g. 12.5 for 12.5%)."
                )
                return

            if hasattr(self.bot_instance, "STOP_LOSS"):
                self.bot_instance.STOP_LOSS = new_sl

            try:
                self.config_manager.set_stop_loss(new_sl)
                self.bot.reply_to(
                    message,
                    f"✅ Global Stop Loss updated to {new_sl:.2f}% (config.yaml updated)",
                )
            except Exception as e:
                self.bot.reply_to(
                    message,
                    f"⚠️ STOP_LOSS changed in memory, but failed to update config.yaml: {e}",
                )

        except Exception as e:
            logger.error(f"💥 Error handling changeslglobal command: {e}")
            self.bot.reply_to(message, f"❌ Error changing global SL: {str(e)}")

    def _handle_change_sl_command(self, message):
        """Handle /changesl SYMBOL SL% command from Telegram."""
        try:
            if not self._verify_authorized_user(message):
                return

            parts = message.text.strip().split()
            if len(parts) != 3:
                self.bot.reply_to(
                    message,
                    "❌ Usage: /changesl SYMBOL SL% (e.g. /changesl BTCUSDT 10)",
                )
                return

            symbol = parts[1].upper()
            try:
                new_tp = float(parts[2])
            except ValueError:
                self.bot.reply_to(message, "❌ SL% must be a number (e.g. 15 for 15%).")
                return

            # Check if the bot currently holds this coin
            if (
                not self.portfolio_manager
                or symbol not in self.portfolio_manager.coins_bought
            ):
                self.bot.reply_to(message, f"❌ No open position for {symbol}.")
                return

            # Update TP in the position
            self.portfolio_manager.update_sl_in_memory_and_json(symbol, new_tp)
            self.portfolio_manager.update_sl_in_db(symbol, new_tp)

            # If you want to persist this change, also update in DB if needed:
            if hasattr(self.portfolio_manager, "save_current_state"):
                self.portfolio_manager.save_current_state()

            self.bot.reply_to(
                message, f"✅ Stop Loss for {symbol} updated to {new_tp:.2f}%"
            )
            logger.info(f"🟢 SL for {symbol} changed to {new_tp:.2f}% via Telegram")

        except Exception as e:
            logger.error(f"💥 Error handling changetp command: {e}")
            self.bot.reply_to(message, f"❌ Error changing SL: {str(e)}")

    def _get_uptime(self) -> str:
        """Get bot uptime."""
        try:
            if hasattr(self.bot_instance, "start_time"):
                uptime = datetime.now() - self.bot_instance.start_time
                return str(uptime).split(".")[0]  # Remove microseconds
            return "Unknown"
        except (AttributeError, TypeError) as e:
            logger.warning(f"Failed to get uptime: {str(e)}")
            return "Unknown"

    def stop_telegram_bot(self):
        """Stop Telegram bot polling."""
        try:
            if self.bot:
                self.bot.stop_polling()
                logger.info("📱 Telegram bot polling stopped")
        except Exception as e:
            logger.error(f"💥 Error stopping Telegram bot: {e}")
