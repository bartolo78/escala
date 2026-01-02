"""Solve/extract/merge pipeline for schedule generation.

This module contains the orchestration pieces that sit between the CP-SAT model
and the app-facing outputs (schedule dict, weekly summary, assignments list).

It is extracted from `logic_g4.py` to reduce file size and make later rule
alignment safer.

Behavior is intended to remain identical to the original implementation.
"""

from __future__ import annotations

from datetime import date

from ortools.sat.python import cp_model

from constants import EQUITY_STATS, SHIFT_TYPES, SOLVER_TIMEOUT_SECONDS
from history_view import HistoryView


def solve_and_extract_results(logger, model, shifts, num_shifts, days, month, shifts_by_day, iso_weeks, workers, assigned, current_stats):
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = SOLVER_TIMEOUT_SECONDS
    solver.parameters.log_search_progress = False  # Disable verbose solver output

    logger.info("Starting schedule optimization...")
    status = solver.Solve(model)

    wall_time = solver.WallTime()
    branches = solver.NumBranches()
    conflicts = solver.NumConflicts()
    objective_value = solver.ObjectiveValue() if status in [cp_model.OPTIMAL, cp_model.FEASIBLE] else None

    if status == cp_model.OPTIMAL:
        status_str = "OPTIMAL"
    elif status == cp_model.FEASIBLE:
        status_str = "FEASIBLE"
    elif status == cp_model.INFEASIBLE:
        status_str = "INFEASIBLE"
    elif status == cp_model.MODEL_INVALID:
        status_str = "MODEL_INVALID"
    else:
        status_str = f"UNKNOWN({status})"

    logger.info(
        f"Solver finished: status={status_str}, time={wall_time:.2f}s, branches={branches}, conflicts={conflicts}"
    )
    if objective_value is not None:
        logger.info(f"Objective value: {objective_value:.2f}")

    stats = {
        "wall_time": wall_time,
        "branches": branches,
        "conflicts": conflicts,
        "objective_value": objective_value,
        "status": status,
    }

    current_stats_computed = {
        stat: [solver.Value(current_stats[stat][w]) for w in range(len(workers))] for stat in EQUITY_STATS
    }

    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        schedule = {}
        for day in days:
            if day.month == month:
                day_str = str(day)
                schedule[day_str] = {}
                for st in SHIFT_TYPES:
                    for s in shifts_by_day[day]:
                        if shifts[s]["type"] == st:
                            for w in range(len(workers)):
                                if solver.Value(assigned[w][s]) == 1:
                                    schedule[day_str][st] = workers[w]["name"]
                                    break

        weekly = {}
        for key in iso_weeks:
            weekly[key] = {}
            for w in range(len(workers)):
                hours = sum(shifts[s]["dur"] * solver.Value(assigned[w][s]) for s in iso_weeks[key]["shifts"])
                load = workers[w]["weekly_load"]
                overtime = max(0, hours - load)
                undertime = max(0, load - hours)
                weekly[key][workers[w]["name"]] = {
                    "hours": hours,
                    "overtime": overtime,
                    "undertime": undertime,
                }

        assignments = []
        for s in range(num_shifts):
            for w in range(len(workers)):
                if solver.Value(assigned[w][s]) == 1:
                    assignments.append(
                        {
                            "worker": workers[w]["name"],
                            "date": str(shifts[s]["day"]),
                            "shift": shifts[s]["type"],
                            "dur": shifts[s]["dur"],
                        }
                    )

        return schedule, weekly, assignments, stats, current_stats_computed

    return {}, {}, [], stats, {}


def merge_excluded_weeks_into_results(schedule, weekly, assignments, excluded_week_keys, all_days, history, workers, selected_month):
    """Integrate prior assignments for ISO weeks that were excluded from optimization."""

    history_by_date = HistoryView(history).assignments_by_date()

    for d in all_days:
        iso_key = d.isocalendar()[:2]
        if iso_key in excluded_week_keys and d.month == selected_month:
            d_str = str(d)
            if d_str not in schedule:
                schedule[d_str] = {}
            for entry in history_by_date.get(d_str, []):
                schedule[d_str][entry["shift"]] = entry["worker"]
                assignments.append(
                    {
                        "worker": entry["worker"],
                        "date": d_str,
                        "shift": entry["shift"],
                        "dur": entry.get("dur", 0),
                    }
                )

    iso_week_days = {}
    for d in all_days:
        key = d.isocalendar()[:2]
        iso_week_days.setdefault(key, []).append(d)

    worker_loads = {w["name"]: w.get("weekly_load", 0) for w in workers}

    for key in excluded_week_keys:
        if key not in weekly:
            weekly[key] = {}

        days_in_week = {str(d) for d in iso_week_days.get(key, [])}
        hours_by_worker = {}
        for d_str in days_in_week:
            for entry in history_by_date.get(d_str, []):
                hours_by_worker[entry["worker"]] = hours_by_worker.get(entry["worker"], 0) + entry.get("dur", 0)

        for wk_name, wk_hours in hours_by_worker.items():
            load = worker_loads.get(wk_name, 0)
            overtime = max(0, wk_hours - load)
            undertime = max(0, load - wk_hours)
            weekly[key][wk_name] = {"hours": wk_hours, "overtime": overtime, "undertime": undertime}

    return schedule, weekly, assignments
