#!/usr/bin/env python3
"""Debug script for three-day weekend handling."""
from scheduling_engine import generate_schedule
from datetime import date
from collections import defaultdict

workers = [
    {'name': f'W{i+1}', 'id': f'ID{i+1:03d}', 'color': '#ff0000', 'can_night': True, 'weekly_load': 18 if i < 2 else 12}
    for i in range(5)
]

unavail = {w['name']: [] for w in workers}
required = {w['name']: [] for w in workers}
history = {}

schedule, weekly, assignments, stats, current_stats = generate_schedule(
    2026, 3, unavail, required, history, workers, holidays=None
)

# Check ALL shifts in ISO week 14 (March 30 - April 5)
print('=== ALL shifts in ISO week 14 (March 30 - April 5) ===')
week_14_dates = ['2026-03-30', '2026-03-31', '2026-04-01', '2026-04-02', '2026-04-03', '2026-04-04', '2026-04-05']
week_14_ass = [a for a in assignments if a['date'] in week_14_dates]

worker_days = defaultdict(list)
for a in sorted(week_14_ass, key=lambda x: (x['date'], x['shift'])):
    print(f"{a['date']} {a['shift']}: {a['worker']}")
    worker_days[a['worker']].append((a['date'], a['shift']))

print()
print('=== Worker summary for week 14 ===')
for w in sorted(worker_days.keys()):
    print(f'{w}: {len(worker_days[w])} shifts')
    for dt, sh in worker_days[w]:
        print(f'    {dt} {sh}')

# Check 3-day weekend specifically
print()
print('=== 3-day weekend (April 3-5) ===')
three_day_dates = ['2026-04-03', '2026-04-04', '2026-04-05']
three_day = [a for a in assignments if a['date'] in three_day_dates]
td_workers = set(a['worker'] for a in three_day)
print(f'Unique workers in 3-day: {len(td_workers)} - {td_workers}')
