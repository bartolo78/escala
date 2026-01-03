"""
Tests for constants.py - Configuration constants
"""

import pytest
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from constants import (
    SHIFTS,
    SHIFT_TYPES,
    SHIFT_DURATIONS,
    EQUITY_STATS,
    EQUITY_WEIGHTS,
    FIXED_HOLIDAYS,
    MOVABLE_HOLIDAY_OFFSETS,
)


class TestShiftConfiguration:
    """Tests for shift configuration constants."""

    def test_shift_types_defined(self):
        """All expected shift types should be defined."""
        assert "M1" in SHIFT_TYPES
        assert "M2" in SHIFT_TYPES
        assert "N" in SHIFT_TYPES

    def test_shifts_have_required_fields(self):
        """Each shift config should have required fields."""
        required_fields = {'start_hour', 'end_hour', 'dur', 'night'}
        for shift_type, config in SHIFTS.items():
            for field in required_fields:
                assert field in config, f"{shift_type} missing {field}"

    def test_night_shift_is_night(self):
        """Night shift should be marked as night."""
        assert SHIFTS['N']['night'] is True

    def test_day_shifts_not_night(self):
        """Day shifts should not be marked as night."""
        assert SHIFTS['M1']['night'] is False
        assert SHIFTS['M2']['night'] is False

    def test_shift_durations_positive(self):
        """All shift durations should be positive."""
        for shift_type, duration in SHIFT_DURATIONS.items():
            assert duration > 0, f"{shift_type} has non-positive duration"

    def test_shift_durations_match_config(self):
        """SHIFT_DURATIONS should match SHIFTS config."""
        for shift_type in SHIFT_TYPES:
            assert SHIFT_DURATIONS[shift_type] == SHIFTS[shift_type]['dur']


class TestEquityConfiguration:
    """Tests for equity/fairness configuration."""

    def test_equity_stats_defined(self):
        """Essential equity stats should be defined per RULES.md priority order."""
        expected_stats = [
            'sat_n',                # Priority 1: Saturday Night
            'sun_holiday_m2',       # Priority 2: Sunday or Holiday M2
            'sun_holiday_m1',       # Priority 3: Sunday or Holiday M1
            'sun_holiday_n',        # Priority 4: Sunday or Holiday N
            'sat_m2',               # Priority 5: Saturday M2
            'sat_m1',               # Priority 6: Saturday M1
            'fri_night',            # Priority 7: Friday N
            'weekday_not_fri_n',    # Priority 8: Weekday (not Friday) N
            'monday_day',           # Priority 9: Monday M1 or M2
            'weekday_not_mon_day',  # Priority 10: Weekday (not Monday) M1 or M2
        ]
        for stat in expected_stats:
            assert stat in EQUITY_STATS

    def test_equity_weights_for_all_stats(self):
        """Each equity stat should have a weight defined."""
        for stat in EQUITY_STATS:
            assert stat in EQUITY_WEIGHTS, f"Missing weight for {stat}"

    def test_equity_weights_non_negative(self):
        """All equity weights should be non-negative."""
        for stat, weight in EQUITY_WEIGHTS.items():
            assert weight >= 0, f"{stat} has negative weight"


class TestHolidayConfiguration:
    """Tests for holiday configuration."""

    def test_fixed_holidays_defined(self):
        """Fixed holidays should be defined for key months."""
        assert 1 in FIXED_HOLIDAYS   # January (New Year)
        assert 12 in FIXED_HOLIDAYS  # December (Christmas)

    def test_new_year_in_january(self):
        """January 1st should be a fixed holiday."""
        assert 1 in FIXED_HOLIDAYS.get(1, [])

    def test_christmas_in_december(self):
        """December 25th should be a fixed holiday."""
        assert 25 in FIXED_HOLIDAYS.get(12, [])

    def test_movable_holidays_defined(self):
        """Movable holidays should be defined."""
        assert 'easter' in MOVABLE_HOLIDAY_OFFSETS
        assert 'good_friday' in MOVABLE_HOLIDAY_OFFSETS
        assert 'carnival' in MOVABLE_HOLIDAY_OFFSETS

    def test_easter_offset_is_zero(self):
        """Easter offset should be 0 (reference point)."""
        assert MOVABLE_HOLIDAY_OFFSETS['easter'] == 0

    def test_good_friday_before_easter(self):
        """Good Friday should be 2 days before Easter."""
        assert MOVABLE_HOLIDAY_OFFSETS['good_friday'] == -2

    def test_carnival_before_easter(self):
        """Carnival should be 47 days before Easter."""
        assert MOVABLE_HOLIDAY_OFFSETS['carnival'] == -47
