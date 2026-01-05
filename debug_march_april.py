#!/usr/bin/env python3
"""
Debug script to test the exact March→April scenario.
Run: python debug_march_april.py
"""

from datetime import date
from scheduler_service import SchedulerService
from scheduling_engine import get_scheduled_iso_weeks
from history_view import HistoryView

print("=" * 70)
print("DEBUG: March 2026 → April 2026 Three-Day Weekend Scenario")
print("=" * 70)

# Create service with default workers
service = SchedulerService()
print(f"\nWorkers: {[w.name for w in service.workers]}")

# Generate March 2026
print("\n" + "=" * 70)
print("STEP 1: Generate March 2026")
print("=" * 70)
result_march = service.generate(2026, 3)
print(f"Status: {result_march.success}")
print(f"Total assignments: {len(result_march.assignments)}")

# Check April 3-5 in March's assignments
three_day_dates = ['2026-04-03', '2026-04-04', '2026-04-05']
april_assignments = [a for a in result_march.assignments if a['date'] in three_day_dates]
print(f"\nApril 3-5 assignments from March schedule:")
workers_april = set()
for a in sorted(april_assignments, key=lambda x: (x['date'], x['shift'])):
    print(f"  {a['date']} {a['shift']}: {a['worker']}")
    workers_april.add(a['worker'])
print(f"\nUnique workers in April 3-5 (from March): {len(workers_april)}")

# Check history after March
print("\n--- History after March ---")
history_after_march = service._history
scheduled_weeks = get_scheduled_iso_weeks(history_after_march)
print(f"Scheduled ISO weeks: {sorted(scheduled_weeks)}")

# Check if week 14 is in history
week_14 = (2026, 14)
print(f"Week 14 in scheduled weeks: {week_14 in scheduled_weeks}")

# What dates are in history for April?
history_view = HistoryView(history_after_march)
by_date = history_view.assignments_by_date()
april_dates_in_history = [d for d in by_date.keys() if d.startswith('2026-04')]
print(f"April dates in history: {sorted(april_dates_in_history)}")

# Generate April 2026
print("\n" + "=" * 70)
print("STEP 2: Generate April 2026")
print("=" * 70)
result_april = service.generate(2026, 4)
print(f"Status: {result_april.success}")
print(f"Total assignments: {len(result_april.assignments)}")

# Check April 3-5 in April's result
april_assignments_2 = [a for a in result_april.assignments if a['date'] in three_day_dates]
print(f"\nApril 3-5 assignments from April schedule:")
workers_april_2 = set()
for a in sorted(april_assignments_2, key=lambda x: (x['date'], x['shift'])):
    print(f"  {a['date']} {a['shift']}: {a['worker']}")
    workers_april_2.add(a['worker'])
print(f"\nUnique workers in April 3-5 (from April): {len(workers_april_2)}")

# Compare
print("\n" + "=" * 70)
print("COMPARISON")
print("=" * 70)
print(f"Workers from March schedule: {len(workers_april)} -> {sorted(workers_april)}")
print(f"Workers from April schedule: {len(workers_april_2)} -> {sorted(workers_april_2)}")

if workers_april == workers_april_2:
    print("\n✓ Same workers - April correctly used history from March")
else:
    print("\n✗ DIFFERENT workers!")
    print(f"  In March but not April: {workers_april - workers_april_2}")
    print(f"  In April but not March: {workers_april_2 - workers_april}")

# Analysis
print("\n" + "=" * 70)
print("ANALYSIS")
print("=" * 70)
if len(workers_april) <= 7:
    print(f"March three-day weekend: ✓ PASS ({len(workers_april)} workers)")
else:
    print(f"March three-day weekend: ✗ FAIL ({len(workers_april)} workers, expected ≤7)")

if len(workers_april_2) <= 7:
    print(f"April three-day weekend: ✓ PASS ({len(workers_april_2)} workers)")
else:
    print(f"April three-day weekend: ✗ FAIL ({len(workers_april_2)} workers, expected ≤7)")

print("\n" + "=" * 70)
print("Done")
print("=" * 70)
