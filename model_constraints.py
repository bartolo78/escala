"""CP-SAT constraint builders.

These functions operate on OR-Tools `CpModel` and variable arrays. They are split
out of `logic_g4.py` to keep scheduling logic modular and refactor-friendly.

Behavior should remain identical to the original implementations.
"""

from __future__ import annotations

import datetime
from datetime import timedelta

from constants import MIN_REST_HOURS, SHIFTS
from history_view import HistoryView


def create_model(cp_model_module):
    """Create a CpModel.

    Accepts the imported `cp_model` module so callers can avoid circular imports.
    """
    return cp_model_module.CpModel()


def define_assigned_vars(model, num_workers: int, num_shifts: int):
    return [[model.NewBoolVar(f"ass_w{w}_s{s}") for s in range(num_shifts)] for w in range(num_workers)]


def add_basic_constraints(model, assigned, num_workers, num_shifts, shifts_by_day, workers, shifts):
    # Each shift exactly one worker
    for s in range(num_shifts):
        model.AddExactlyOne(assigned[w][s] for w in range(num_workers))

    # No multiple shifts on same day
    for w in range(num_workers):
        for d in shifts_by_day:
            model.Add(sum(assigned[w][s] for s in shifts_by_day[d]) <= 1)

    # No night for some workers
    for w in range(num_workers):
        if not workers[w]["can_night"]:
            for s in range(num_shifts):
                if shifts[s]["night"]:
                    model.Add(assigned[w][s] == 0)

    return model


def add_unavail_req_constraints(model, assigned, unav_parsed, req_parsed, shifts_by_day, shifts, num_workers):
    """Add unavailability and required shift constraints with validation."""
    from logger import get_logger
    logger = get_logger('constraints')
    
    for w in range(num_workers):
        for d, sh in unav_parsed[w]:
            if sh is None:
                if d in shifts_by_day:
                    for s in shifts_by_day[d]:
                        model.Add(assigned[w][s] == 0)
            else:
                if d in shifts_by_day:
                    shift_found = False
                    for s in shifts_by_day[d]:
                        if shifts[s]["type"] == sh:
                            model.Add(assigned[w][s] == 0)
                            shift_found = True
                            break
                    if not shift_found:
                        logger.warning(f"No shift of type '{sh}' found on {d} for unavailability constraint")

        for d, sh in req_parsed[w]:
            if sh is None:
                if d in shifts_by_day:
                    model.Add(sum(assigned[w][s] for s in shifts_by_day[d]) >= 1)
            else:
                if d in shifts_by_day:
                    shift_found = False
                    for s in shifts_by_day[d]:
                        if shifts[s]["type"] == sh:
                            model.Add(assigned[w][s] == 1)
                            shift_found = True
                            break
                    if not shift_found:
                        logger.warning(f"No shift of type '{sh}' found on {d} for required constraint (worker {w})")

    return model


def add_24h_interval_constraints(model, assigned, shifts, num_shifts, num_workers):
    """Add 24h rest interval constraints between shifts.
    
    Optimized to only check shift pairs that could actually conflict (within 48h),
    rather than all O(n²) pairs which explodes for large schedules.
    """
    # Pre-sort shifts by start time for efficient neighbor finding
    sorted_indices = sorted(range(num_shifts), key=lambda s: shifts[s]["start"])
    
    # For each shift, only check shifts within 48 hours (beyond that, 24h rest is guaranteed)
    MAX_CHECK_HOURS = 48
    
    constraints_added = 0
    for w in range(num_workers):
        for idx_i, i in enumerate(sorted_indices):
            si = shifts[i]
            start_i = si["start"]
            end_i = si["end"]
            
            # Only check subsequent shifts within MAX_CHECK_HOURS
            for idx_j in range(idx_i + 1, len(sorted_indices)):
                j = sorted_indices[idx_j]
                sj = shifts[j]
                start_j = sj["start"]
                end_j = sj["end"]
                
                # If shift j starts more than MAX_CHECK_HOURS after shift i ends,
                # no need to check further shifts (they're sorted by start time)
                hours_apart = (start_j - end_i).total_seconds() / 3600
                if hours_apart >= MAX_CHECK_HOURS:
                    break
                
                # Check for overlap
                if max(start_i, start_j) < min(end_i, end_j):
                    model.AddBoolOr([assigned[w][i].Not(), assigned[w][j].Not()])
                    constraints_added += 1
                else:
                    # Check rest interval
                    if start_j >= end_i:
                        delta = (start_j - end_i).total_seconds() / 3600
                        if delta < MIN_REST_HOURS:
                            model.AddBoolOr([assigned[w][i].Not(), assigned[w][j].Not()])
                            constraints_added += 1
                    elif start_i >= end_j:
                        delta = (start_i - end_j).total_seconds() / 3600
                        if delta < MIN_REST_HOURS:
                            model.AddBoolOr([assigned[w][i].Not(), assigned[w][j].Not()])
                            constraints_added += 1

    return model


def add_cross_week_interval_constraints(model, assigned, shifts, workers, days, history):
    """
    Add 24-hour interval constraints across ISO week boundaries.
    
    When scheduling a new set of ISO weeks, this function checks if any worker
    had a shift at the end of a previously scheduled week (from history) that
    would conflict with shifts at the start of the current scheduling window.
    
    This is critical because the main add_24h_interval_constraints function only
    considers shifts within the current scheduling window, not historical shifts.
    """
    import logging
    logger = logging.getLogger('escala')
    
    if not days or not history:
        return model

    hv = HistoryView(history)
    first_day = days[0]
    
    # Only check shifts in the first 2 days of the window — later shifts can't
    # possibly conflict with history from 1-2 days before (24h rest is satisfied).
    early_window_cutoff = datetime.datetime.combine(
        first_day + timedelta(days=2), datetime.time()
    )
    
    # Check shifts from the 2 days before the scheduling window starts.
    # This covers all scenarios since the maximum rest needed is 24 hours:
    # - A night shift ending at 08:00 on day-0 (first_day) could conflict with day shifts on first_day
    # - An M2 shift ending at 23:00 on day-1 could conflict with shifts starting before 23:00+24h on first_day
    days_to_check = [
        first_day - timedelta(days=1),  # Yesterday
        first_day - timedelta(days=2),  # Day before yesterday (for completeness)
    ]
    
    blocked_count = 0
    for w_idx, worker in enumerate(workers):
        w_name = worker["name"]
        
        for hist_day in days_to_check:
            hist_shift_type = hv.fixed_shift_for(w_name, hist_day)
            if hist_shift_type is None:
                continue
            
            # Get end time of the historical shift
            hist_config = SHIFTS.get(hist_shift_type)
            if hist_config is None:
                continue
            
            hist_day_dt = datetime.datetime.combine(hist_day, datetime.time())
            hist_end = hist_day_dt + timedelta(hours=hist_config["end_hour"])
            
            # Check only early shifts in the scheduling window that could conflict
            for s_idx, shift in enumerate(shifts):
                shift_start = shift["start"]
                
                # Skip shifts that are far enough into the window to never conflict
                if shift_start >= early_window_cutoff:
                    continue
                
                # If the new shift starts before or exactly when the historical shift ends,
                # they overlap, which is definitely not allowed
                if shift_start <= hist_end:
                    model.Add(assigned[w_idx][s_idx] == 0)
                    blocked_count += 1
                    logger.info(f"Cross-week block: {w_name} blocked from shift {s_idx} on {shift['day']} {shift['type']} (overlap with {hist_shift_type} on {hist_day})")
                    continue
                
                # If the new shift starts after the historical shift ends,
                # check if there's enough rest time (>= MIN_REST_HOURS)
                delta_hours = (shift_start - hist_end).total_seconds() / 3600
                
                if delta_hours < MIN_REST_HOURS:
                    # This shift would violate the 24-hour rest rule
                    model.Add(assigned[w_idx][s_idx] == 0)
                    blocked_count += 1
                    logger.info(f"Cross-week block: {w_name} blocked from shift {s_idx} on {shift['day']} {shift['type']} ({delta_hours:.1f}h rest after {hist_shift_type} on {hist_day})")
    
    if blocked_count > 0:
        logger.info(f"Cross-week constraints: {blocked_count} worker-shift combinations blocked due to history")
    

def add_weekly_participation_constraints(model, assigned, iso_weeks, unav_parsed, num_workers):
    """Add weekly participation constraints per RULES.md.
    
    Weekly Participation: each worker with at least one available weekday must get
    at least one shift (weekday OR weekend) during that ISO week.
    
    Note: The weekday distribution rule ("no 2nd weekday shift until all have 1st")
    is intentionally NOT enforced as a hard constraint here. With 15 workers, 15
    weekday shifts, and the 24h rest + night restrictions, it can create infeasibility
    when some workers are blocked from all weekday shifts. The solver's equity
    objectives naturally encourage fair distribution without causing infeasibility.
    """
    import logging
    logger = logging.getLogger('escala')
    for key in iso_weeks:
        week = iso_weeks[key]
        relevant = []

        # Use weekdays_for_distribution (Mon-Fri including holidays) to determine eligibility
        for w in range(num_workers):
            avail_weekdays = [wd for wd in week["weekdays_for_distribution"] if (wd, None) not in unav_parsed[w]]
            if len(avail_weekdays) >= 1:
                relevant.append(w)

        num_relevant = len(relevant)
        total_weekday_shifts = len(week["weekday_shifts_for_distribution"])

        logger.info(f"WEEK {key}: num_relevant={num_relevant}, total_weekday_shifts={total_weekday_shifts}, relevant_workers={relevant}")
        logger.info(f"  weekdays_for_distribution: {week['weekdays_for_distribution']}")
        logger.info(f"  weekday_shifts_for_distribution: {week['weekday_shifts_for_distribution']}")
        logger.info(f"  all shifts: {week['shifts']}")

        # Weekly Participation (RULES.md): each eligible worker must have >=1 shift in the ISO week.
        # Eligibility is based on having at least one available weekday in that ISO week.
        # The shift can be on any day (weekday or weekend).
        for w in relevant:
            num_shifts_week = sum(assigned[w][s] for s in week["shifts"])
            model.Add(num_shifts_week >= 1)

        logger.info(f"  Weekly participation: {num_relevant} workers each need >=1 shift from {len(week['shifts'])} available")

    return model


def fix_previous_assignments(model, assigned, history, workers, days, shifts_by_day, shifts):
    hv = HistoryView(history)
    for day in days:
        for w_idx, worker in enumerate(workers):
            w_name = worker["name"]
            shift_type = hv.fixed_shift_for(w_name, day)
            if shift_type is None:
                continue
            for s in shifts_by_day[day]:
                if shifts[s]["type"] == shift_type:
                    model.Add(assigned[w_idx][s] == 1)
                    break
    return model
