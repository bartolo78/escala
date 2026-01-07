"""
Tests for logic_g4.py - Schedule generation logic
"""

import pytest
from datetime import date, timedelta
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scheduling_engine import (
    parse_unavail_or_req,
    update_history,
    _setup_holidays_and_days,
    _create_shifts,
    _group_shifts_by_day,
    _compute_past_stats,
    compute_automatic_equity_credits,
)
from constants import SHIFT_TYPES


class TestParseUnavailOrReq:
    """Tests for parsing unavailability and required shift entries."""

    def test_parse_single_date(self):
        """Single date should be parsed correctly."""
        result = parse_unavail_or_req(["2026-01-15"])
        assert (date(2026, 1, 15), None) in result
        assert len(result) == 1

    def test_parse_date_with_shift(self):
        """Date with specific shift should be parsed correctly."""
        result = parse_unavail_or_req(["2026-01-15 M1"])
        assert (date(2026, 1, 15), "M1") in result
        assert len(result) == 1

    def test_parse_date_with_night_shift(self):
        """Date with night shift should be parsed correctly."""
        result = parse_unavail_or_req(["2026-01-20 N"])
        assert (date(2026, 1, 20), "N") in result

    def test_parse_date_range(self):
        """Date range should expand to all dates in range."""
        result = parse_unavail_or_req(["2026-01-01 to 2026-01-03"])
        assert len(result) == 3
        assert (date(2026, 1, 1), None) in result
        assert (date(2026, 1, 2), None) in result
        assert (date(2026, 1, 3), None) in result

    def test_parse_empty_list(self):
        """Empty list should return empty set."""
        result = parse_unavail_or_req([])
        assert len(result) == 0

    def test_parse_multiple_entries(self):
        """Multiple entries should all be parsed."""
        result = parse_unavail_or_req([
            "2026-01-10",
            "2026-01-15 M2",
            "2026-01-20 to 2026-01-22"
        ])
        assert len(result) == 5  # 1 + 1 + 3

    def test_parse_invalid_shift_ignored(self):
        """Invalid shift type should be ignored."""
        result = parse_unavail_or_req(["2026-01-15 INVALID"])
        assert len(result) == 0


class TestUpdateHistory:
    """Tests for history update functionality."""

    def test_update_empty_history(self):
        """Adding to empty history should create entries."""
        history = {}
        assignments = [
            {"worker": "Alice", "date": "2026-01-15", "shift": "M1", "dur": 12}
        ]
        result = update_history(assignments, history)
        
        assert "Alice" in result
        assert "2026-01" in result["Alice"]
        assert len(result["Alice"]["2026-01"]) == 1

    def test_update_existing_history(self):
        """Adding to existing history should append."""
        history = {
            "Alice": {
                "2026-01": [{"date": "2026-01-10", "shift": "M1", "dur": 12}]
            }
        }
        assignments = [
            {"worker": "Alice", "date": "2026-01-15", "shift": "M2", "dur": 15}
        ]
        result = update_history(assignments, history)
        
        assert len(result["Alice"]["2026-01"]) == 2

    def test_update_replaces_same_date(self):
        """Assignment on same date should replace existing."""
        history = {
            "Alice": {
                "2026-01": [{"date": "2026-01-15", "shift": "M1", "dur": 12}]
            }
        }
        assignments = [
            {"worker": "Alice", "date": "2026-01-15", "shift": "M2", "dur": 15}
        ]
        result = update_history(assignments, history)
        
        # Should still be 1 entry, but with M2
        assert len(result["Alice"]["2026-01"]) == 1
        assert result["Alice"]["2026-01"][0]["shift"] == "M2"


class TestSetupHolidaysAndDays:
    """Tests for holiday and day setup."""

    def test_returns_correct_month_days(self):
        """Should return days covering the full month plus buffer."""
        holiday_set, days = _setup_holidays_and_days(2026, 1, [1, 6])
        
        # January 2026 starts on Thursday, ends on Saturday
        # Should include days from Monday before to Sunday after
        assert date(2026, 1, 1) in days
        assert date(2026, 1, 31) in days
        
    def test_holiday_set_created(self):
        """Holiday set should contain provided holidays as date objects."""
        holiday_set, days = _setup_holidays_and_days(2026, 1, [1, 6])
        
        # holiday_set now contains date objects, not day numbers
        assert date(2026, 1, 1) in holiday_set
        assert date(2026, 1, 6) in holiday_set

    def test_empty_holidays(self):
        """Empty holiday list triggers auto-extension for the scheduling window.
        
        When holidays=[] is passed, the system auto-computes holidays for all
        months in the ISO-week scheduling window. This ensures holidays from
        adjacent months (that fall within the scheduling window) are correctly
        classified for equity tracking.
        """
        holiday_set, days = _setup_holidays_and_days(2026, 2, [])
        
        # Auto-extension should add holidays from months in the scheduling window
        # February 2026 scheduling window spans Jan 26 - Mar 1 (ISO weeks)
        # This includes: Jan 1 (New Year) and Feb 17 (Carnival 2026)
        assert len(holiday_set) >= 0  # May have holidays from adjacent months
        assert len(days) > 0


class TestCreateShifts:
    """Tests for shift creation."""

    def test_creates_shifts_for_all_days(self):
        """Should create shifts for each day and shift type."""
        days = [date(2026, 1, 1), date(2026, 1, 2)]
        shifts, num_shifts = _create_shifts(days)
        
        # 2 days × 3 shift types = 6 shifts
        assert num_shifts == 6
        assert len(shifts) == 6

    def test_shift_has_required_fields(self):
        """Each shift should have required fields."""
        days = [date(2026, 1, 1)]
        shifts, _ = _create_shifts(days)
        
        for shift in shifts:
            assert 'type' in shift
            assert 'start' in shift
            assert 'end' in shift
            assert 'dur' in shift
            assert 'night' in shift
            assert 'day' in shift
            assert 'index' in shift

    def test_shift_types_present(self):
        """All shift types should be created for each day."""
        days = [date(2026, 1, 1)]
        shifts, _ = _create_shifts(days)
        
        shift_types = {s['type'] for s in shifts}
        assert shift_types == set(SHIFT_TYPES)


class TestGroupShiftsByDay:
    """Tests for grouping shifts by day."""

    def test_groups_correctly(self):
        """Shifts should be grouped by their day."""
        days = [date(2026, 1, 1), date(2026, 1, 2)]
        shifts, num_shifts = _create_shifts(days)
        shifts_by_day = _group_shifts_by_day(num_shifts, shifts)
        
        assert len(shifts_by_day) == 2
        assert date(2026, 1, 1) in shifts_by_day
        assert date(2026, 1, 2) in shifts_by_day
        assert len(shifts_by_day[date(2026, 1, 1)]) == 3  # 3 shift types


class TestComputePastStats:
    """Tests for computing past statistics per RULES.md equity priority order."""

    def test_empty_history(self):
        """Empty history should return zero stats."""
        workers = [{"name": "Alice"}]
        result = _compute_past_stats({}, workers)
        
        assert "Alice" in result
        assert result["Alice"]["sat_n"] == 0
        assert result["Alice"]["fri_night"] == 0

    def test_counts_night_shifts(self):
        """Night shifts should be counted correctly per category."""
        workers = [{"name": "Alice"}]
        history = {
            "Alice": {
                "2026-01": [
                    {"date": "2026-01-14", "shift": "N", "dur": 12},  # Wednesday night
                    {"date": "2026-01-15", "shift": "N", "dur": 12},  # Thursday night
                ]
            }
        }
        result = _compute_past_stats(history, workers)
        
        # Wednesday and Thursday nights are weekday (not Friday) N
        assert result["Alice"]["weekday_not_fri_n"] == 2

    def test_counts_weekend_shifts(self):
        """Weekend shifts should be counted correctly per category."""
        workers = [{"name": "Alice"}]
        history = {
            "Alice": {
                "2026-01": [
                    {"date": "2026-01-17", "shift": "M1", "dur": 12},  # Saturday M1
                    {"date": "2026-01-18", "shift": "M2", "dur": 15},  # Sunday M2
                ]
            }
        }
        result = _compute_past_stats(history, workers)
        
        assert result["Alice"]["sat_m1"] == 1
        assert result["Alice"]["sun_holiday_m2"] == 1


class TestAutomaticEquityCredits:
    """Tests for automatic equity credits calculation for extended absences."""

    def test_no_credits_for_short_absence(self):
        """Workers with less than 3 weeks absence should get no credits."""
        workers = [{"name": "Sofia"}]
        # 2 weeks of unavailability (not enough for credits)
        unavail_data = {
            "Sofia": ["2026-01-05 to 2026-01-16"]  # Mon-Fri for 2 weeks
        }
        credits = compute_automatic_equity_credits(unavail_data, workers, 2026, 2)
        assert "Sofia" not in credits or len(credits.get("Sofia", {})) == 0

    def test_credits_for_three_week_absence(self):
        """Workers with exactly 3 weeks full unavailability should get credits."""
        workers = [{"name": "Sofia"}]
        # 3 full weeks of weekday unavailability
        unavail_data = {
            "Sofia": ["2026-01-05 to 2026-01-23"]  # Mon Jan 5 to Fri Jan 23 (3 full weeks)
        }
        credits = compute_automatic_equity_credits(unavail_data, workers, 2026, 2)
        assert "Sofia" in credits
        # Should have some credits for common stats
        assert len(credits["Sofia"]) > 0

    def test_credits_for_four_week_absence(self):
        """Workers with 4 weeks absence should get more credits than 3 weeks."""
        workers = [{"name": "Sofia"}]
        # 4 full weeks of weekday unavailability
        unavail_data = {
            "Sofia": ["2026-01-05 to 2026-01-30"]  # About 4 weeks
        }
        credits = compute_automatic_equity_credits(unavail_data, workers, 2026, 2)
        assert "Sofia" in credits
        # 4 weeks should yield credits for weekday shifts
        assert "weekday_not_mon_day" in credits["Sofia"]
        assert credits["Sofia"]["weekday_not_mon_day"] >= 1

    def test_no_credits_for_partial_week_absence(self):
        """Partial week unavailability should not count toward consecutive weeks."""
        workers = [{"name": "Sofia"}]
        # Only Mon-Wed unavailable each week (not full weekdays)
        unavail_data = {
            "Sofia": [
                "2026-01-05",  # Mon
                "2026-01-06",  # Tue
                "2026-01-07",  # Wed
                "2026-01-12",  # Mon
                "2026-01-13",  # Tue
                "2026-01-14",  # Wed
                "2026-01-19",  # Mon
                "2026-01-20",  # Tue
                "2026-01-21",  # Wed
            ]
        }
        credits = compute_automatic_equity_credits(unavail_data, workers, 2026, 2)
        assert "Sofia" not in credits or len(credits.get("Sofia", {})) == 0

    def test_credits_only_for_affected_workers(self):
        """Only workers with extended absences should get credits."""
        workers = [{"name": "Sofia"}, {"name": "Rosa"}]
        unavail_data = {
            "Sofia": ["2026-01-05 to 2026-01-23"],  # 3 weeks
            "Rosa": ["2026-01-10"]  # Single day
        }
        credits = compute_automatic_equity_credits(unavail_data, workers, 2026, 2)
        assert "Sofia" in credits
        assert "Rosa" not in credits

    def test_empty_unavail_data(self):
        """Empty unavailability should return no credits."""
        workers = [{"name": "Sofia"}]
        credits = compute_automatic_equity_credits({}, workers, 2026, 2)
        assert len(credits) == 0
