"""Debug script to test three-day weekend handling in transition weeks."""

from scheduling_engine import generate_schedule
from datetime import date, timedelta
from utils import compute_holidays
import calendar

# First, let's verify that the holiday set is correctly extended
print("=== Verifying holiday detection for March 2026 ===")
year, month = 2026, 3

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

# Build holiday_set as scheduling_engine does
holiday_set = set()
months_in_window = {(d.year, d.month) for d in days}
print(f"Months in scheduling window: {months_in_window}")

for y, m in months_in_window:
    for hd in compute_holidays(y, m):
        holiday_set.add(date(y, m, hd))

print(f"Holiday set: {sorted(holiday_set)}")
print(f"April 3, 2026 (Good Friday) in holiday_set: {date(2026, 4, 3) in holiday_set}")

# Check three-day weekend detection
print("\n=== Three-day weekend detection ===")
week_14_days = [d for d in days if d.isocalendar()[1] == 14]
print(f"Week 14 days: {week_14_days}")

is_three_day = any(day in holiday_set and day.weekday() in [0, 4] for day in week_14_days)
print(f"is_three_day_weekend: {is_three_day}")

# Find the three-day periods
for day in week_14_days:
    if day in holiday_set:
        print(f"  Holiday: {day} ({day.strftime('%A')}) weekday={day.weekday()}")
        if day.weekday() == 4:  # Friday
            sat = day + timedelta(days=1)
            sun = day + timedelta(days=2)
            if sat in week_14_days and sun in week_14_days:
                print(f"    -> 3-day weekend: {day}, {sat}, {sun}")

# Now run the actual schedule
print("\n" + "="*60)
print("=== SCENARIO 1: Fresh March schedule (no history) ===")
print("="*60)

# Create 15 workers like the real app
workers = [
    {'name': f'W{i+1}', 'id': f'ID{i+1:03d}', 'color': '#ff0000', 'can_night': True, 'weekly_load': 18 if i < 5 else 12}
    for i in range(15)
]

unavail = {w['name']: [] for w in workers}
required = {w['name']: [] for w in workers}
history = {}

print("Generating schedule for March 2026 with 15 workers...")

schedule_march, weekly_march, assignments_march, stats_march, _ = generate_schedule(
    2026, 3, unavail, required, history, workers, holidays=None
)

print()
print('=== April 3-5, 2026 (Three-day weekend) - MARCH schedule ===')
three_day = [a for a in assignments_march if a['date'] in ['2026-04-03', '2026-04-04', '2026-04-05']]
for a in sorted(three_day, key=lambda x: (x['date'], x['shift'])):
    print(f"{a['date']} {a['shift']}: {a['worker']}")

workers_in_period_march = set(a['worker'] for a in three_day)
print()
print(f'Unique workers in three-day period (March schedule): {len(workers_in_period_march)}')
print(f'Workers: {sorted(workers_in_period_march)}')

# Now simulate what happens if user then generates April
# The history would contain March's assignments
print("\n" + "="*60)
print("=== SCENARIO 2: April schedule AFTER March (with history) ===")
print("="*60)

# Build history from March's assignments
from scheduling_engine import update_history
history_after_march = update_history(assignments_march, {})

print(f"History keys after March: {list(history_after_march.keys())[:5]}...")

print("Generating schedule for April 2026...")

schedule_april, weekly_april, assignments_april, stats_april, _ = generate_schedule(
    2026, 4, unavail, required, history_after_march, workers, holidays=None
)

print()
print('=== April 3-5, 2026 (Three-day weekend) - APRIL schedule ===')
three_day_april = [a for a in assignments_april if a['date'] in ['2026-04-03', '2026-04-04', '2026-04-05']]
for a in sorted(three_day_april, key=lambda x: (x['date'], x['shift'])):
    print(f"{a['date']} {a['shift']}: {a['worker']}")

workers_in_period_april = set(a['worker'] for a in three_day_april)
print()
print(f'Unique workers in three-day period (April schedule): {len(workers_in_period_april)}')
print(f'Workers: {sorted(workers_in_period_april)}')

# Check if the week was excluded (should be since it was already scheduled in March)
print()
print("Note: If April was scheduled AFTER March, ISO week 14 should have been")
print("excluded from re-optimization, and the assignments should match March's.")
print(f"March workers: {sorted(workers_in_period_march)}")
print(f"April workers: {sorted(workers_in_period_april)}")
print(f"Match: {workers_in_period_march == workers_in_period_april}")
