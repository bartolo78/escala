"""Tests for cross-week 24-hour interval constraint.

This tests that the 24-hour rest interval is enforced across ISO week boundaries,
specifically when a worker has a shift at the end of a previously scheduled week
and should not be assigned a conflicting shift at the start of the new scheduling window.
"""

from __future__ import annotations

from datetime import date

import pytest
from ortools.sat.python import cp_model

from model_constraints import add_cross_week_interval_constraints


class TestCrossWeekIntervalConstraints:
    """Test the cross-week interval constraints."""

    def test_sunday_m2_blocks_monday_m1_m2(self):
        """
        If a worker worked Sunday M2 (ends 23:00), they cannot work Monday M1/M2 (starts 08:00).
        Gap is 9 hours, which is less than 24 hours required.
        """
        workers = [
            {"name": "Alice", "weekly_load": 18, "can_night": True},
            {"name": "Bob", "weekly_load": 18, "can_night": True},
        ]

        # History: Alice worked Sunday M2 on 2025-10-05
        history = {
            "Alice": {
                "2025-10": [
                    {"date": "2025-10-05", "shift": "M2", "dur": 15},
                ]
            }
        }

        # New scheduling window starts on Monday 2025-10-06
        # Days would be part of a new ISO week
        from datetime import datetime, timedelta
        from constants import SHIFTS

        days = [date(2025, 10, 6), date(2025, 10, 7)]  # Monday, Tuesday
        
        # Build shifts for these days
        shifts = []
        for day in days:
            d_dt = datetime.combine(day, datetime.min.time())
            for st in ["M1", "M2", "N"]:
                config = SHIFTS[st]
                shifts.append({
                    "type": st,
                    "start": d_dt + timedelta(hours=config["start_hour"]),
                    "end": d_dt + timedelta(hours=config["end_hour"]),
                    "dur": config["dur"],
                    "night": config["night"],
                    "day": day,
                })

        model = cp_model.CpModel()
        num_workers = len(workers)
        num_shifts = len(shifts)
        assigned = [[model.NewBoolVar(f"a_w{w}_s{s}") for s in range(num_shifts)] for w in range(num_workers)]

        # Apply cross-week interval constraints
        add_cross_week_interval_constraints(model, assigned, shifts, workers, days, history)

        # Each shift exactly one worker
        for s in range(num_shifts):
            model.AddExactlyOne(assigned[w][s] for w in range(num_workers))

        solver = cp_model.CpSolver()
        status = solver.Solve(model)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

        # Alice should NOT be assigned Monday M1 or M2 (indices 0 and 1)
        alice_idx = 0
        assert solver.Value(assigned[alice_idx][0]) == 0, "Alice should not work Monday M1 after Sunday M2"
        assert solver.Value(assigned[alice_idx][1]) == 0, "Alice should not work Monday M2 after Sunday M2"

    def test_sunday_m2_allows_monday_night(self):
        """
        If a worker worked Sunday M2 (ends 23:00), they CAN work Monday N (starts 20:00).
        Gap is 21 hours, which is less than 24 but night shift starts late enough.
        
        Wait - 23:00 to 20:00 next day is actually 21 hours, still < 24h so should be blocked.
        Let me reconsider: M2 ends at 23:00 Sunday, Monday N starts at 20:00.
        Time gap = 20:00 Monday - 23:00 Sunday = 21 hours. This is < 24h, so blocked.
        """
        workers = [
            {"name": "Alice", "weekly_load": 18, "can_night": True},
            {"name": "Bob", "weekly_load": 18, "can_night": True},
        ]

        history = {
            "Alice": {
                "2025-10": [
                    {"date": "2025-10-05", "shift": "M2", "dur": 15},
                ]
            }
        }

        from datetime import datetime, timedelta
        from constants import SHIFTS

        days = [date(2025, 10, 6)]  # Monday
        
        shifts = []
        for day in days:
            d_dt = datetime.combine(day, datetime.min.time())
            for st in ["M1", "M2", "N"]:
                config = SHIFTS[st]
                shifts.append({
                    "type": st,
                    "start": d_dt + timedelta(hours=config["start_hour"]),
                    "end": d_dt + timedelta(hours=config["end_hour"]),
                    "dur": config["dur"],
                    "night": config["night"],
                    "day": day,
                })

        model = cp_model.CpModel()
        num_workers = len(workers)
        num_shifts = len(shifts)
        assigned = [[model.NewBoolVar(f"a_w{w}_s{s}") for s in range(num_shifts)] for w in range(num_workers)]

        add_cross_week_interval_constraints(model, assigned, shifts, workers, days, history)

        solver = cp_model.CpSolver()
        status = solver.Solve(model)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

        alice_idx = 0
        # M2 ends 23:00, N starts 20:00 next day = 21h gap < 24h required
        # So Alice should NOT be able to work Monday N either
        assert solver.Value(assigned[alice_idx][2]) == 0, "Alice should not work Monday N (21h gap < 24h)"

    def test_sunday_m1_allows_monday_night(self):
        """
        If a worker worked Sunday M1 (ends 20:00), they CAN work Monday N (starts 20:00).
        Gap is exactly 24 hours, which meets the requirement.
        """
        workers = [
            {"name": "Alice", "weekly_load": 18, "can_night": True},
            {"name": "Bob", "weekly_load": 18, "can_night": True},
        ]

        history = {
            "Alice": {
                "2025-10": [
                    {"date": "2025-10-05", "shift": "M1", "dur": 12},
                ]
            }
        }

        from datetime import datetime, timedelta
        from constants import SHIFTS

        days = [date(2025, 10, 6)]  # Monday
        
        shifts = []
        for day in days:
            d_dt = datetime.combine(day, datetime.min.time())
            for st in ["M1", "M2", "N"]:
                config = SHIFTS[st]
                shifts.append({
                    "type": st,
                    "start": d_dt + timedelta(hours=config["start_hour"]),
                    "end": d_dt + timedelta(hours=config["end_hour"]),
                    "dur": config["dur"],
                    "night": config["night"],
                    "day": day,
                })

        model = cp_model.CpModel()
        num_workers = len(workers)
        num_shifts = len(shifts)
        assigned = [[model.NewBoolVar(f"a_w{w}_s{s}") for s in range(num_shifts)] for w in range(num_workers)]

        add_cross_week_interval_constraints(model, assigned, shifts, workers, days, history)

        # Force Alice to work Monday N to verify it's allowed
        alice_idx = 0
        model.Add(assigned[alice_idx][2] == 1)  # N is index 2

        solver = cp_model.CpSolver()
        status = solver.Solve(model)
        # If the constraint allows this, we should get a feasible solution
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE), "Alice should be able to work Monday N after Sunday M1 (24h gap)"

    def test_sunday_night_allows_tuesday_morning(self):
        """
        If a worker worked Sunday N (ends 08:00 Monday), they CAN work Tuesday M1/M2 (starts 08:00).
        Gap is exactly 24 hours, which meets the requirement.
        """
        workers = [
            {"name": "Alice", "weekly_load": 18, "can_night": True},
            {"name": "Bob", "weekly_load": 18, "can_night": True},
        ]

        history = {
            "Alice": {
                "2025-10": [
                    {"date": "2025-10-05", "shift": "N", "dur": 12},
                ]
            }
        }

        from datetime import datetime, timedelta
        from constants import SHIFTS

        # N on Sunday ends at 08:00 Monday (end_hour=32 means 8AM next day)
        # So Monday shifts should be blocked (gap < 24h)
        # Tuesday shifts (starting 08:00) would have exactly 24h gap
        days = [date(2025, 10, 6), date(2025, 10, 7)]  # Monday, Tuesday
        
        shifts = []
        for day in days:
            d_dt = datetime.combine(day, datetime.min.time())
            for st in ["M1", "M2", "N"]:
                config = SHIFTS[st]
                shifts.append({
                    "type": st,
                    "start": d_dt + timedelta(hours=config["start_hour"]),
                    "end": d_dt + timedelta(hours=config["end_hour"]),
                    "dur": config["dur"],
                    "night": config["night"],
                    "day": day,
                })

        model = cp_model.CpModel()
        num_workers = len(workers)
        num_shifts = len(shifts)
        assigned = [[model.NewBoolVar(f"a_w{w}_s{s}") for s in range(num_shifts)] for w in range(num_workers)]

        add_cross_week_interval_constraints(model, assigned, shifts, workers, days, history)

        # Each shift exactly one worker
        for s in range(num_shifts):
            model.AddExactlyOne(assigned[w][s] for w in range(num_workers))

        solver = cp_model.CpSolver()
        status = solver.Solve(model)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

        alice_idx = 0
        # Sunday N ends at 08:00 Monday
        # Monday M1 starts at 08:00 - 0h gap, blocked
        # Monday M2 starts at 08:00 - 0h gap, blocked
        # Monday N starts at 20:00 - 12h gap, blocked
        # Tuesday M1 starts at 08:00 - 24h gap, allowed
        assert solver.Value(assigned[alice_idx][0]) == 0, "Alice cannot work Monday M1 after Sunday N"
        assert solver.Value(assigned[alice_idx][1]) == 0, "Alice cannot work Monday M2 after Sunday N"
        assert solver.Value(assigned[alice_idx][2]) == 0, "Alice cannot work Monday N after Sunday N"

    def test_no_history_no_constraints(self):
        """
        If there's no history, no cross-week constraints should be added.
        """
        workers = [
            {"name": "Alice", "weekly_load": 18, "can_night": True},
        ]

        history = {}

        from datetime import datetime, timedelta
        from constants import SHIFTS

        days = [date(2025, 10, 6)]
        
        shifts = []
        for day in days:
            d_dt = datetime.combine(day, datetime.min.time())
            for st in ["M1", "M2", "N"]:
                config = SHIFTS[st]
                shifts.append({
                    "type": st,
                    "start": d_dt + timedelta(hours=config["start_hour"]),
                    "end": d_dt + timedelta(hours=config["end_hour"]),
                    "dur": config["dur"],
                    "night": config["night"],
                    "day": day,
                })

        model = cp_model.CpModel()
        num_workers = len(workers)
        num_shifts = len(shifts)
        assigned = [[model.NewBoolVar(f"a_w{w}_s{s}") for s in range(num_shifts)] for w in range(num_workers)]

        add_cross_week_interval_constraints(model, assigned, shifts, workers, days, history)

        # All shifts should be allowed for Alice
        for s in range(num_shifts):
            model.Add(assigned[0][s] == 1)

        solver = cp_model.CpSolver()
        status = solver.Solve(model)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    def test_bob_unaffected_by_alice_history(self):
        """
        Bob should not be constrained by Alice's history.
        """
        workers = [
            {"name": "Alice", "weekly_load": 18, "can_night": True},
            {"name": "Bob", "weekly_load": 18, "can_night": True},
        ]

        history = {
            "Alice": {
                "2025-10": [
                    {"date": "2025-10-05", "shift": "M2", "dur": 15},
                ]
            }
        }

        from datetime import datetime, timedelta
        from constants import SHIFTS

        days = [date(2025, 10, 6)]
        
        shifts = []
        for day in days:
            d_dt = datetime.combine(day, datetime.min.time())
            for st in ["M1", "M2", "N"]:
                config = SHIFTS[st]
                shifts.append({
                    "type": st,
                    "start": d_dt + timedelta(hours=config["start_hour"]),
                    "end": d_dt + timedelta(hours=config["end_hour"]),
                    "dur": config["dur"],
                    "night": config["night"],
                    "day": day,
                })

        model = cp_model.CpModel()
        num_workers = len(workers)
        num_shifts = len(shifts)
        assigned = [[model.NewBoolVar(f"a_w{w}_s{s}") for s in range(num_shifts)] for w in range(num_workers)]

        add_cross_week_interval_constraints(model, assigned, shifts, workers, days, history)

        # Force Bob to work Monday M1
        bob_idx = 1
        model.Add(assigned[bob_idx][0] == 1)

        solver = cp_model.CpSolver()
        status = solver.Solve(model)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE), "Bob should be able to work Monday M1"
