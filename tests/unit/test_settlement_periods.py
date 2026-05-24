"""Unit tests for settlement period math — no database required."""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from app.services.settlement_service import _expected_periods


def _contract(start: date, end: date) -> MagicMock:
    c = MagicMock()
    c.start_date = start
    c.end_date = end
    return c


@pytest.mark.unit
class TestExpectedPeriods:
    def test_no_dates_returns_empty(self):
        c = MagicMock()
        c.start_date = None
        c.end_date = None
        assert _expected_periods(c, date.today()) == []

    def test_no_completed_periods_returns_empty(self):
        """Contract just started today — no period has ended yet."""
        today = date(2026, 1, 1)
        c = _contract(today, today + timedelta(days=365))
        assert _expected_periods(c, today) == []

    def test_one_completed_period(self):
        """Exactly one 91-day period completed before 'today'."""
        start = date(2025, 1, 1)
        end = start + timedelta(days=365)
        today = start + timedelta(days=91 + 1)  # period ended yesterday

        periods = _expected_periods(_contract(start, end), today)
        assert len(periods) == 1
        period_start, period_end, due_date = periods[0]
        assert period_start == start
        assert period_end == start + timedelta(days=90)  # 91 days → index 0..90
        assert due_date == period_end + timedelta(days=30)  # 30-day grace

    def test_two_completed_periods(self):
        start = date(2025, 1, 1)
        end = start + timedelta(days=730)
        today = start + timedelta(days=91 * 2 + 1)

        periods = _expected_periods(_contract(start, end), today)
        assert len(periods) == 2

    def test_period_boundary_not_yet_complete(self):
        """Period end equals today — should NOT be included (not yet finished)."""
        start = date(2025, 1, 1)
        end = start + timedelta(days=365)
        period_end = start + timedelta(days=90)
        today = period_end  # exactly at boundary

        periods = _expected_periods(_contract(start, end), today)
        assert len(periods) == 0

    def test_due_date_is_30_days_after_period_end(self):
        start = date(2024, 1, 1)
        end = start + timedelta(days=365)
        today = start + timedelta(days=200)

        periods = _expected_periods(_contract(start, end), today)
        for _, period_end, due_date in periods:
            assert due_date == period_end + timedelta(days=30)

    def test_periods_are_contiguous(self):
        """Each period_start should immediately follow the previous period_end."""
        start = date(2024, 1, 1)
        end = start + timedelta(days=730)
        today = start + timedelta(days=500)

        periods = _expected_periods(_contract(start, end), today)
        assert len(periods) >= 2
        for i in range(1, len(periods)):
            prev_end = periods[i - 1][1]
            curr_start = periods[i][0]
            assert curr_start == prev_end + timedelta(days=1)
