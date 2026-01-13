"""Pure builder helpers for schedule generation.

This module intentionally contains *no* OR-Tools logic. It builds the time window,
shift instances, and ISO-week groupings used by the CP-SAT model.

These functions are extracted from scheduling_engine.py to make refactoring safer.
"""

from __future__ import annotations

import calendar
import datetime
from datetime import date, timedelta

from constants import SHIFTS, SHIFT_TYPES


def setup_holidays_and_days(year: int, month: int, holidays) -> tuple[set[date], list[date]]:
    """Return (holiday_set, days_window).

    - holiday_set contains date objects.
    - days_window includes all dates from the Monday of the ISO week containing
      the 1st of the month through the Sunday of the ISO week containing the
      last day of the month.

    This mirrors logic_g4._setup_holidays_and_days behavior.
    """
    if holidays is None:
        holidays = []

    holiday_set: set[date] = set()
    for h in holidays:
        if isinstance(h, int):
            try:
                holiday_set.add(date(year, month, h))
            except ValueError:
                pass
        elif isinstance(h, date):
            holiday_set.add(h)

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

    # Ensure uniqueness + stable ordering
    days = sorted(set(days))
    return holiday_set, days


def create_shifts(days: list[date]):
    shifts = []
    for day in days:
        d_dt = datetime.datetime.combine(day, datetime.time())
        for st in SHIFT_TYPES:
            config = SHIFTS[st]
            shifts.append(
                {
                    "type": st,
                    "start": d_dt + timedelta(hours=config["start_hour"]),
                    "end": d_dt + timedelta(hours=config["end_hour"]),
                    "dur": config["dur"],
                    "night": config["night"],
                    "day": day,
                }
            )

    num_shifts = len(shifts)
    for i in range(num_shifts):
        shifts[i]["index"] = i
    return shifts, num_shifts


def group_shifts_by_day(num_shifts: int, shifts: list[dict]) -> dict[date, list[int]]:
    shifts_by_day: dict[date, list[int]] = {}
    for s in range(num_shifts):
        d = shifts[s]["day"]
        shifts_by_day.setdefault(d, []).append(s)
    return shifts_by_day


def setup_iso_weeks(days: list[date], shifts: list[dict], holiday_set: set[date]):
    iso_weeks: dict[tuple[int, int], dict] = {}
    for day in days:
        iso = day.isocalendar()
        key = (iso[0], iso[1])
        if key not in iso_weeks:
            iso_weeks[key] = {
                "days": [],
                "weekdays": [],
                "weekdays_for_distribution": [],
                "shifts": [],
                "weekday_shifts": [],
                "weekday_shifts_for_distribution": [],
                "monday": day - timedelta(days=day.weekday()),
            }
        iso_weeks[key]["days"].append(day)

        if day.weekday() < 5 and day not in holiday_set:
            iso_weeks[key]["weekdays"].append(day)
        if day.weekday() < 5:
            iso_weeks[key]["weekdays_for_distribution"].append(day)

        iso_weeks[key]["shifts"].append([shift["index"] for shift in shifts if shift["day"] == day])

        if day.weekday() < 5 and day not in holiday_set:
            iso_weeks[key]["weekday_shifts"].append(
                [shift["index"] for shift in shifts if shift["day"] == day]
            )
        if day.weekday() < 5:
            iso_weeks[key]["weekday_shifts_for_distribution"].append(
                [shift["index"] for shift in shifts if shift["day"] == day]
            )

    for key in iso_weeks:
        iso_weeks[key]["shifts"] = [item for sublist in iso_weeks[key]["shifts"] for item in sublist]
        iso_weeks[key]["weekday_shifts"] = [
            item for sublist in iso_weeks[key]["weekday_shifts"] for item in sublist
        ]
        iso_weeks[key]["weekday_shifts_for_distribution"] = [
            item for sublist in iso_weeks[key]["weekday_shifts_for_distribution"] for item in sublist
        ]

    return iso_weeks


def define_stat_indices(shifts: list[dict], num_shifts: int, holiday_set: set[date]):
    """Define shift indices for each equity stat category per RULES.md priority order.
    
    Equity Priority Order (highest to lowest):
      1) Sunday or Holiday M2
      2) Saturday N
      3) Saturday M2
      4) Sunday or Holiday N (holidays on Saturday excluded)
      5) Sunday or Holiday M1
      6) Saturday M1
      7) Weekday N (all Mon-Fri nights combined, to balance total night burden)
      8) Friday N
      9) Weekday (not Friday) N
      10) Monday M1 or M2
      11) Weekday (not Monday) M1 or M2
    
    Holiday Counting Rules:
      - Holiday on Saturday: M1/M2 count as Holiday M1/M2; N counts as Saturday N (not double-counted).
      - Holiday on Sunday: counts in the "Sunday or Holiday" category.
      - Holiday on a weekday (Mon–Fri): counts in the "Sunday or Holiday" category for equity purposes.
    """
    # Helper to check shift properties
    def is_saturday(s):
        return shifts[s]["day"].weekday() == 5
    
    def is_sunday(s):
        return shifts[s]["day"].weekday() == 6
    
    def is_holiday(s):
        return shifts[s]["day"] in holiday_set
    
    def is_weekday_holiday(s):
        return is_holiday(s) and shifts[s]["day"].weekday() < 5
    
    def is_saturday_holiday(s):
        return is_holiday(s) and is_saturday(s)
    
    def is_night(s):
        return shifts[s]["night"]
    
    def is_m1(s):
        return shifts[s]["type"] == "M1"
    
    def is_m2(s):
        return shifts[s]["type"] == "M2"
    
    def is_day_shift(s):
        return is_m1(s) or is_m2(s)
    
    def is_monday(s):
        return shifts[s]["day"].weekday() == 0
    
    def is_friday(s):
        return shifts[s]["day"].weekday() == 4
    
    def is_weekday(s):
        return shifts[s]["day"].weekday() < 5
    
    # Priority 1: Saturday N (includes Saturday holidays - N on Sat holiday counts as Sat N)
    sat_n_indices = [s for s in range(num_shifts) if is_saturday(s) and is_night(s)]
    
    # Priority 2: Sunday or Holiday M2 (Sunday, or weekday holiday, or Sat holiday for M2)
    # For Sat holiday: M2 counts as Holiday M2
    sun_holiday_m2_indices = [
        s for s in range(num_shifts)
        if is_m2(s) and (is_sunday(s) or is_weekday_holiday(s) or is_saturday_holiday(s))
    ]
    
    # Priority 3: Sunday or Holiday M1 (Sunday, or weekday holiday, or Sat holiday for M1)
    sun_holiday_m1_indices = [
        s for s in range(num_shifts)
        if is_m1(s) and (is_sunday(s) or is_weekday_holiday(s) or is_saturday_holiday(s))
    ]
    
    # Priority 4: Sunday or Holiday N (Sat holidays excluded - they count as Sat N)
    # This is Sunday N, or weekday holiday N (not Sat holiday N which is in sat_n)
    sun_holiday_n_indices = [
        s for s in range(num_shifts)
        if is_night(s) and (is_sunday(s) or is_weekday_holiday(s))
    ]
    
    # Priority 5: Saturday M2 (non-holiday Saturday M2, since Sat holiday M2 is in sun_holiday_m2)
    sat_m2_indices = [
        s for s in range(num_shifts)
        if is_saturday(s) and is_m2(s) and not is_holiday(s)
    ]
    
    # Priority 6: Saturday M1 (non-holiday Saturday M1, since Sat holiday M1 is in sun_holiday_m1)
    sat_m1_indices = [
        s for s in range(num_shifts)
        if is_saturday(s) and is_m1(s) and not is_holiday(s)
    ]
    
    # Priority 7: Weekday N (all Mon-Fri nights, non-holiday - combines fri_night and weekday_not_fri_n)
    # This tracks total weekday night burden to prevent a worker from being overloaded on nights overall
    weekday_n_indices = [
        s for s in range(num_shifts)
        if is_weekday(s) and is_night(s) and not is_holiday(s)
    ]
    
    # Priority 8: Friday N (non-holiday Friday nights)
    fri_night_indices = [
        s for s in range(num_shifts)
        if is_friday(s) and is_night(s) and not is_holiday(s)
    ]
    
    # Priority 9: Weekday (not Friday) N (Mon-Thu nights, non-holiday)
    weekday_not_fri_n_indices = [
        s for s in range(num_shifts)
        if is_weekday(s) and not is_friday(s) and is_night(s) and not is_holiday(s)
    ]
    
    # Priority 9: Monday M1 or M2 (non-holiday Mondays)
    monday_day_indices = [
        s for s in range(num_shifts)
        if is_monday(s) and is_day_shift(s) and not is_holiday(s)
    ]
    
    # Priority 11: Weekday (not Monday) M1 or M2 (Tue-Fri day shifts, non-holiday)
    weekday_not_mon_day_indices = [
        s for s in range(num_shifts)
        if is_weekday(s) and not is_monday(s) and is_day_shift(s) and not is_holiday(s)
    ]
    
    # Priority 12: Weekday M2 (Mon-Fri M2 shifts, non-holiday) - for allocation control
    weekday_m2_indices = [
        s for s in range(num_shifts)
        if is_weekday(s) and is_m2(s) and not is_holiday(s)
    ]
    
    # Day-of-week indices for DOW equity (unchanged)
    dow_indices = {d: [s for s in range(num_shifts) if shifts[s]["day"].weekday() == d] for d in range(7)}

    return {
        "sat_n": sat_n_indices,
        "sun_holiday_m2": sun_holiday_m2_indices,
        "sun_holiday_m1": sun_holiday_m1_indices,
        "sun_holiday_n": sun_holiday_n_indices,
        "sat_m2": sat_m2_indices,
        "sat_m1": sat_m1_indices,
        "weekday_n": weekday_n_indices,
        "fri_night": fri_night_indices,
        "weekday_not_fri_n": weekday_not_fri_n_indices,
        "monday_day": monday_day_indices,
        "weekday_not_mon_day": weekday_not_mon_day_indices,
        "weekday_m2": weekday_m2_indices,
        "dow": dow_indices,
    }
