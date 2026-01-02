import calendar
import datetime
from ortools.sat.python import cp_model
import json
from datetime import date, timedelta
from utils import compute_holidays, easter_date
from constants import *
from logger import get_logger

logger = get_logger('logic')


def get_scheduled_iso_weeks(history: dict) -> set:
    """
    Get set of (iso_year, iso_week) tuples that have already been scheduled.
    An ISO week is considered scheduled if ANY assignment exists for any day in that week.
    """
    scheduled = set()
    for worker_data in history.values():
        for month_assignments in worker_data.values():
            for ass in month_assignments:
                if 'date' in ass:
                    try:
                        d = date.fromisoformat(ass['date'])
                        iso_cal = d.isocalendar()
                        scheduled.add((iso_cal[0], iso_cal[1]))
                    except (ValueError, TypeError):
                        continue
    return scheduled


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
    if holidays is None:
        holidays = []
    
    # Convert holiday day numbers to date objects
    holiday_set = set()
    for h in holidays:
        if isinstance(h, int):
            try:
                holiday_set.add(date(year, month, h))
            except ValueError:
                pass  # Invalid day number
        elif isinstance(h, date):
            holiday_set.add(h)
    
    _, num_days_in_month = calendar.monthrange(year, month)
    first_day = date(year, month, 1)
    last_day = date(year, month, num_days_in_month)
    
    # Find Monday of the ISO week containing the first day
    first_monday = first_day - timedelta(days=first_day.weekday())
    
    # Find Sunday of the ISO week containing the last day
    last_sunday = last_day + timedelta(days=(6 - last_day.weekday()))
    
    # Generate all days from first Monday to last Sunday
    days = []
    current_day = first_monday
    while current_day <= last_sunday:
        days.append(current_day)
        current_day += timedelta(days=1)
    
    days = sorted(set(days))  # Unique days
    logger.info(f"Scheduling {len(days)} days from {first_monday} to {last_sunday} for {year}-{month:02d}")
    return holiday_set, days

def _create_shifts(days):
    shifts = []
    for day in days:
        d_dt = datetime.datetime.combine(day, datetime.time())
        for st in SHIFT_TYPES:
            config = SHIFTS[st]
            shifts.append({
                'type': st,
                'start': d_dt + timedelta(hours=config['start_hour']),
                'end': d_dt + timedelta(hours=config['end_hour']),
                'dur': config['dur'],
                'night': config['night'],
                'day': day
            })
    num_shifts = len(shifts)
    for i in range(num_shifts):
        shifts[i]['index'] = i
    return shifts, num_shifts

def _group_shifts_by_day(num_shifts, shifts):
    shifts_by_day = {}
    for s in range(num_shifts):
        d = shifts[s]['day']
        if d not in shifts_by_day:
            shifts_by_day[d] = []
        shifts_by_day[d].append(s)
    return shifts_by_day

def _setup_iso_weeks(days, shifts, holiday_set):
    iso_weeks = {}
    for day in days:
        iso = day.isocalendar()
        key = (iso[0], iso[1])
        if key not in iso_weeks:
            iso_weeks[key] = {
                'days': [],
                'weekdays': [],  # Mon-Fri excluding holidays (for equity/vacation checks)
                'weekdays_for_distribution': [],  # Mon-Fri including holidays (for shift distribution rule)
                'shifts': [],
                'weekday_shifts': [],  # Shifts on Mon-Fri excluding holidays (for equity)
                'weekday_shifts_for_distribution': [],  # Shifts on Mon-Fri including holidays
                'monday': day - timedelta(days=day.weekday())
            }
        iso_weeks[key]['days'].append(day)
        # Weekdays excluding holidays (for equity metrics and vacation determination)
        if day.weekday() < 5 and day not in holiday_set:
            iso_weeks[key]['weekdays'].append(day)
        # Weekdays including holidays (for weekday shift distribution rule)
        if day.weekday() < 5:
            iso_weeks[key]['weekdays_for_distribution'].append(day)
        iso_weeks[key]['shifts'].append([shift['index'] for shift in shifts if shift['day'] == day])
        # Weekday shifts excluding holidays (for equity)
        if day.weekday() < 5 and day not in holiday_set:
            iso_weeks[key]['weekday_shifts'].append([shift['index'] for shift in shifts if shift['day'] == day])
        # Weekday shifts including holidays (for distribution rule)
        if day.weekday() < 5:
            iso_weeks[key]['weekday_shifts_for_distribution'].append([shift['index'] for shift in shifts if shift['day'] == day])
    for key in iso_weeks:
        iso_weeks[key]['shifts'] = [item for sublist in iso_weeks[key]['shifts'] for item in sublist]
        iso_weeks[key]['weekday_shifts'] = [item for sublist in iso_weeks[key]['weekday_shifts'] for item in sublist]
        iso_weeks[key]['weekday_shifts_for_distribution'] = [item for sublist in iso_weeks[key]['weekday_shifts_for_distribution'] for item in sublist]
    return iso_weeks

def _define_stat_indices(shifts, num_shifts, holiday_set):
    weekend_shift_indices = [s for s in range(num_shifts) if shifts[s]['day'].weekday() >= 5 or shifts[s]['day'] in holiday_set]
    sat_indices = [s for s in range(num_shifts) if shifts[s]['day'].weekday() == 5]
    sun_indices = [s for s in range(num_shifts) if shifts[s]['day'].weekday() == 6]
    weekend_day_indices = [s for s in weekend_shift_indices if not shifts[s]['night']]
    weekend_night_indices = [s for s in weekend_shift_indices if shifts[s]['night']]
    weekday_day_indices = [s for s in range(num_shifts) if not (shifts[s]['day'].weekday() >= 5 or shifts[s]['day'] in holiday_set) and not shifts[s]['night']]
    weekday_night_indices = [s for s in range(num_shifts) if not (shifts[s]['day'].weekday() >= 5 or shifts[s]['day'] in holiday_set) and shifts[s]['night']]
    fri_night_indices = [s for s in weekday_night_indices if shifts[s]['day'].weekday() == 4]
    dow_indices = {d: [s for s in range(num_shifts) if shifts[s]['day'].weekday() == d] for d in range(7)}
    total_night_indices = [s for s in range(num_shifts) if shifts[s]['night']]
    return {
        'weekend_shifts': weekend_shift_indices,
        'sat_shifts': sat_indices,
        'sun_shifts': sun_indices,
        'weekend_day': weekend_day_indices,
        'weekend_night': weekend_night_indices,
        'weekday_day': weekday_day_indices,
        'weekday_night': weekday_night_indices,
        'total_night': total_night_indices,
        'fri_night': fri_night_indices,
        'dow': dow_indices
    }

def _create_model():
    return cp_model.CpModel()

def _define_assigned_vars(model, num_workers, num_shifts):
    assigned = [[model.NewBoolVar(f'ass_w{w}_s{s}') for s in range(num_shifts)] for w in range(num_workers)]
    return assigned

def _add_basic_constraints(model, assigned, num_workers, num_shifts, shifts_by_day, workers, shifts):
    # Each shift exactly one worker
    for s in range(num_shifts):
        model.AddExactlyOne(assigned[w][s] for w in range(num_workers))
    # No multiple shifts on same day
    for w in range(num_workers):
        for d in shifts_by_day:
            model.Add(sum(assigned[w][s] for s in shifts_by_day[d]) <= 1)
    # No night for some workers
    for w in range(num_workers):
        if not workers[w]['can_night']:
            for s in range(num_shifts):
                if shifts[s]['night']:
                    model.Add(assigned[w][s] == 0)
    return model

def _parse_unavail_and_req(unavail_data, required_data, workers):
    unav_parsed = [parse_unavail_or_req(unavail_data.get(workers[w]['name'], [])) for w in range(len(workers))]
    req_parsed = [parse_unavail_or_req(required_data.get(workers[w]['name'], []), is_unavail=False) for w in range(len(workers))]
    return unav_parsed, req_parsed

def _add_unavail_req_constraints(model, assigned, unav_parsed, req_parsed, shifts_by_day, shifts, num_workers):
    for w in range(num_workers):
        for d, sh in unav_parsed[w]:
            if sh is None:
                if d in shifts_by_day:
                    for s in shifts_by_day[d]:
                        model.Add(assigned[w][s] == 0)
            else:
                if d in shifts_by_day:
                    for s in shifts_by_day[d]:
                        if shifts[s]['type'] == sh:
                            model.Add(assigned[w][s] == 0)
                            break
        for d, sh in req_parsed[w]:
            if sh is None:
                if d in shifts_by_day:
                    model.Add(sum(assigned[w][s] for s in shifts_by_day[d]) >= 1)
            else:
                if d in shifts_by_day:
                    for s in shifts_by_day[d]:
                        if shifts[s]['type'] == sh:
                            model.Add(assigned[w][s] == 1)
                            break
    return model

def _add_24h_interval_constraints(model, assigned, shifts, num_shifts, num_workers):
    for w in range(num_workers):
        for i in range(num_shifts):
            for j in range(i + 1, num_shifts):
                si = shifts[i]
                sj = shifts[j]
                start_i = si['start']
                end_i = si['end']
                start_j = sj['start']
                end_j = sj['end']
                if max(start_i, start_j) < min(end_i, end_j):
                    model.AddBoolOr(assigned[w][i].Not(), assigned[w][j].Not())
                else:
                    if start_j >= end_i:
                        delta = (start_j - end_i).total_seconds() / 3600
                        if delta < MIN_REST_HOURS:
                            model.AddBoolOr(assigned[w][i].Not(), assigned[w][j].Not())
                    elif start_i >= end_j:
                        delta = (start_i - end_j).total_seconds() / 3600
                        if delta < MIN_REST_HOURS:
                            model.AddBoolOr(assigned[w][i].Not(), assigned[w][j].Not())
    return model

def _add_weekly_participation_constraints(model, assigned, iso_weeks, unav_parsed, num_workers):
    for key in iso_weeks:
        week = iso_weeks[key]
        relevant = []
        for w in range(num_workers):
            # Use weekdays_for_distribution (Mon-Fri including holidays) to determine eligibility
            avail_weekdays = [wd for wd in week['weekdays_for_distribution'] if (wd, None) not in unav_parsed[w]]
            if len(avail_weekdays) >= 1:
                relevant.append(w)
        num_relevant = len(relevant)
        # Use weekday_shifts_for_distribution (includes holidays on Mon-Fri) for distribution rule
        total_weekday_shifts = len(week['weekday_shifts_for_distribution'])
        for w in relevant:
            num_shifts_week = sum(assigned[w][s] for s in week['shifts'])
            model.Add(num_shifts_week >= 1)
        # Count weekday shifts using distribution list (holidays on Mon-Fri count as weekday shifts)
        num_weekday = [sum(assigned[w][s] for s in week['weekday_shifts_for_distribution']) for w in range(num_workers)]
        has_at_least_one = [model.NewBoolVar(f'has1_w{w}_wk{key[0]}_{key[1]}') for w in range(num_workers)]
        for ww in range(num_workers):
            model.Add(num_weekday[ww] >= 1).OnlyEnforceIf(has_at_least_one[ww])
            model.Add(num_weekday[ww] == 0).OnlyEnforceIf(has_at_least_one[ww].Not())
        all_have_one = model.NewBoolVar(f'all_have_wk{key[0]}_{key[1]}')
        if relevant:
            model.AddBoolAnd([has_at_least_one[w] for w in relevant]).OnlyEnforceIf(all_have_one)
            model.AddBoolOr([has_at_least_one[w].Not() for w in relevant]).OnlyEnforceIf(all_have_one.Not())
            for ww in range(num_workers):
                model.Add(num_weekday[ww] <= 1).OnlyEnforceIf(all_have_one.Not())
            if total_weekday_shifts >= num_relevant:
                model.Add(all_have_one == 1)
    return model

def _fix_previous_assignments(model, assigned, history, workers, days, shifts_by_day, shifts):
    for day in days:
        day_str = str(day)
        m_y = day.strftime('%Y-%m')
        for w_idx, worker in enumerate(workers):
            w_name = worker['name']
            if m_y in history.get(w_name, {}) and history[w_name][m_y]:
                for ass in history[w_name][m_y]:
                    if ass['date'] == day_str:
                        shift_type = ass['shift']
                        for s in shifts_by_day[day]:
                            if shifts[s]['type'] == shift_type:
                                model.Add(assigned[w_idx][s] == 1)
                                break
    return model

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
    for worker in past_stats:
        if worker in history:
            for my in history[worker]:
                try:
                    y, m = map(int, my.split('-'))
                except:
                    continue
                holidays = set(compute_holidays(y, m))
                for ass in history[worker][my]:
                    day = date.fromisoformat(ass['date'])
                    shift = ass['shift']
                    is_night = shift == 'N'
                    is_day = shift in ['M1', 'M2']
                    wd = day.weekday()
                    is_weekend = wd >= 5 or day in holidays
                    past_stats[worker]['dow'][wd] += 1
                    if is_weekend:
                        past_stats[worker]['weekend_shifts'] += 1
                        if wd == 5:
                            past_stats[worker]['sat_shifts'] += 1
                        if wd == 6:
                            past_stats[worker]['sun_shifts'] += 1
                        if is_day:
                            past_stats[worker]['weekend_day'] += 1
                        if is_night:
                            past_stats[worker]['weekend_night'] += 1
                    else:
                        if is_day:
                            past_stats[worker]['weekday_day'] += 1
                        if is_night:
                            past_stats[worker]['weekday_night'] += 1
                    if is_night:
                        past_stats[worker]['total_night'] += 1
                    if wd == 4 and is_night:
                        past_stats[worker]['fri_night'] += 1
    return past_stats

def _define_current_stats_vars(model, assigned, stat_indices, num_workers):
    current_stats = {}
    for stat in EQUITY_STATS[:-2]:  # Exclude 'total_night' and 'fri_night' for now
        current_stats[stat] = [sum(assigned[w][s] for s in stat_indices[stat]) for w in range(num_workers)]
    current_stats['total_night'] = [sum(assigned[w][s] for s in stat_indices['weekend_night'] + stat_indices['weekday_night']) for w in range(num_workers)]
    current_stats['fri_night'] = [sum(assigned[w][s] for s in stat_indices['fri_night']) for w in range(num_workers)]
    current_dow = [[sum(assigned[w][s] for s in stat_indices['dow'][d]) for w in range(num_workers)] for d in range(7)]
    return current_stats, current_dow

def _add_load_balancing_objective(model, obj, iso_weeks, shifts, assigned, workers, weight_load):
    for key in iso_weeks:
        week_shifts = iso_weeks[key]['shifts']
        for w in range(len(workers)):
            hours = sum(shifts[s]['dur'] * assigned[w][s] for s in week_shifts)
            load = workers[w]['weekly_load']
            over = model.NewIntVar(0, MAX_STAT_VALUE, f'over_w{w}_k{key}')
            under = model.NewIntVar(0, MAX_STAT_VALUE, f'under_w{w}_k{key}')
            model.Add(over >= hours - load)
            model.Add(under >= load - hours)
            obj += weight_load * (over + under)
    return obj

def _add_three_day_weekend_min_objective(model, obj, weight_flex, iso_weeks, holiday_set, shifts_by_day, assigned, num_workers):
    """
    Flexible Rule 2: Three-Day Weekend Worker Minimization
    When a holiday on Monday or Friday creates a 3-day weekend, minimize the number of 
    different workers assigned shifts over those 3 days by favoring multiple shifts to same worker.
    """
    for key in iso_weeks:
        week = iso_weeks[key]
        days = week['days']
        
        # Find 3-day weekend periods
        three_day_periods = []
        for day in days:
            if day in holiday_set:
                if day.weekday() == 4:  # Friday holiday -> Fri-Sat-Sun
                    fri = day
                    sat = day + timedelta(days=1)
                    sun = day + timedelta(days=2)
                    if sat in days and sun in days:
                        three_day_periods.append([fri, sat, sun])
                elif day.weekday() == 0:  # Monday holiday -> Sat-Sun-Mon
                    mon = day
                    sat = day - timedelta(days=2)
                    sun = day - timedelta(days=1)
                    if sat in days and sun in days:
                        three_day_periods.append([sat, sun, mon])
        
        for period in three_day_periods:
            # Collect all shifts in this 3-day period
            period_shifts = []
            for d in period:
                period_shifts.extend(shifts_by_day.get(d, []))
            
            if not period_shifts:
                continue
            
            # Penalize each worker who works during this period (minimize unique workers)
            for w in range(num_workers):
                has_shift_in_period = model.NewBoolVar(f'has_3day_w{w}_k{key}_{period[0]}')
                sum_in_period = sum(assigned[w][s] for s in period_shifts)
                model.Add(sum_in_period >= 1).OnlyEnforceIf(has_shift_in_period)
                model.Add(sum_in_period == 0).OnlyEnforceIf(has_shift_in_period.Not())
                # Penalize having ANY worker in the period (solver will consolidate shifts)
                obj += weight_flex * has_shift_in_period
    
    return obj

def _add_weekend_shift_limits_objective(model, obj, weight_flex, iso_weeks, holiday_set, assigned, num_workers, shifts):
    """
    Flexible Rule 3: Weekend Shift Limits
    Avoid assigning the same worker two shifts in the same weekend (Saturday and Sunday),
    unless the Three-Day Weekend Worker Minimization rule applies.
    """
    for key in iso_weeks:
        week = iso_weeks[key]
        # Check if this is a 3-day weekend (skip limit if so, as rule 2 takes precedence)
        is_three_day = any(day in holiday_set and day.weekday() in [0, 4] for day in week['days'])
        if is_three_day:
            continue
        
        # Get Saturday and Sunday shifts separately
        sat_shifts = [s for s in week['shifts'] if shifts[s]['day'].weekday() == 5]
        sun_shifts = [s for s in week['shifts'] if shifts[s]['day'].weekday() == 6]
        
        for w in range(num_workers):
            # Penalize if worker has shifts on BOTH Saturday AND Sunday
            has_sat = model.NewBoolVar(f'has_sat_w{w}_k{key}')
            has_sun = model.NewBoolVar(f'has_sun_w{w}_k{key}')
            
            if sat_shifts:
                model.Add(sum(assigned[w][s] for s in sat_shifts) >= 1).OnlyEnforceIf(has_sat)
                model.Add(sum(assigned[w][s] for s in sat_shifts) == 0).OnlyEnforceIf(has_sat.Not())
            else:
                model.Add(has_sat == 0)
                
            if sun_shifts:
                model.Add(sum(assigned[w][s] for s in sun_shifts) >= 1).OnlyEnforceIf(has_sun)
                model.Add(sum(assigned[w][s] for s in sun_shifts) == 0).OnlyEnforceIf(has_sun.Not())
            else:
                model.Add(has_sun == 0)
            
            # Penalize having both
            has_both = model.NewBoolVar(f'has_both_weekend_w{w}_k{key}')
            model.AddBoolAnd([has_sat, has_sun]).OnlyEnforceIf(has_both)
            model.AddBoolOr([has_sat.Not(), has_sun.Not()]).OnlyEnforceIf(has_both.Not())
            obj += weight_flex * has_both
    
    return obj


def _add_consecutive_weekend_avoidance_objective(model, obj, weight_flex, iso_weeks, holiday_set, history, workers, assigned, num_workers, shifts, year, month):
    """
    Flexible Rule 4: Consecutive Weekend Shift Avoidance
    Avoid assigning a worker shifts on consecutive weekends if there are other workers
    who have not yet worked a weekend shift in that month.
    
    "In that month" refers strictly to the current calendar month being scheduled.
    """
    # Sort iso_weeks by key to process in order
    sorted_keys = sorted(iso_weeks.keys())
    
    # Compute which workers have already worked a weekend shift in history for this month
    current_month_str = f'{year}-{month:02d}'
    workers_with_weekend_in_month = set()
    for w_name, months_data in history.items():
        if current_month_str in months_data:
            for ass in months_data[current_month_str]:
                try:
                    d = date.fromisoformat(ass['date'])
                    if d.weekday() >= 5:  # Saturday or Sunday
                        workers_with_weekend_in_month.add(w_name)
                        break
                except (ValueError, TypeError):
                    continue
    
    for i, key in enumerate(sorted_keys):
        week = iso_weeks[key]
        monday = week['monday']
        
        # Get weekend shifts for this week
        weekend_shifts_this = [s for s in week['shifts'] if shifts[s]['day'].weekday() >= 5]
        if not weekend_shifts_this:
            continue
        
        # Build a variable to track which workers get weekend shifts this week
        # This will be used to update "has worked weekend this month" dynamically
        has_weekend_this_week = []
        for w_idx in range(num_workers):
            var = model.NewBoolVar(f'has_wknd_w{w_idx}_k{key}')
            if weekend_shifts_this:
                model.Add(sum(assigned[w_idx][s] for s in weekend_shifts_this) >= 1).OnlyEnforceIf(var)
                model.Add(sum(assigned[w_idx][s] for s in weekend_shifts_this) == 0).OnlyEnforceIf(var.Not())
            else:
                model.Add(var == 0)
            has_weekend_this_week.append(var)
        
        for w_idx, worker in enumerate(workers):
            w_name = worker['name']
            
            # Check if worker worked previous weekend (from history)
            worked_prev = False
            weekend_prev_days = [monday - timedelta(days=2), monday - timedelta(days=1)]  # Prev Sat, Sun
            
            for d in weekend_prev_days:
                m_y = d.strftime('%Y-%m')
                day_str = str(d)
                if m_y in history.get(w_name, {}):
                    for ass in history[w_name][m_y]:
                        if ass['date'] == day_str:
                            worked_prev = True
                            break
                if worked_prev:
                    break
            
            if worked_prev:
                # Only penalize if there are other workers who haven't worked a weekend this month
                # Count workers without weekend shifts in this month (from history + prior weeks in schedule)
                other_workers_without_weekend = []
                for other_idx, other_w in enumerate(workers):
                    if other_idx == w_idx:
                        continue
                    # Check if this other worker has NOT worked a weekend in history for this month
                    other_has_weekend_in_history = other_w['name'] in workers_with_weekend_in_month
                    if not other_has_weekend_in_history:
                        other_workers_without_weekend.append(other_idx)
                
                # If there are other workers without weekend shifts, penalize consecutive weekend
                if other_workers_without_weekend:
                    has_weekend_this = model.NewBoolVar(f'consec_wknd_w{w_idx}_k{key}')
                    model.Add(sum(assigned[w_idx][s] for s in weekend_shifts_this) >= 1).OnlyEnforceIf(has_weekend_this)
                    model.Add(sum(assigned[w_idx][s] for s in weekend_shifts_this) == 0).OnlyEnforceIf(has_weekend_this.Not())
                    obj += weight_flex * has_weekend_this
    
    return obj


def _add_m2_priority_objective(model, obj, weight_flex, shifts, num_shifts, assigned, workers):
    """
    Flexible Rule 5: M2 Priority
    Prioritize M2 shifts over M1 shifts for workers with a standard weekly load of 18 hours.
    This penalizes assigning M1 to 18h workers, encouraging M2 assignment instead.
    """
    for s in range(num_shifts):
        if shifts[s]['type'] == 'M1':
            for w in range(len(workers)):
                if workers[w]['weekly_load'] == 18:
                    # Penalize M1 for 18h workers
                    obj += weight_flex * assigned[w][s]
    return obj

def _add_equity_objective(model, obj, equity_weights, past_stats, current_stats, workers, num_workers):
    for stat in EQUITY_STATS:
        totals = [past_stats[workers[w]['name']][stat] + current_stats[stat][w] for w in range(num_workers)]
        max_t = model.NewIntVar(0, MAX_STAT_VALUE, f'max_{stat}')
        min_t = model.NewIntVar(0, MAX_STAT_VALUE, f'min_{stat}')
        for t in totals:
            model.Add(max_t >= t)
            model.Add(min_t <= t)
        obj += equity_weights.get(stat, 0) * (max_t - min_t)
    return obj

def _add_dow_equity_objective(model, obj, dow_equity_weight, past_stats, current_dow, workers, num_workers):
    for d in range(7):
        totals_d = [past_stats[workers[w]['name']]['dow'][d] + current_dow[d][w] for w in range(num_workers)]
        max_d = model.NewIntVar(0, MAX_STAT_VALUE, f'max_dow{d}')
        min_d = model.NewIntVar(0, MAX_STAT_VALUE, f'min_dow{d}')
        for t in totals_d:
            model.Add(max_d >= t)
            model.Add(min_d <= t)
        obj += dow_equity_weight * (max_d - min_d)
    return obj

def _add_consec_shifts_48h_objective(model, obj, weight_flex, assigned, shifts, num_shifts, num_workers):
    min_penalty, max_penalty = CONSECUTIVE_SHIFT_PENALTY_RANGE
    for w in range(num_workers):
        for i in range(num_shifts):
            for j in range(i + 1, num_shifts):
                si = shifts[i]
                sj = shifts[j]
                if si['day'] == sj['day']:
                    continue
                start_i = si['start']
                end_i = si['end']
                start_j = sj['start']
                end_j = sj['end']
                if max(start_i, start_j) < min(end_i, end_j):
                    continue
                delta = abs((start_j - end_i).total_seconds() / 3600 if start_j > end_i else (start_i - end_j).total_seconds() / 3600)
                if min_penalty <= delta < max_penalty:
                    violate = model.NewBoolVar(f'v48_w{w}_i{i}_j{j}')
                    model.Add(violate <= assigned[w][i])
                    model.Add(violate <= assigned[w][j])
                    model.Add(violate >= assigned[w][i] + assigned[w][j] - 1)
                    obj += weight_flex * violate
    return obj


def _add_tiebreak_objective(model, obj, assigned, num_workers, num_shifts):
    """
    Deterministic Tie-Break: Add a tiny penalty based on worker index.
    This ensures that when multiple assignments have equal cost, workers with
    lower indices are preferred, producing stable results across runs.
    
    The weight is extremely small (1e-9) to not affect actual optimization decisions,
    only to break ties deterministically.
    """
    tiebreak_weight = 1e-9
    for w in range(num_workers):
        for s in range(num_shifts):
            # Higher worker index = slightly higher penalty
            obj += tiebreak_weight * w * assigned[w][s]
    return obj


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
    for key in iso_weeks:
        week = iso_weeks[key]
        sat = week['monday'] + timedelta(days=5)
        sun = week['monday'] + timedelta(days=6)

        # Categorize shifts by preference tier (Mon-Fri uses calendar weekday, not holiday status)
        weekday_day_shifts = [s for s in week['shifts'] if shifts[s]['day'].weekday() < 5 and not shifts[s]['night']]
        weekday_night_shifts = [s for s in week['shifts'] if shifts[s]['day'].weekday() < 5 and shifts[s]['night']]
        sat_day_shifts = [s for s in week['shifts'] if shifts[s]['day'] == sat and not shifts[s]['night']]
        sat_night_shifts = [s for s in week['shifts'] if shifts[s]['day'] == sat and shifts[s]['night']]
        sun_day_shifts = [s for s in week['shifts'] if shifts[s]['day'] == sun and not shifts[s]['night']]
        sun_night_shifts = [s for s in week['shifts'] if shifts[s]['day'] == sun and shifts[s]['night']]

        for w in range(num_workers):
            # Skip if worker has no available weekdays (vacation week - exempt from participation)
            weekday_dates = [d for d in week['days'] if d.weekday() < 5]
            avail_weekdays = [wd for wd in weekday_dates if (wd, None) not in unav_parsed[w]]
            if not avail_weekdays:
                continue

            # Detect presence in each tier
            has_weekday_day = model.NewBoolVar(f'has_wd_day_w{w}_k{key}')
            has_weekday_night = model.NewBoolVar(f'has_wd_night_w{w}_k{key}')
            has_sat_day = model.NewBoolVar(f'has_sat_day_w{w}_k{key}')
            has_sat_night = model.NewBoolVar(f'has_sat_night_w{w}_k{key}')
            has_sun_day = model.NewBoolVar(f'has_sun_day_w{w}_k{key}')
            has_sun_night = model.NewBoolVar(f'has_sun_night_w{w}_k{key}')
            has_any_shift = model.NewBoolVar(f'has_any_w{w}_k{key}')

            # Link bool vars to actual assignments
            if weekday_day_shifts:
                model.Add(sum(assigned[w][s] for s in weekday_day_shifts) >= 1).OnlyEnforceIf(has_weekday_day)
                model.Add(sum(assigned[w][s] for s in weekday_day_shifts) == 0).OnlyEnforceIf(has_weekday_day.Not())
            else:
                model.Add(has_weekday_day == 0)

            if weekday_night_shifts:
                model.Add(sum(assigned[w][s] for s in weekday_night_shifts) >= 1).OnlyEnforceIf(has_weekday_night)
                model.Add(sum(assigned[w][s] for s in weekday_night_shifts) == 0).OnlyEnforceIf(has_weekday_night.Not())
            else:
                model.Add(has_weekday_night == 0)

            if sat_day_shifts:
                model.Add(sum(assigned[w][s] for s in sat_day_shifts) >= 1).OnlyEnforceIf(has_sat_day)
                model.Add(sum(assigned[w][s] for s in sat_day_shifts) == 0).OnlyEnforceIf(has_sat_day.Not())
            else:
                model.Add(has_sat_day == 0)

            if sat_night_shifts:
                model.Add(sum(assigned[w][s] for s in sat_night_shifts) >= 1).OnlyEnforceIf(has_sat_night)
                model.Add(sum(assigned[w][s] for s in sat_night_shifts) == 0).OnlyEnforceIf(has_sat_night.Not())
            else:
                model.Add(has_sat_night == 0)

            if sun_day_shifts:
                model.Add(sum(assigned[w][s] for s in sun_day_shifts) >= 1).OnlyEnforceIf(has_sun_day)
                model.Add(sum(assigned[w][s] for s in sun_day_shifts) == 0).OnlyEnforceIf(has_sun_day.Not())
            else:
                model.Add(has_sun_day == 0)

            if sun_night_shifts:
                model.Add(sum(assigned[w][s] for s in sun_night_shifts) >= 1).OnlyEnforceIf(has_sun_night)
                model.Add(sum(assigned[w][s] for s in sun_night_shifts) == 0).OnlyEnforceIf(has_sun_night.Not())
            else:
                model.Add(has_sun_night == 0)

            sum_all = sum(assigned[w][s] for s in week['shifts'])
            model.Add(sum_all >= 1).OnlyEnforceIf(has_any_shift)
            model.Add(sum_all == 0).OnlyEnforceIf(has_any_shift.Not())

            # Tiered penalties (only apply if worker has any shift this week)
            # Penalty increases as we go down the fallback order
            # Tier 1: Weekday day → 0 penalty (best)
            # Tier 2: Weekday night (no weekday day) → penalty 1
            # Tier 3: Saturday day (no weekday) → penalty 2
            # Tier 4: Saturday night (no weekday, no sat day) → penalty 3
            # Tier 5: Sunday day (no weekday, no sat) → penalty 4
            # Tier 6: Sunday night (no weekday, no sat, no sun day) → penalty 5

            # Penalty for tier 2: has weekday night but no weekday day
            tier2 = model.NewBoolVar(f't2_w{w}_k{key}')
            model.Add(tier2 <= has_weekday_day.Not())
            model.Add(tier2 <= has_weekday_night)
            model.Add(tier2 <= has_any_shift)
            model.Add(tier2 >= has_weekday_day.Not() + has_weekday_night + has_any_shift - 2)
            obj += (weight_flex * 0.01) * tier2

            # Penalty for tier 3: has sat day but no weekday shifts
            tier3 = model.NewBoolVar(f't3_w{w}_k{key}')
            model.Add(tier3 <= has_weekday_day.Not())
            model.Add(tier3 <= has_weekday_night.Not())
            model.Add(tier3 <= has_sat_day)
            model.Add(tier3 <= has_any_shift)
            model.Add(tier3 >= has_weekday_day.Not() + has_weekday_night.Not() + has_sat_day + has_any_shift - 3)
            obj += (weight_flex * 0.02) * tier3

            # Penalty for tier 4: has sat night but no weekday, no sat day
            tier4 = model.NewBoolVar(f't4_w{w}_k{key}')
            model.Add(tier4 <= has_weekday_day.Not())
            model.Add(tier4 <= has_weekday_night.Not())
            model.Add(tier4 <= has_sat_day.Not())
            model.Add(tier4 <= has_sat_night)
            model.Add(tier4 <= has_any_shift)
            model.Add(tier4 >= has_weekday_day.Not() + has_weekday_night.Not() + has_sat_day.Not() + has_sat_night + has_any_shift - 4)
            obj += (weight_flex * 0.03) * tier4

            # Penalty for tier 5: has sun day but no weekday, no sat
            tier5 = model.NewBoolVar(f't5_w{w}_k{key}')
            model.Add(tier5 <= has_weekday_day.Not())
            model.Add(tier5 <= has_weekday_night.Not())
            model.Add(tier5 <= has_sat_day.Not())
            model.Add(tier5 <= has_sat_night.Not())
            model.Add(tier5 <= has_sun_day)
            model.Add(tier5 <= has_any_shift)
            model.Add(tier5 >= has_weekday_day.Not() + has_weekday_night.Not() + has_sat_day.Not() + has_sat_night.Not() + has_sun_day + has_any_shift - 5)
            obj += (weight_flex * 0.04) * tier5

            # Penalty for tier 6: only sun night (worst case)
            tier6 = model.NewBoolVar(f't6_w{w}_k{key}')
            model.Add(tier6 <= has_weekday_day.Not())
            model.Add(tier6 <= has_weekday_night.Not())
            model.Add(tier6 <= has_sat_day.Not())
            model.Add(tier6 <= has_sat_night.Not())
            model.Add(tier6 <= has_sun_day.Not())
            model.Add(tier6 <= has_sun_night)
            model.Add(tier6 <= has_any_shift)
            model.Add(tier6 >= has_weekday_day.Not() + has_weekday_night.Not() + has_sat_day.Not() + has_sat_night.Not() + has_sun_day.Not() + has_sun_night + has_any_shift - 6)
            obj += (weight_flex * 0.05) * tier6

    return obj

def _solve_and_extract_results(model, shifts, num_shifts, days, month, shifts_by_day, iso_weeks, workers, assigned, current_stats):
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = SOLVER_TIMEOUT_SECONDS
    solver.parameters.log_search_progress = False  # Disable verbose solver output

    logger.info("Starting schedule optimization...")
    status = solver.Solve(model)

    # Log solver statistics
    wall_time = solver.WallTime()
    branches = solver.NumBranches()
    conflicts = solver.NumConflicts()
    objective_value = solver.ObjectiveValue() if status in [cp_model.OPTIMAL, cp_model.FEASIBLE] else None
    
    status_names = {cp_model.OPTIMAL: 'OPTIMAL', cp_model.FEASIBLE: 'FEASIBLE', 
                    cp_model.INFEASIBLE: 'INFEASIBLE', cp_model.MODEL_INVALID: 'MODEL_INVALID'}
    status_str = status_names.get(status, f'UNKNOWN({status})')
    
    logger.info(f"Solver finished: status={status_str}, time={wall_time:.2f}s, branches={branches}, conflicts={conflicts}")
    if objective_value is not None:
        logger.info(f"Objective value: {objective_value:.2f}")

    # Log or save these (e.g., to a file or dict for comparison)
    stats = {
        'wall_time': wall_time,
        'branches': branches,
        'conflicts': conflicts,
        'objective_value': objective_value,
        'status': status
    }

    current_stats_computed = {stat: [solver.Value(current_stats[stat][w]) for w in range(len(workers))] for stat in
                              EQUITY_STATS}

    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        # Collect schedule for the month
        schedule = {}
        for day in days:
            if day.month == month:
                day_str = str(day)
                schedule[day_str] = {}
                for st in SHIFT_TYPES:
                    for s in shifts_by_day[day]:
                        if shifts[s]['type'] == st:
                            for w in range(len(workers)):
                                if solver.Value(assigned[w][s]) == 1:
                                    schedule[day_str][st] = workers[w]['name']
                                    break
        # Weekly summary
        weekly = {}
        for key in iso_weeks:
            weekly[key] = {}
            for w in range(len(workers)):
                hours = sum(shifts[s]['dur'] * solver.Value(assigned[w][s]) for s in iso_weeks[key]['shifts'])
                load = workers[w]['weekly_load']
                overtime = max(0, hours - load)
                undertime = max(0, load - hours)
                weekly[key][workers[w]['name']] = {'hours': hours, 'overtime': overtime, 'undertime': undertime}
        # Assignments for saving
        assignments = []
        for s in range(num_shifts):
            for w in range(len(workers)):
                if solver.Value(assigned[w][s]) == 1:
                    assignments.append({
                        'worker': workers[w]['name'],
                        'date': str(shifts[s]['day']),
                        'shift': shifts[s]['type'],
                        'dur': shifts[s]['dur']
                    })

        return schedule, weekly, assignments, stats, current_stats_computed
    else:
        return {}, {}, [], stats, {}

def generate_schedule(year, month, unavail_data, required_data, history, workers, holidays=None, equity_weights=None, dow_equity_weight=None):
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
    obj = 0
    obj = _add_load_balancing_objective(model, obj, iso_weeks, shifts, assigned, workers, OBJECTIVE_WEIGHT_LOAD)
    # Flexible rules in order of importance (Rule 1 = highest priority)
    # Rule 1: Saturday Preference for First Shift
    obj = _add_saturday_preference_objective(model, obj, OBJECTIVE_FLEX_WEIGHTS[0], iso_weeks, assigned, num_workers,
                                             shifts, unav_parsed, holiday_set)
    # Rule 2: Three-Day Weekend Worker Minimization
    obj = _add_three_day_weekend_min_objective(model, obj, OBJECTIVE_FLEX_WEIGHTS[1], iso_weeks, holiday_set,
                                               shifts_by_day, assigned, num_workers)
    # Rule 3: Weekend Shift Limits
    obj = _add_weekend_shift_limits_objective(model, obj, OBJECTIVE_FLEX_WEIGHTS[2], iso_weeks, holiday_set, assigned,
                                              num_workers, shifts)
    # Rule 4: Consecutive Weekend Avoidance
    obj = _add_consecutive_weekend_avoidance_objective(model, obj, OBJECTIVE_FLEX_WEIGHTS[3], iso_weeks, holiday_set,
                                                       history, workers, assigned, num_workers, shifts, year, month)
    # Rule 5: M2 Priority
    obj = _add_m2_priority_objective(model, obj, OBJECTIVE_FLEX_WEIGHTS[4], shifts, num_shifts, assigned, workers)
    # Rules 6-10: Equity objectives
    obj = _add_equity_objective(model, obj, equity_weights, past_stats, current_stats, workers, num_workers)
    obj = _add_dow_equity_objective(model, obj, dow_equity_weight, past_stats, current_dow, workers, num_workers)
    # Rule 11: Consecutive Shifts >48h preference
    obj = _add_consec_shifts_48h_objective(model, obj, OBJECTIVE_FLEX_WEIGHTS[10], assigned, shifts, num_shifts,
                                           num_workers)
    # Deterministic tie-break: add tiny penalty based on worker index to ensure stable ordering
    obj = _add_tiebreak_objective(model, obj, assigned, num_workers, num_shifts)
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
    """
    Integrate prior assignments for ISO weeks that were excluded from optimization
    (because they were already scheduled previously). Ensures visualization for the
    selected month shows these fixed assignments and weekly summaries include them.
    """
    # Build a quick lookup of history assignments by date
    history_by_date = {}
    for w_name, months in history.items():
        for my, ass_list in months.items():
            for ass in ass_list:
                d = ass.get('date')
                sh = ass.get('shift')
                if not d or not sh:
                    continue
                history_by_date.setdefault(d, []).append({'worker': w_name, 'shift': sh, 'dur': ass.get('dur', 0)})

    # Merge daily schedule for days in excluded weeks that fall in the selected calendar month
    for d in all_days:
        iso_key = d.isocalendar()[:2]
        if iso_key in excluded_week_keys and d.month == selected_month:
            d_str = str(d)
            # Initialize entry if missing
            if d_str not in schedule:
                schedule[d_str] = {}
            # Fill each shift type from history if present
            for entry in history_by_date.get(d_str, []):
                schedule[d_str][entry['shift']] = entry['worker']
                # Also include in assignments list for completeness
                assignments.append({
                    'worker': entry['worker'],
                    'date': d_str,
                    'shift': entry['shift'],
                    'dur': entry.get('dur', 0)
                })

    # Merge weekly summaries for excluded ISO weeks
    # Build mapping from iso week key to its days within visualization window
    iso_week_days = {}
    for d in all_days:
        key = d.isocalendar()[:2]
        iso_week_days.setdefault(key, []).append(d)

    # Map worker name to standard weekly load
    worker_loads = {w['name']: w.get('weekly_load', 0) for w in workers}

    for key in excluded_week_keys:
        # Initialize weekly entry if missing
        if key not in weekly:
            weekly[key] = {}
        # Compute totals per worker from history for this iso week
        days_in_week = {str(d) for d in iso_week_days.get(key, [])}
        # Aggregate hours per worker
        hours_by_worker = {}
        for d_str in days_in_week:
            for entry in history_by_date.get(d_str, []):
                hours_by_worker[entry['worker']] = hours_by_worker.get(entry['worker'], 0) + entry.get('dur', 0)
        # Fill weekly summary using workers' standard loads
        for wk_name, wk_hours in hours_by_worker.items():
            load = worker_loads.get(wk_name, 0)
            overtime = max(0, wk_hours - load)
            undertime = max(0, load - wk_hours)
            weekly[key][wk_name] = {'hours': wk_hours, 'overtime': overtime, 'undertime': undertime}

    return schedule, weekly, assignments