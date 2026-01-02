"""Characterization / invariants tests for schedule generation.

These tests are intentionally invariant-based (not exact schedule snapshots)
so we can refactor internals without changing externally observable behavior.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

import pytest

from constants import SHIFTS, SHIFT_TYPES, MIN_REST_HOURS
from scheduling_engine import generate_schedule


def _shift_window(day: date, shift_type: str) -> tuple[datetime, datetime]:
    cfg = SHIFTS[shift_type]
    start = datetime.combine(day, datetime.min.time()) + timedelta(hours=cfg["start_hour"])
    end = datetime.combine(day, datetime.min.time()) + timedelta(hours=cfg["end_hour"])
    return start, end


def _rest_hours(prev_end: datetime, next_start: datetime) -> float:
    return (next_start - prev_end).total_seconds() / 3600.0


@pytest.mark.parametrize("year,month", [(2026, 1)])
def test_generate_schedule_invariants_small(empty_history, year, month):
    # The model requires 3 shifts/day and enforces a 24h rest window.
    # With only 3 workers, coverage would force each worker to work daily, which is infeasible.
    # Use 15 workers (the real application size) to characterize behavior safely.
    workers = [
        {"name": f"W{i:02d}", "id": f"ID{i:03d}", "color": "#000000", "can_night": True, "weekly_load": 18}
        for i in range(1, 13)
    ] + [
        {"name": "W13", "id": "ID013", "color": "#000000", "can_night": False, "weekly_load": 12},
        {"name": "W14", "id": "ID014", "color": "#000000", "can_night": False, "weekly_load": 12},
        {"name": "W15", "id": "ID015", "color": "#000000", "can_night": True, "weekly_load": 12},
    ]
    unavail = {w["name"]: [] for w in workers}
    required = {w["name"]: [] for w in workers}

    schedule, weekly, assignments, stats, _current_stats = generate_schedule(
        year, month, unavail, required, empty_history, workers, holidays=None
    )

    assert stats["status"] in {2, 4}  # FEASIBLE=2, OPTIMAL=4 (cp_model)
    assert assignments, "Expected non-empty assignments"

    # Group assignments by date
    by_date: dict[str, list[dict]] = defaultdict(list)
    for a in assignments:
        by_date[a["date"]].append(a)

    # Every scheduled day must have exactly 3 shifts assigned, one per type.
    for day_str, day_ass in by_date.items():
        assert len(day_ass) == len(SHIFT_TYPES)
        assert {a["shift"] for a in day_ass} == set(SHIFT_TYPES)

        # No worker does more than one shift per day
        assert len({a["worker"] for a in day_ass}) == len(day_ass)

    # Night restrictions respected
    can_night = {w["name"]: w.get("can_night", True) for w in workers}
    for a in assignments:
        if a["shift"] == "N":
            assert can_night[a["worker"]] is True

    # Weekly participation: each worker gets at least one shift per ISO week
    by_iso_week: dict[tuple[int, int], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for a in assignments:
        d = date.fromisoformat(a["date"])
        iso = d.isocalendar()
        by_iso_week[(iso[0], iso[1])][a["worker"]] += 1

    for iso_key, counts in by_iso_week.items():
        for w in workers:
            assert counts[w["name"]] >= 1, f"Worker {w['name']} missing participation in {iso_key}"

    # Weekday distribution rule (as implemented):
    # if some worker has 0 weekday shifts, then nobody may have > 1 weekday shift.
    for iso_key in by_iso_week.keys():
        weekday_counts = defaultdict(int)
        for a in assignments:
            d = date.fromisoformat(a["date"])
            if d.isocalendar()[:2] != iso_key:
                continue
            if d.weekday() < 5:  # Mon-Fri
                weekday_counts[a["worker"]] += 1

        # ensure keys exist for all workers
        vals = [weekday_counts[w["name"]] for w in workers]
        if min(vals) == 0:
            assert max(vals) <= 1

    # 24h rest constraints: at least MIN_REST_HOURS between shifts for same worker
    shifts_by_worker: dict[str, list[tuple[datetime, datetime, str]]] = defaultdict(list)
    for a in assignments:
        d = date.fromisoformat(a["date"])
        start, end = _shift_window(d, a["shift"])
        shifts_by_worker[a["worker"]].append((start, end, a["shift"]))

    for worker, windows in shifts_by_worker.items():
        windows_sorted = sorted(windows, key=lambda x: x[0])
        for i in range(1, len(windows_sorted)):
            prev_end = windows_sorted[i - 1][1]
            next_start = windows_sorted[i][0]
            assert _rest_hours(prev_end, next_start) >= MIN_REST_HOURS
