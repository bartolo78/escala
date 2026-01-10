#!/usr/bin/env python3
"""Debug script to identify which constraint causes infeasibility with history."""

from datetime import date, timedelta
from ortools.sat.python import cp_model

from scheduler_service import SchedulerService
from scheduling_engine import (
    _setup_holidays_and_days,
    _create_shifts,
    _group_shifts_by_day,
    _setup_iso_weeks,
    _define_stat_indices,
    _create_model,
    _define_assigned_vars,
    _add_basic_constraints,
    _parse_unavail_and_req,
    _add_unavail_req_constraints,
    _add_24h_interval_constraints,
    _add_cross_week_interval_constraints,
    _add_weekly_participation_constraints,
    _fix_previous_assignments,
)
from history_view import HistoryView


def main():
    service = SchedulerService()
    service.load_config("config.yaml")
    
    # Try to load history
    try:
        service.import_history("logs/maio.json")
        print("History loaded successfully")
    except Exception as e:
        print(f"No history file or error loading: {e}")
    
    year, month = 2026, 6
    
    workers = [w.to_dict() for w in service._workers]
    history = service._history
    unavail_data = service._unavail
    required_data = service._req
    holidays = service.get_holidays(year, month)
    
    # Setup
    holiday_set, all_days = _setup_holidays_and_days(year, month, holidays)
    scheduled_dates = HistoryView(history).scheduled_dates()
    overlap_dates = {str(d) for d in all_days}
    excluded_dates = scheduled_dates.intersection(overlap_dates)
    days = [d for d in all_days if str(d) not in excluded_dates]
    
    shifts, num_shifts = _create_shifts(days)
    shifts_by_day = _group_shifts_by_day(num_shifts, shifts)
    iso_weeks = _setup_iso_weeks(days, shifts, holiday_set)
    
    num_workers = len(workers)
    
    print(f"\nJune 2026: {len(days)} days, {num_shifts} shifts, {num_workers} workers")
    print(f"Holidays: {holiday_set}")
    print(f"History has {len(scheduled_dates)} scheduled dates")
    
    # Check history for May 30-31
    hv = HistoryView(history)
    first_day = days[0]
    print(f"\nFirst scheduling day: {first_day}")
    
    print("\nHistory from days before June 1:")
    for d in [first_day - timedelta(days=2), first_day - timedelta(days=1)]:
        print(f"  {d}:")
        for worker in workers:
            shift = hv.fixed_shift_for(worker["name"], d)
            if shift:
                print(f"    {worker['name']}: {shift}")
    
    # Test incremental constraint addition
    print("\n" + "=" * 70)
    print("INCREMENTAL CONSTRAINT TESTING")
    print("=" * 70)
    
    def test_model(name, model, assigned):
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 10.0
        status = solver.Solve(model)
        status_str = {
            cp_model.OPTIMAL: "OPTIMAL",
            cp_model.FEASIBLE: "FEASIBLE", 
            cp_model.INFEASIBLE: "INFEASIBLE",
            cp_model.MODEL_INVALID: "MODEL_INVALID",
            cp_model.UNKNOWN: "UNKNOWN/TIMEOUT",
        }.get(status, f"STATUS_{status}")
        print(f"  {name}: {status_str}")
        return status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    
    # Step 1: Base model (shift coverage + one-per-day + night restrictions)
    print("\n[1] Base model (coverage + one-per-day + night restrictions):")
    model = _create_model()
    assigned = _define_assigned_vars(model, num_workers, num_shifts)
    model = _add_basic_constraints(model, assigned, num_workers, num_shifts, shifts_by_day, workers, shifts)
    test_model("Base", model, assigned)
    
    # Step 2: Add unavailability
    print("\n[2] + Unavailability/requests:")
    model = _create_model()
    assigned = _define_assigned_vars(model, num_workers, num_shifts)
    model = _add_basic_constraints(model, assigned, num_workers, num_shifts, shifts_by_day, workers, shifts)
    unav_parsed, req_parsed = _parse_unavail_and_req(unavail_data, required_data, workers)
    model = _add_unavail_req_constraints(model, assigned, unav_parsed, req_parsed, shifts_by_day, shifts, num_workers)
    test_model("+ Unavail", model, assigned)
    
    # Step 3: Add 24h interval
    print("\n[3] + 24h interval:")
    model = _create_model()
    assigned = _define_assigned_vars(model, num_workers, num_shifts)
    model = _add_basic_constraints(model, assigned, num_workers, num_shifts, shifts_by_day, workers, shifts)
    unav_parsed, req_parsed = _parse_unavail_and_req(unavail_data, required_data, workers)
    model = _add_unavail_req_constraints(model, assigned, unav_parsed, req_parsed, shifts_by_day, shifts, num_workers)
    model = _add_24h_interval_constraints(model, assigned, shifts, num_shifts, num_workers)
    test_model("+ 24h", model, assigned)
    
    # Step 4: Add cross-week interval
    print("\n[4] + Cross-week interval (from history):")
    model = _create_model()
    assigned = _define_assigned_vars(model, num_workers, num_shifts)
    model = _add_basic_constraints(model, assigned, num_workers, num_shifts, shifts_by_day, workers, shifts)
    unav_parsed, req_parsed = _parse_unavail_and_req(unavail_data, required_data, workers)
    model = _add_unavail_req_constraints(model, assigned, unav_parsed, req_parsed, shifts_by_day, shifts, num_workers)
    model = _add_24h_interval_constraints(model, assigned, shifts, num_shifts, num_workers)
    model = _add_cross_week_interval_constraints(model, assigned, shifts, workers, days, history)
    feasible = test_model("+ Cross-week", model, assigned)
    
    # Step 5: Add weekly participation
    print("\n[5] + Weekly participation:")
    model = _create_model()
    assigned = _define_assigned_vars(model, num_workers, num_shifts)
    model = _add_basic_constraints(model, assigned, num_workers, num_shifts, shifts_by_day, workers, shifts)
    unav_parsed, req_parsed = _parse_unavail_and_req(unavail_data, required_data, workers)
    model = _add_unavail_req_constraints(model, assigned, unav_parsed, req_parsed, shifts_by_day, shifts, num_workers)
    model = _add_24h_interval_constraints(model, assigned, shifts, num_shifts, num_workers)
    model = _add_cross_week_interval_constraints(model, assigned, shifts, workers, days, history)
    model = _add_weekly_participation_constraints(model, assigned, iso_weeks, unav_parsed, num_workers)
    feasible = test_model("+ Participation", model, assigned)
    
    if not feasible:
        print("\n*** INFEASIBLE at step 5 - weekly participation with cross-week constraints ***")
        
        # Try without cross-week to confirm
        print("\n[5b] Without cross-week (participation only):")
        model = _create_model()
        assigned = _define_assigned_vars(model, num_workers, num_shifts)
        model = _add_basic_constraints(model, assigned, num_workers, num_shifts, shifts_by_day, workers, shifts)
        unav_parsed, req_parsed = _parse_unavail_and_req(unavail_data, required_data, workers)
        model = _add_unavail_req_constraints(model, assigned, unav_parsed, req_parsed, shifts_by_day, shifts, num_workers)
        model = _add_24h_interval_constraints(model, assigned, shifts, num_shifts, num_workers)
        # NO cross-week
        model = _add_weekly_participation_constraints(model, assigned, iso_weeks, unav_parsed, num_workers)
        test_model("No cross-week", model, assigned)


if __name__ == "__main__":
    main()
