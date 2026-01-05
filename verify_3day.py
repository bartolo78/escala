#!/usr/bin/env python3
"""Quick verification script for three-day weekend detection in March 2026.

Run with: python verify_3day.py
"""

import sys
from datetime import date, timedelta

# First, test basic detection
from utils import compute_holidays

print("=" * 60)
print("THREE-DAY WEEKEND VERIFICATION FOR MARCH 2026")
print("=" * 60)

print("\n=== 1. Holiday Detection Test ===")
holidays_march = compute_holidays(2026, 3)
holidays_april = compute_holidays(2026, 4)
print(f"March 2026 holidays: {holidays_march}")
print(f"April 2026 holidays: {holidays_april}")

# Easter 2026 is April 5, so Good Friday is April 3
good_friday = date(2026, 4, 3)
print(f"\nGood Friday 2026: {good_friday}")
print(f"Good Friday is in April holidays: {good_friday in holidays_april}")
print(f"Good Friday weekday: {good_friday.weekday()} (4=Friday)")

# Check ISO week
print(f"\nGood Friday ISO week: {good_friday.isocalendar()[:2]}")
print(f"Last day of March 2026: {date(2026, 3, 31).isocalendar()[:2]}")

print("\n=== 2. Scheduling Window Test ===")
import calendar
from datetime import date, timedelta

year, month = 2026, 3
_, num_days_in_month = calendar.monthrange(year, month)
first_day = date(year, month, 1)
last_day = date(year, month, num_days_in_month)
first_monday = first_day - timedelta(days=first_day.weekday())
last_sunday = last_day + timedelta(days=(6 - last_day.weekday()))

print(f"March 2026 scheduling window: {first_monday} to {last_sunday}")
print(f"Days in scheduling window: {(last_sunday - first_monday).days + 1}")

# Build holiday_set as scheduler does
days = []
current_day = first_monday
while current_day <= last_sunday:
    days.append(current_day)
    current_day += timedelta(days=1)

holiday_set = set()
months_in_window = {(d.year, d.month) for d in days}
print(f"Months in window: {sorted(months_in_window)}")
for y, m in months_in_window:
    for hd in compute_holidays(y, m):
        holiday_set.add(date(y, m, hd))

print(f"\nHolidays in window: {sorted(holiday_set)}")
print(f"Good Friday in holiday_set: {good_friday in holiday_set}")

# Get week 14 days
week_14_days = [d for d in days if d.isocalendar()[1] == 14]
print(f"\nISO Week 14 days: {week_14_days}")

is_three_day = any(day in holiday_set and day.weekday() in [0, 4] for day in week_14_days)
print(f"Week 14 has three-day weekend: {is_three_day}")

print("\n=== 3. Running Scheduler for March 2026 ===")
from scheduler_service import SchedulerService

service = SchedulerService()

# Build schedule for March 2026
result = service.build_schedule(year=2026, month=3)

if result['status'] in ['optimal', 'feasible']:
    print(f"\nSchedule status: {result['status']}")
    schedule = result['schedule']
    assignments = result['assignments']
    
    # The schedule dict only contains March dates (filtered by month)
    # But assignments contains ALL dates including April 3-5
    
    print(f"\n=== NOTE ===")
    print("The schedule dict (UI grid) only shows March dates.")
    print("April 3-5 are scheduled but NOT displayed in March's grid.")
    print("Looking in assignments list for April 3-5...")
    
    # Find shifts on April 3, 4, 5 (the three-day weekend) in assignments
    three_day_dates = ['2026-04-03', '2026-04-04', '2026-04-05']
    
    print(f"\n=== Three-Day Weekend Shifts (April 3-5 from assignments) ===")
    workers_with_shifts = {}
    for assignment in assignments:
        if assignment['date'] in three_day_dates:
            day_str = assignment['date']
            worker = assignment['worker']
            shift_type = assignment['shift']
            print(f"  {day_str}: {shift_type} -> {worker}")
            if worker not in workers_with_shifts:
                workers_with_shifts[worker] = []
            workers_with_shifts[worker].append((day_str, shift_type))
    
    print(f"\n=== Unique Workers Summary ===")
    print(f"Total shifts on 3-day weekend: {sum(len(s) for s in workers_with_shifts.values())}")
    print(f"Unique workers on 3-day weekend: {len(workers_with_shifts)}")
    
    if workers_with_shifts:
        for worker, shifts in sorted(workers_with_shifts.items()):
            print(f"  {worker}: {len(shifts)} shift(s)")
    
        # Analysis
        print(f"\n=== Analysis ===")
        print(f"With 9 shifts and 24h interval constraint:")
        print(f"  - Theoretical minimum: ~5 workers")
        print(f"  - Your result: {len(workers_with_shifts)} workers")
        
        if len(workers_with_shifts) <= 7:
            print("  ✓ PASS: Worker minimization is working correctly!")
        elif len(workers_with_shifts) <= 9:
            print("  ⚠ Partial: Some consolidation is happening but limited by constraints")
        else:
            print("  ✗ FAIL: More workers than shifts - something is wrong")
    else:
        print("  No April 3-5 assignments found - check if week is in scheduling window")
else:
    print(f"Schedule failed: {result.get('error', 'unknown error')}")

print("\n=== Done ===")
