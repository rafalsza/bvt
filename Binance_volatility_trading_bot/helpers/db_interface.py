# helpers/db_interface.py
import sqlalchemy as db
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from loguru import logger


class DbInterface:

    def __init__(self, db_path, config: Dict[str, Any]):
        self.config = config
        # Configure SQLite with explicit dialect and connection parameters
        self.engine = db.create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
            echo=False,
        )
        self.connection = self.engine.connect()
        self.metadata = db.MetaData()
        self.metadata.reflect(self.connection)
        if "transactions" not in self.metadata.tables.keys():
            self.create_db()

    def create_db(self):
        """Create database schema."""
        self.metadata.reflect(self.connection)
        self.metadata.drop_all(self.engine, tables=self.metadata.sorted_tables)

        db.Table(
            "transactions",
            self.metadata,
            db.Column("id", db.Integer(), db.Sequence("user_id_seq"), primary_key=True),
            db.Column("order_id", db.Integer()),
            db.Column("buy_time", db.TIMESTAMP, nullable=False),
            db.Column("symbol", db.String, nullable=False),
            db.Column("volume", db.Float(), nullable=False),
            db.Column("bought_at", db.Float(), nullable=False),
            db.Column("now_at", db.Float(), nullable=False),
            db.Column("change_perc", db.Float(), nullable=False),
            db.Column("profit_dollars", db.Float(), nullable=False),
            db.Column("time_held", db.String(), nullable=False),
            db.Column("tp_perc", db.Float(), nullable=False),
            db.Column("sl_perc", db.Float(), nullable=False),
            db.Column("TTP_TSL", db.Boolean(), nullable=True, default=False),
            db.Column("closed", db.Integer(), default=0, nullable=False),
            db.Column("sell_time", db.TIMESTAMP, nullable=True),
            db.Column("sold_at", db.Float(), nullable=True),
            db.Column("buy_signal", db.String, nullable=True),
            db.Column("sell_reason", db.String, nullable=True),
            extend_existing=True,
        )

        self.metadata.create_all(self.engine)
        logger.info("🗃️ Database schema created")

    def add_record(self, record):
        """Add a single transaction record."""
        try:
            transactions = db.Table(
                "transactions", self.metadata, autoload=True, autoload_with=self.engine
            )
            query = transactions.insert().values(**record)
            self.connection.execute(query)
            self.connection.commit()
            logger.debug(f"📝 Record added: {record.get('symbol', 'Unknown')}")
        except Exception as e:
            logger.error(f"💥 Failed to add record: {e}")
            raise

    def update_transaction_record(self, symbol, update_dict):
        """Update existing transaction record."""
        try:
            transactions = db.Table(
                "transactions", self.metadata, autoload=True, autoload_with=self.engine
            )
            query = (
                transactions.update()
                .values(**update_dict)
                .where(
                    db.and_(
                        transactions.columns.symbol == symbol,
                        transactions.columns.closed == 0,
                    )
                )
            )
            self.connection.execute(query)
            self.connection.commit()
            logger.debug(f"📝 Record updated: {symbol}")
        except Exception as e:
            logger.error(f"💥 Failed to update record: {e}")
            raise

    # === PORTFOLIO MANAGEMENT METHODS ===

    def get_open_positions(self) -> Dict[str, Dict[str, Any]]:
        """Get all open positions with complete data from database."""
        try:
            transactions = db.Table(
                "transactions", self.metadata, autoload_with=self.engine
            )

            columns = [
                transactions.c.symbol,
                transactions.c.volume,
                transactions.c.bought_at,
                transactions.c.now_at,
                transactions.c.change_perc,
                transactions.c.profit_dollars,
                transactions.c.time_held,
                transactions.c.buy_time,
                transactions.c.order_id,
                transactions.c.buy_signal,
                transactions.c.tp_perc,
                transactions.c.sl_perc,
                transactions.c.TTP_TSL,
            ]

            query = db.select(*columns).where(transactions.c.closed.is_(False))

            result = self.connection.execute(query)
            positions = {}

            for row in result:
                buy_time = row.buy_time
                if buy_time:
                    if isinstance(buy_time, str):
                        time_str = buy_time
                    else:
                        time_str = buy_time.isoformat()
                else:
                    time_str = None

                positions[row.symbol] = {
                    "symbol": row.symbol,
                    "volume": float(row.volume) if row.volume is not None else 0.0,
                    "bought_at": (
                        float(row.bought_at) if row.bought_at is not None else 0.0
                    ),
                    "now_at": (
                        float(row.now_at)
                        if row.now_at is not None
                        else float(row.bought_at or 0)
                    ),
                    "change_perc": (
                        float(row.change_perc) if row.change_perc is not None else 0.0
                    ),
                    "profit_dollars": (
                        float(row.profit_dollars)
                        if row.profit_dollars is not None
                        else 0.0
                    ),
                    "time_held": row.time_held or "00:00:00",
                    "buy_time": time_str,
                    "order_id": row.order_id,
                    "signal": row.buy_signal or "unknown",
                    "tp_perc": float(row.tp_perc),
                    "sl_perc": float(row.sl_perc),
                    "TTP_TSL": bool(row.TTP_TSL),
                }

            logger.debug(f"💼 Retrieved {len(positions)} complete open positions")
            return positions

        except Exception as e:
            logger.error(f"💥 Error getting open positions: {e}")
            import traceback

            logger.error(f"💥 Traceback: {traceback.format_exc()}")
            return {}

    def get_position_details(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a specific position.

        Args:
            symbol: Trading pair symbol

        Returns:
            Dict with position details or None
        """
        try:
            transactions = db.Table(
                "transactions", self.metadata, autoload=True, autoload_with=self.engine
            )

            query = db.select(transactions).where(
                db.and_(transactions.c.symbol == symbol, transactions.c.closed == 0)
            )

            result = self.connection.execute(query).fetchone()

            if not result:
                return None

            return {
                "symbol": result.symbol,
                "volume": float(result.volume),
                "bought_at": float(result.bought_at),
                "now_at": float(result.now_at),
                "change_perc": float(result.change_perc),
                "profit_dollars": float(result.profit_dollars),
                "time_held": result.time_held,
                "buy_time": result.buy_time.isoformat() if result.buy_time else None,
                "buy_signal": result.buy_signal,
                "tp_perc": float(result.tp_perc),
                "sl_perc": float(result.sl_perc),
                "order_id": result.order_id,
                "TTP_TSL": result.TTP_TSL,
            }

        except Exception as e:
            logger.error(f"💥 Error getting position details for {symbol}: {e}")
            return None

    def update_position_price_and_profit_loss(
        self, symbol: str, current_price: float, time_held: str
    ):
        """
        Update current price and calculated fields for a position.

        Args:
            symbol: Trading pair symbol
            current_price: Current market price
            time_held: Time position has been held
        """
        try:
            # Get current position data
            position = self.get_position_details(symbol)
            if not position:
                return

            bought_at = position["bought_at"]
            volume = position["volume"]

            trading_fee = self.config.get("TRADING_FEE") / 100
            sell_fee = current_price * trading_fee
            buy_fee = bought_at * trading_fee

            last_price_less_fees = current_price - sell_fee
            buy_price_plus_fees = bought_at + buy_fee

            change_perc_inc_fees = (
                ((last_price_less_fees - buy_price_plus_fees) / buy_price_plus_fees)
                * 100
                if buy_price_plus_fees > 0
                else 0
            )
            profit_dollars_inc_fees = (
                last_price_less_fees - buy_price_plus_fees
            ) * volume

            update_dict = {
                "now_at": current_price,
                "change_perc": change_perc_inc_fees,
                "profit_dollars": profit_dollars_inc_fees,
            }

            if time_held:
                update_dict["time_held"] = time_held

            self.update_transaction_record(symbol, update_dict)
            logger.debug(f"📊 Updated price for {symbol}: {current_price}")

        except Exception as e:
            logger.error(f"💥 Error updating position price for {symbol}: {e}")

    def update_position_tp(self, symbol: str, tp_perc: float):
        """
        Update take profit percentage for a position.

        Args:
            symbol: Trading pair symbol
            tp_perc: Take profit percentage
        """
        try:
            update_dict = {"tp_perc": tp_perc}
            self.update_transaction_record(symbol, update_dict)
            logger.debug(f"📊 Updated TP for {symbol}: {tp_perc}")

        except Exception as e:
            logger.error(f"💥 Error updating position TP for {symbol}: {e}")

    def update_position_sl(self, symbol: str, sl_perc: float):
        """
        Update stop loss percentage for a position.

        Args:
            symbol: Trading pair symbol
            sl_perc: Stop loss percentage
        """
        try:
            update_dict = {"sl_perc": sl_perc}
            self.update_transaction_record(symbol, update_dict)
            logger.debug(f"📊 Updated SL for {symbol}: {sl_perc}")

        except Exception as e:
            logger.error(f"💥 Error updating position SL for {symbol}: {e}")

    def close_position(self, symbol: str, sell_price: float, sell_reason: str = ""):
        """
        Close a position by marking it as sold.

        Args:
            symbol: Trading pair symbol
            sell_price: Price at which position was sold
            sell_reason: Reason for selling
        """
        try:
            # Get current position data
            position = self.get_position_details(symbol)
            if not position:
                logger.warning(f"⚠️ No open position found for {symbol}")
                return

            bought_at = position["bought_at"]
            volume = position["volume"]
            trading_fee = self.config.get("TRADING_FEE", 0.1) / 100

            sell_fee = sell_price * trading_fee
            buy_fee = bought_at * trading_fee

            sell_price_less_fees = sell_price - sell_fee
            buy_price_plus_fees = bought_at + buy_fee

            profit_after_fees = sell_price_less_fees - buy_price_plus_fees
            change_perc_inc_fees = (
                (profit_after_fees / buy_price_plus_fees) * 100
                if buy_price_plus_fees > 0
                else 0
            )
            profit_dollars_inc_fees = profit_after_fees * volume

            # Calculate time held
            buy_time = datetime.fromisoformat(position["buy_time"])
            time_held = str(datetime.now() - buy_time)

            update_dict = {
                "now_at": sell_price,
                "change_perc": change_perc_inc_fees,
                "profit_dollars": profit_dollars_inc_fees,
                "time_held": time_held,
                "closed": 1,
                "sell_time": datetime.now(),
                "sold_at": sell_price,
                "sell_reason": sell_reason,
            }

            self.update_transaction_record(symbol, update_dict)
            logger.info(
                f"🔴 Position closed: {symbol} - P&L: {profit_dollars_inc_fees:.8f}"
            )

        except Exception as e:
            logger.error(f"💥 Error closing position for {symbol}: {e}")

    # === STATISTICS AND REPORTING ===
    def get_portfolio_statistics(self) -> Dict[str, Any]:
        """Get comprehensive portfolio statistics."""
        try:
            query = db.text(
                """
                SELECT 
                    -- Open positions
                    SUM(CASE WHEN closed = 0 THEN 1 ELSE 0 END) as open_positions,
                    COALESCE(SUM(CASE WHEN closed = 0 THEN volume * bought_at ELSE 0 END), 0) as total_exposure,
                    COALESCE(SUM(CASE WHEN closed = 0 THEN profit_dollars ELSE 0 END), 0) as unrealized_pnl,

                    -- Closed positions
                    SUM(CASE WHEN closed = 1 THEN 1 ELSE 0 END) as total_trades,
                    SUM(CASE WHEN closed = 1 AND profit_dollars > 0 THEN 1 ELSE 0 END) as winning_trades,
                    SUM(CASE WHEN closed = 1 AND profit_dollars < 0 THEN 1 ELSE 0 END) as losing_trades,
                    COALESCE(SUM(CASE WHEN closed = 1 THEN profit_dollars ELSE 0 END), 0) as total_realized_pnl,
                    COALESCE(AVG(CASE WHEN closed = 1 THEN profit_dollars ELSE NULL END), 0) as avg_profit_per_trade,
                    COALESCE(MAX(CASE WHEN closed = 1 THEN profit_dollars ELSE NULL END), 0) as best_trade,
                    COALESCE(MIN(CASE WHEN closed = 1 THEN profit_dollars ELSE NULL END), 0) as worst_trade
                FROM transactions
            """
            )

            result = self.connection.execute(query).fetchone()

            if not result:
                return {
                    "open_positions": 0,
                    "total_exposure": 0,
                    "unrealized_pnl": 0,
                    "total_trades": 0,
                    "winning_trades": 0,
                    "losing_trades": 0,
                    "win_rate": 0,
                    "total_realized_pnl": 0,
                    "avg_profit_per_trade": 0,
                    "best_trade": 0,
                    "worst_trade": 0,
                }

            open_positions = result[0] or 0
            total_exposure = float(result[1] or 0)
            unrealized_pnl = float(result[2] or 0)
            total_trades = result[3] or 0
            winning_trades = result[4] or 0
            losing_trades = result[5] or 0
            total_realized_pnl = float(result[6] or 0)
            avg_profit_per_trade = float(result[7] or 0)
            best_trade = float(result[8] or 0)
            worst_trade = float(result[9] or 0)

            win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

            return {
                "open_positions": open_positions,
                "total_exposure": total_exposure,
                "unrealized_pnl": unrealized_pnl,
                "total_trades": total_trades,
                "winning_trades": winning_trades,
                "losing_trades": losing_trades,
                "win_rate": win_rate,
                "total_realized_pnl": total_realized_pnl,
                "avg_profit_per_trade": avg_profit_per_trade,
                "best_trade": best_trade,
                "worst_trade": worst_trade,
            }

        except Exception as e:
            logger.error(f"💥 Error getting portfolio statistics: {e}")
            return {
                "open_positions": 0,
                "total_exposure": 0,
                "unrealized_pnl": 0,
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0,
                "total_realized_pnl": 0,
                "avg_profit_per_trade": 0,
                "best_trade": 0,
                "worst_trade": 0,
            }

    def get_trading_history(
        self, limit: int = 100, symbol: str = None
    ) -> List[Dict[str, Any]]:
        """
        Get trading history with optional filtering.

        Args:
            limit: Maximum number of records to return
            symbol: Optional symbol filter

        Returns:
            List of trading records
        """
        try:
            transactions = db.Table(
                "transactions", self.metadata, autoload=True, autoload_with=self.engine
            )

            query = db.select([transactions]).order_by(transactions.c.buy_time.desc())

            if symbol:
                query = query.where(transactions.c.symbol.is_(symbol))

            if limit:
                query = query.limit(limit)

            result = self.connection.execute(query)
            history = []

            for row in result:
                history.append(
                    {
                        "id": row.id,
                        "symbol": row.symbol,
                        "volume": float(row.volume),
                        "bought_at": float(row.bought_at),
                        "sold_at": float(row.sold_at) if row.sold_at else None,
                        "profit_dollars": float(row.profit_dollars),
                        "change_perc": float(row.change_perc),
                        "buy_time": row.buy_time.isoformat() if row.buy_time else None,
                        "sell_time": (
                            row.sell_time.isoformat() if row.sell_time else None
                        ),
                        "time_held": row.time_held,
                        "buy_signal": row.buy_signal,
                        "sell_reason": row.sell_reason,
                        "closed": bool(row.closed),
                    }
                )

            return history

        except Exception as e:
            logger.error(f"💥 Error getting trading history: {e}")
            return []

    def get_total_bot_profit(self) -> float:
        try:
            query = db.text(
                """
                SELECT COALESCE(SUM(profit_dollars), 0) as total_profit
                FROM transactions
                WHERE closed = 1
                """
            )
            result = self.connection.execute(query).fetchone()
            return float(result[0] if result else 0)
        except Exception as e:
            logger.error(f"💥 Error getting total bot profit from DB: {e}")
            return 0.0

    def get_performance_metrics(self, days: int = 30) -> Dict[str, Any]:
        """
        Get performance metrics for specified period.

        Args:
            days: Number of days to analyze

        Returns:
            Dict with performance metrics
        """
        try:
            transactions = db.Table(
                "transactions", self.metadata, autoload=True, autoload_with=self.engine
            )

            # Calculate date threshold
            date_threshold = datetime.now() - timedelta(days=days)

            query = db.select(
                [
                    db.func.count(transactions.c.id).label("trades_count"),
                    db.func.sum(transactions.c.profit_dollars).label("total_pnl"),
                    db.func.avg(transactions.c.profit_dollars).label("avg_pnl"),
                    db.func.sum(
                        db.case([(transactions.c.profit_dollars > 0, 1)], else_=0)
                    ).label("wins"),
                    db.func.sum(
                        db.case([(transactions.c.profit_dollars < 0, 1)], else_=0)
                    ).label("losses"),
                ]
            ).where(
                db.and_(
                    transactions.c.closed == 1,
                    transactions.c.sell_time >= date_threshold,
                )
            )

            result = self.connection.execute(query).fetchone()

            trades_count = result.trades_count or 0
            total_pnl = float(result.total_pnl or 0)
            avg_pnl = float(result.avg_pnl or 0)
            wins = result.wins or 0
            losses = result.losses or 0

            win_rate = (wins / trades_count * 100) if trades_count > 0 else 0

            return {
                "period_days": days,
                "trades_count": trades_count,
                "total_pnl": total_pnl,
                "avg_pnl_per_trade": avg_pnl,
                "wins": wins,
                "losses": losses,
                "win_rate": win_rate,
            }

        except Exception as e:
            logger.error(f"💥 Error getting performance metrics: {e}")
            return {}

    def close(self):
        """Close database connection."""
        try:
            if self.connection:
                self.connection.close()
                logger.info("🔌 Database connection closed")
        except Exception as e:
            logger.warning(f"⚠️ Error closing database connection: {e}")
