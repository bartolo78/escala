#!/usr/bin/env python3
"""
Debug script to reproduce and diagnose the infeasibility issue when scheduling
June 2026 with lexicographic mode enabled and history imported.
"""

import json
from datetime import date, timedelta
from ortools.sat.python import cp_model

from scheduling_engine import generate_schedule
from logger import get_logger

logger = get_logger('debug')

# Load the history file
with open('/workspaces/escala/logs/maio.json', 'r') as f:
    history = json.load(f)

# Workers from config.yaml (matching the history file)
workers = [
    {"name": "Tome", "can_night": True, "weekly_load": 12},
    {"name": "Rosa", "can_night": True, "weekly_load": 18},
    {"name": "Lucas", "can_night": True, "weekly_load": 18},
    {"name": "Bartolo", "can_night": True, "weekly_load": 18},
    {"name": "Gilberto", "can_night": True, "weekly_load": 18},
    {"name": "Pego", "can_night": True, "weekly_load": 18},
    {"name": "Celeste", "can_night": True, "weekly_load": 12},
    {"name": "Sofia", "can_night": True, "weekly_load": 18},
    {"name": "Lucilia", "can_night": True, "weekly_load": 12},
    {"name": "Teresa", "can_night": True, "weekly_load": 18},
    {"name": "Fernando", "can_night": False, "weekly_load": 12},
    {"name": "Rosario", "can_night": True, "weekly_load": 12},
    {"name": "Nuno", "can_night": True, "weekly_load": 18},
    {"name": "Filomena", "can_night": False, "weekly_load": 12},
    {"name": "Angela", "can_night": True, "weekly_load": 18},
]

print("=" * 60)
print("Testing June 2026 with lexicographic mode and history")
print("=" * 60)

# Test with lexicographic mode (should fail according to user)
print("\n--- Lexicographic mode ---")
schedule, weekly, assignments, stats, _ = generate_schedule(
    year=2026,
    month=6,
    unavail_data={},
    required_data={},
    history=history,
    workers=workers,
    lexicographic=True,
)

if stats.get("error"):
    print(f"FAILED: {stats.get('error')}")
    if stats.get("diagnostic_report"):
        report = stats["diagnostic_report"]
        print(f"Relaxation results: {report.relaxation_results}")
        print(f"Summary: {report.summary}")
else:
    print(f"SUCCESS: {len(assignments)} assignments")
    print(f"Status: {stats.get('status')}, Time: {stats.get('wall_time'):.2f}s")

print("\n--- Non-lexicographic mode ---")
schedule2, weekly2, assignments2, stats2, _ = generate_schedule(
    year=2026,
    month=6,
    unavail_data={},
    required_data={},
    history=history,
    workers=workers,
    lexicographic=False,
)

if stats2.get("error"):
    print(f"FAILED: {stats2.get('error')}")
else:
    print(f"SUCCESS: {len(assignments2)} assignments")
    print(f"Status: {stats2.get('status')}, Time: {stats2.get('wall_time'):.2f}s")


print("\n--- Lexicographic mode WITHOUT history ---")
schedule3, weekly3, assignments3, stats3, _ = generate_schedule(
    year=2026,
    month=6,
    unavail_data={},
    required_data={},
    history={},
    workers=workers,
    lexicographic=True,
)

if stats3.get("error"):
    print(f"FAILED: {stats3.get('error')}")
else:
    print(f"SUCCESS: {len(assignments3)} assignments")
    print(f"Status: {stats3.get('status')}, Time: {stats3.get('wall_time'):.2f}s")
