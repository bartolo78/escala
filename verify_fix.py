#!/usr/bin/env python3
"""Quick verification that the empty holidays bug is fixed."""

from datetime import date
from scheduling_engine import _setup_holidays_and_days
from utils import compute_holidays

print("=" * 60)
print("VERIFYING EMPTY HOLIDAYS BUG FIX")
print("=" * 60)

# Test 1: March 2026 has no holidays
print("\n1. Checking March 2026 holidays...")
march_holidays = compute_holidays(2026, 3)
print(f"   compute_holidays(2026, 3) = {march_holidays}")
assert march_holidays == [], f"Expected empty, got {march_holidays}"
print("   ✓ PASS: March 2026 has no holidays (this is the edge case)")

# Test 2: April has Good Friday
print("\n2. Checking April 2026 holidays...")
april_holidays = compute_holidays(2026, 4)
print(f"   compute_holidays(2026, 4) = {april_holidays}")
assert 3 in april_holidays, f"Expected 3 (Good Friday), got {april_holidays}"
print("   ✓ PASS: April 3 (Good Friday) is in April holidays")

# Test 3: Empty list should trigger auto-extension
print("\n3. Testing empty list auto-extension...")
holiday_set_empty, days = _setup_holidays_and_days(2026, 3, holidays=[])
good_friday = date(2026, 4, 3)
print(f"   Holiday set with holidays=[]: {sorted(holiday_set_empty)}")
assert good_friday in holiday_set_empty, f"Good Friday not in holiday_set!"
print(f"   ✓ PASS: Good Friday {good_friday} IS in holiday_set (bug fixed!)")

# Test 4: None should also trigger auto-extension
print("\n4. Testing None auto-extension...")
holiday_set_none, _ = _setup_holidays_and_days(2026, 3, holidays=None)
print(f"   Holiday set with holidays=None: {sorted(holiday_set_none)}")
assert good_friday in holiday_set_none, f"Good Friday not in holiday_set!"
print(f"   ✓ PASS: Good Friday {good_friday} IS in holiday_set")

# Test 5: Day-of-month list should also auto-extend
print("\n5. Testing day-of-month list auto-extension...")
holiday_set_ints, _ = _setup_holidays_and_days(2026, 4, holidays=[25])  # April 25
print(f"   Holiday set with holidays=[25]: {sorted(holiday_set_ints)}")
assert good_friday in holiday_set_ints, f"Good Friday not in holiday_set!"
print(f"   ✓ PASS: Good Friday {good_friday} IS in holiday_set")

print("\n" + "=" * 60)
print("ALL TESTS PASSED - BUG IS FIXED!")
print("=" * 60)
