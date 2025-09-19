# portfolio_manager.py
import json
import os
import math
import time
from datetime import datetime
from typing import Dict, Any
from loguru import logger
from binance.client import Client
from globals import user_data_path


class PortfolioManager:
    """portfolio manager using DbInterface for data operations."""

    def __init__(
        self,
        client: Client,
        config: Dict[str, Any],
        script_config: Dict[str, Any],
        db_interface,
        data_provider=None,
    ):
        self.client = client
        self.config = config
        self.script_config = script_config
        self.db_interface = db_interface
        self.data_provider = data_provider
        self.notification_manager = None

        self.TRADE_TOTAL = float(config.get("TRADE_TOTAL", 100))
        self.TRADE_SLOTS = int(config.get("TRADE_SLOTS", 5))
        self.PAIR_WITH = config.get("PAIR_WITH", "USDT")
        self.TEST_MODE = script_config.get("TEST_MODE", True)
        self.USE_TRAILING_STOP_LOSS = config.get("USE_TRAILING_STOP_LOSS", False)
        self.TRAILING_STOP_LOSS = float(config.get("TRAILING_STOP_LOSS", 0.2))
        self.TRAILING_TAKE_PROFIT = float(config.get("TRAILING_TAKE_PROFIT", 0.05))
        self.TAKE_PROFIT = float(config.get("TAKE_PROFIT", 2.0))
        self.STOP_LOSS = float(config.get("STOP_LOSS", 10.0))
        self.REINVEST_PROFITS = self.config.get("REINVEST_PROFITS", False)

        # File paths
        self.coins_bought_file_path = f"{user_data_path}/coins_bought.json"

        logger.info("💼 Portfolio manager initialized")

    def load_open_positions(self):
        """Load open positions from database and update JSON backup."""
        try:
            positions = self.db_interface.get_open_positions()
            logger.info(f"💼 Loaded {len(positions)} open positions from database")

            # Update JSON backup with database positions
            self.save_current_state()
        except Exception as e:
            logger.error(f"💥 Failed to load open positions from database: {e}")
            try:
                positions = self.load_from_json_backup()
                logger.warning(
                    f"💼 Using JSON backup - loaded {len(positions)} positions"
                )
                # Restore positions to database
                for symbol, position in positions.items():
                    self.db_interface.add_record(position)
                logger.info("💼 Restored positions to database from JSON backup")
            except Exception as backup_error:
                logger.error(f"💥 Failed to load from JSON backup: {backup_error}")

    def load_from_json_backup(self):
        """Load positions from JSON backup file as fallback."""
        try:
            if not os.path.exists(self.coins_bought_file_path):
                logger.info("💼 No JSON backup file found")
                return {}

            with open(self.coins_bought_file_path, "r") as f:
                backup_data = json.load(f)

            positions = backup_data.get("positions", {})
            last_updated = backup_data.get("last_updated", "Unknown")

            logger.info(
                f"💼 Loaded {len(positions)} positions from JSON backup (last updated: {last_updated})"
            )
            return positions

        except Exception as e:
            logger.error(f"💥 Failed to load from JSON backup: {e}")
            return {}

    def get_portfolio_status(self) -> Dict[str, Any]:
        """Get portfolio status using DbInterface."""
        try:
            stats = self.db_interface.get_portfolio_statistics()
            positions = self.db_interface.get_open_positions()

            return {
                "positions": stats.get("open_positions", 0),
                "total_exposure": stats.get("total_exposure", 0),
                "unrealized_pnl": stats.get("unrealized_pnl", 0),
                "available_slots": (
                    max(0, self.TRADE_SLOTS - len(positions))
                    if self.TRADE_SLOTS > 0
                    else float("inf")
                ),
                "coins_bought": positions.copy(),
            }
        except Exception as e:
            logger.error(f"💥 Error getting portfolio status: {e}")
            return {"positions": 0, "total_exposure": 0, "unrealized_pnl": 0}

    def execute_buy(self, signal: Dict[str, Any]):
        """Execute buy order and log to database."""
        try:
            symbol = signal.get("symbol")
            if not symbol:
                logger.error("💥 No symbol in buy signal")
                return

            # Check if we already have this position
            if self.db_interface.get_position_details(symbol):
                logger.warning(f"⚠️ Already have position in {symbol}")
                return

            current_price = self._get_symbol_price(symbol)
            if current_price <= 0:
                logger.error(f"💥 Invalid price for {symbol}: {current_price}")
                return

            volume = self.TRADE_TOTAL / current_price

            # Validate minimum volume
            if volume <= 0:
                logger.error(f"💥 Invalid volume for {symbol}: {volume}")
                return

            if self.TEST_MODE:
                order_data = self._create_mock_buy_order(symbol, volume, current_price)
            else:
                order_data = self._execute_real_buy_order(symbol, volume)

            # Log to database
            self._log_buy_transaction(order_data, signal)

            # Update JSON backup
            self.save_current_state()
            logger.info(
                f"🟢 BUY executed: {symbol} - Volume: {volume:.8f} - Price: {current_price:.8f}"
            )

            trade_data = {
                "symbol": order_data.get("symbol"),
                "side": "BUY",
                "quantity": order_data.get("volume"),
                "price": order_data.get("avgPrice"),
                "total": order_data.get("volume") * current_price,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "signal": signal.get("buy_signal", "unknown"),
            }
            self.notification_manager.send_trade_notification(trade_data)

        except Exception as e:
            logger.error(f"💥 Error executing buy: {e}")

    def execute_sell(self, symbol: str, reason: str):
        """Execute sell order and update database and JSON."""
        try:
            position = self.db_interface.get_position_details(symbol)
            if not position:
                logger.warning(f"⚠️ No position found for {symbol}")
                return {"success": False, "reason": "No position found"}

            volume = float(position.get("volume", 0))
            bought_at = float(position.get("bought_at", 0))

            if self.TEST_MODE:
                order_data = self._create_mock_sell_order(symbol, volume)
            else:
                order_data = self._execute_real_sell_order(symbol, volume)

            sell_price = float(order_data.get("avgPrice", 0))
            if sell_price <= 0:
                logger.error(f"💥 Invalid sell price for {symbol}: {sell_price}")
                return {"success": False, "reason": "Invalid sell price"}

            trading_fee = self.config.get("TRADING_FEE", 0.1) / 100
            buy_fee = bought_at * trading_fee
            sell_fee = sell_price * trading_fee
            sell_price_less_fees = sell_price - sell_fee
            buy_price_plus_fees = bought_at + buy_fee
            profit = (sell_price_less_fees - buy_price_plus_fees) * volume
            profit_pct = (
                ((sell_price_less_fees / buy_price_plus_fees) - 1) * 100
                if buy_price_plus_fees > 0
                else 0
            )

            # Close position in database
            self.db_interface.close_position(symbol, sell_price, reason)

            if self.REINVEST_PROFITS:
                increment = profit / self.TRADE_SLOTS
                self.TRADE_TOTAL += increment
                logger.info(
                    f"💸 Reinvested profits: increased TRADE_TOTAL by {increment:.2f} to {self.TRADE_TOTAL:.2f}"
                )

            # Update JSON backup
            self.save_current_state()

            logger.info(
                f"🔴 SELL executed: {symbol} - Profit: {profit:.2f} {self.PAIR_WITH} - Profit %: {profit_pct:.2f}% - Reason: {reason}"
            )

            trade_data = {
                "symbol": symbol,
                "side": "SELL",
                "quantity": volume,
                "price": float(sell_price),
                "profit": float(profit),
                "profit_pct": float(profit_pct),
                "total": sell_price * volume,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "reason": reason,
            }
            self.notification_manager.send_trade_notification(trade_data)
            return {
                "success": True,
                "profit": profit,
                "profit_pct": profit_pct,
                "order_data": order_data,
            }

        except Exception as e:
            logger.error(f"💥 Error executing sell: {e}")
            return {"success": False, "reason": str(e)}

    def update_open_positions_details(self):
        """
        Update prices, profits, TP, SL, and trailing logic for all open positions.
        """
        try:
            current_prices = self._get_current_prices()

            trading_fee = self.config.get("TRADING_FEE", 0.075) / 100
            tsl_enabled = self.config.get("USE_TRAILING_STOP_LOSS", True)
            trailing_sl = self.config.get("TRAILING_STOP_LOSS", 3)
            trailing_tp = self.config.get("TRAILING_TAKE_PROFIT", 1)

            base_sl_percent = self.config.get("STOP_LOSS", 5)
            base_tp_percent = self.config.get("TAKE_PROFIT", 3.0)

            positions = self.db_interface.get_open_positions()
            for symbol, pos in positions.items():
                current_price = current_prices.get(symbol, 0)
                if current_price <= 0:
                    logger.warning(f"⚠️ Invalid price for {symbol}: {current_price}")
                    continue

                self.db_interface.update_position_price_and_profit_loss(
                    symbol,
                    current_price,
                    self.notification_manager.calculate_time_held(pos),
                )

                position_data = self.db_interface.get_position_details(symbol)
                entry_price = float(position_data.get("bought_at", 0))

                if entry_price <= 0:
                    logger.warning(
                        f"Invalid bought_at price for {symbol}, skipping update"
                    )
                    continue

                ttp_tsl_active = position_data.get("TTP_TSL", False)
                max_price = float(position_data.get("max_price", entry_price))
                min_sl_price = float(position_data.get("min_sl_price", 0))
                min_tp_price = float(position_data.get("min_tp_price", 0))

                buy_fee = entry_price * trading_fee
                sell_fee = current_price * trading_fee
                price_after_fees = current_price - sell_fee
                entry_price_plus_fees = entry_price + buy_fee

                if price_after_fees > max_price:
                    max_price = price_after_fees
                    self.db_interface.update_transaction_record(
                        symbol, {"max_price": max_price}
                    )

                if entry_price_plus_fees <= 0:
                    logger.warning(
                        f"Invalid entry price plus fees for {symbol}, skipping update"
                    )
                    continue

                base_sl_price = entry_price_plus_fees * (1 - base_sl_percent / 100)
                if price_after_fees <= base_sl_price:
                    logger.info(
                        f"🔴 Price reached base SL for {symbol} ({price_after_fees:.6f} ≤ {base_sl_price:.6f}), closing position."
                    )
                    self.execute_sell(symbol, "Price reached base SL")
                    continue

                if symbol in self.data_provider.get_delisted_coins():
                    logger.info(
                        f"🔴 {symbol} is scheduled for delisting, closing position."
                    )
                    self.execute_sell(symbol, "Coin scheduled for delisting")
                    continue

                if tsl_enabled and not self.config.get("SESSION_TPSL_OVERRIDE", False):
                    if not ttp_tsl_active:
                        base_tp_price = entry_price_plus_fees * (
                            1 + base_tp_percent / 100
                        )
                        if price_after_fees >= base_tp_price:
                            min_sl_price = price_after_fees * (1 - trailing_sl / 100)
                            min_tp_price = price_after_fees * (1 + trailing_tp / 100)
                            sl_perc = (
                                (min_sl_price - entry_price_plus_fees)
                                / entry_price_plus_fees
                            ) * 100
                            tp_perc = (
                                (min_tp_price - entry_price_plus_fees)
                                / entry_price_plus_fees
                            ) * 100
                            self.db_interface.update_transaction_record(
                                symbol,
                                {
                                    "TTP_TSL": True,
                                    "min_sl_price": min_sl_price,
                                    "min_tp_price": min_tp_price,
                                    "sl_perc": sl_perc,
                                    "tp_perc": tp_perc,
                                },
                            )
                            logger.info(
                                f"⚡ Trailing activated for {symbol}. TP: {min_tp_price:.6f}, SL: {min_sl_price:.6f}"
                            )
                            self.save_current_state()
                            continue
                    else:
                        new_min_sl_price = max_price * (1 - trailing_sl / 100)
                        new_min_tp_price = max_price * (1 + trailing_tp / 100)

                        if new_min_sl_price > min_sl_price:
                            min_sl_price = new_min_sl_price
                            min_tp_price = new_min_tp_price
                            sl_perc = (
                                (min_sl_price - entry_price_plus_fees)
                                / entry_price_plus_fees
                            ) * 100
                            tp_perc = (
                                (min_tp_price - entry_price_plus_fees)
                                / entry_price_plus_fees
                            ) * 100
                            self.db_interface.update_transaction_record(
                                symbol,
                                {
                                    "min_sl_price": min_sl_price,
                                    "min_tp_price": min_tp_price,
                                    "sl_perc": sl_perc,
                                    "tp_perc": tp_perc,
                                },
                            )
                            logger.debug(
                                f"🔵 Updated trailing TP/SL for {symbol}: TP={min_tp_price:.6f}, SL={min_sl_price:.6f}"
                            )

                        if price_after_fees <= min_sl_price:
                            logger.info(
                                f"⚡ Trailing Stop Loss hit for {symbol} at price {price_after_fees:.6f}"
                            )
                            self.execute_sell(symbol, "Trailing Stop Loss hit")
                            continue

                        if price_after_fees >= min_tp_price:
                            logger.info(
                                f"⚡ Trailing Take Profit hit for {symbol} at price {price_after_fees:.6f}"
                            )
                            self.execute_sell(symbol, "Trailing Take Profit hit")
                            continue
                else:
                    base_tp_price = entry_price_plus_fees * (1 + base_tp_percent / 100)
                    if price_after_fees >= base_tp_price:
                        logger.info(
                            f"⚡ Take Profit hit for {symbol} at price {price_after_fees:.6f}"
                        )
                        self.execute_sell(symbol, "Take Profit reached")
                        continue

            logger.debug(
                "✅ Updated positions prices, TP, SL and managed trailing stops"
            )

        except Exception as e:
            logger.error(f"💥 Error updating open positions details: {e}")

    def update_tp_in_db(self, symbol, new_tp):
        """Update TP for an open position in the database and JSON."""
        try:
            self.db_interface.update_position_tp(symbol, new_tp)
            self.save_current_state()
            return True
        except Exception as e:
            logger.error(f"[ERROR] Failed to update TP in DB for {symbol}: {e}")
            return False

    def update_sl_in_db(self, symbol, new_sl):
        """Update SL for an open position in the database and JSON."""
        try:
            self.db_interface.update_position_sl(symbol, new_sl)
            self.save_current_state()
            return True
        except Exception as e:
            logger.error(f"[ERROR] Failed to update SL in DB for {symbol}: {e}")
            return False

    def _log_buy_transaction(self, order_data: Dict[str, Any], signal: Dict[str, Any]):
        """Log buy transaction to database."""
        transact_time_ms = order_data.get("transactTime")
        buy_time = datetime.fromtimestamp(transact_time_ms / 1000)

        record = {
            "order_id": int(order_data.get("orderId", 0)),
            "buy_time": buy_time,
            "symbol": order_data.get("symbol"),
            "volume": float(order_data.get("volume", 0)),
            "bought_at": float(order_data.get("avgPrice", 0)),
            "now_at": float(order_data.get("avgPrice", 0)),
            "change_perc": 0.0,
            "profit_dollars": 0.0,
            "time_held": "0",
            "tp_perc": self.TAKE_PROFIT,
            "sl_perc": self.STOP_LOSS,
            "TTP_TSL": False,
            "closed": 0,
            "buy_signal": signal.get("buy_signal", "unknown"),
        }

        self.db_interface.add_record(record)

    def sell_all_positions(self, reason: str):
        """Sell all open positions."""
        try:
            positions = self.db_interface.get_open_positions()
            if not positions:
                logger.info("💼 No open positions to sell")
                return

            logger.info(f"🔴 Selling {len(positions)} positions: {reason}")
            successful_sells = 0
            failed_sells = 0

            for symbol in positions.keys():
                try:
                    self.execute_sell(symbol, reason)
                    successful_sells += 1
                    logger.info(f"🔴 Successfully sold {symbol}")
                except Exception as e:
                    failed_sells += 1
                    logger.error(f"💥 Failed to sell {symbol}: {e}")
                    continue

            logger.info(
                f"🔴 Sell all completed - Success: {successful_sells}, Failed: {failed_sells}"
            )
            self.save_current_state()

        except Exception as e:
            logger.error(f"💥 Error selling all positions: {e}")
            raise

    def close_all_positions_emergency(self, reason: str = "Emergency close"):
        """Emergency close all positions."""
        try:
            logger.warning(f"🚨 Emergency closing all positions: {reason}")
            positions = self.db_interface.get_open_positions()

            for symbol in positions.keys():
                try:
                    current_price = self._get_symbol_price(symbol)
                    if current_price:
                        self.db_interface.close_position(symbol, current_price, reason)
                        logger.info(f"🚨 Emergency closed {symbol} in database")
                except Exception as e:
                    logger.error(f"💥 Failed to emergency close {symbol}: {e}")
                    continue

            self.save_current_state()
            logger.warning("🚨 Emergency close completed")

        except Exception as e:
            logger.error(f"💥 Error in emergency close: {e}")

    def get_portfolio_summary(self) -> Dict[str, Any]:
        try:
            db_stats = self.db_interface.get_portfolio_statistics()
            positions = self.db_interface.get_open_positions()
            current_prices = self._get_current_prices()
            total_current_value = 0.0
            total_invested = 0.0
            unrealised_session_profit_incfees_total = 0.0
            budget = self.TRADE_SLOTS * self.TRADE_TOTAL

            for symbol, position in positions.items():
                current_price = current_prices.get(symbol, 0)
                sell_fee = current_price * (self.config.get("TRADING_FEE", 0.075) / 100)
                volume = float(position.get("volume", 0))
                bought_at = float(position.get("bought_at", 0))
                buy_fee = bought_at * (self.config.get("TRADING_FEE", 0.075) / 100)

                total_invested += volume * bought_at
                total_current_value += volume * current_price

                price_change_total = (
                    (current_price - sell_fee) - (bought_at + buy_fee)
                ) * volume
                unrealised_session_profit_incfees_total += price_change_total

            unrealised_session_profit_incfees_perc = (
                (unrealised_session_profit_incfees_total / budget) * 100
                if budget > 0
                else 0
            )

            return {
                "active_positions": len(positions),
                "total_invested": total_invested,
                "total_current_value": total_current_value,
                "unrealized_pnl": unrealised_session_profit_incfees_total,
                "unrealized_pnl_pct": unrealised_session_profit_incfees_perc,
                "available_slots": (
                    max(0, self.TRADE_SLOTS - len(positions))
                    if self.TRADE_SLOTS > 0
                    else float("inf")
                ),
                "total_trades": db_stats.get("total_trades", 0),
                "win_rate": db_stats.get("win_rate", 0),
                "total_realized_pnl": db_stats.get("total_realized_pnl", 0),
            }
        except Exception as e:
            logger.error(f"💥 Error getting portfolio summary: {e}")
            return {
                "active_positions": 0,
                "total_invested": 0,
                "total_current_value": 0,
                "unrealized_pnl": 0,
                "unrealized_pnl_pct": 0,
                "available_slots": self.TRADE_SLOTS,
            }

    def get_positions_count(self) -> int:
        """Get number of open positions."""
        return len(self.db_interface.get_open_positions())

    def has_open_positions(self) -> bool:
        """Check if there are any open positions."""
        return len(self.db_interface.get_open_positions()) > 0

    def get_positions_list(self) -> list:
        """Get list of symbols with open positions."""
        return list(self.db_interface.get_open_positions().keys())

    def _get_symbol_price(self, symbol: str) -> float:
        """Get symbol price from data provider cache."""
        return self.data_provider.get_symbol_price(symbol)

    def _get_current_prices(self) -> Dict[str, float]:
        """Get current prices from data provider."""
        return self.data_provider.get_current_prices()

    def _create_mock_order(
        self,
        symbol: str,
        volume: float,
        price: float,
    ) -> Dict[str, Any]:
        """
        Create mock order for test mode.

        Args:
            symbol: Trading pair symbol
            volume: Quantity to buy/sell
            price: Price per unit

        Returns:
            Dict: Mock order data
        """
        now_ts = int(time.time() * 1000)
        order_id = now_ts
        trade_fee_bnb = 0.0
        avg_price = float(price)
        truncated_volume = self.truncate(volume, decimals=8)
        trade_fee_unit = avg_price * (self.config.get("TRADING_FEE", 0.1) / 100)

        return {
            "symbol": symbol,
            "orderId": order_id,
            "transactTime": now_ts,
            "avgPrice": avg_price,
            "volume": truncated_volume,
            "tradeFeeBNB": trade_fee_bnb,
            "tradeFeeUnit": trade_fee_unit,
        }

    def _create_mock_buy_order(
        self, symbol: str, volume: float, price: float
    ) -> Dict[str, Any]:
        return self._create_mock_order(symbol, volume, price)

    def _create_mock_sell_order(self, symbol: str, volume: float) -> Dict[str, Any]:
        current_price = self._get_symbol_price(symbol)
        return self._create_mock_order(symbol, volume, current_price)

    def _execute_real_buy_order(self, symbol: str, volume: float) -> Dict[str, Any]:
        """
        Execute real buy order via Binance API.

        Args:
            symbol: Trading pair symbol
            volume: Quantity to buy

        Returns:
            Dict: Order response from Binance
        """
        try:
            order = self.client.create_order(
                symbol=symbol, side="BUY", type="MARKET", quantity=volume
            )
            order_data = self.extract_order_data(order)

            logger.info(f"🟢 Real buy order executed: {symbol}")
            return order_data

        except Exception as e:
            logger.error(f"💥 Failed to execute real buy order for {symbol}: {e}")
            raise

    def _execute_real_sell_order(self, symbol: str, volume: float) -> Dict[str, Any]:
        """
        Execute real sell order via Binance API.

        Args:
            symbol: Trading pair symbol
            volume: Quantity to sell

        Returns:
            Dict: Order response from Binance
        """
        try:
            order = self.client.create_order(
                symbol=symbol, side="SELL", type="MARKET", quantity=volume
            )

            order_data = self.extract_order_data(order)
            logger.info(f"🔴 Real sell order executed: {symbol}")
            return order_data

        except Exception as e:
            logger.error(f"💥 Failed to execute real sell order for {symbol}: {e}")
            raise

    def extract_order_data(self, order_details):
        """
        Extracts summarized order data from Binance order response (handles multi-fills).
        """
        fills_total = 0
        fills_qty = 0
        fills_fee = 0
        fee_warning = 0
        trading_fee = self.config.get("TRADING_FEE", 0.1)
        for fill in order_details.get("fills", []):
            price = float(fill["price"])
            qty = float(fill["qty"])
            fee = float(fill["commission"])
            fills_total += price * qty
            fills_qty += qty
            fills_fee += fee

            if (
                fill["commissionAsset"] != "BNB"
                and float(trading_fee) == 0.075
                and not fee_warning
            ):
                logger.warning("❗️ BNB not used for trading fee!")
                fee_warning = 1

        avg_price = fills_total / fills_qty if fills_qty > 0 else 0.0
        trade_fee_unit = avg_price * (float(trading_fee) / 100.0)

        try:
            info = self.client.get_symbol_info(order_details["symbol"])
            step_size = info["filters"][1]["stepSize"]
            lot_size = step_size.index("1") - 1
            if lot_size <= 0:
                volume = int(fills_qty)
            else:
                volume = self.truncate(fills_qty, lot_size)
        except Exception as e:
            logger.warning(f"extract_order_data: precision adjust fail: {e}")
            volume = fills_qty

        return {
            "symbol": order_details["symbol"],
            "orderId": order_details["orderId"],
            "transactTime": order_details["transactTime"],
            "avgPrice": float(avg_price),
            "volume": float(volume),
            "tradeFeeBNB": float(fills_fee),
            "tradeFeeUnit": trade_fee_unit,
        }

    @staticmethod
    def truncate(number: float, decimals: int = 0) -> float:
        """
        Returns value truncated to a specific number of decimal places.
        Better than rounding.

        Args:
            number: The number to truncate.
            decimals: Number of decimal places (default 0).

        Returns:
            Truncated number as a float.

        Raises:
            TypeError: If decimals is not an integer.
            ValueError: If decimals is negative.
        """
        if decimals < 0:
            raise ValueError("decimal places has to be 0 or more.")
        if decimals == 0:
            return float(math.trunc(number))
        factor = 10.0**decimals
        return math.trunc(number * factor) / factor

    def save_current_state(self):
        """Save current portfolio state from database to JSON file."""
        try:
            positions = self.db_interface.get_open_positions()
            backup_data = {
                "positions": positions,
                "last_updated": datetime.now().isoformat(),
                "total_positions": len(positions),
                "metadata": {
                    "trade_total": self.TRADE_TOTAL,
                    "trade_slots": self.TRADE_SLOTS,
                    "pair_with": self.PAIR_WITH,
                    "test_mode": self.TEST_MODE,
                },
            }

            with open(self.coins_bought_file_path, "w") as f:
                json.dump(backup_data, f, indent=2, default=str)

            logger.debug(f"💾 Portfolio state saved to {self.coins_bought_file_path}")

        except Exception as e:
            logger.error(f"💥 Failed to save portfolio state: {e}")
