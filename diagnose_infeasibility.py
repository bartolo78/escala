#!/usr/bin/env python3
"""
Diagnostic script to identify the exact constraint causing infeasibility.

Run this script with history loaded to pinpoint which constraint makes the model infeasible.
"""

from datetime import date, timedelta
from ortools.sat.python import cp_model

from scheduler_service import SchedulerService
from scheduling_engine import (
    _setup_holidays_and_days,
    _create_shifts,
    _group_shifts_by_day,
    _setup_iso_weeks,
)
from model_constraints import (
    add_basic_constraints,
    add_unavail_req_constraints,
    add_24h_interval_constraints,
    add_cross_week_interval_constraints,
    add_weekly_participation_constraints,
    fix_previous_assignments,
)
from history_view import HistoryView
from logger import get_logger

logger = get_logger('diagnose')


def test_feasibility(model, name, timeout=30.0):
    """Test if model is feasible and return status."""
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = timeout
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)
    status_str = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.MODEL_INVALID: "MODEL_INVALID",
        cp_model.UNKNOWN: "UNKNOWN/TIMEOUT",
    }.get(status, f"STATUS_{status}")
    is_ok = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    print(f"  {name}: {status_str} ({solver.WallTime():.2f}s)")
    return is_ok, status_str


def main():
    print("=" * 70)
    print("INFEASIBILITY DIAGNOSTIC")
    print("=" * 70)
    
    # Load service and config
    service = SchedulerService()
    service.load_config("config.yaml")
    
    # Try to load history
    print("\nLoading history...")
    try:
        # Try the service's load_history method first
        if service.load_history("logs/maio.json"):
            print(f"  History loaded via load_history: {len(service._history)} workers")
        else:
            # Fallback to direct loading
            import json
            with open("logs/maio.json", 'r') as f:
                loaded_history = json.load(f)
            service._history = loaded_history
            print(f"  History loaded directly: {len(service._history)} workers")
    except Exception as e:
        print(f"  No history file or error: {e}")
        print("  Running without history - if this works, the history is the problem")
    
    year, month = 2026, 6
    
    workers = [w.to_dict() for w in service._workers]
    history = service._history
    unavail_data = service._unavail
    required_data = service._req
    holidays = service.get_holidays(year, month)
    
    print(f"\nConfiguration:")
    print(f"  Workers: {len(workers)}")
    print(f"  Unavailabilities: {sum(len(v) for v in unavail_data.values())} entries")
    print(f"  Required shifts: {sum(len(v) for v in required_data.values())} entries")
    print(f"  Holidays: {holidays}")
    
    # Setup
    holiday_set, all_days = _setup_holidays_and_days(year, month, holidays)
    scheduled_dates = HistoryView(history).scheduled_dates()
    overlap_dates = {str(d) for d in all_days}
    excluded_dates = scheduled_dates.intersection(overlap_dates)
    days = [d for d in all_days if str(d) not in excluded_dates]
    
    print(f"\nScheduling window:")
    print(f"  Full window: {all_days[0]} to {all_days[-1]} ({len(all_days)} days)")
    print(f"  Scheduled in history: {len(excluded_dates)} dates excluded")
    print(f"  Days to optimize: {len(days)} ({days[0]} to {days[-1]})" if days else "  No days to optimize!")
    
    if not days:
        print("\nERROR: No days to schedule - all days already in history")
        return
    
    shifts, num_shifts = _create_shifts(days)
    shifts_by_day = _group_shifts_by_day(num_shifts, shifts)
    iso_weeks = _setup_iso_weeks(days, shifts, holiday_set)
    num_workers = len(workers)
    
    print(f"  Shifts to assign: {num_shifts}")
    print(f"  ISO weeks: {list(iso_weeks.keys())}")
    
    # Parse unavailability
    from scheduling_engine import parse_unavail_or_req
    unav_parsed = []
    req_parsed = []
    for worker in workers:
        w_name = worker["name"]
        unav_parsed.append(parse_unavail_or_req(unavail_data.get(w_name, []), is_unavail=True))
        req_parsed.append(parse_unavail_or_req(required_data.get(w_name, []), is_unavail=False))
    
    # Show history summary for first few days
    hv = HistoryView(history)
    print(f"\nHistory for days before {days[0]}:")
    for delta in [1, 2]:
        check_day = days[0] - timedelta(days=delta)
        print(f"  {check_day} ({check_day.strftime('%A')}):")
        shifts_found = []
        for w in workers:
            shift = hv.fixed_shift_for(w["name"], check_day)
            if shift:
                shifts_found.append(f"{w['name']}: {shift}")
        if shifts_found:
            for sf in shifts_found[:5]:
                print(f"    {sf}")
            if len(shifts_found) > 5:
                print(f"    ... and {len(shifts_found) - 5} more")
        else:
            print("    (no shifts)")
    
    # Incremental constraint testing
    print("\n" + "=" * 70)
    print("INCREMENTAL CONSTRAINT TESTING")
    print("=" * 70)
    
    def create_base_model():
        model = cp_model.CpModel()
        assigned = [[model.NewBoolVar(f"a_w{w}_s{s}") for s in range(num_shifts)] for w in range(num_workers)]
        return model, assigned
    
    # Test 1: Just coverage constraint (each shift has exactly one worker)
    print("\n[1] Shift coverage (each shift exactly one worker):")
    model, assigned = create_base_model()
    for s in range(num_shifts):
        model.AddExactlyOne(assigned[w][s] for w in range(num_workers))
    ok1, _ = test_feasibility(model, "Coverage only")
    
    # Test 2: + One shift per day per worker
    print("\n[2] + One shift per day:")
    model, assigned = create_base_model()
    for s in range(num_shifts):
        model.AddExactlyOne(assigned[w][s] for w in range(num_workers))
    for w in range(num_workers):
        for d, day_shifts in shifts_by_day.items():
            model.Add(sum(assigned[w][s] for s in day_shifts) <= 1)
    ok2, _ = test_feasibility(model, "+ One/day")
    
    # Test 3: + Night restrictions
    print("\n[3] + Night restrictions:")
    model, assigned = create_base_model()
    add_basic_constraints(model, assigned, num_workers, num_shifts, shifts_by_day, workers, shifts)
    ok3, _ = test_feasibility(model, "+ Night restrictions")
    
    # Test 4: + Unavailability/requests
    print("\n[4] + Unavailability/Required:")
    model, assigned = create_base_model()
    add_basic_constraints(model, assigned, num_workers, num_shifts, shifts_by_day, workers, shifts)
    add_unavail_req_constraints(model, assigned, unav_parsed, req_parsed, shifts_by_day, shifts, num_workers)
    ok4, _ = test_feasibility(model, "+ Unavail/Req")
    
    # Test 5: + 24h interval
    print("\n[5] + 24h interval:")
    model, assigned = create_base_model()
    add_basic_constraints(model, assigned, num_workers, num_shifts, shifts_by_day, workers, shifts)
    add_unavail_req_constraints(model, assigned, unav_parsed, req_parsed, shifts_by_day, shifts, num_workers)
    add_24h_interval_constraints(model, assigned, shifts, num_shifts, num_workers)
    ok5, _ = test_feasibility(model, "+ 24h interval")
    
    # Test 6: + Cross-week interval (from history)
    print("\n[6] + Cross-week interval (from history):")
    model, assigned = create_base_model()
    add_basic_constraints(model, assigned, num_workers, num_shifts, shifts_by_day, workers, shifts)
    add_unavail_req_constraints(model, assigned, unav_parsed, req_parsed, shifts_by_day, shifts, num_workers)
    add_24h_interval_constraints(model, assigned, shifts, num_shifts, num_workers)
    add_cross_week_interval_constraints(model, assigned, shifts, workers, days, history)
    ok6, _ = test_feasibility(model, "+ Cross-week")
    
    # Test 7: + Weekly participation
    print("\n[7] + Weekly participation:")
    model, assigned = create_base_model()
    add_basic_constraints(model, assigned, num_workers, num_shifts, shifts_by_day, workers, shifts)
    add_unavail_req_constraints(model, assigned, unav_parsed, req_parsed, shifts_by_day, shifts, num_workers)
    add_24h_interval_constraints(model, assigned, shifts, num_shifts, num_workers)
    add_cross_week_interval_constraints(model, assigned, shifts, workers, days, history)
    add_weekly_participation_constraints(model, assigned, iso_weeks, unav_parsed, num_workers)
    ok7, _ = test_feasibility(model, "+ Participation")
    
    # Test 8: + Fix previous assignments
    print("\n[8] + Fix previous assignments:")
    model, assigned = create_base_model()
    add_basic_constraints(model, assigned, num_workers, num_shifts, shifts_by_day, workers, shifts)
    add_unavail_req_constraints(model, assigned, unav_parsed, req_parsed, shifts_by_day, shifts, num_workers)
    add_24h_interval_constraints(model, assigned, shifts, num_shifts, num_workers)
    add_cross_week_interval_constraints(model, assigned, shifts, workers, days, history)
    add_weekly_participation_constraints(model, assigned, iso_weeks, unav_parsed, num_workers)
    fix_previous_assignments(model, assigned, history, workers, days, shifts_by_day, shifts)
    ok8, _ = test_feasibility(model, "+ Fix previous")
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    results = [
        ("Shift coverage", ok1),
        ("+ One/day", ok2),
        ("+ Night restrictions", ok3),
        ("+ Unavail/Req", ok4),
        ("+ 24h interval", ok5),
        ("+ Cross-week", ok6),
        ("+ Participation", ok7),
        ("+ Fix previous", ok8),
    ]
    
    first_fail = None
    for name, ok in results:
        status = "✓ OK" if ok else "✗ FAILED"
        print(f"  {name}: {status}")
        if not ok and first_fail is None:
            first_fail = name
    
    if first_fail:
        print(f"\n*** First failure at: {first_fail} ***")
        print("The constraint at this step makes the model infeasible.")
        print("Check the constraint logic and input data for conflicts.")
        return
    
    # If base constraints pass, test the objective builders
    print("\n" + "=" * 70)
    print("TESTING OBJECTIVE BUILDERS")
    print("=" * 70)
    print("(These should only add soft constraints, not cause infeasibility)")
    
    import model_objectives as _mo
    from constants import EQUITY_WEIGHTS, DOW_EQUITY_WEIGHT, MONTHLY_SHIFT_BALANCE_WEIGHT
    
    # Compute stat_indices and current_stats for equity
    from scheduling_engine import _define_stat_indices, _compute_past_stats
    stat_indices = _define_stat_indices(shifts, num_shifts, holiday_set)
    past_stats = _compute_past_stats(history, workers)
    
    def create_full_model():
        """Create model with all base constraints."""
        model = cp_model.CpModel()
        assigned = [[model.NewBoolVar(f"a_w{w}_s{s}") for s in range(num_shifts)] for w in range(num_workers)]
        add_basic_constraints(model, assigned, num_workers, num_shifts, shifts_by_day, workers, shifts)
        add_unavail_req_constraints(model, assigned, unav_parsed, req_parsed, shifts_by_day, shifts, num_workers)
        add_24h_interval_constraints(model, assigned, shifts, num_shifts, num_workers)
        add_cross_week_interval_constraints(model, assigned, shifts, workers, days, history)
        add_weekly_participation_constraints(model, assigned, iso_weeks, unav_parsed, num_workers)
        fix_previous_assignments(model, assigned, history, workers, days, shifts_by_day, shifts)
        return model, assigned
    
    # Test each objective builder
    print("\n[9] + Saturday preference cost:")
    model, assigned = create_full_model()
    _mo.build_saturday_preference_cost(model, iso_weeks, assigned, num_workers, shifts, unav_parsed, holiday_set)
    ok9, _ = test_feasibility(model, "+ Sat pref")
    
    print("\n[10] + 3-day weekend cost:")
    model, assigned = create_full_model()
    _mo.build_three_day_weekend_unique_workers_cost(model, iso_weeks, holiday_set, shifts_by_day, assigned, num_workers)
    ok10, _ = test_feasibility(model, "+ 3-day wknd")
    
    print("\n[11] + Weekend shift limits cost:")
    model, assigned = create_full_model()
    _mo.build_weekend_shift_limits_cost(model, iso_weeks, holiday_set, assigned, num_workers, shifts)
    ok11, _ = test_feasibility(model, "+ Wknd limits")
    
    print("\n[12] + Consecutive weekend avoidance cost:")
    model, assigned = create_full_model()
    _mo.build_consecutive_weekend_avoidance_cost(model, iso_weeks, holiday_set, history, workers, assigned, num_workers, shifts, year, month)
    ok12, _ = test_feasibility(model, "+ Consec wknd")
    
    print("\n[13] + All objectives combined:")
    model, assigned = create_full_model()
    current_stats, current_dow = _mo.define_current_stats_vars(model, assigned, stat_indices, num_workers)
    _mo.build_saturday_preference_cost(model, iso_weeks, assigned, num_workers, shifts, unav_parsed, holiday_set)
    _mo.build_three_day_weekend_unique_workers_cost(model, iso_weeks, holiday_set, shifts_by_day, assigned, num_workers)
    _mo.build_weekend_shift_limits_cost(model, iso_weeks, holiday_set, assigned, num_workers, shifts)
    _mo.build_consecutive_weekend_avoidance_cost(model, iso_weeks, holiday_set, history, workers, assigned, num_workers, shifts, year, month)
    _mo.build_m2_priority_cost(model, shifts, assigned, workers)
    _mo.build_load_balancing_cost(model, iso_weeks, shifts, assigned, workers)
    _mo.build_equity_cost_scaled(model, EQUITY_WEIGHTS, past_stats, current_stats, workers, num_workers)
    _mo.build_dow_equity_cost_scaled(model, DOW_EQUITY_WEIGHT, past_stats, current_dow, workers, num_workers)
    _mo.build_monthly_shift_balance_cost(model, assigned, num_workers, num_shifts, MONTHLY_SHIFT_BALANCE_WEIGHT)
    _mo.build_consec_shifts_48h_cost(model, assigned, shifts, num_shifts, num_workers)
    _mo.build_night_shift_min_interval_cost(model, assigned, shifts, num_shifts, num_workers)
    _mo.build_consecutive_night_shift_avoidance_cost(model, assigned, shifts, num_shifts, num_workers)
    _mo.build_tiebreak_cost(model, assigned, num_workers, num_shifts, workers)
    ok13, _ = test_feasibility(model, "+ All objectives")
    
    # Final summary
    print("\n" + "=" * 70)
    print("OBJECTIVE BUILDER SUMMARY")
    print("=" * 70)
    obj_results = [
        ("+ Sat pref", ok9),
        ("+ 3-day wknd", ok10),
        ("+ Wknd limits", ok11),
        ("+ Consec wknd", ok12),
        ("+ All objectives", ok13),
    ]
    
    obj_fail = None
    for name, ok in obj_results:
        status = "✓ OK" if ok else "✗ FAILED"
        print(f"  {name}: {status}")
        if not ok and obj_fail is None:
            obj_fail = name
    
    if obj_fail:
        print(f"\n*** Objective builder failure at: {obj_fail} ***")
        print("This objective builder is adding constraints that cause infeasibility.")
    else:
        print("\nAll constraints and objectives pass!")
        print("The model should be feasible. If you're still seeing issues:")
        print("  1. Try increasing SOLVER_TIMEOUT_SECONDS in constants.py")
        print("  2. Check if the solver is returning UNKNOWN vs INFEASIBLE")
        print("  3. The issue may be in the staged optimization, not feasibility")


if __name__ == "__main__":
    main()
