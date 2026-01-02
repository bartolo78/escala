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
    weekend_shift_indices = [
        s
        for s in range(num_shifts)
        if shifts[s]["day"].weekday() >= 5 or shifts[s]["day"] in holiday_set
    ]
    sat_indices = [s for s in range(num_shifts) if shifts[s]["day"].weekday() == 5]
    sun_indices = [s for s in range(num_shifts) if shifts[s]["day"].weekday() == 6]
    weekend_day_indices = [s for s in weekend_shift_indices if not shifts[s]["night"]]
    weekend_night_indices = [s for s in weekend_shift_indices if shifts[s]["night"]]
    weekday_day_indices = [
        s
        for s in range(num_shifts)
        if not (shifts[s]["day"].weekday() >= 5 or shifts[s]["day"] in holiday_set)
        and not shifts[s]["night"]
    ]
    weekday_night_indices = [
        s
        for s in range(num_shifts)
        if not (shifts[s]["day"].weekday() >= 5 or shifts[s]["day"] in holiday_set)
        and shifts[s]["night"]
    ]
    fri_night_indices = [s for s in weekday_night_indices if shifts[s]["day"].weekday() == 4]
    dow_indices = {d: [s for s in range(num_shifts) if shifts[s]["day"].weekday() == d] for d in range(7)}
    total_night_indices = [s for s in range(num_shifts) if shifts[s]["night"]]

    return {
        "weekend_shifts": weekend_shift_indices,
        "sat_shifts": sat_indices,
        "sun_shifts": sun_indices,
        "weekend_day": weekend_day_indices,
        "weekend_night": weekend_night_indices,
        "weekday_day": weekday_day_indices,
        "weekday_night": weekday_night_indices,
        "total_night": total_night_indices,
        "fri_night": fri_night_indices,
        "dow": dow_indices,
    }
