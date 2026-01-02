"""CP-SAT constraint builders.

These functions operate on OR-Tools `CpModel` and variable arrays. They are split
out of `logic_g4.py` to keep scheduling logic modular and refactor-friendly.

Behavior should remain identical to the original implementations.
"""

from __future__ import annotations

from datetime import timedelta

from constants import MIN_REST_HOURS
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
    for w in range(num_workers):
        for d, sh in unav_parsed[w]:
            if sh is None:
                if d in shifts_by_day:
                    for s in shifts_by_day[d]:
                        model.Add(assigned[w][s] == 0)
            else:
                if d in shifts_by_day:
                    for s in shifts_by_day[d]:
                        if shifts[s]["type"] == sh:
                            model.Add(assigned[w][s] == 0)
                            break

        for d, sh in req_parsed[w]:
            if sh is None:
                if d in shifts_by_day:
                    model.Add(sum(assigned[w][s] for s in shifts_by_day[d]) >= 1)
            else:
                if d in shifts_by_day:
                    for s in shifts_by_day[d]:
                        if shifts[s]["type"] == sh:
                            model.Add(assigned[w][s] == 1)
                            break

    return model


def add_24h_interval_constraints(model, assigned, shifts, num_shifts, num_workers):
    for w in range(num_workers):
        for i in range(num_shifts):
            for j in range(i + 1, num_shifts):
                si = shifts[i]
                sj = shifts[j]
                start_i = si["start"]
                end_i = si["end"]
                start_j = sj["start"]
                end_j = sj["end"]

                # overlap -> cannot do both
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


def add_weekly_participation_constraints(model, assigned, iso_weeks, unav_parsed, num_workers):
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

        for w in relevant:
            num_shifts_week = sum(assigned[w][s] for s in week["shifts"])
            model.Add(num_shifts_week >= 1)

        # Count weekday shifts using distribution list (holidays on Mon-Fri count as weekday shifts)
        num_weekday = [sum(assigned[w][s] for s in week["weekday_shifts_for_distribution"]) for w in range(num_workers)]
        has_at_least_one = [model.NewBoolVar(f"has1_w{w}_wk{key[0]}_{key[1]}") for w in range(num_workers)]
        for ww in range(num_workers):
            model.Add(num_weekday[ww] >= 1).OnlyEnforceIf(has_at_least_one[ww])
            model.Add(num_weekday[ww] == 0).OnlyEnforceIf(has_at_least_one[ww].Not())

        all_have_one = model.NewBoolVar(f"all_have_wk{key[0]}_{key[1]}")
        if relevant:
            model.AddBoolAnd([has_at_least_one[w] for w in relevant]).OnlyEnforceIf(all_have_one)
            model.AddBoolOr([has_at_least_one[w].Not() for w in relevant]).OnlyEnforceIf(all_have_one.Not())

            for ww in range(num_workers):
                model.Add(num_weekday[ww] <= 1).OnlyEnforceIf(all_have_one.Not())

            if total_weekday_shifts >= num_relevant:
                model.Add(all_have_one == 1)

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
