"""Solve/extract/merge pipeline for schedule generation.

This module contains the orchestration pieces that sit between the CP-SAT model
and the app-facing outputs (schedule dict, weekly summary, assignments list).

It is extracted from `logic_g4.py` to reduce file size and make later rule
alignment safer.

Behavior is intended to remain identical to the original implementation.
"""

from __future__ import annotations

import time
from datetime import date
from typing import TYPE_CHECKING

from ortools.sat.python import cp_model

from constants import EQUITY_STATS, SHIFT_TYPES, SOLVER_TIMEOUT_SECONDS
from logger import get_logger

_pipeline_logger = get_logger('schedule_pipeline')
from history_view import HistoryView

if TYPE_CHECKING:
    from constraint_diagnostics import DiagnosticReport


def solve_and_extract_results(
    logger,
    model,
    shifts,
    num_shifts,
    days,
    month,
    shifts_by_day,
    iso_weeks,
    workers,
    assigned,
    current_stats,
    stage_objectives: list[tuple[str, cp_model.IntVar]] | None = None,
    diagnostic_context: dict | None = None,
):
    # One shared time budget for either single-shot or staged solves.
    start_t = time.time()

    logger.info("Starting schedule optimization...")

    stage_values: dict[str, int] = {}
    status = None
    solver = None

    if stage_objectives:
        best_solver = None
        best_status = None

        # Staged optimization: process each objective in priority order.
        # Unlike a pure feasibility check (no objective), we use the first stage's
        # objective from the start. This helps OR-Tools' search strategy find
        # feasible solutions more effectively, especially for tightly constrained
        # problems with cross-week history constraints.
        for idx, (stage_name, obj_var) in enumerate(stage_objectives):
            elapsed = time.time() - start_t
            remaining = max(0.1, SOLVER_TIMEOUT_SECONDS - elapsed)
            stages_left = max(1, len(stage_objectives) - idx)
            
            # First stage gets most of the time budget to find feasibility
            if idx == 0:
                per_stage = max(220.0, remaining * 0.9)
            else:
                per_stage = max(1.0, remaining / stages_left)
            
            # Stop if we're running low on time
            if remaining < 2.0 and idx > 0:
                logger.info(f"Stopping optimization early - {remaining:.1f}s remaining")
                break

            stage_solver = cp_model.CpSolver()
            stage_solver.parameters.max_time_in_seconds = per_stage
            stage_solver.parameters.log_search_progress = False
            # Use parallel search for all stages
            stage_solver.parameters.num_search_workers = 8

            model.Minimize(obj_var)
            stage_status = stage_solver.Solve(model)
            
            if stage_status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                if idx == 0:
                    # First stage failed - no feasible solution found
                    status_name = {
                        cp_model.INFEASIBLE: "INFEASIBLE",
                        cp_model.MODEL_INVALID: "MODEL_INVALID",
                        cp_model.UNKNOWN: "UNKNOWN/TIMEOUT",
                    }.get(stage_status, f"STATUS_{stage_status}")
                    logger.error(f"Stage '{stage_name}' failed with status {status_name} after {stage_solver.WallTime():.1f}s")
                    solver = None
                    status = None
                    break
                else:
                    # Later stage timed out - keep the best solution we have
                    logger.warning(f"Stage '{stage_name}' timed out, keeping previous solution")
                    break

            v = int(stage_solver.Value(obj_var))
            stage_values[stage_name] = v
            logger.info(f"Stage {stage_name}: value={v}")

            # Fix the optimal value for the next stage.
            model.Add(obj_var == v)

            best_solver = stage_solver
            best_status = stage_status
            solver = stage_solver
            status = stage_status
    else:
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = SOLVER_TIMEOUT_SECONDS
        solver.parameters.log_search_progress = False
        status = solver.Solve(model)

    # If staged solving failed before any feasible stage, fall back to an empty result.
    if solver is None or status is None:
        logger.error("Solver or status is None - no feasible solution found in any stage")
        stats = {
            "wall_time": 0.0,
            "branches": 0,
            "conflicts": 0,
            "objective_value": None,
            "status": cp_model.UNKNOWN,
            "diagnostic_report": None,
            "error": "No feasible solution found in staged optimization"
        }
        if stage_values:
            stats["stage_values"] = stage_values

        # Run diagnostics if context is provided
        if diagnostic_context:
            diagnostic_report = _run_infeasibility_diagnostics(logger, diagnostic_context)
            stats["diagnostic_report"] = diagnostic_report

        return {}, {}, [], stats, {}

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
        "diagnostic_report": None,
    }
    if stage_values:
        stats["stage_values"] = stage_values

    # Run diagnostics if infeasible and context is provided
    if status == cp_model.INFEASIBLE and diagnostic_context:
        logger.warning("Schedule is INFEASIBLE. Running constraint diagnostics...")
        diagnostic_report = _run_infeasibility_diagnostics(logger, diagnostic_context)
        stats["diagnostic_report"] = diagnostic_report
        logger.info(f"Diagnostic summary: {diagnostic_report.summary}")

    current_stats_computed = {
        stat: [solver.Value(current_stats[stat][w]) for w in range(len(workers))] for stat in EQUITY_STATS
    } if status in [cp_model.OPTIMAL, cp_model.FEASIBLE] else {}


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


def merge_history_into_results(schedule, weekly, assignments, all_days, history, workers, selected_month):
    """Integrate prior assignments for the selected month from history."""

    history_by_date = HistoryView(history).assignments_by_date()

    month_history_dates = 0
    for d_str in history_by_date.keys():
        try:
            d = date.fromisoformat(d_str)
        except ValueError:
            continue
        if d.month == selected_month:
            month_history_dates += 1

    _pipeline_logger.info(f"Merging history for month {selected_month}")
    _pipeline_logger.info(
        f"History has {month_history_dates} dates with assignments in month {selected_month}"
    )

    for d in all_days:
        if d.month == selected_month:
            d_str = str(d)
            entries = history_by_date.get(d_str, [])
            if not entries:
                continue
            schedule.setdefault(d_str, {})
            for entry in entries:
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

    # Compute weekly stats for weeks with history assignments in the selected month
    weeks_with_history = set()
    for d_str, entries in history_by_date.items():
        try:
            d = date.fromisoformat(d_str)
            if d.month == selected_month:
                weeks_with_history.add(d.isocalendar()[:2])
        except ValueError:
            continue

    for key in weeks_with_history:
        if key not in weekly:
            weekly[key] = {}

        days_in_week = {str(d) for d in iso_week_days.get(key, []) if d.month == selected_month}
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


def _run_infeasibility_diagnostics(logger, diagnostic_context: dict):
    """Run constraint diagnostics when solver returns INFEASIBLE.

    Args:
        logger: Logger instance
        diagnostic_context: Dict containing scheduling context needed for diagnostics

    Returns:
        DiagnosticReport with analysis results
    """
    from constraint_diagnostics import run_diagnostics

    return run_diagnostics(
        workers=diagnostic_context["workers"],
        days=diagnostic_context["days"],
        shifts=diagnostic_context["shifts"],
        shifts_by_day=diagnostic_context["shifts_by_day"],
        iso_weeks=diagnostic_context["iso_weeks"],
        unav_parsed=diagnostic_context["unav_parsed"],
        req_parsed=diagnostic_context["req_parsed"],
        holiday_set=diagnostic_context["holiday_set"],
        logger=logger,
        full_analysis=True,
    )
    return schedule, weekly, assignments
