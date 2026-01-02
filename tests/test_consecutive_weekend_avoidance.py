"""Focused unit tests for Flexible Rule 4: Consecutive Weekend Shift Avoidance.

We test the objective builder in isolation with a tiny model to avoid depending
on full-month optimization behavior.
"""

from __future__ import annotations

from datetime import date

from ortools.sat.python import cp_model

from model_objectives import add_consecutive_weekend_avoidance_objective


def test_consecutive_weekend_penalizes_when_others_without_prior_weekend():
    # October 2025: first in-month weekend is Oct 4-5 (ISO week 40, monday 2025-09-29)
    # Previous weekend is Sep 27-28.
    workers = [
        {"name": "A", "weekly_load": 18, "can_night": True},
        {"name": "B", "weekly_load": 18, "can_night": True},
        {"name": "C", "weekly_load": 18, "can_night": True},
    ]

    history = {
        "A": {
            "2025-09": [
                {"date": "2025-09-27", "shift": "M1", "dur": 12},
            ]
        }
    }

    # Build two weeks with only weekend days represented, one shift per day.
    d1 = date(2025, 10, 4)  # Sat
    d2 = date(2025, 10, 5)  # Sun
    d3 = date(2025, 10, 11)  # Sat
    d4 = date(2025, 10, 12)  # Sun

    shifts = [
        {"day": d1, "type": "M1"},
        {"day": d2, "type": "M1"},
        {"day": d3, "type": "M1"},
        {"day": d4, "type": "M1"},
    ]

    iso_weeks = {
        (2025, 40): {"monday": date(2025, 9, 29), "shifts": [0, 1], "days": [d1, d2]},
        (2025, 41): {"monday": date(2025, 10, 6), "shifts": [2, 3], "days": [d3, d4]},
    }

    model = cp_model.CpModel()
    num_workers = len(workers)
    num_shifts = len(shifts)
    assigned = [[model.NewBoolVar(f"a_w{w}_s{s}") for s in range(num_shifts)] for w in range(num_workers)]

    # Each shift assigned to exactly one worker.
    for s in range(num_shifts):
        model.AddExactlyOne(assigned[w][s] for w in range(num_workers))

    # Objective: only consecutive weekend avoidance.
    obj = 0
    obj = add_consecutive_weekend_avoidance_objective(
        model,
        obj,
        weight_flex=100,
        iso_weeks=iso_weeks,
        holiday_set=set(),
        history=history,
        workers=workers,
        assigned=assigned,
        num_workers=num_workers,
        shifts=shifts,
        year=2025,
        month=10,
    )
    model.Minimize(obj)

    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    # Worker A worked the previous weekend in history, and other workers had not yet
    # worked a weekend earlier in October, so A should be avoided on Oct 4-5.
    a_idx = 0
    assert solver.Value(assigned[a_idx][0]) == 0
    assert solver.Value(assigned[a_idx][1]) == 0
