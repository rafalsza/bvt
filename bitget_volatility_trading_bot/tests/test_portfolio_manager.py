import unittest
from unittest.mock import MagicMock
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from bitget_volatility_trading_bot.portfolio_manager import PortfolioManager


def _record_calls_with(mock_method, **expected_keys):
    """Return recorded update payloads containing all expected keys."""
    return [
        call
        for call in mock_method.call_args_list
        if isinstance(call.args[1], dict)
        and all(k in call.args[1] for k in expected_keys)
    ]


class TestPortfolioManagerUpdatePositions(unittest.TestCase):
    def setUp(self):
        self.pm = PortfolioManager.__new__(PortfolioManager)

        self.pm.config = {
            "TRADING_FEE": 0.075,
            "SESSION_TPSL_OVERRIDE": False,
            "USE_TRAILING_STOP_LOSS": True,
            "TRAILING_STOP_LOSS": 3,
            "TRAILING_TAKE_PROFIT": 1,
            "TAKE_PROFIT": 2.0,
            "STOP_LOSS": 10.0,
        }

        self.pm._get_current_prices = MagicMock()
        self.pm.db_interface = MagicMock()
        self.pm.notification_manager = MagicMock()
        self.pm.notification_manager.calculate_time_held.return_value = "some_time"
        self.pm.data_provider = MagicMock()
        self.pm.data_provider.get_delisted_coins.return_value = []
        self.pm.execute_sell = MagicMock()
        self.pm.execute_sell.return_value = {"success": True, "profit_pct": -6.0}
        self.pm.save_current_state = MagicMock()
        self.pm.risk_manager = MagicMock()

    def test_trailing_activated_when_price_reaches_base_tp(self):
        self.pm._get_current_prices.return_value = {
            "BTCUSDT": 102.5,
            "ETHUSDT": 198,
        }
        self.pm.db_interface.get_open_positions.return_value = {
            "BTCUSDT": {"bought_at": 100},
            "ETHUSDT": {"bought_at": 200},
        }
        self.pm.db_interface.get_position_details.side_effect = [
            {"bought_at": 100, "tp_perc": 2, "sl_perc": 10, "TTP_TSL": False},
            {"bought_at": 200, "tp_perc": 2, "sl_perc": 10, "TTP_TSL": False},
        ]

        self.pm.update_open_positions_details()

        activation_calls = _record_calls_with(
            self.pm.db_interface.update_transaction_record, TTP_TSL=True
        )
        self.assertEqual(len(activation_calls), 1)
        self.assertEqual(activation_calls[0].args[0], "BTCUSDT")
        self.pm.execute_sell.assert_not_called()

    def test_sell_triggered_when_price_falls_below_sl(self):
        self.pm._get_current_prices.return_value = {
            "BTCUSDT": 97,
            "ETHUSDT": 180,
        }
        self.pm.db_interface.get_open_positions.return_value = {
            "BTCUSDT": {"bought_at": 100},
            "ETHUSDT": {"bought_at": 200},
        }
        self.pm.db_interface.get_position_details.side_effect = [
            {
                "bought_at": 100,
                "tp_perc": 3,
                "sl_perc": 7,
                "TTP_TSL": True,
                "min_sl_price": 98,
                "min_tp_price": 104,
                "max_price": 105,
            },
            {"bought_at": 200, "tp_perc": 2, "sl_perc": 10, "TTP_TSL": False},
        ]

        self.pm.update_open_positions_details()

        self.pm.execute_sell.assert_any_call(
            "BTCUSDT", "Trailing Stop Loss hit"
        )
        # ETH fell through its base 10% stop loss as well
        self.pm.execute_sell.assert_any_call(
            "ETHUSDT", "Price reached base SL"
        )

    def test_trailing_sl_only_increases_not_decreases(self):
        # price unchanged relative to stored max -> no trailing updates
        self.pm._get_current_prices.return_value = {"BTCUSDT": 100}
        self.pm.db_interface.get_open_positions.return_value = {
            "BTCUSDT": {"bought_at": 100},
        }
        self.pm.db_interface.get_position_details.return_value = {
            "bought_at": 100,
            "tp_perc": 3,
            "sl_perc": 2,
            "TTP_TSL": True,
            "min_sl_price": 98,
            "min_tp_price": 104,
            "max_price": 100,
        }

        self.pm.update_open_positions_details()

        sl_calls = _record_calls_with(
            self.pm.db_interface.update_transaction_record, min_sl_price=True
        )
        self.assertEqual(sl_calls, [])
        self.pm.execute_sell.assert_not_called()

    def test_trailing_tp_and_sl_are_updated_when_price_above_trailing_tp_price(self):
        self.pm._get_current_prices.return_value = {"BTCUSDT": 104}
        self.pm.db_interface.get_open_positions.return_value = {
            "BTCUSDT": {"bought_at": 100},
        }
        self.pm.db_interface.get_position_details.return_value = {
            "bought_at": 100,
            "tp_perc": 3,
            "sl_perc": 2,
            "TTP_TSL": True,
            "min_sl_price": 98.9,
            "min_tp_price": 104,
            "max_price": 102,
        }

        self.pm.update_open_positions_details()

        trailing_calls = _record_calls_with(
            self.pm.db_interface.update_transaction_record,
            tp_perc=True,
            sl_perc=True,
        )
        self.assertEqual(len(trailing_calls), 1)
        payload = trailing_calls[0].args[1]
        self.assertGreater(payload["tp_perc"], 3)
        self.assertGreater(payload["sl_perc"], 0)
        # new min_sl_price moved up from 98.9
        self.assertGreater(payload["min_sl_price"], 98.9)

    def test_post_sell_cooloff_applied_on_sl_close(self):
        # price below base SL -> sell at a loss -> LOSS cooloff blocks instant rebuy
        self.pm._get_current_prices.return_value = {"BTCUSDT": 89}
        self.pm.db_interface.get_open_positions.return_value = {
            "BTCUSDT": {"bought_at": 100},
        }
        self.pm.db_interface.get_position_details.return_value = {
            "bought_at": 100,
            "tp_perc": 2,
            "sl_perc": 10,
            "TTP_TSL": False,
        }

        self.pm.update_open_positions_details()

        self.pm.execute_sell.assert_called_once_with(
            "BTCUSDT", "Price reached base SL"
        )
        self.pm.risk_manager.set_adaptive_cooloff.assert_called_once_with(
            "BTCUSDT", "LOSS"
        )

    def test_post_sell_cooloff_profit_result(self):
        # trailing TP close at a profit -> PROFIT cooloff
        self.pm.execute_sell.return_value = {"success": True, "profit_pct": 12.6}
        self.pm._get_current_prices.return_value = {"BTCUSDT": 104}
        self.pm.db_interface.get_open_positions.return_value = {
            "BTCUSDT": {"bought_at": 100},
        }
        self.pm.db_interface.get_position_details.return_value = {
            "bought_at": 100,
            "tp_perc": 3,
            "sl_perc": 2,
            "TTP_TSL": True,
            # min_sl above the freshly trailed level -> no SL update, so the
            # stored min_tp stays 100 and the 103.92 print triggers TP
            "min_sl_price": 103,
            "min_tp_price": 100,
            "max_price": 103,
        }

        self.pm.update_open_positions_details()

        self.pm.execute_sell.assert_called_once_with(
            "BTCUSDT", "Trailing Take Profit hit"
        )
        args = self.pm.risk_manager.set_adaptive_cooloff.call_args
        self.assertEqual(args.args[1], "PROFIT")

    def test_no_cooloff_without_risk_manager(self):
        # back-compat: no risk_manager wired -> nothing crashes, no cooloff
        self.pm.risk_manager = None
        self.pm._get_current_prices.return_value = {"BTCUSDT": 89}
        self.pm.db_interface.get_open_positions.return_value = {
            "BTCUSDT": {"bought_at": 100},
        }
        self.pm.db_interface.get_position_details.return_value = {
            "bought_at": 100,
            "tp_perc": 2,
            "sl_perc": 10,
            "TTP_TSL": False,
        }
        self.pm.update_open_positions_details()
        self.pm.execute_sell.assert_called_once()


class TestExtractOrderData(unittest.TestCase):
    def setUp(self):
        self.pm = PortfolioManager.__new__(PortfolioManager)
        self.pm.config = {"TRADING_FEE": 0.1}
        self.pm.client = MagicMock()
        self.pm.client.get_symbol_info.return_value = {
            "symbol": "BTCUSDT",
            "filters": [
                {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                {"filterType": "LOT_SIZE", "stepSize": "0.0001"},
            ],
        }

    def test_multi_fill_average_price(self):
        order = {
            "symbol": "BTCUSDT",
            "orderId": "42",
            "transactTime": 1700000000000,
            "fills": [
                {
                    "price": "50000",
                    "qty": "0.002",
                    "commission": "0.0000001",
                    "commissionAsset": "BTC",
                },
                {
                    "price": "50100",
                    "qty": "0.003",
                    "commission": "0.0000001",
                    "commissionAsset": "BTC",
                },
            ],
        }
        data = self.pm.extract_order_data(order)
        # (50000*0.002 + 50100*0.003) / 0.005 = 50060
        self.assertAlmostEqual(data["avgPrice"], 50060.0)
        self.assertAlmostEqual(data["volume"], 0.005)
        self.assertEqual(data["orderId"], "42")
        self.assertGreater(data["tradeFeeBNB"], 0)

    def test_empty_fills_yield_zero(self):
        order = {
            "symbol": "BTCUSDT",
            "orderId": "1",
            "transactTime": 0,
            "fills": [],
        }
        data = self.pm.extract_order_data(order)
        self.assertEqual(data["avgPrice"], 0.0)
        self.assertEqual(data["volume"], 0.0)

    def test_missing_symbol_info_falls_back(self):
        self.pm.client.get_symbol_info.side_effect = Exception("no info")
        order = {
            "symbol": "BTCUSDT",
            "orderId": "7",
            "transactTime": 0,
            "fills": [
                {
                    "price": "100",
                    "qty": "1.5",
                    "commission": "0.1",
                    "commissionAsset": "USDT",
                }
            ],
        }
        data = self.pm.extract_order_data(order)
        self.assertEqual(data["volume"], 1.5)  # untruncated fallback

    def test_truncate(self):
        self.assertEqual(PortfolioManager.truncate(1.23456, 3), 1.234)
        self.assertEqual(PortfolioManager.truncate(5.0, 0), 5.0)


if __name__ == "__main__":
    unittest.main()
