import unittest
from unittest.mock import MagicMock
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from Binance_volatility_trading_bot.portfolio_manager import PortfolioManager


class TestPortfolioManagerUpdatePositions(unittest.TestCase):
    def setUp(self):
        self.pm = PortfolioManager.__new__(PortfolioManager)

        self.pm.USE_TRAILING_STOP_LOSS = True
        self.pm.TRAILING_STOP_LOSS = 3
        self.pm.TRAILING_TAKE_PROFIT = 1
        self.pm.TAKE_PROFIT = 2.0
        self.pm.STOP_LOSS = 10.0
        self.pm.config = {"TRADING_FEE": 0.075, "SESSION_TPSL_OVERRIDE": False, "TRAILING_THRESHOLD": 0.8}

        self.pm._get_current_prices = MagicMock()
        self.pm.db_interface = MagicMock()
        self.pm.notification_manager = MagicMock()
        self.pm.execute_sell = MagicMock()
        self.pm.update_tp_in_db = MagicMock()
        self.pm.update_tp_in_memory_and_json = MagicMock()
        self.pm.update_sl_in_db = MagicMock()
        self.pm.update_sl_in_memory_and_json = MagicMock()

        self.pm.coins_bought = {
            "BTCUSDT": {"bought_at": 100, "symbol": "BTCUSDT"},
            "ETHUSDT": {"bought_at": 200, "symbol": "ETHUSDT"}
        }

    def test_trailing_activated_when_price_reaches_base_tp(self):
        # Przygotuj ceny
        self.pm._get_current_prices.return_value = {
            "BTCUSDT": 102.5,
            "ETHUSDT": 198
        }

        self.pm.db_interface.get_position_details.side_effect = [
            {"bought_at": 100, "tp_perc": 2, "sl_perc": 10, "TTP_TSL": False},
            {"bought_at": 200, "tp_perc": 2, "sl_perc": 10, "TTP_TSL": False}
        ]

        self.pm.notification_manager.calculate_time_held.return_value = "some_time"

        self.pm.update_open_positions_details()

        self.assertTrue(self.pm.coins_bought["BTCUSDT"].get("TTP_TSL", True))
        self.pm.db_interface.update_transaction_record.assert_called_with("BTCUSDT", {"TTP_TSL": True})

        self.pm.execute_sell.assert_not_called()

    def test_sell_triggered_when_price_falls_below_sl(self):
        self.pm.coins_bought["BTCUSDT"]["min_sl_price"] = 98

        self.pm._get_current_prices.return_value = {
            "BTCUSDT": 97,
            "ETHUSDT": 180
        }

        self.pm.db_interface.get_position_details.side_effect = [
            {"bought_at": 100, "tp_perc": 3, "sl_perc": 7, "TTP_TSL": True, "min_sl_price": 98, "max_price": 105},
            {"bought_at": 200, "tp_perc": 2, "sl_perc": 10, "TTP_TSL": False}
        ]

        self.pm.notification_manager.calculate_time_held.return_value = "some_time"

        self.pm.update_open_positions_details()

        self.pm.execute_sell.assert_any_call("BTCUSDT", reason="Trailing Stop Loss hit")

    def test_trailing_sl_only_increases_not_decreases(self):
        self.pm.coins_bought["BTCUSDT"]["min_sl_price"] = 98

        self.pm._get_current_prices.return_value = {
            "BTCUSDT": 100
        }

        self.pm.db_interface.get_position_details.return_value = {
            "bought_at": 100,
            "tp_perc": 3,
            "sl_perc": 2,
            "TTP_TSL": True,
            "min_sl_price": 98,
            "max_price": 100
        }

        self.pm.notification_manager.calculate_time_held.return_value = "some_time"

        self.pm.update_open_positions_details()

        self.assertEqual(self.pm.coins_bought["BTCUSDT"]["min_sl_price"], 98)

    def test_trailing_tp_and_sl_are_updated_when_price_above_trailing_tp_price(self):
        self.pm.coins_bought["BTCUSDT"]["tp_perc"] = 3
        self.pm.coins_bought["BTCUSDT"]["sl_perc"] = 2
        self.pm.coins_bought["BTCUSDT"]["max_price"] = 102

        self.pm._get_current_prices.return_value = {
            "BTCUSDT": 104,
        }

        self.pm.db_interface.get_position_details.return_value = {
            "bought_at": 100,
            "tp_perc": 3,
            "sl_perc": 2,
            "TTP_TSL": True,
            "min_sl_price": 98.9,
            "max_price": 102
        }

        self.pm.notification_manager.calculate_time_held.return_value = "some_time"

        self.pm.update_open_positions_details()

        updated_tp = self.pm.coins_bought["BTCUSDT"]["tp_perc"]
        updated_sl = self.pm.coins_bought["BTCUSDT"]["sl_perc"]
        self.assertGreater(updated_tp, 3)
        self.assertGreater(updated_sl, 0)

if __name__ == "__main__":
    unittest.main()
