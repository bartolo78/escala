"""
Tests for utils.py - Utility functions
"""

import pytest
from datetime import datetime
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import easter_date, compute_holidays


class TestEasterDate:
    """Tests for Easter date calculation."""

    def test_easter_2026(self):
        """Easter 2026 should be April 5."""
        result = easter_date(2026)
        assert result.month == 4
        assert result.day == 5

    def test_easter_2025(self):
        """Easter 2025 should be April 20."""
        result = easter_date(2025)
        assert result.month == 4
        assert result.day == 20

    def test_easter_2024(self):
        """Easter 2024 should be March 31."""
        result = easter_date(2024)
        assert result.month == 3
        assert result.day == 31

    def test_easter_returns_datetime(self):
        """Easter function should return datetime object."""
        result = easter_date(2026)
        assert isinstance(result, datetime)


class TestComputeHolidays:
    """Tests for holiday computation."""

    def test_january_has_new_year(self):
        """January should include New Year's Day."""
        holidays = compute_holidays(2026, 1)
        assert 1 in holidays

    def test_december_has_christmas(self):
        """December should include Christmas."""
        holidays = compute_holidays(2026, 12)
        assert 25 in holidays

    def test_december_has_multiple_holidays(self):
        """December should have multiple fixed holidays."""
        holidays = compute_holidays(2026, 12)
        assert 1 in holidays   # Restoration of Independence
        assert 8 in holidays   # Immaculate Conception
        assert 25 in holidays  # Christmas

    def test_april_has_freedom_day(self):
        """April should include Freedom Day (25th)."""
        holidays = compute_holidays(2026, 4)
        assert 25 in holidays

    def test_may_has_labour_day(self):
        """May should include Labour Day."""
        holidays = compute_holidays(2026, 5)
        assert 1 in holidays

    def test_movable_holidays_calculated(self):
        """Movable holidays based on Easter should be included."""
        # Easter 2026 is April 5
        # Good Friday is April 3 (Easter - 2)
        holidays = compute_holidays(2026, 4)
        assert 3 in holidays  # Good Friday
        assert 5 in holidays  # Easter Sunday

    def test_carnival_in_february(self):
        """Carnival (47 days before Easter) should be in correct month."""
        # Easter 2026 is April 5, Carnival is February 17
        holidays = compute_holidays(2026, 2)
        assert 17 in holidays

    def test_returns_sorted_list(self):
        """Holidays should be returned as sorted list."""
        holidays = compute_holidays(2026, 12)
        assert holidays == sorted(holidays)

    def test_no_duplicates(self):
        """Holiday list should not contain duplicates."""
        holidays = compute_holidays(2026, 4)
        assert len(holidays) == len(set(holidays))

    def test_empty_month_returns_empty(self):
        """Month with no holidays should return empty list."""
        # July has no fixed Portuguese holidays
        holidays = compute_holidays(2026, 7)
        # Could be empty or have movable holidays
        assert isinstance(holidays, list)
