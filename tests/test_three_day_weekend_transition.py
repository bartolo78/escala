"""Test that three-day weekends in transition weeks are properly handled."""

import pytest
from datetime import date, timedelta
from scheduling_engine import generate_schedule, _setup_holidays_and_days
from utils import compute_holidays
import calendar


class TestThreeDayWeekendTransition:
    """Tests for three-day weekend handling in transition weeks between months."""

    def test_march_2026_has_no_holidays(self):
        """March 2026 should have no holidays (key edge case for bug)."""
        holidays = compute_holidays(2026, 3)
        assert holidays == [], f"Expected no holidays for March 2026, got {holidays}"
    
    def test_april_2026_has_good_friday(self):
        """April 2026 should include Good Friday (April 3)."""
        holidays = compute_holidays(2026, 4)
        assert 3 in holidays, f"Expected April 3 (Good Friday) in holidays, got {holidays}"

    def test_empty_holidays_list_triggers_auto_extend(self):
        """Empty holidays list should still trigger auto-extension.
        
        This tests the critical bug fix: when a month has no holidays (like March 2026),
        passing an empty list should still trigger holiday auto-extension to include
        holidays from adjacent months in the scheduling window.
        """
        # Call _setup_holidays_and_days with empty list (simulating March 2026)
        holiday_set, days = _setup_holidays_and_days(2026, 3, holidays=[])
        
        # April 3 (Good Friday) should be in the holiday_set due to auto-extension
        good_friday = date(2026, 4, 3)
        assert good_friday in holiday_set, (
            f"Good Friday {good_friday} should be auto-extended into holiday_set. "
            f"Holiday set: {sorted(holiday_set)}"
        )
        
    def test_none_holidays_triggers_auto_extend(self):
        """None holidays should trigger auto-extension."""
        holiday_set, days = _setup_holidays_and_days(2026, 3, holidays=None)
        
        good_friday = date(2026, 4, 3)
        assert good_friday in holiday_set, (
            f"Good Friday {good_friday} should be auto-extended. "
            f"Holiday set: {sorted(holiday_set)}"
        )

    def test_holiday_set_extended_for_transition_week(self):
        """Holiday set should include holidays from adjacent months in scheduling window."""
        year, month = 2026, 3  # March 2026
        
        # Calculate scheduling window (same logic as scheduling_engine)
        _, num_days_in_month = calendar.monthrange(year, month)
        first_day = date(year, month, 1)
        last_day = date(year, month, num_days_in_month)
        first_monday = first_day - timedelta(days=first_day.weekday())
        last_sunday = last_day + timedelta(days=(6 - last_day.weekday()))
        
        days = []
        current_day = first_monday
        while current_day <= last_sunday:
            days.append(current_day)
            current_day += timedelta(days=1)
        
        # Build holiday_set as scheduling_engine does
        holiday_set = set()
        months_in_window = {(d.year, d.month) for d in days}
        for y, m in months_in_window:
            for hd in compute_holidays(y, m):
                holiday_set.add(date(y, m, hd))
        
        # April 3, 2026 (Good Friday) should be in holiday_set
        good_friday = date(2026, 4, 3)
        assert good_friday in holiday_set, f"Good Friday {good_friday} should be in holiday_set"
        
        # Scheduling window should include April 3-5
        assert good_friday in days, "Good Friday should be in scheduling window"
        assert date(2026, 4, 4) in days, "April 4 should be in scheduling window"
        assert date(2026, 4, 5) in days, "April 5 should be in scheduling window"

    def test_three_day_weekend_detection_in_transition_week(self):
        """Three-day weekend should be detected when holiday is in transition week."""
        year, month = 2026, 3
        
        # Build scheduling window
        _, num_days_in_month = calendar.monthrange(year, month)
        first_day = date(year, month, 1)
        last_day = date(year, month, num_days_in_month)
        first_monday = first_day - timedelta(days=first_day.weekday())
        last_sunday = last_day + timedelta(days=(6 - last_day.weekday()))
        
        days = []
        current_day = first_monday
        while current_day <= last_sunday:
            days.append(current_day)
            current_day += timedelta(days=1)
        
        # Build holiday_set
        holiday_set = set()
        months_in_window = {(d.year, d.month) for d in days}
        for y, m in months_in_window:
            for hd in compute_holidays(y, m):
                holiday_set.add(date(y, m, hd))
        
        # Get week 14 days
        week_14_days = [d for d in days if d.isocalendar()[1] == 14]
        
        # Check three-day weekend detection (same logic as model_objectives)
        good_friday = date(2026, 4, 3)
        is_three_day = any(day in holiday_set and day.weekday() in [0, 4] for day in week_14_days)
        
        assert is_three_day, "Week 14 should be detected as having a three-day weekend"
        
        # Check that all three days are in the week
        sat = good_friday + timedelta(days=1)
        sun = good_friday + timedelta(days=2)
        assert good_friday in week_14_days, "Good Friday should be in week 14"
        assert sat in week_14_days, "Saturday should be in week 14"
        assert sun in week_14_days, "Sunday should be in week 14"

    def test_three_day_weekend_minimization_small_team(self):
        """With 5 workers, three-day weekend should use 5 workers (theoretical minimum)."""
        workers = [
            {'name': f'W{i+1}', 'id': f'ID{i+1:03d}', 'color': '#ff0000', 
             'can_night': True, 'weekly_load': 18 if i < 2 else 12}
            for i in range(5)
        ]
        
        unavail = {w['name']: [] for w in workers}
        required = {w['name']: [] for w in workers}
        history = {}
        
        schedule, weekly, assignments, stats, current_stats = generate_schedule(
            2026, 3, unavail, required, history, workers, holidays=None
        )
        
        # Get three-day weekend assignments
        three_day_dates = ['2026-04-03', '2026-04-04', '2026-04-05']
        three_day_assignments = [a for a in assignments if a['date'] in three_day_dates]
        
        workers_in_period = set(a['worker'] for a in three_day_assignments)
        
        # With 5 workers and 9 shifts, given 24h constraints, 5 is the minimum
        assert len(workers_in_period) == 5, (
            f"Expected 5 unique workers in 3-day weekend with 5 total workers, "
            f"got {len(workers_in_period)}: {sorted(workers_in_period)}"
        )

    def test_three_day_weekend_minimization_large_team(self):
        """With 15 workers, three-day weekend should still minimize unique workers."""
        workers = [
            {'name': f'W{i+1}', 'id': f'ID{i+1:03d}', 'color': '#ff0000', 
             'can_night': True, 'weekly_load': 18 if i < 5 else 12}
            for i in range(15)
        ]
        
        unavail = {w['name']: [] for w in workers}
        required = {w['name']: [] for w in workers}
        history = {}
        
        schedule, weekly, assignments, stats, current_stats = generate_schedule(
            2026, 3, unavail, required, history, workers, holidays=None
        )
        
        # Get three-day weekend assignments
        three_day_dates = ['2026-04-03', '2026-04-04', '2026-04-05']
        three_day_assignments = [a for a in assignments if a['date'] in three_day_dates]
        
        workers_in_period = set(a['worker'] for a in three_day_assignments)
        
        # With 15 workers and 9 shifts, given 24h constraints:
        # Theoretical minimum is still around 5 (limited by 24h rule, not worker count)
        # But with other constraints (weekly participation), it might be higher
        # It should NEVER be 9 (one per shift) - that would mean NO consolidation
        assert len(workers_in_period) < 9, (
            f"Expected fewer than 9 unique workers in 3-day weekend (consolidation should happen), "
            f"got {len(workers_in_period)}: {sorted(workers_in_period)}"
        )
        
        # Ideally should be 7 or fewer (allowing some slack for other constraints)
        # This is what the logs showed: value=7
        assert len(workers_in_period) <= 7, (
            f"Expected 7 or fewer workers in 3-day weekend, got {len(workers_in_period)}"
        )
