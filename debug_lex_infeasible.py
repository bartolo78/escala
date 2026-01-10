#!/usr/bin/env python3
"""Debug script to identify which lexicographic objective builder causes infeasibility."""

from datetime import date
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
    _compute_past_stats,
    _define_current_stats_vars,
)
from history_view import HistoryView
import model_objectives as _mo
from constants import (
    EQUITY_WEIGHTS,
    DOW_EQUITY_WEIGHT,
    MONTHLY_SHIFT_BALANCE_WEIGHT,
)


def main():
    service = SchedulerService()
    service.load_config("config.yaml")
    
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
    stat_indices = _define_stat_indices(shifts, num_shifts, holiday_set)
    
    num_workers = len(workers)
    
    print(f"June 2026: {len(days)} days, {num_shifts} shifts, {num_workers} workers")
    print(f"Holidays: {holiday_set}")
    print(f"ISO weeks: {list(iso_weeks.keys())}")
    
    # Build base model (constraints only)
    def build_base_model():
        model = _create_model()
        assigned = _define_assigned_vars(model, num_workers, num_shifts)
        model = _add_basic_constraints(model, assigned, num_workers, num_shifts, shifts_by_day, workers, shifts)
        unav_parsed, req_parsed = _parse_unavail_and_req(unavail_data, required_data, workers)
        model = _add_unavail_req_constraints(model, assigned, unav_parsed, req_parsed, shifts_by_day, shifts, num_workers)
        model = _add_24h_interval_constraints(model, assigned, shifts, num_shifts, num_workers)
        model = _add_cross_week_interval_constraints(model, assigned, shifts, workers, days, history)
        model = _add_weekly_participation_constraints(model, assigned, iso_weeks, unav_parsed, num_workers)
        model = _fix_previous_assignments(model, assigned, history, workers, days, shifts_by_day, shifts)
        return model, assigned, unav_parsed
    
    # Test base model
    print("\n" + "=" * 60)
    print("Testing base model (constraints only)...")
    model, assigned, unav_parsed = build_base_model()
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10.0
    status = solver.Solve(model)
    print(f"Base model: {['UNKNOWN', 'MODEL_INVALID', 'FEASIBLE', 'INFEASIBLE', 'OPTIMAL'][status]}")
    
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print("Base model is already infeasible - issue is in core constraints!")
        return
    
    # Test adding each objective builder one at a time
    objective_builders = [
        ("sat_pref_cost", lambda m, a, up: _mo.build_saturday_preference_cost(m, iso_weeks, a, num_workers, shifts, up, holiday_set)),
        ("three_day_cost", lambda m, a, up: _mo.build_three_day_weekend_unique_workers_cost(m, iso_weeks, holiday_set, shifts_by_day, a, num_workers)),
        ("weekend_limits_cost", lambda m, a, up: _mo.build_weekend_shift_limits_cost(m, iso_weeks, holiday_set, a, num_workers, shifts)),
        ("consec_weekend_cost", lambda m, a, up: _mo.build_consecutive_weekend_avoidance_cost(m, iso_weeks, holiday_set, history, workers, a, num_workers, shifts, year, month)),
        ("m2_cost", lambda m, a, up: _mo.build_m2_priority_cost(m, shifts, a, workers)),
        ("load_cost", lambda m, a, up: _mo.build_load_balancing_cost(m, iso_weeks, shifts, a, workers)),
        ("consec48_cost", lambda m, a, up: _mo.build_consec_shifts_48h_cost(m, a, shifts, num_shifts, num_workers)),
        ("night_interval_cost", lambda m, a, up: _mo.build_night_shift_min_interval_cost(m, a, shifts, num_shifts, num_workers)),
        ("consec_night_cost", lambda m, a, up: _mo.build_consecutive_night_shift_avoidance_cost(m, a, shifts, num_shifts, num_workers)),
    ]
    
    for name, builder in objective_builders:
        print(f"\n{'-' * 60}")
        print(f"Testing: {name}")
        model, assigned, unav_parsed = build_base_model()
        
        try:
            cost_var = builder(model, assigned, unav_parsed)
            solver = cp_model.CpSolver()
            solver.parameters.max_time_in_seconds = 10.0
            status = solver.Solve(model)
            status_str = ['UNKNOWN', 'MODEL_INVALID', 'FEASIBLE', 'INFEASIBLE', 'OPTIMAL'][status]
            print(f"  Result: {status_str}")
            if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                print(f"  *** FOUND PROBLEMATIC BUILDER: {name} ***")
        except Exception as e:
            print(f"  Error: {e}")
    
    # Test adding all builders together
    print(f"\n{'=' * 60}")
    print("Testing ALL objective builders together...")
    model, assigned, unav_parsed = build_base_model()
    
    for name, builder in objective_builders:
        try:
            cost_var = builder(model, assigned, unav_parsed)
        except Exception as e:
            print(f"Error building {name}: {e}")
    
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30.0
    status = solver.Solve(model)
    status_str = ['UNKNOWN', 'MODEL_INVALID', 'FEASIBLE', 'INFEASIBLE', 'OPTIMAL'][status]
    print(f"All builders: {status_str}")


if __name__ == "__main__":
    main()
