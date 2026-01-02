"""
Test that overlapping ISO weeks already scheduled are not rescheduled and
are merged from history into the output for the selected month.
"""

import sys
import os
from datetime import date

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scheduling_engine import generate_schedule


def test_overlapping_week_respected_and_merged():
    # ISO week 40 of 2025: Monday 2025-09-29 to Sunday 2025-10-05
    # We'll provide history assignments for 2025-10-01 (Wed in that ISO week)
    workers = [
        {"name": "W1", "id": "ID001", "color": "#ff0000", "can_night": True, "weekly_load": 18},
        {"name": "W2", "id": "ID002", "color": "#00ff00", "can_night": True, "weekly_load": 18},
        {"name": "W3", "id": "ID003", "color": "#0000ff", "can_night": True, "weekly_load": 12},
    ]

    history = {
        "W1": {
            "2025-10": [
                {"date": "2025-10-01", "shift": "M1", "dur": 12},
            ]
        },
        "W2": {
            "2025-10": [
                {"date": "2025-10-01", "shift": "M2", "dur": 15},
            ]
        },
        "W3": {
            "2025-10": [
                {"date": "2025-10-01", "shift": "N", "dur": 12},
            ]
        },
    }

    # No special unavailability or requirements
    unavail = {w["name"]: [] for w in workers}
    required = {w["name"]: [] for w in workers}

    # Generate schedule for October 2025
    schedule, weekly, assignments, stats, current_stats = generate_schedule(
        2025, 10, unavail, required, history, workers, holidays=None
    )

    # Verify that 2025-10-01 reflects history (merged, not rescheduled differently)
    assert schedule.get("2025-10-01", {}) == {"M1": "W1", "M2": "W2", "N": "W3"}

    # Verify assignments contain the historical entries for 2025-10-01
    day_assignments = [a for a in assignments if a["date"] == "2025-10-01"]
    assert len(day_assignments) == 3
    assert {a["worker"] for a in day_assignments} == {"W1", "W2", "W3"}
    assert {a["shift"] for a in day_assignments} == {"M1", "M2", "N"}

    # Verify weekly summary for ISO week 40 includes hours for the three workers
    # ISO key is (year, week_number) => (2025, 40)
    key = (2025, 40)
    assert key in weekly
    assert weekly[key]["W1"]["hours"] == 12
    assert weekly[key]["W2"]["hours"] == 15
    assert weekly[key]["W3"]["hours"] == 12

    # Check overtime/undertime calculation against weekly loads
    assert weekly[key]["W1"]["undertime"] == 6  # 18 - 12
    assert weekly[key]["W2"]["undertime"] == 3  # 18 - 15
    assert weekly[key]["W3"]["undertime"] == 0  # 12 - 12
    assert weekly[key]["W1"]["overtime"] == 0
    assert weekly[key]["W2"]["overtime"] == 0
    assert weekly[key]["W3"]["overtime"] == 0
