from ortools.sat.python import cp_model
from datetime import date, timedelta
from utils import compute_holidays
from constants import (
    DOW_EQUITY_WEIGHT,
    EQUITY_WEIGHTS,
    OBJECTIVE_FLEX_WEIGHTS,
    OBJECTIVE_WEIGHT_LOAD,
    SHIFT_TYPES,
)
from scheduler_builders import (
    setup_holidays_and_days as _setup_holidays_and_days_pure,
    create_shifts as _create_shifts_pure,
    group_shifts_by_day as _group_shifts_by_day_pure,
    setup_iso_weeks as _setup_iso_weeks_pure,
    define_stat_indices as _define_stat_indices_pure,
)
from history_view import HistoryView
from logger import get_logger
import model_constraints as _mc
import model_objectives as _mo
import schedule_pipeline as _sp

logger = get_logger('logic')


def get_scheduled_iso_weeks(history: dict) -> set:
    """
    Get set of (iso_year, iso_week) tuples that have already been scheduled.
    An ISO week is considered scheduled if ANY assignment exists for any day in that week.
    """
    return HistoryView(history).scheduled_iso_weeks()


def is_vacation_week(worker_name: str, week_days: list, unav_parsed: set) -> bool:
    """
    Check if worker has no available weekdays (Mon-Fri) in the given ISO week.
    A vacation week means the worker cannot be scheduled for any weekday.
    """
    weekdays_available = 0
    for d in week_days:
        if d.weekday() < 5:  # Monday=0 to Friday=4
            # Check if date is not in unavailable set
            if (d, None) not in unav_parsed:
                weekdays_available += 1
    return weekdays_available == 0

def parse_unavail_or_req(unav_list, is_unavail=True):
    unav_set = set()
    for item in unav_list:
        parts = item.split()
        if len(parts) == 1:
            # Single date only (no range, no shift)
            unav_set.add((date.fromisoformat(item), None))
        elif len(parts) == 2:
            # date shift
            d = date.fromisoformat(parts[0])
            sh = parts[1]
            if sh in SHIFT_TYPES:
                unav_set.add((d, sh))
            else:
                # Invalid, ignore
                pass
        elif len(parts) == 3 and parts[1] == 'to':
            # Date range: "YYYY-MM-DD to YYYY-MM-DD"
            start_d = date.fromisoformat(parts[0])
            end_d = date.fromisoformat(parts[2])
            d = start_d
            while d <= end_d:
                unav_set.add((d, None))
                d += timedelta(days=1)
    return unav_set

def update_history(assignments, history):
    ass_by_month = {}
    for ass in assignments:
        day = date.fromisoformat(ass['date'])
        m_y = day.strftime('%Y-%m')
        if m_y not in ass_by_month:
            ass_by_month[m_y] = []
        ass_by_month[m_y].append(ass)
    for m_y in ass_by_month:
        for ass in ass_by_month[m_y]:
            w_name = ass['worker']
            if w_name not in history:
                history[w_name] = {}
            if m_y not in history[w_name]:
                history[w_name][m_y] = []
            # Check if already exists, replace or add
            history[w_name][m_y] = [a for a in history[w_name].get(m_y, []) if a['date'] != ass['date']]
            history[w_name][m_y].append(ass)
    return history

def _setup_holidays_and_days(year, month, holidays):
    """Setup holiday set and list of days to schedule.

    The holiday_set contains date objects for holidays.
    Days include all days in ISO weeks that contain any day of the selected month.
    """
    holiday_set, days = _setup_holidays_and_days_pure(year, month, holidays)

    # RULES.md: For equity/objective accounting, holidays on weekdays should be
    # treated as weekend days. When scheduling a month, the model operates on a
    # full ISO-week window which may include days outside the selected month.
    # If holidays are auto-provided (None or day-of-month ints), extend the
    # holiday set to cover all months present in the window so overlap days are
    # classified correctly.
    should_auto_extend = holidays is None or (
        isinstance(holidays, list) and holidays and all(isinstance(h, int) for h in holidays)
    )
    if should_auto_extend:
        months_in_window = {(d.year, d.month) for d in days}
        for y, m in months_in_window:
            for hd in compute_holidays(y, m):
                try:
                    holiday_set.add(date(y, m, hd))
                except ValueError:
                    pass
    first_monday = days[0]
    last_sunday = days[-1]
    logger.info(f"Scheduling {len(days)} days from {first_monday} to {last_sunday} for {year}-{month:02d}")
    return holiday_set, days

def _create_shifts(days):
    return _create_shifts_pure(days)

def _group_shifts_by_day(num_shifts, shifts):
    return _group_shifts_by_day_pure(num_shifts, shifts)

def _setup_iso_weeks(days, shifts, holiday_set):
    return _setup_iso_weeks_pure(days, shifts, holiday_set)

def _define_stat_indices(shifts, num_shifts, holiday_set):
    return _define_stat_indices_pure(shifts, num_shifts, holiday_set)

def _create_model():
    return _mc.create_model(cp_model)

def _define_assigned_vars(model, num_workers, num_shifts):
    return _mc.define_assigned_vars(model, num_workers, num_shifts)

def _add_basic_constraints(model, assigned, num_workers, num_shifts, shifts_by_day, workers, shifts):
    return _mc.add_basic_constraints(model, assigned, num_workers, num_shifts, shifts_by_day, workers, shifts)

def _parse_unavail_and_req(unavail_data, required_data, workers):
    unav_parsed = [parse_unavail_or_req(unavail_data.get(workers[w]['name'], [])) for w in range(len(workers))]
    req_parsed = [parse_unavail_or_req(required_data.get(workers[w]['name'], []), is_unavail=False) for w in range(len(workers))]
    return unav_parsed, req_parsed

def _add_unavail_req_constraints(model, assigned, unav_parsed, req_parsed, shifts_by_day, shifts, num_workers):
    return _mc.add_unavail_req_constraints(model, assigned, unav_parsed, req_parsed, shifts_by_day, shifts, num_workers)

def _add_24h_interval_constraints(model, assigned, shifts, num_shifts, num_workers):
    return _mc.add_24h_interval_constraints(model, assigned, shifts, num_shifts, num_workers)

def _add_weekly_participation_constraints(model, assigned, iso_weeks, unav_parsed, num_workers):
    return _mc.add_weekly_participation_constraints(model, assigned, iso_weeks, unav_parsed, num_workers)

def _fix_previous_assignments(model, assigned, history, workers, days, shifts_by_day, shifts):
    return _mc.fix_previous_assignments(model, assigned, history, workers, days, shifts_by_day, shifts)

def _compute_past_stats(history, workers):
    past_stats = {w['name']: {
        'weekend_shifts': 0,
        'sat_shifts': 0,
        'sun_shifts': 0,
        'weekend_day': 0,
        'weekend_night': 0,
        'weekday_day': 0,
        'weekday_night': 0,
        'total_night': 0,
        'fri_night': 0,
        'dow': [0] * 7
    } for w in workers}
    hv = HistoryView(history)
    for worker_name, month_key, ass in hv.iter_assignments():
        if worker_name not in past_stats:
            continue
        try:
            y, m = map(int, month_key.split('-'))
        except Exception:
            continue
        # compute_holidays returns day numbers; compare with day.day
        holidays = set(compute_holidays(y, m))
        try:
            day = date.fromisoformat(ass['date'])
        except Exception:
            continue
        shift = ass.get('shift')
        if not isinstance(shift, str):
            continue
        is_night = shift == 'N'
        is_day = shift in ['M1', 'M2']
        wd = day.weekday()
        is_weekend = wd >= 5 or day.day in holidays
        past_stats[worker_name]['dow'][wd] += 1
        if is_weekend:
            past_stats[worker_name]['weekend_shifts'] += 1
            if wd == 5:
                past_stats[worker_name]['sat_shifts'] += 1
            if wd == 6:
                past_stats[worker_name]['sun_shifts'] += 1
            if is_day:
                past_stats[worker_name]['weekend_day'] += 1
            if is_night:
                past_stats[worker_name]['weekend_night'] += 1
        else:
            if is_day:
                past_stats[worker_name]['weekday_day'] += 1
            if is_night:
                past_stats[worker_name]['weekday_night'] += 1
        if is_night:
            past_stats[worker_name]['total_night'] += 1
        if wd == 4 and is_night:
            past_stats[worker_name]['fri_night'] += 1
    return past_stats

def _define_current_stats_vars(model, assigned, stat_indices, num_workers):
    return _mo.define_current_stats_vars(model, assigned, stat_indices, num_workers)

def _add_load_balancing_objective(model, obj, iso_weeks, shifts, assigned, workers, weight_load):
    return _mo.add_load_balancing_objective(model, obj, iso_weeks, shifts, assigned, workers, weight_load)

def _add_three_day_weekend_min_objective(model, obj, weight_flex, iso_weeks, holiday_set, shifts_by_day, assigned, num_workers):
    return _mo.add_three_day_weekend_min_objective(model, obj, weight_flex, iso_weeks, holiday_set, shifts_by_day, assigned, num_workers)

def _add_weekend_shift_limits_objective(model, obj, weight_flex, iso_weeks, holiday_set, assigned, num_workers, shifts):
    return _mo.add_weekend_shift_limits_objective(model, obj, weight_flex, iso_weeks, holiday_set, assigned, num_workers, shifts)


def _add_consecutive_weekend_avoidance_objective(model, obj, weight_flex, iso_weeks, holiday_set, history, workers, assigned, num_workers, shifts, year, month):
    return _mo.add_consecutive_weekend_avoidance_objective(
        model, obj, weight_flex, iso_weeks, holiday_set, history, workers, assigned, num_workers, shifts, year, month
    )


def _add_m2_priority_objective(model, obj, weight_flex, shifts, num_shifts, assigned, workers):
    return _mo.add_m2_priority_objective(model, obj, weight_flex, shifts, num_shifts, assigned, workers)

def _add_equity_objective(model, obj, equity_weights, past_stats, current_stats, workers, num_workers):
    return _mo.add_equity_objective(model, obj, equity_weights, past_stats, current_stats, workers, num_workers)

def _add_dow_equity_objective(model, obj, dow_equity_weight, past_stats, current_dow, workers, num_workers):
    return _mo.add_dow_equity_objective(model, obj, dow_equity_weight, past_stats, current_dow, workers, num_workers)

def _add_consec_shifts_48h_objective(model, obj, weight_flex, assigned, shifts, num_shifts, num_workers):
    return _mo.add_consec_shifts_48h_objective(model, obj, weight_flex, assigned, shifts, num_shifts, num_workers)


def _add_tiebreak_objective(model, obj, assigned, num_workers, num_shifts, workers):
    """
    Deterministic Tie-Break: Add a tiny penalty based on a stable worker order.
    This ensures that when multiple assignments have equal cost, workers are
    preferred deterministically (by id, then name), producing stable results.
    
    The weight is extremely small (1e-9) to not affect actual optimization decisions,
    only to break ties deterministically.
    """
    return _mo.add_tiebreak_objective(model, obj, assigned, num_workers, num_shifts, workers)


def _add_saturday_preference_objective(model, obj, weight_flex, iso_weeks, assigned, num_workers, shifts, unav_parsed,
                                       holiday_set):
    """
    Flexible Rule 1: First-Shift Preference Fallback Order
    Priority for each worker's first shift of the ISO week (highest to lowest):
      1) Weekday day shift (M1/M2), even if it's a holiday
      2) Weekday night shift (N), even if it's a holiday
      3) Saturday day shift (M1/M2)
      4) Saturday night shift (N)
      5) Sunday day shift (M1/M2)
      6) Sunday night shift (N)
    Uses tiered penalties to enforce strict ordering.
    """
    return _mo.add_saturday_preference_objective(model, obj, weight_flex, iso_weeks, assigned, num_workers, shifts, unav_parsed, holiday_set)

def _solve_and_extract_results(
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
    stage_objectives=None,
):
    return _sp.solve_and_extract_results(
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
        stage_objectives=stage_objectives,
    )

def generate_schedule(
    year,
    month,
    unavail_data,
    required_data,
    history,
    workers,
    holidays=None,
    equity_weights=None,
    dow_equity_weight=None,
    lexicographic: bool = True,
):
    if equity_weights is None:
        equity_weights = EQUITY_WEIGHTS
    if dow_equity_weight is None:
        dow_equity_weight = DOW_EQUITY_WEIGHT
    # Build full visualization window (all days from first Monday to last Sunday around month)
    holiday_set, all_days = _setup_holidays_and_days(year, month, holidays)

    # Determine which ISO weeks within the visualization window are already scheduled
    scheduled_weeks = get_scheduled_iso_weeks(history)
    overlap_week_keys = set()
    for d in all_days:
        iso = d.isocalendar()
        overlap_week_keys.add((iso[0], iso[1]))
    excluded_week_keys = scheduled_weeks.intersection(overlap_week_keys)

    # Filter days to schedule: exclude all days in previously scheduled ISO weeks
    days = [d for d in all_days if d.isocalendar()[:2] not in excluded_week_keys]

    # Proceed with model only for unscheduled weeks/days
    shifts, num_shifts = _create_shifts(days)
    shifts_by_day = _group_shifts_by_day(num_shifts, shifts)
    iso_weeks = _setup_iso_weeks(days, shifts, holiday_set)
    stat_indices = _define_stat_indices(shifts, num_shifts, holiday_set)
    model = _create_model()
    num_workers = len(workers)
    assigned = _define_assigned_vars(model, num_workers, num_shifts)
    model = _add_basic_constraints(model, assigned, num_workers, num_shifts, shifts_by_day, workers, shifts)
    unav_parsed, req_parsed = _parse_unavail_and_req(unavail_data, required_data, workers)
    model = _add_unavail_req_constraints(model, assigned, unav_parsed, req_parsed, shifts_by_day, shifts, num_workers)
    model = _add_24h_interval_constraints(model, assigned, shifts, num_shifts, num_workers)
    model = _add_weekly_participation_constraints(model, assigned, iso_weeks, unav_parsed, num_workers)
    model = _fix_previous_assignments(model, assigned, history, workers, days, shifts_by_day, shifts)
    past_stats = _compute_past_stats(history, workers)
    current_stats, current_dow = _define_current_stats_vars(model, assigned, stat_indices, num_workers)
    if lexicographic:
        # Build integer-valued stage objectives and solve lexicographically in RULES.md order.
        sat_pref_cost = _mo.build_saturday_preference_cost(model, iso_weeks, assigned, num_workers, shifts, unav_parsed)
        three_day_cost = _mo.build_three_day_weekend_unique_workers_cost(
            model, iso_weeks, holiday_set, shifts_by_day, assigned, num_workers
        )
        weekend_limits_cost = _mo.build_weekend_shift_limits_cost(model, iso_weeks, holiday_set, assigned, num_workers, shifts)
        consec_weekend_cost = _mo.build_consecutive_weekend_avoidance_cost(
            model, iso_weeks, holiday_set, history, workers, assigned, num_workers, shifts, year, month
        )
        m2_cost = _mo.build_m2_priority_cost(model, shifts, assigned, workers)

        # Rule 6-10 (equity) + load balancing are treated as a combined fairness stage.
        load_cost = _mo.build_load_balancing_cost(model, iso_weeks, shifts, assigned, workers)
        equity_cost = _mo.build_equity_cost_scaled(model, equity_weights, past_stats, current_stats, workers, num_workers)
        dow_cost = _mo.build_dow_equity_cost_scaled(model, dow_equity_weight, past_stats, current_dow, workers, num_workers)
        # Generous upper bound; exact tightness isn't required.
        fairness_cost = model.NewIntVar(0, 10_000_000, "fairness_cost")
        model.Add(fairness_cost == load_cost + equity_cost + dow_cost)

        # Rule 11: prefer >48h gaps (penalize 24-48h gaps)
        consec48_cost = _mo.build_consec_shifts_48h_cost(model, assigned, shifts, num_shifts, num_workers)

        # Deterministic final tie-break
        tiebreak_cost = _mo.build_tiebreak_cost(model, assigned, num_workers, num_shifts, workers)

        stage_objectives = [
            ("rule1_sat_pref", sat_pref_cost),
            ("rule2_3day_min_workers", three_day_cost),
            ("rule3_weekend_limits", weekend_limits_cost),
            ("rule4_consec_weekend", consec_weekend_cost),
            ("rule5_m2_priority", m2_cost),
            ("fairness_load_equity", fairness_cost),
            ("rule11_consec48", consec48_cost),
            ("tiebreak", tiebreak_cost),
        ]

        schedule, weekly, assignments, stats, current_stats_computed = _solve_and_extract_results(
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
            stage_objectives=stage_objectives,
        )
    else:
        # Backwards-compatible single-objective weighted-sum mode.
        obj = 0
        obj = _add_load_balancing_objective(model, obj, iso_weeks, shifts, assigned, workers, OBJECTIVE_WEIGHT_LOAD)
        obj = _add_saturday_preference_objective(model, obj, OBJECTIVE_FLEX_WEIGHTS[0], iso_weeks, assigned, num_workers,
                                                 shifts, unav_parsed, holiday_set)
        obj = _add_three_day_weekend_min_objective(model, obj, OBJECTIVE_FLEX_WEIGHTS[1], iso_weeks, holiday_set,
                                                   shifts_by_day, assigned, num_workers)
        obj = _add_weekend_shift_limits_objective(model, obj, OBJECTIVE_FLEX_WEIGHTS[2], iso_weeks, holiday_set, assigned,
                                                  num_workers, shifts)
        obj = _add_consecutive_weekend_avoidance_objective(model, obj, OBJECTIVE_FLEX_WEIGHTS[3], iso_weeks, holiday_set,
                                                           history, workers, assigned, num_workers, shifts, year, month)
        obj = _add_m2_priority_objective(model, obj, OBJECTIVE_FLEX_WEIGHTS[4], shifts, num_shifts, assigned, workers)
        obj = _add_equity_objective(model, obj, equity_weights, past_stats, current_stats, workers, num_workers)
        obj = _add_dow_equity_objective(model, obj, dow_equity_weight, past_stats, current_dow, workers, num_workers)
        obj = _add_consec_shifts_48h_objective(model, obj, OBJECTIVE_FLEX_WEIGHTS[10], assigned, shifts, num_shifts,
                                               num_workers)
        obj = _add_tiebreak_objective(model, obj, assigned, num_workers, num_shifts, workers)
        model.Minimize(obj)
        schedule, weekly, assignments, stats, current_stats_computed = _solve_and_extract_results(
            model, shifts, num_shifts, days, month, shifts_by_day, iso_weeks, workers, assigned, current_stats
        )

    # Merge previously scheduled (excluded) ISO weeks into results for visualization
    schedule, weekly, assignments = _merge_excluded_weeks_into_results(
        schedule, weekly, assignments, excluded_week_keys, all_days, history, workers, month
    )

    return schedule, weekly, assignments, stats, current_stats_computed


def _merge_excluded_weeks_into_results(schedule, weekly, assignments, excluded_week_keys, all_days, history, workers, selected_month):
    return _sp.merge_excluded_weeks_into_results(
        schedule, weekly, assignments, excluded_week_keys, all_days, history, workers, selected_month
    )