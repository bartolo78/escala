"""CP-SAT objective builders.

These functions add terms to a numeric objective expression. They are split out
of `logic_g4.py` for modularity.

Behavior should remain identical to the original implementations.
"""

from __future__ import annotations

from datetime import timedelta

from constants import (
    CONSECUTIVE_SHIFT_PENALTY_RANGE,
    EQUITY_STATS,
    MAX_STAT_VALUE,
    NIGHT_SHIFT_MIN_INTERVAL_HOURS,
    NIGHT_SHIFT_CONSECUTIVE_MIN_HOURS,
)
from logger import get_logger

logger = get_logger('model_objectives')


def build_load_balancing_cost(model, iso_weeks, shifts, assigned, workers):
    """Return IntVar representing total load deviation (over+under) across weeks."""
    terms = []
    for key in iso_weeks:
        week_shifts = iso_weeks[key]["shifts"]
        for w in range(len(workers)):
            hours = sum(shifts[s]["dur"] * assigned[w][s] for s in week_shifts)
            load = workers[w]["weekly_load"]
            over = model.NewIntVar(0, MAX_STAT_VALUE, f"over_w{w}_k{key}")
            under = model.NewIntVar(0, MAX_STAT_VALUE, f"under_w{w}_k{key}")
            model.Add(over >= hours - load)
            model.Add(under >= load - hours)
            terms.append(over)
            terms.append(under)

    cost = model.NewIntVar(0, MAX_STAT_VALUE * max(1, len(terms)), "load_balance_cost")
    if terms:
        model.Add(cost == sum(terms))
    else:
        model.Add(cost == 0)
    return cost


def build_three_day_weekend_unique_workers_cost(model, iso_weeks, holiday_set, shifts_by_day, assigned, num_workers):
    """Return IntVar counting unique-worker usage across 3-day holiday weekends."""
    terms = []
    for key in iso_weeks:
        week = iso_weeks[key]
        days = week["days"]

        three_day_periods = []
        for day in days:
            if day in holiday_set:
                if day.weekday() == 4:  # Friday holiday -> Fri-Sat-Sun
                    fri = day
                    sat = day + timedelta(days=1)
                    sun = day + timedelta(days=2)
                    if sat in days and sun in days:
                        three_day_periods.append([fri, sat, sun])
                        logger.info(f"Three-day weekend detected in week {key}: {fri} (Fri) to {sun} (Sun)")
                    else:
                        logger.warning(f"Friday holiday {fri} found but Sat/Sun not in week days. sat in days: {sat in days}, sun in days: {sun in days}")
                elif day.weekday() == 0:  # Monday holiday -> Sat-Sun-Mon
                    mon = day
                    sat = day - timedelta(days=2)
                    sun = day - timedelta(days=1)
                    if sat in days and sun in days:
                        three_day_periods.append([sat, sun, mon])
                        logger.info(f"Three-day weekend detected in week {key}: {sat} (Sat) to {mon} (Mon)")
                    else:
                        logger.warning(f"Monday holiday {mon} found but Sat/Sun not in week days. sat in days: {sat in days}, sun in days: {sun in days}")

        for period in three_day_periods:
            period_shifts = []
            for d in period:
                period_shifts.extend(shifts_by_day.get(d, []))
            if not period_shifts:
                logger.warning(f"Three-day period {period[0]} to {period[-1]} has no shifts!")
                continue

            logger.info(f"Three-day period {period[0]} to {period[-1]} has {len(period_shifts)} shifts")
            
            for w in range(num_workers):
                has_shift_in_period = model.NewBoolVar(f"has_3day_w{w}_k{key}_{period[0]}")
                sum_in_period = sum(assigned[w][s] for s in period_shifts)
                model.Add(sum_in_period >= 1).OnlyEnforceIf(has_shift_in_period)
                model.Add(sum_in_period == 0).OnlyEnforceIf(has_shift_in_period.Not())
                terms.append(has_shift_in_period)

    cost = model.NewIntVar(0, max(1, len(terms)), "three_day_unique_workers_cost")
    if terms:
        model.Add(cost == sum(terms))
    else:
        model.Add(cost == 0)
    return cost


def build_weekend_shift_limits_cost(model, iso_weeks, holiday_set, assigned, num_workers, shifts):
    """Return IntVar counting workers assigned both Sat and Sun in a non-3-day weekend.
    
    This rule is completely disabled for weekends that are part of a three-day weekend
    (Friday-Saturday-Sunday or Saturday-Sunday-Monday due to a holiday on Friday or Monday).
    When a three-day weekend exists, the 'Three-Day Weekend Worker Minimization' rule takes
    precedence, allowing the optimizer to freely assign multiple shifts to the same worker.
    """
    terms = []
    for key in iso_weeks:
        week = iso_weeks[key]
        is_three_day = any(day in holiday_set and day.weekday() in [0, 4] for day in week["days"])
        if is_three_day:
            continue

        sat_shifts = [s for s in week["shifts"] if shifts[s]["day"].weekday() == 5]
        sun_shifts = [s for s in week["shifts"] if shifts[s]["day"].weekday() == 6]

        for w in range(num_workers):
            has_sat = model.NewBoolVar(f"has_sat_w{w}_k{key}")
            has_sun = model.NewBoolVar(f"has_sun_w{w}_k{key}")

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

            has_both = model.NewBoolVar(f"has_both_weekend_w{w}_k{key}")
            model.AddBoolAnd([has_sat, has_sun]).OnlyEnforceIf(has_both)
            model.AddBoolOr([has_sat.Not(), has_sun.Not()]).OnlyEnforceIf(has_both.Not())
            terms.append(has_both)

    cost = model.NewIntVar(0, max(1, len(terms)), "weekend_shift_limits_cost")
    if terms:
        model.Add(cost == sum(terms))
    else:
        model.Add(cost == 0)
    return cost


def build_consecutive_weekend_avoidance_cost(model, iso_weeks, holiday_set, history, workers, assigned, num_workers, shifts, year, month):
    """Return IntVar counting consecutive-weekend penalties (Flexible Rule 4)."""
    terms = []
    # Sort weeks chronologically by their monday date
    sorted_keys = sorted(iso_weeks.keys(), key=lambda k: iso_weeks[k]["monday"])

    current_month_str = f"{year}-{month:02d}"
    history_has_weekend_in_month = set()
    for w_name, months_data in (history or {}).items():
        if current_month_str not in months_data:
            continue
        for ass in months_data[current_month_str]:
            try:
                d = __import__("datetime").date.fromisoformat(ass["date"])
            except Exception:
                continue
            if d.weekday() >= 5:
                history_has_weekend_in_month.add(w_name)
                break

    has_weekend_week = {}
    for i, key in enumerate(sorted_keys):
        week = iso_weeks[key]
        weekend_shifts_in_month = [
            s for s in week["shifts"] if shifts[s]["day"].weekday() >= 5 and shifts[s]["day"].month == month
        ]
        for w_idx in range(num_workers):
            var = model.NewBoolVar(f"has_wknd_m{month}_w{w_idx}_i{i}")
            if weekend_shifts_in_month:
                model.Add(sum(assigned[w_idx][s] for s in weekend_shifts_in_month) >= 1).OnlyEnforceIf(var)
                model.Add(sum(assigned[w_idx][s] for s in weekend_shifts_in_month) == 0).OnlyEnforceIf(var.Not())
            else:
                model.Add(var == 0)
            has_weekend_week[(w_idx, i)] = var

    prefix = {}
    for w_idx, worker in enumerate(workers):
        base = 1 if worker["name"] in history_has_weekend_in_month else 0
        for i in range(len(sorted_keys)):
            p = model.NewBoolVar(f"wknd_prefix_m{month}_w{w_idx}_i{i}")
            if i == 0:
                if base:
                    model.Add(p == 1)
                else:
                    model.Add(p >= has_weekend_week[(w_idx, 0)])
                    model.Add(p <= has_weekend_week[(w_idx, 0)])
            else:
                prev = prefix[(w_idx, i - 1)]
                cur = has_weekend_week[(w_idx, i)]
                model.Add(p >= prev)
                model.Add(p >= cur)
                model.Add(p <= prev + cur)
            prefix[(w_idx, i)] = p

    for i, key in enumerate(sorted_keys):
        week = iso_weeks[key]
        monday = week["monday"]

        weekend_shifts_this_week = [s for s in week["shifts"] if shifts[s]["day"].weekday() >= 5]
        if not weekend_shifts_this_week:
            continue

        for w_idx, worker in enumerate(workers):
            w_name = worker["name"]

            worked_prev = False
            weekend_prev_days = [monday - timedelta(days=2), monday - timedelta(days=1)]
            for d in weekend_prev_days:
                m_y = d.strftime("%Y-%m")
                day_str = str(d)
                if m_y in (history or {}).get(w_name, {}):
                    for ass in history[w_name][m_y]:
                        if ass.get("date") == day_str:
                            worked_prev = True
                            break
                if worked_prev:
                    break

            if not worked_prev:
                continue

            if i == 0:
                others_without_weekend = [
                    model.NewConstant(1)
                    for other_idx, other_w in enumerate(workers)
                    if other_idx != w_idx and other_w["name"] not in history_has_weekend_in_month
                ]
            else:
                others_without_weekend = [
                    prefix[(other_idx, i - 1)].Not() for other_idx in range(num_workers) if other_idx != w_idx
                ]

            if not others_without_weekend:
                continue

            any_other_without = model.NewBoolVar(f"any_other_no_wknd_m{month}_w{w_idx}_i{i}")
            model.AddBoolOr(list(others_without_weekend)).OnlyEnforceIf(any_other_without)
            model.AddBoolAnd([lit.Not() for lit in others_without_weekend]).OnlyEnforceIf(any_other_without.Not())

            pen = model.NewBoolVar(f"consec_wknd_pen_w{w_idx}_i{i}")
            model.Add(pen <= has_weekend_week[(w_idx, i)])
            model.Add(pen <= any_other_without)
            model.Add(pen >= has_weekend_week[(w_idx, i)] + any_other_without - 1)
            terms.append(pen)

    cost = model.NewIntVar(0, max(1, len(terms)), "consecutive_weekend_avoidance_cost")
    if terms:
        model.Add(cost == sum(terms))
    else:
        model.Add(cost == 0)
    return cost


def build_m2_priority_cost(model, shifts, assigned, workers):
    """Return IntVar counting M1 assignments given to 18h workers (lower is better)."""
    terms = []
    for s, sh in enumerate(shifts):
        if sh["type"] != "M1":
            continue
        for w in range(len(workers)):
            if workers[w].get("weekly_load") == 18:
                terms.append(assigned[w][s])

    cost = model.NewIntVar(0, max(1, len(terms)), "m2_priority_cost")
    if terms:
        model.Add(cost == sum(terms))
    else:
        model.Add(cost == 0)
    return cost


def build_equity_cost_scaled(model, equity_weights, past_stats, current_stats, workers, num_workers, scale: int = 10):
    """Return IntVar for equity objective with integer-scaled weights.

    CP-SAT objectives are integer-based. We scale potentially-float weights to
    integers so lexicographic solving can fix exact objective values.
    """
    terms = []
    for stat in EQUITY_STATS:
        weight = equity_weights.get(stat, 0)
        weight_i = int(round(float(weight) * scale))
        if weight_i == 0:
            continue

        totals = [past_stats[workers[w]["name"]][stat] + current_stats[stat][w] for w in range(num_workers)]
        max_t = model.NewIntVar(0, MAX_STAT_VALUE, f"max_{stat}")
        min_t = model.NewIntVar(0, MAX_STAT_VALUE, f"min_{stat}")
        for t in totals:
            model.Add(max_t >= t)
            model.Add(min_t <= t)
        terms.append(weight_i * (max_t - min_t))

    cost = model.NewIntVar(0, MAX_STAT_VALUE * max(1, len(EQUITY_STATS)) * max(1, scale), "equity_cost")
    if terms:
        model.Add(cost == sum(terms))
    else:
        model.Add(cost == 0)
    return cost


def build_dow_equity_cost_scaled(model, dow_equity_weight, past_stats, current_dow, workers, num_workers, scale: int = 10):
    weight_i = int(round(float(dow_equity_weight) * scale))
    terms = []
    if weight_i != 0:
        for d in range(7):
            totals_d = [past_stats[workers[w]["name"]]["dow"][d] + current_dow[d][w] for w in range(num_workers)]
            max_d = model.NewIntVar(0, MAX_STAT_VALUE, f"max_dow{d}")
            min_d = model.NewIntVar(0, MAX_STAT_VALUE, f"min_dow{d}")
            for t in totals_d:
                model.Add(max_d >= t)
                model.Add(min_d <= t)
            terms.append(weight_i * (max_d - min_d))

    cost = model.NewIntVar(0, MAX_STAT_VALUE * 7 * max(1, scale), "dow_equity_cost")
    if terms:
        model.Add(cost == sum(terms))
    else:
        model.Add(cost == 0)
    return cost


def build_consec_shifts_48h_cost(model, assigned, shifts, num_shifts, num_workers):
    """Return IntVar counting <48h-rest-but-legal consecutive shift pairs."""
    min_penalty, max_penalty = CONSECUTIVE_SHIFT_PENALTY_RANGE
    terms = []
    for w in range(num_workers):
        for i in range(num_shifts):
            for j in range(i + 1, num_shifts):
                si = shifts[i]
                sj = shifts[j]
                if si["day"] == sj["day"]:
                    continue
                start_i = si["start"]
                end_i = si["end"]
                start_j = sj["start"]
                end_j = sj["end"]
                if max(start_i, start_j) < min(end_i, end_j):
                    continue
                delta = abs(
                    (start_j - end_i).total_seconds() / 3600 if start_j > end_i else (start_i - end_j).total_seconds() / 3600
                )
                if min_penalty <= delta < max_penalty:
                    violate = model.NewBoolVar(f"v48_w{w}_i{i}_j{j}")
                    model.Add(violate <= assigned[w][i])
                    model.Add(violate <= assigned[w][j])
                    model.Add(violate >= assigned[w][i] + assigned[w][j] - 1)
                    terms.append(violate)

    cost = model.NewIntVar(0, max(1, len(terms)), "consec_shifts_48h_cost")
    if terms:
        model.Add(cost == sum(terms))
    else:
        model.Add(cost == 0)
    return cost


def build_night_shift_min_interval_cost(model, assigned, shifts, num_shifts, num_workers):
    """Return IntVar penalizing night shifts with less than 48h between them.
    
    This implements Flexible Rule 12: avoid night shifts with 48h or less apart.
    If a worker does a night shift on day 1, they shouldn't do another night shift
    on day 3 (which would be within 48h of each other, start-to-start).
    
    The penalty is applied when two night shifts have their start times within
    NIGHT_SHIFT_MIN_INTERVAL_HOURS (48h) of each other.
    """
    terms = []
    night_shift_indices = [i for i in range(num_shifts) if shifts[i].get("night", False)]
    
    for w in range(num_workers):
        for idx_i, i in enumerate(night_shift_indices):
            for j in night_shift_indices[idx_i + 1:]:
                si = shifts[i]
                sj = shifts[j]
                
                # Calculate hours between start times
                start_i = si["start"]
                start_j = sj["start"]
                delta_hours = abs((start_j - start_i).total_seconds()) / 3600
                
                # Penalize if night shifts are within NIGHT_SHIFT_MIN_INTERVAL_HOURS of each other
                if delta_hours <= NIGHT_SHIFT_MIN_INTERVAL_HOURS:
                    violate = model.NewBoolVar(f"night_interval_w{w}_i{i}_j{j}")
                    model.Add(violate <= assigned[w][i])
                    model.Add(violate <= assigned[w][j])
                    model.Add(violate >= assigned[w][i] + assigned[w][j] - 1)
                    terms.append(violate)
    
    cost = model.NewIntVar(0, max(1, len(terms)), "night_shift_min_interval_cost")
    if terms:
        model.Add(cost == sum(terms))
    else:
        model.Add(cost == 0)
    return cost


def build_consecutive_night_shift_avoidance_cost(model, assigned, shifts, num_shifts, num_workers):
    """Return IntVar penalizing consecutive night shifts unless 96h apart.
    
    This implements Flexible Rule 13: avoid 2 night shifts in a row, unless
    the begin of one shift and the begin of the next are separated by at least
    NIGHT_SHIFT_CONSECUTIVE_MIN_HOURS (96h).
    
    "Consecutive" means back-to-back nights (day N and day N+1). The penalty
    is applied unless the start times are at least 96h apart.
    """
    terms = []
    night_shift_indices = [i for i in range(num_shifts) if shifts[i].get("night", False)]
    
    for w in range(num_workers):
        for idx_i, i in enumerate(night_shift_indices):
            for j in night_shift_indices[idx_i + 1:]:
                si = shifts[i]
                sj = shifts[j]
                
                # Check if these are consecutive nights (1 day apart)
                day_i = si["day"]
                day_j = sj["day"]
                days_apart = abs((day_j - day_i).days)
                
                if days_apart != 1:
                    continue  # Not consecutive nights
                
                # Calculate hours between start times
                start_i = si["start"]
                start_j = sj["start"]
                delta_hours = abs((start_j - start_i).total_seconds()) / 3600
                
                # Penalize consecutive nights unless start times are >= 96h apart
                # (which would happen in special scheduling scenarios like 3-day weekends)
                if delta_hours < NIGHT_SHIFT_CONSECUTIVE_MIN_HOURS:
                    violate = model.NewBoolVar(f"consec_night_w{w}_i{i}_j{j}")
                    model.Add(violate <= assigned[w][i])
                    model.Add(violate <= assigned[w][j])
                    model.Add(violate >= assigned[w][i] + assigned[w][j] - 1)
                    terms.append(violate)
    
    cost = model.NewIntVar(0, max(1, len(terms)), "consecutive_night_shift_avoidance_cost")
    if terms:
        model.Add(cost == sum(terms))
    else:
        model.Add(cost == 0)
    return cost


def build_tiebreak_cost(model, assigned, num_workers, num_shifts, workers):
    """Return IntVar that prefers lower (id,name) workers in remaining ties."""

    def _worker_key(worker: dict) -> tuple[str, str]:
        worker_id = worker.get("id")
        worker_name = worker.get("name")
        return (str(worker_id) if worker_id is not None else "", str(worker_name) if worker_name is not None else "")

    order = sorted(range(num_workers), key=lambda i: _worker_key(workers[i]))
    rank_by_index = {idx: rank for rank, idx in enumerate(order)}
    terms = []
    for w in range(num_workers):
        rank = rank_by_index[w]
        for s in range(num_shifts):
            if rank:
                terms.append(rank * assigned[w][s])
            else:
                terms.append(assigned[w][s] * 0)

    # Upper bound: rank max ~ num_workers, assignments total ~ num_shifts
    cost = model.NewIntVar(0, max(1, num_workers * num_shifts), "tiebreak_cost")
    if terms:
        model.Add(cost == sum(terms))
    else:
        model.Add(cost == 0)
    return cost


def build_saturday_preference_cost(model, iso_weeks, assigned, num_workers, shifts, unav_parsed, holiday_set=None):
    """Return IntVar encoding the first-shift fallback preference (Flexible Rule 1).

    This keeps the *same approximation* as the existing objective: it prefers
    each worker to have at least one shift in the best-available category
    (weekday day, weekday night, Saturday day, ...).
    
    During three-day weekends (Friday or Monday holiday), the Saturday/Sunday
    penalties are skipped to avoid conflicting with the Three-Day Weekend Worker
    Minimization rule which has priority for those weekends.
    """
    if holiday_set is None:
        holiday_set = set()

    terms = []
    for key in iso_weeks:
        week = iso_weeks[key]
        sat = week["monday"] + timedelta(days=5)
        sun = week["monday"] + timedelta(days=6)
        
        # Check if this week has a three-day weekend (Friday or Monday holiday)
        is_three_day_weekend = any(day in holiday_set and day.weekday() in [0, 4] for day in week["days"])

        weekday_day_shifts = [s for s in week["shifts"] if shifts[s]["day"].weekday() < 5 and not shifts[s]["night"]]
        weekday_night_shifts = [s for s in week["shifts"] if shifts[s]["day"].weekday() < 5 and shifts[s]["night"]]
        sat_day_shifts = [s for s in week["shifts"] if shifts[s]["day"] == sat and not shifts[s]["night"]]
        sat_night_shifts = [s for s in week["shifts"] if shifts[s]["day"] == sat and shifts[s]["night"]]
        sun_day_shifts = [s for s in week["shifts"] if shifts[s]["day"] == sun and not shifts[s]["night"]]
        sun_night_shifts = [s for s in week["shifts"] if shifts[s]["day"] == sun and shifts[s]["night"]]

        for w in range(num_workers):
            weekday_dates = [d for d in week["days"] if d.weekday() < 5]
            avail_weekdays = [wd for wd in weekday_dates if (wd, None) not in unav_parsed[w]]
            if not avail_weekdays:
                continue

            has_weekday_day = model.NewBoolVar(f"has_wd_day_w{w}_k{key}")
            has_weekday_night = model.NewBoolVar(f"has_wd_night_w{w}_k{key}")
            has_sat_day = model.NewBoolVar(f"has_sat_day_w{w}_k{key}")
            has_sat_night = model.NewBoolVar(f"has_sat_night_w{w}_k{key}")
            has_sun_day = model.NewBoolVar(f"has_sun_day_w{w}_k{key}")
            has_sun_night = model.NewBoolVar(f"has_sun_night_w{w}_k{key}")
            has_any_shift = model.NewBoolVar(f"has_any_w{w}_k{key}")

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

            sum_all = sum(assigned[w][s] for s in week["shifts"])
            model.Add(sum_all >= 1).OnlyEnforceIf(has_any_shift)
            model.Add(sum_all == 0).OnlyEnforceIf(has_any_shift.Not())

            # During three-day weekends, skip the Saturday/Sunday tier penalties to let
            # the Three-Day Weekend Worker Minimization rule (rule 2) take precedence.
            # Workers whose first shift is on Sat/Sun during a 3-day weekend get no penalty.
            if is_three_day_weekend:
                # Only track weekday tier penalties; Sat/Sun shifts get tier 0 (no penalty)
                t0 = model.NewBoolVar(f"t0_w{w}_k{key}")
                t1 = model.NewBoolVar(f"t1_w{w}_k{key}")
                
                model.Add(t0 + t1 == 0).OnlyEnforceIf(has_any_shift.Not())
                model.Add(t0 + t1 == 1).OnlyEnforceIf(has_any_shift)
                
                # Tier 0: has weekday day OR has any Saturday/Sunday shift (no penalty)
                has_weekend = model.NewBoolVar(f"has_weekend_w{w}_k{key}")
                weekend_sum = []
                if sat_day_shifts:
                    weekend_sum.extend([assigned[w][s] for s in sat_day_shifts])
                if sat_night_shifts:
                    weekend_sum.extend([assigned[w][s] for s in sat_night_shifts])
                if sun_day_shifts:
                    weekend_sum.extend([assigned[w][s] for s in sun_day_shifts])
                if sun_night_shifts:
                    weekend_sum.extend([assigned[w][s] for s in sun_night_shifts])
                if weekend_sum:
                    model.Add(sum(weekend_sum) >= 1).OnlyEnforceIf(has_weekend)
                    model.Add(sum(weekend_sum) == 0).OnlyEnforceIf(has_weekend.Not())
                else:
                    model.Add(has_weekend == 0)
                
                # t0 = has weekday day OR has weekend shift (both get no penalty during 3-day weekend)
                model.AddBoolOr([has_weekday_day, has_weekend]).OnlyEnforceIf([has_any_shift, t0])
                model.Add(t0 == 0).OnlyEnforceIf([has_weekday_day.Not(), has_weekend.Not()])
                
                # Tier 1: has weekday night only (slight penalty)
                model.Add(t1 <= has_weekday_day.Not())
                model.Add(t1 <= has_weekend.Not())
                model.Add(t1 <= has_weekday_night)
                model.Add(t1 >= has_weekday_day.Not() + has_weekend.Not() + has_weekday_night + has_any_shift - 3)
                
                # Cost: only tier 1 has penalty (1 point for weekday night being first shift)
                terms.append(1 * t1)
                continue  # Skip the normal tier logic below

            # Normal week (no three-day weekend): full tier penalty logic
            # Exclusive tier selection, best available category wins.
            t0 = model.NewBoolVar(f"t0_w{w}_k{key}")
            t1 = model.NewBoolVar(f"t1_w{w}_k{key}")
            t2 = model.NewBoolVar(f"t2_w{w}_k{key}")
            t3 = model.NewBoolVar(f"t3_w{w}_k{key}")
            t4 = model.NewBoolVar(f"t4_w{w}_k{key}")
            t5 = model.NewBoolVar(f"t5_w{w}_k{key}")

            # If the worker has no shift (shouldn't happen for eligible workers), don't penalize.
            model.Add(t0 + t1 + t2 + t3 + t4 + t5 == 0).OnlyEnforceIf(has_any_shift.Not())
            model.Add(t0 + t1 + t2 + t3 + t4 + t5 == 1).OnlyEnforceIf(has_any_shift)

            # Tier 0: has weekday day.
            model.Add(t0 == 1).OnlyEnforceIf([has_any_shift, has_weekday_day])
            model.Add(t0 == 0).OnlyEnforceIf(has_weekday_day.Not())

            # Tier 1..5: require no better tier is available.
            model.Add(t1 <= has_weekday_day.Not())
            model.Add(t1 <= has_weekday_night)
            model.Add(t1 >= has_weekday_day.Not() + has_weekday_night + has_any_shift - 2)

            model.Add(t2 <= has_weekday_day.Not())
            model.Add(t2 <= has_weekday_night.Not())
            model.Add(t2 <= has_sat_day)
            model.Add(t2 >= has_weekday_day.Not() + has_weekday_night.Not() + has_sat_day + has_any_shift - 3)

            model.Add(t3 <= has_weekday_day.Not())
            model.Add(t3 <= has_weekday_night.Not())
            model.Add(t3 <= has_sat_day.Not())
            model.Add(t3 <= has_sat_night)
            model.Add(t3 >= has_weekday_day.Not() + has_weekday_night.Not() + has_sat_day.Not() + has_sat_night + has_any_shift - 4)

            model.Add(t4 <= has_weekday_day.Not())
            model.Add(t4 <= has_weekday_night.Not())
            model.Add(t4 <= has_sat_day.Not())
            model.Add(t4 <= has_sat_night.Not())
            model.Add(t4 <= has_sun_day)
            model.Add(t4 >= has_weekday_day.Not() + has_weekday_night.Not() + has_sat_day.Not() + has_sat_night.Not() + has_sun_day + has_any_shift - 5)

            model.Add(t5 <= has_weekday_day.Not())
            model.Add(t5 <= has_weekday_night.Not())
            model.Add(t5 <= has_sat_day.Not())
            model.Add(t5 <= has_sat_night.Not())
            model.Add(t5 <= has_sun_day.Not())
            model.Add(t5 <= has_sun_night)
            model.Add(t5 >= has_weekday_day.Not() + has_weekday_night.Not() + has_sat_day.Not() + has_sat_night.Not() + has_sun_day.Not() + has_sun_night + has_any_shift - 6)

            # Cost contribution = tier index.
            terms.append(1 * t1 + 2 * t2 + 3 * t3 + 4 * t4 + 5 * t5)

    cost = model.NewIntVar(0, 5 * num_workers * max(1, len(iso_weeks)), "saturday_preference_cost")
    if terms:
        model.Add(cost == sum(terms))
    else:
        model.Add(cost == 0)
    return cost


def define_current_stats_vars(model, assigned, stat_indices, num_workers):
    """Define current stats variables for RULES.md equity priority order."""
    current_stats = {}
    for stat in EQUITY_STATS:
        current_stats[stat] = [sum(assigned[w][s] for s in stat_indices[stat]) for w in range(num_workers)]
    current_dow = [[sum(assigned[w][s] for s in stat_indices["dow"][d]) for w in range(num_workers)] for d in range(7)]
    return current_stats, current_dow


def add_load_balancing_objective(model, obj, iso_weeks, shifts, assigned, workers, weight_load):
    for key in iso_weeks:
        week_shifts = iso_weeks[key]["shifts"]
        for w in range(len(workers)):
            hours = sum(shifts[s]["dur"] * assigned[w][s] for s in week_shifts)
            load = workers[w]["weekly_load"]
            over = model.NewIntVar(0, MAX_STAT_VALUE, f"over_w{w}_k{key}")
            under = model.NewIntVar(0, MAX_STAT_VALUE, f"under_w{w}_k{key}")
            model.Add(over >= hours - load)
            model.Add(under >= load - hours)
            obj += weight_load * (over + under)
    return obj


def add_three_day_weekend_min_objective(model, obj, weight_flex, iso_weeks, holiday_set, shifts_by_day, assigned, num_workers):
    for key in iso_weeks:
        week = iso_weeks[key]
        days = week["days"]

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
            period_shifts = []
            for d in period:
                period_shifts.extend(shifts_by_day.get(d, []))

            if not period_shifts:
                continue

            for w in range(num_workers):
                has_shift_in_period = model.NewBoolVar(f"has_3day_w{w}_k{key}_{period[0]}")
                sum_in_period = sum(assigned[w][s] for s in period_shifts)
                model.Add(sum_in_period >= 1).OnlyEnforceIf(has_shift_in_period)
                model.Add(sum_in_period == 0).OnlyEnforceIf(has_shift_in_period.Not())
                obj += weight_flex * has_shift_in_period

    return obj


def add_weekend_shift_limits_objective(model, obj, weight_flex, iso_weeks, holiday_set, assigned, num_workers, shifts):
    for key in iso_weeks:
        week = iso_weeks[key]
        is_three_day = any(day in holiday_set and day.weekday() in [0, 4] for day in week["days"])
        if is_three_day:
            continue

        sat_shifts = [s for s in week["shifts"] if shifts[s]["day"].weekday() == 5]
        sun_shifts = [s for s in week["shifts"] if shifts[s]["day"].weekday() == 6]

        for w in range(num_workers):
            has_sat = model.NewBoolVar(f"has_sat_w{w}_k{key}")
            has_sun = model.NewBoolVar(f"has_sun_w{w}_k{key}")

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

            has_both = model.NewBoolVar(f"has_both_weekend_w{w}_k{key}")
            model.AddBoolAnd([has_sat, has_sun]).OnlyEnforceIf(has_both)
            model.AddBoolOr([has_sat.Not(), has_sun.Not()]).OnlyEnforceIf(has_both.Not())
            obj += weight_flex * has_both

    return obj


def add_consecutive_weekend_avoidance_objective(model, obj, weight_flex, iso_weeks, holiday_set, history, workers, assigned, num_workers, shifts, year, month):
    # Sort weeks chronologically by their monday date
    sorted_keys = sorted(iso_weeks.keys(), key=lambda k: iso_weeks[k]["monday"])

    # History: who already has a weekend (Sat/Sun) shift in the current calendar month
    current_month_str = f"{year}-{month:02d}"
    history_has_weekend_in_month = set()
    for w_name, months_data in (history or {}).items():
        if current_month_str not in months_data:
            continue
        for ass in months_data[current_month_str]:
            try:
                d = __import__("datetime").date.fromisoformat(ass["date"])
            except Exception:
                continue
            if d.weekday() >= 5:
                history_has_weekend_in_month.add(w_name)
                break

    # For each week, create bool vars for whether a worker has a weekend shift *in the selected month*
    has_weekend_week = {}  # (w_idx, week_i) -> BoolVar
    for i, key in enumerate(sorted_keys):
        week = iso_weeks[key]
        weekend_shifts_in_month = [
            s
            for s in week["shifts"]
            if shifts[s]["day"].weekday() >= 5 and shifts[s]["day"].month == month
        ]
        for w_idx in range(num_workers):
            var = model.NewBoolVar(f"has_wknd_m{month}_w{w_idx}_i{i}")
            if weekend_shifts_in_month:
                model.Add(sum(assigned[w_idx][s] for s in weekend_shifts_in_month) >= 1).OnlyEnforceIf(var)
                model.Add(sum(assigned[w_idx][s] for s in weekend_shifts_in_month) == 0).OnlyEnforceIf(var.Not())
            else:
                model.Add(var == 0)
            has_weekend_week[(w_idx, i)] = var

    # Prefix: weekend worked earlier in the month (history + previous weeks)
    prefix = {}  # (w_idx, i) -> BoolVar meaning weekend in month up through week i
    for w_idx, worker in enumerate(workers):
        base = 1 if worker["name"] in history_has_weekend_in_month else 0
        for i in range(len(sorted_keys)):
            p = model.NewBoolVar(f"wknd_prefix_m{month}_w{w_idx}_i{i}")
            if i == 0:
                if base:
                    model.Add(p == 1)
                else:
                    # p == has_weekend_week[w,0]
                    model.Add(p >= has_weekend_week[(w_idx, 0)])
                    model.Add(p <= has_weekend_week[(w_idx, 0)])
            else:
                prev = prefix[(w_idx, i - 1)]
                cur = has_weekend_week[(w_idx, i)]
                # p = OR(prev, cur)
                model.Add(p >= prev)
                model.Add(p >= cur)
                model.Add(p <= prev + cur)
            prefix[(w_idx, i)] = p

    for i, key in enumerate(sorted_keys):
        week = iso_weeks[key]
        monday = week["monday"]

        # Weekend shifts of this ISO week (used for consecutive lookback), regardless of month.
        weekend_shifts_this_week = [s for s in week["shifts"] if shifts[s]["day"].weekday() >= 5]
        if not weekend_shifts_this_week:
            continue

        # Determine which workers have had a weekend in the month *before* this week.
        # For week index 0, this is just the history base.
        for w_idx, worker in enumerate(workers):
            w_name = worker["name"]

            # Consecutive lookback: did worker work the previous weekend (Sat/Sun) in history?
            worked_prev = False
            weekend_prev_days = [monday - timedelta(days=2), monday - timedelta(days=1)]
            for d in weekend_prev_days:
                m_y = d.strftime("%Y-%m")
                day_str = str(d)
                if m_y in (history or {}).get(w_name, {}):
                    for ass in history[w_name][m_y]:
                        if ass.get("date") == day_str:
                            worked_prev = True
                            break
                if worked_prev:
                    break

            if not worked_prev:
                continue

            # If there exists another worker with no weekend earlier in the month, penalize
            # assigning this worker a weekend shift (in-month) in this week.
            if i == 0:
                others_without_weekend = [
                    model.NewConstant(1)
                    for other_idx, other_w in enumerate(workers)
                    if other_idx != w_idx and other_w["name"] not in history_has_weekend_in_month
                ]
            else:
                others_without_weekend = [
                    prefix[(other_idx, i - 1)].Not()
                    for other_idx in range(num_workers)
                    if other_idx != w_idx
                ]

            if not others_without_weekend:
                continue

            any_other_without = model.NewBoolVar(f"any_other_no_wknd_m{month}_w{w_idx}_i{i}")
            model.AddBoolOr(list(others_without_weekend)).OnlyEnforceIf(any_other_without)
            model.AddBoolAnd([lit.Not() for lit in others_without_weekend]).OnlyEnforceIf(any_other_without.Not())

            pen = model.NewBoolVar(f"consec_wknd_pen_w{w_idx}_i{i}")
            model.Add(pen <= has_weekend_week[(w_idx, i)])
            model.Add(pen <= any_other_without)
            model.Add(pen >= has_weekend_week[(w_idx, i)] + any_other_without - 1)
            obj += weight_flex * pen

    return obj


def add_m2_priority_objective(model, obj, weight_flex, shifts, num_shifts, assigned, workers):
    for s in range(num_shifts):
        if shifts[s]["type"] == "M1":
            for w in range(len(workers)):
                if workers[w]["weekly_load"] == 18:
                    obj += weight_flex * assigned[w][s]
    return obj


def add_equity_objective(model, obj, equity_weights, past_stats, current_stats, workers, num_workers):
    for stat in EQUITY_STATS:
        totals = [past_stats[workers[w]["name"]][stat] + current_stats[stat][w] for w in range(num_workers)]
        max_t = model.NewIntVar(0, MAX_STAT_VALUE, f"max_{stat}")
        min_t = model.NewIntVar(0, MAX_STAT_VALUE, f"min_{stat}")
        for t in totals:
            model.Add(max_t >= t)
            model.Add(min_t <= t)
        obj += equity_weights.get(stat, 0) * (max_t - min_t)
    return obj


def add_dow_equity_objective(model, obj, dow_equity_weight, past_stats, current_dow, workers, num_workers):
    for d in range(7):
        totals_d = [past_stats[workers[w]["name"]]["dow"][d] + current_dow[d][w] for w in range(num_workers)]
        max_d = model.NewIntVar(0, MAX_STAT_VALUE, f"max_dow{d}")
        min_d = model.NewIntVar(0, MAX_STAT_VALUE, f"min_dow{d}")
        for t in totals_d:
            model.Add(max_d >= t)
            model.Add(min_d <= t)
        obj += dow_equity_weight * (max_d - min_d)
    return obj


def add_consec_shifts_48h_objective(model, obj, weight_flex, assigned, shifts, num_shifts, num_workers):
    min_penalty, max_penalty = CONSECUTIVE_SHIFT_PENALTY_RANGE
    for w in range(num_workers):
        for i in range(num_shifts):
            for j in range(i + 1, num_shifts):
                si = shifts[i]
                sj = shifts[j]
                if si["day"] == sj["day"]:
                    continue
                start_i = si["start"]
                end_i = si["end"]
                start_j = sj["start"]
                end_j = sj["end"]
                if max(start_i, start_j) < min(end_i, end_j):
                    continue
                delta = abs(
                    (start_j - end_i).total_seconds() / 3600 if start_j > end_i else (start_i - end_j).total_seconds() / 3600
                )
                if min_penalty <= delta < max_penalty:
                    violate = model.NewBoolVar(f"v48_w{w}_i{i}_j{j}")
                    model.Add(violate <= assigned[w][i])
                    model.Add(violate <= assigned[w][j])
                    model.Add(violate >= assigned[w][i] + assigned[w][j] - 1)
                    obj += weight_flex * violate
    return obj


def add_night_shift_min_interval_objective(model, obj, weight_flex, assigned, shifts, num_shifts, num_workers):
    """Add penalty for night shifts within 48h of each other (Flexible Rule 12).
    
    Penalizes having two night shifts where start times are within
    NIGHT_SHIFT_MIN_INTERVAL_HOURS (48h) of each other.
    """
    night_shift_indices = [i for i in range(num_shifts) if shifts[i].get("night", False)]
    
    for w in range(num_workers):
        for idx_i, i in enumerate(night_shift_indices):
            for j in night_shift_indices[idx_i + 1:]:
                si = shifts[i]
                sj = shifts[j]
                
                start_i = si["start"]
                start_j = sj["start"]
                delta_hours = abs((start_j - start_i).total_seconds()) / 3600
                
                if delta_hours <= NIGHT_SHIFT_MIN_INTERVAL_HOURS:
                    violate = model.NewBoolVar(f"night_interval_obj_w{w}_i{i}_j{j}")
                    model.Add(violate <= assigned[w][i])
                    model.Add(violate <= assigned[w][j])
                    model.Add(violate >= assigned[w][i] + assigned[w][j] - 1)
                    obj += weight_flex * violate
    return obj


def add_consecutive_night_shift_avoidance_objective(model, obj, weight_flex, assigned, shifts, num_shifts, num_workers):
    """Add penalty for consecutive night shifts unless 96h apart (Flexible Rule 13).
    
    Penalizes having two consecutive nights (day N and day N+1) unless the
    start times are at least NIGHT_SHIFT_CONSECUTIVE_MIN_HOURS (96h) apart.
    """
    night_shift_indices = [i for i in range(num_shifts) if shifts[i].get("night", False)]
    
    for w in range(num_workers):
        for idx_i, i in enumerate(night_shift_indices):
            for j in night_shift_indices[idx_i + 1:]:
                si = shifts[i]
                sj = shifts[j]
                
                # Check if consecutive nights (1 day apart)
                day_i = si["day"]
                day_j = sj["day"]
                days_apart = abs((day_j - day_i).days)
                
                if days_apart != 1:
                    continue
                
                start_i = si["start"]
                start_j = sj["start"]
                delta_hours = abs((start_j - start_i).total_seconds()) / 3600
                
                if delta_hours < NIGHT_SHIFT_CONSECUTIVE_MIN_HOURS:
                    violate = model.NewBoolVar(f"consec_night_obj_w{w}_i{i}_j{j}")
                    model.Add(violate <= assigned[w][i])
                    model.Add(violate <= assigned[w][j])
                    model.Add(violate >= assigned[w][i] + assigned[w][j] - 1)
                    obj += weight_flex * violate
    return obj


def add_tiebreak_objective(model, obj, assigned, num_workers, num_shifts, workers):
    """Add a deterministic, stable tie-break term.

    RULES.md requires stable tie-breaks to avoid oscillations across runs.
    We rank workers by (id, name) and add a small integer penalty proportional
    to the rank so the solver prefers earlier workers when costs are otherwise equal.

    NOTE: CP-SAT objectives are integer-based, so we use integer weights.
    The weight is kept small (1 per rank) to only affect true ties.
    """

    def _worker_key(worker: dict) -> tuple[str, str]:
        worker_id = worker.get("id")
        worker_name = worker.get("name")
        return (str(worker_id) if worker_id is not None else "", str(worker_name) if worker_name is not None else "")

    order = sorted(range(num_workers), key=lambda i: _worker_key(workers[i]))
    rank_by_index = {idx: rank for rank, idx in enumerate(order)}

    # Use integer weight of 1 per rank (CP-SAT requires integer coefficients)
    for w in range(num_workers):
        rank = rank_by_index[w]
        for s in range(num_shifts):
            if rank:
                obj += rank * assigned[w][s]
    return obj


def add_saturday_preference_objective(model, obj, weight_flex, iso_weeks, assigned, num_workers, shifts, unav_parsed, holiday_set):
    for key in iso_weeks:
        week = iso_weeks[key]
        sat = week["monday"] + timedelta(days=5)
        sun = week["monday"] + timedelta(days=6)
        
        # Check if this week has a three-day weekend (Friday or Monday holiday)
        is_three_day_weekend = any(day in holiday_set and day.weekday() in [0, 4] for day in week["days"])

        weekday_day_shifts = [s for s in week["shifts"] if shifts[s]["day"].weekday() < 5 and not shifts[s]["night"]]
        weekday_night_shifts = [s for s in week["shifts"] if shifts[s]["day"].weekday() < 5 and shifts[s]["night"]]
        sat_day_shifts = [s for s in week["shifts"] if shifts[s]["day"] == sat and not shifts[s]["night"]]
        sat_night_shifts = [s for s in week["shifts"] if shifts[s]["day"] == sat and shifts[s]["night"]]
        sun_day_shifts = [s for s in week["shifts"] if shifts[s]["day"] == sun and not shifts[s]["night"]]
        sun_night_shifts = [s for s in week["shifts"] if shifts[s]["day"] == sun and shifts[s]["night"]]

        for w in range(num_workers):
            weekday_dates = [d for d in week["days"] if d.weekday() < 5]
            avail_weekdays = [wd for wd in weekday_dates if (wd, None) not in unav_parsed[w]]
            if not avail_weekdays:
                continue

            has_weekday_day = model.NewBoolVar(f"has_wd_day_w{w}_k{key}")
            has_weekday_night = model.NewBoolVar(f"has_wd_night_w{w}_k{key}")
            has_sat_day = model.NewBoolVar(f"has_sat_day_w{w}_k{key}")
            has_sat_night = model.NewBoolVar(f"has_sat_night_w{w}_k{key}")
            has_sun_day = model.NewBoolVar(f"has_sun_day_w{w}_k{key}")
            has_sun_night = model.NewBoolVar(f"has_sun_night_w{w}_k{key}")
            has_any_shift = model.NewBoolVar(f"has_any_w{w}_k{key}")

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

            sum_all = sum(assigned[w][s] for s in week["shifts"])
            model.Add(sum_all >= 1).OnlyEnforceIf(has_any_shift)
            model.Add(sum_all == 0).OnlyEnforceIf(has_any_shift.Not())

            # During three-day weekends, skip Saturday/Sunday penalties to let rule 2 take precedence
            if is_three_day_weekend:
                # Only apply weekday night penalty; weekend shifts get no penalty
                tier2 = model.NewBoolVar(f"t2_w{w}_k{key}")
                model.Add(tier2 <= has_weekday_day.Not())
                model.Add(tier2 <= has_weekday_night)
                model.Add(tier2 <= has_any_shift)
                model.Add(tier2 >= has_weekday_day.Not() + has_weekday_night + has_any_shift - 2)
                obj += (weight_flex * 0.01) * tier2
                continue  # Skip all Sat/Sun penalties

            tier2 = model.NewBoolVar(f"t2_w{w}_k{key}")
            model.Add(tier2 <= has_weekday_day.Not())
            model.Add(tier2 <= has_weekday_night)
            model.Add(tier2 <= has_any_shift)
            model.Add(tier2 >= has_weekday_day.Not() + has_weekday_night + has_any_shift - 2)
            obj += (weight_flex * 0.01) * tier2

            tier3 = model.NewBoolVar(f"t3_w{w}_k{key}")
            model.Add(tier3 <= has_weekday_day.Not())
            model.Add(tier3 <= has_weekday_night.Not())
            model.Add(tier3 <= has_sat_day)
            model.Add(tier3 <= has_any_shift)
            model.Add(tier3 >= has_weekday_day.Not() + has_weekday_night.Not() + has_sat_day + has_any_shift - 3)
            obj += (weight_flex * 0.02) * tier3

            tier4 = model.NewBoolVar(f"t4_w{w}_k{key}")
            model.Add(tier4 <= has_weekday_day.Not())
            model.Add(tier4 <= has_weekday_night.Not())
            model.Add(tier4 <= has_sat_day.Not())
            model.Add(tier4 <= has_sat_night)
            model.Add(tier4 <= has_any_shift)
            model.Add(tier4 >= has_weekday_day.Not() + has_weekday_night.Not() + has_sat_day.Not() + has_sat_night + has_any_shift - 4)
            obj += (weight_flex * 0.03) * tier4

            tier5 = model.NewBoolVar(f"t5_w{w}_k{key}")
            model.Add(tier5 <= has_weekday_day.Not())
            model.Add(tier5 <= has_weekday_night.Not())
            model.Add(tier5 <= has_sat_day.Not())
            model.Add(tier5 <= has_sat_night.Not())
            model.Add(tier5 <= has_sun_day)
            model.Add(tier5 <= has_any_shift)
            model.Add(tier5 >= has_weekday_day.Not() + has_weekday_night.Not() + has_sat_day.Not() + has_sat_night.Not() + has_sun_day + has_any_shift - 5)
            obj += (weight_flex * 0.04) * tier5

            tier6 = model.NewBoolVar(f"t6_w{w}_k{key}")
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
