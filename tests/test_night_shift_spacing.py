"""Tests for night shift spacing flexible rules.

Tests the following flexible rules:
- Rule 6: Night Shift Minimum Interval - avoid night shifts within 48h of each other
- Rule 7: Consecutive Night Shift Avoidance - avoid night-to-night sequences (next shift after night being night)
"""

import pytest
from datetime import datetime, date, timedelta
from ortools.sat.python import cp_model

from model_objectives import (
    build_night_shift_min_interval_cost,
    build_consecutive_night_shift_avoidance_cost,
    add_night_shift_min_interval_objective,
    add_consecutive_night_shift_avoidance_objective,
)
from constants import NIGHT_SHIFT_MIN_INTERVAL_HOURS, NIGHT_SHIFT_CONSECUTIVE_MIN_HOURS


def create_night_shifts(days):
    """Create night shifts for the given days."""
    shifts = []
    for day in days:
        d_dt = datetime.combine(day, datetime.min.time())
        shifts.append({
            "type": "N",
            "start": d_dt + timedelta(hours=20),  # 8 PM
            "end": d_dt + timedelta(hours=32),     # 8 AM next day
            "dur": 12,
            "night": True,
            "day": day,
            "index": len(shifts)
        })
    return shifts


class TestNightShiftMinIntervalCost:
    """Tests for build_night_shift_min_interval_cost function."""
    
    def test_consecutive_nights_penalized(self):
        """Two consecutive nights (24h apart) should be penalized."""
        model = cp_model.CpModel()
        days = [date(2026, 1, 5), date(2026, 1, 6)]
        shifts = create_night_shifts(days)
        num_shifts = len(shifts)
        num_workers = 1
        
        assigned = [[model.NewBoolVar(f"ass_w{w}_s{s}") for s in range(num_shifts)] for w in range(num_workers)]
        cost = build_night_shift_min_interval_cost(model, assigned, shifts, num_shifts, num_workers)
        
        # Force worker to have both nights
        model.Add(assigned[0][0] == 1)
        model.Add(assigned[0][1] == 1)
        model.Minimize(cost)
        
        solver = cp_model.CpSolver()
        status = solver.Solve(model)
        
        assert status == cp_model.OPTIMAL
        assert solver.Value(cost) == 1  # Should be penalized (24h < 48h)
    
    def test_nights_48h_apart_penalized(self):
        """Nights exactly 48h apart should be penalized (<=48h)."""
        model = cp_model.CpModel()
        days = [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)]
        shifts = create_night_shifts(days)
        num_shifts = len(shifts)
        num_workers = 1
        
        assigned = [[model.NewBoolVar(f"ass_w{w}_s{s}") for s in range(num_shifts)] for w in range(num_workers)]
        cost = build_night_shift_min_interval_cost(model, assigned, shifts, num_shifts, num_workers)
        
        # Night on day 1 and day 3 (48h apart exactly)
        model.Add(assigned[0][0] == 1)
        model.Add(assigned[0][1] == 0)
        model.Add(assigned[0][2] == 1)
        model.Minimize(cost)
        
        solver = cp_model.CpSolver()
        status = solver.Solve(model)
        
        assert status == cp_model.OPTIMAL
        assert solver.Value(cost) == 1  # Should be penalized (48h == 48h threshold)
    
    def test_nights_72h_apart_not_penalized(self):
        """Nights 72h apart should NOT be penalized."""
        model = cp_model.CpModel()
        days = [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7), date(2026, 1, 8)]
        shifts = create_night_shifts(days)
        num_shifts = len(shifts)
        num_workers = 1
        
        assigned = [[model.NewBoolVar(f"ass_w{w}_s{s}") for s in range(num_shifts)] for w in range(num_workers)]
        cost = build_night_shift_min_interval_cost(model, assigned, shifts, num_shifts, num_workers)
        
        # Night on day 1 and day 4 (72h apart)
        model.Add(assigned[0][0] == 1)
        model.Add(assigned[0][1] == 0)
        model.Add(assigned[0][2] == 0)
        model.Add(assigned[0][3] == 1)
        model.Minimize(cost)
        
        solver = cp_model.CpSolver()
        status = solver.Solve(model)
        
        assert status == cp_model.OPTIMAL
        assert solver.Value(cost) == 0  # Should NOT be penalized (72h > 48h)


class TestConsecutiveNightShiftAvoidanceCost:
    """Tests for build_consecutive_night_shift_avoidance_cost function.
    
    This rule penalizes when a worker's next shift after a night shift is also
    a night shift (night-to-night sequence), regardless of days apart.
    """
    
    def test_back_to_back_nights_penalized(self):
        """Two back-to-back nights (day N and day N+1) should be penalized."""
        model = cp_model.CpModel()
        days = [date(2026, 1, 5), date(2026, 1, 6)]
        shifts = create_night_shifts(days)
        num_shifts = len(shifts)
        num_workers = 1
        
        assigned = [[model.NewBoolVar(f"ass_w{w}_s{s}") for s in range(num_shifts)] for w in range(num_workers)]
        cost = build_consecutive_night_shift_avoidance_cost(model, assigned, shifts, num_shifts, num_workers)
        
        model.Add(assigned[0][0] == 1)
        model.Add(assigned[0][1] == 1)
        model.Minimize(cost)
        
        solver = cp_model.CpSolver()
        status = solver.Solve(model)
        
        assert status == cp_model.OPTIMAL
        assert solver.Value(cost) == 1  # Should be penalized (night-to-night, 24h < 96h)
    
    def test_night_to_night_with_gap_still_penalized(self):
        """Night-to-night sequence with days gap (no intervening shift) should be penalized."""
        model = cp_model.CpModel()
        # Only night shifts, no day shifts between
        days = [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)]
        shifts = create_night_shifts(days)
        num_shifts = len(shifts)
        num_workers = 1
        
        assigned = [[model.NewBoolVar(f"ass_w{w}_s{s}") for s in range(num_shifts)] for w in range(num_workers)]
        cost = build_consecutive_night_shift_avoidance_cost(model, assigned, shifts, num_shifts, num_workers)
        
        # Night on day 1 and day 3 (skipping day 2), but day 2's night is not assigned
        # So the worker's sequence is: N on day1 -> N on day3 (next shift is night)
        model.Add(assigned[0][0] == 1)
        model.Add(assigned[0][1] == 0)
        model.Add(assigned[0][2] == 1)
        model.Minimize(cost)
        
        solver = cp_model.CpSolver()
        status = solver.Solve(model)
        
        assert status == cp_model.OPTIMAL
        # Should be penalized: next shift after night is another night (48h apart < 96h)
        assert solver.Value(cost) == 1
    
    def test_single_night_no_penalty(self):
        """A single night shift should have no penalty."""
        model = cp_model.CpModel()
        days = [date(2026, 1, 5), date(2026, 1, 6)]
        shifts = create_night_shifts(days)
        num_shifts = len(shifts)
        num_workers = 1
        
        assigned = [[model.NewBoolVar(f"ass_w{w}_s{s}") for s in range(num_shifts)] for w in range(num_workers)]
        cost = build_consecutive_night_shift_avoidance_cost(model, assigned, shifts, num_shifts, num_workers)
        
        model.Add(assigned[0][0] == 1)
        model.Add(assigned[0][1] == 0)
        model.Minimize(cost)
        
        solver = cp_model.CpSolver()
        status = solver.Solve(model)
        
        assert status == cp_model.OPTIMAL
        assert solver.Value(cost) == 0


class TestMultipleWorkers:
    """Tests with multiple workers."""
    
    def test_penalty_per_worker(self):
        """Each worker's night-to-night sequences should be penalized independently."""
        model = cp_model.CpModel()
        days = [date(2026, 1, 5), date(2026, 1, 6)]
        shifts = create_night_shifts(days)
        num_shifts = len(shifts)
        num_workers = 2
        
        assigned = [[model.NewBoolVar(f"ass_w{w}_s{s}") for s in range(num_shifts)] for w in range(num_workers)]
        cost = build_consecutive_night_shift_avoidance_cost(model, assigned, shifts, num_shifts, num_workers)
        
        # Worker 0 has both nights (penalized - night-to-night)
        model.Add(assigned[0][0] == 1)
        model.Add(assigned[0][1] == 1)
        # Worker 1 has no nights (not penalized)
        model.Add(assigned[1][0] == 0)
        model.Add(assigned[1][1] == 0)
        model.Minimize(cost)
        
        solver = cp_model.CpSolver()
        status = solver.Solve(model)
        
        assert status == cp_model.OPTIMAL
        assert solver.Value(cost) == 1  # Only worker 0 penalized


class TestConstants:
    """Test that constants are correctly defined."""
    
    def test_night_shift_min_interval_constant(self):
        assert NIGHT_SHIFT_MIN_INTERVAL_HOURS == 48
    
    def test_night_shift_consecutive_min_constant(self):
        assert NIGHT_SHIFT_CONSECUTIVE_MIN_HOURS == 96
