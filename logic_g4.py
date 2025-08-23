import calendar
import datetime
from ortools.sat.python import cp_model
import json
from datetime import date, timedelta
from utils import compute_holidays, easter_date
from constants import *

def parse_unavail_or_req(unav_list, is_unavail=True):
    unav_set = set()
    for item in unav_list:
        parts = item.split()
        if len(parts) == 1:
            # Single date or range
            if ' to ' in item:
                start, end = item.split(' to ')
                start_d = date.fromisoformat(start)
                end_d = date.fromisoformat(end)
                d = start_d
                while d <= end_d:
                    unav_set.add((d, None))
                    d += timedelta(days=1)
            else:
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
    if holidays is None:
        holidays = []
    holiday_set = set(holidays)
    _, num_days_in_month = calendar.monthrange(year, month)
    first_day = date(year, month, 1)
    last_day = date(year, month, num_days_in_month)
    first_monday = first_day - timedelta(days=first_day.weekday())
    last_sunday = last_day + timedelta(days=(6 - last_day.weekday()))
    days = []
    current_day = first_monday
    while current_day <= last_sunday:
        days.append(current_day)
        current_day += timedelta(days=1)
    days = sorted(set(days))  # Unique days
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
            iso_weeks[key] = {'days': [], 'weekdays': [], 'shifts': [], 'weekday_shifts': [], 'monday': day - timedelta(days=day.weekday())}
        iso_weeks[key]['days'].append(day)
        if day.weekday() < 5 and day not in holiday_set:
            iso_weeks[key]['weekdays'].append(day)
        iso_weeks[key]['shifts'].append([shift['index'] for shift in shifts if shift['day'] == day])
        if day.weekday() < 5 and day not in holiday_set:
            iso_weeks[key]['weekday_shifts'].append([shift['index'] for shift in shifts if shift['day'] == day])
    for key in iso_weeks:
        iso_weeks[key]['shifts'] = [item for sublist in iso_weeks[key]['shifts'] for item in sublist]
        iso_weeks[key]['weekday_shifts'] = [item for sublist in iso_weeks[key]['weekday_shifts'] for item in sublist]
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
            avail_weekdays = [wd for wd in week['weekdays'] if (wd, None) not in unav_parsed[w]]
            if len(avail_weekdays) >= 1:
                relevant.append(w)
        num_relevant = len(relevant)
        total_weekday_shifts = len(week['weekday_shifts'])
        for w in relevant:
            num_shifts_week = sum(assigned[w][s] for s in week['shifts'])
            model.Add(num_shifts_week >= 1)
        num_weekday = [sum(assigned[w][s] for s in week['weekday_shifts']) for w in range(num_workers)]
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
    for key in iso_weeks:
        week = iso_weeks[key]
        days = week['days']
        is_three_day = False
        for day in days:
            if day in holiday_set and day.weekday() in [0, 4]:  # Monday or Friday holiday
                is_three_day = True
                break
        if not is_three_day:
            continue
        for w in range(num_workers):
            if is_three_day:
                has_shift_during_three_day = model.NewBoolVar(f'has_three_day_shift_w{w}_k{key}')
                three_day_shifts = []
                for day in days:
                    if day in holiday_set or day.weekday() >= 5:
                        three_day_shifts.extend(shifts_by_day.get(day, []))
                model.Add(sum(assigned[w][s] for s in three_day_shifts) >= 1).OnlyEnforceIf(has_shift_during_three_day)
                model.Add(sum(assigned[w][s] for s in three_day_shifts) == 0).OnlyEnforceIf(has_shift_during_three_day.Not())
                obj += weight_flex * has_shift_during_three_day
    return obj

def _add_weekend_shift_limits_objective(model, obj, weight_flex, iso_weeks, holiday_set, assigned, num_workers, shifts):
    for key in iso_weeks:
        week = iso_weeks[key]
        is_three_day = any(day in holiday_set and day.weekday() in [0, 4] for day in week['days'])
        if is_three_day:
            continue
        weekend_shifts = [s for s in week['shifts'] if shifts[s]['day'].weekday() >= 5 or shifts[s]['day'] in holiday_set]
        for w in range(num_workers):
            has_both = model.NewBoolVar(f'has_both_weekend_w{w}_k{key}')
            sum_weekend = sum(assigned[w][s] for s in weekend_shifts)
            model.Add(sum_weekend >= 2).OnlyEnforceIf(has_both)
            model.Add(sum_weekend < 2).OnlyEnforceIf(has_both.Not())
            obj += weight_flex * has_both
    return obj

def _add_consecutive_weekend_avoidance_objective(model, obj, weight_flex, iso_weeks, holiday_set, history, workers, assigned, num_workers, shifts):
    for key in iso_weeks:
        week = iso_weeks[key]
        monday = week['monday']
        weekend_prev_days = [monday - timedelta(days=2), monday - timedelta(days=1)]  # Prev Sat, Sun
        for w_idx, worker in enumerate(workers):
            w_name = worker['name']
            worked_prev = False
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
                weekend_shifts_this = [s for s in week['shifts'] if shifts[s]['day'].weekday() >= 5 or shifts[s]['day'] in holiday_set]
                has_weekend_this = model.NewBoolVar(f'has_weekend_this_w{w_idx}_k{key}')
                model.Add(sum(assigned[w_idx][s] for s in weekend_shifts_this) >= 1).OnlyEnforceIf(has_weekend_this)
                model.Add(sum(assigned[w_idx][s] for s in weekend_shifts_this) == 0).OnlyEnforceIf(has_weekend_this.Not())
                obj += weight_flex * has_weekend_this
    return obj

def _add_m2_priority_objective(model, obj, weight_flex, shifts, num_shifts, assigned, workers):
    for s in range(num_shifts):
        if shifts[s]['type'] == 'M1':
            for w in range(len(workers)):
                if workers[w]['weekly_load'] == 18:
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


def _add_saturday_preference_objective(model, obj, weight_flex, iso_weeks, assigned, num_workers, shifts, unav_parsed,
                                       holiday_set):
    for key in iso_weeks:
        week = iso_weeks[key]
        sat = week['monday'] + timedelta(days=5)  # Saturday of this ISO week
        if sat not in week[
            'days'] or sat in holiday_set:  # Skip if Saturday not in schedule or is holiday (treat as weekend but no pref)
            continue

        sat_day_shifts = [s for s in week['shifts'] if
                          shifts[s]['day'] == sat and shifts[s]['type'] in ['M1', 'M2']]  # M1 or M2 on Sat

        for w in range(num_workers):
            # Skip if unavailable on all weekdays or on Saturday
            avail_weekdays = [wd for wd in week['weekdays'] if (wd, None) not in unav_parsed[w]]
            if not avail_weekdays:
                continue
            if (sat, None) in unav_parsed[w] or all((sat, shifts[s]['type']) in unav_parsed[w] for s in sat_day_shifts):
                continue

            # Detect if worker has a weekday shift
            has_weekday = model.NewBoolVar(f'has_weekday_pref_w{w}_k{key}')
            sum_weekday = sum(assigned[w][s] for s in week['weekday_shifts'])
            model.Add(sum_weekday >= 1).OnlyEnforceIf(has_weekday)
            model.Add(sum_weekday == 0).OnlyEnforceIf(has_weekday.Not())

            # Detect if worker has a Saturday day shift (M1/M2)
            has_sat_day = model.NewBoolVar(f'has_sat_day_w{w}_k{key}')
            sum_sat_day = sum(assigned[w][s] for s in sat_day_shifts)
            model.Add(sum_sat_day >= 1).OnlyEnforceIf(has_sat_day)
            model.Add(sum_sat_day == 0).OnlyEnforceIf(has_sat_day.Not())

            # Detect if worker has any shift this week (to avoid penalizing no-shifters)
            has_any_shift = model.NewBoolVar(f'has_any_shift_w{w}_k{key}')
            sum_shifts = sum(assigned[w][s] for s in week['shifts'])
            model.Add(sum_shifts >= 1).OnlyEnforceIf(has_any_shift)
            model.Add(sum_shifts == 0).OnlyEnforceIf(has_any_shift.Not())

            # Penalty only if: no weekday, no Sat day, but has some shift (e.g., penalize Sunday or Sat night instead)
            violate_pref = model.NewBoolVar(f'v_sat_pref_w{w}_k{key}')
            model.Add(violate_pref <= has_weekday.Not())
            model.Add(violate_pref <= has_sat_day.Not())
            model.Add(violate_pref <= has_any_shift)
            model.Add(violate_pref >= has_weekday.Not() + has_sat_day.Not() + has_any_shift - 2)

            obj += weight_flex * violate_pref  # Add to objective; solver minimizes this

    return obj

def _solve_and_extract_results(model, shifts, num_shifts, days, month, shifts_by_day, iso_weeks, workers, assigned, current_stats):
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = SOLVER_TIMEOUT_SECONDS
    solver.parameters.log_search_progress = True  # Enables detailed search logs (output to console)

    status = solver.Solve(model)

    # After solve, capture and print/log stats
    print(solver.ResponseStats())  # Summary: wall time, branches, conflicts, objective bounds, etc.
    # Or access individually:
    wall_time = solver.WallTime()  # Total solve time in seconds
    branches = solver.NumBranches()  # Branches explored
    conflicts = solver.NumConflicts()  # Conflicts encountered
    objective_value = solver.ObjectiveValue() if status in [cp_model.OPTIMAL, cp_model.FEASIBLE] else None

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
        return {}, {}, [], stats

def generate_schedule(year, month, unavail_data, required_data, history, workers, holidays=None, equity_weights=None, dow_equity_weight=None):
    if equity_weights is None:
        equity_weights = EQUITY_WEIGHTS
    if dow_equity_weight is None:
        dow_equity_weight = DOW_EQUITY_WEIGHT
    holiday_set, days = _setup_holidays_and_days(year, month, holidays)
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
    # Removed: obj = _add_sat_priority_objective(...)  # Redundant due to hard no-multi-shift-per-day constraint
    obj = _add_three_day_weekend_min_objective(model, obj, OBJECTIVE_FLEX_WEIGHTS[0], iso_weeks, holiday_set,
                                               shifts_by_day, assigned, num_workers)
    obj = _add_weekend_shift_limits_objective(model, obj, OBJECTIVE_FLEX_WEIGHTS[1], iso_weeks, holiday_set, assigned,
                                              num_workers, shifts)
    obj = _add_consecutive_weekend_avoidance_objective(model, obj, OBJECTIVE_FLEX_WEIGHTS[2], iso_weeks, holiday_set,
                                                       history, workers, assigned, num_workers, shifts)
    obj = _add_m2_priority_objective(model, obj, OBJECTIVE_FLEX_WEIGHTS[3], shifts, num_shifts, assigned, workers)
    obj = _add_equity_objective(model, obj, equity_weights, past_stats, current_stats, workers, num_workers)
    obj = _add_dow_equity_objective(model, obj, dow_equity_weight, past_stats, current_dow, workers, num_workers)
    obj = _add_consec_shifts_48h_objective(model, obj, OBJECTIVE_FLEX_WEIGHTS[9], assigned, shifts, num_shifts,
                                           num_workers)
    obj = _add_saturday_preference_objective(model, obj, OBJECTIVE_FLEX_WEIGHTS[10], iso_weeks, assigned, num_workers,
                                             shifts, unav_parsed, holiday_set)
    model.Minimize(obj)
    return _solve_and_extract_results(model, shifts, num_shifts, days, month, shifts_by_day, iso_weeks, workers, assigned, current_stats)