"""Tests for reporting_manager.py - session profit accounting."""
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from reporting_manager import ReportingManager


def _make_manager():
    db = MagicMock()
    mgr = ReportingManager({"TRADE_TOTAL": 500, "TRADE_SLOTS": 10}, db)
    mgr.session_stats = {}
    return mgr


class TestSessionRollover:
    def test_session_start_rolls_to_today(self):
        # a process started yesterday must not keep counting yesterday's
        # trades - the calendar-day start rolls forward at midnight
        mgr = _make_manager()
        mgr.session_start_time = datetime.now() - timedelta(days=1)
        mgr.db_interface.connection.execute.return_value.fetchone.return_value = (
            0,
        )
        mgr._calculate_session_profit()
        assert mgr.session_start_time == datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    def test_same_day_start_unchanged(self):
        mgr = _make_manager()
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        mgr.session_start_time = today
        mgr.db_interface.connection.execute.return_value.fetchone.return_value = (
            0,
        )
        mgr._calculate_session_profit()
        assert mgr.session_start_time == today
