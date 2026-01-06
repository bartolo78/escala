# Shift configurations
SHIFTS = {
    'M1': {'start_hour': 8, 'end_hour': 20, 'dur': 12, 'night': False},
    'M2': {'start_hour': 8, 'end_hour': 23, 'dur': 15, 'night': False},
    'N': {'start_hour': 20, 'end_hour': 32, 'dur': 12, 'night': True},  # 32 = 8 AM next day
}

SHIFT_TYPES = list(SHIFTS.keys())
SHIFT_DURATIONS = {k: v['dur'] for k, v in SHIFTS.items()}
SHIFT_START_HOURS = {k: v['start_hour'] for k, v in SHIFTS.items()}
SHIFT_END_HOURS = {k: v['end_hour'] for k, v in SHIFTS.items()}
SHIFT_NIGHT_FLAGS = {k: v['night'] for k, v in SHIFTS.items()}

# UI display names for shifts (e.g., 'N' displays as 'Night')
SHIFT_DISPLAY_NAMES = {'M1': 'M1', 'M2': 'M2', 'N': 'Night'}

# Equity objectives
# These stats track various shift categories for workers over time.
# They are used to compute imbalances (max - min across workers) in the objective function.
# 
# RULES.md Equity Priority Order (highest to lowest):
#   1) Sunday or Holiday M2
#   2) Saturday N
#   3) Saturday M2
#   4) Sunday or Holiday N (holidays on Saturday excluded—see below)
#   5) Sunday or Holiday M1
#   6) Saturday M1
#   7) Friday N
#   8) Weekday (not Friday) N
#   9) Monday M1 or M2
#   10) Weekday (not Monday) M1 or M2
#
# Holiday Counting Rules for Equity:
#   - Holiday on Saturday: M1/M2 count as Holiday M1/M2; N counts as Saturday N (not double-counted).
#   - Holiday on Sunday: counts in the "Sunday or Holiday" category.
#   - Holiday on a weekday (Mon–Fri): counts in the "Sunday or Holiday" category for equity purposes.
EQUITY_STATS = [
    'sun_holiday_m2',           # Priority 1: Sunday or Holiday M2
    'sat_n',                    # Priority 2: Saturday Night
    'sat_m2',                   # Priority 3: Saturday M2
    'sun_holiday_n',            # Priority 4: Sunday or Holiday N (Sat holidays excluded)
    'sun_holiday_m1',           # Priority 5: Sunday or Holiday M1
    'sat_m1',                   # Priority 6: Saturday M1
    'fri_night',                # Priority 7: Friday N
    'weekday_not_fri_n',        # Priority 8: Weekday (not Friday) N
    'monday_day',               # Priority 9: Monday M1 or M2
    'weekday_not_mon_day',      # Priority 10: Weekday (not Monday) M1 or M2
]

# Weights for equity objectives in the optimization model.
# Each weight multiplies the imbalance (max - min) for the corresponding stat in EQUITY_STATS.
# Higher weight means the solver will prioritize balancing that stat more strongly (i.e., penalize imbalances more).
# Weights are set in descending order to match the RULES.md priority order.
# If changed:
# - Increasing a weight: Makes the schedule fairer for that specific metric but may worsen other aspects like load balancing.
# - Decreasing a weight: Allows more flexibility in assignments, potentially improving overall feasibility or other objectives, but may lead to unfair distributions.
EQUITY_WEIGHTS = {
    # Weights ordered by EQUITY_STATS priority (highest priority = highest weight)
    'sun_holiday_m2': 10000.0,   # Priority 1: Sunday or Holiday M2
    'sat_n': 9500.0,             # Priority 2: Saturday N
    'sat_m2': 9200.0,            # Priority 3: Saturday M2
    'sun_holiday_n': 8300.0,     # Priority 4: Sunday or Holiday N (Sat holidays excluded)
    'sun_holiday_m1': 7600.0,    # Priority 5: Sunday or Holiday M1
    'sat_m1': 6800.0,            # Priority 6: Saturday M1
    'fri_night': 1000.0,         # Priority 7: Friday N
    'weekday_not_fri_n': 700.0,  # Priority 8: Weekday (not Friday) N
    'monday_day': 300.0,         # Priority 9: Monday M1 or M2
    'weekday_not_mon_day': 50.0, # Priority 10: Weekday (not Monday) M1 or M2
}

# Weight for day-of-week equity (balances shifts per specific weekday across workers).
# Similar to EQUITY_WEIGHTS: higher value penalizes imbalances in shifts on Mondays, Tuesdays, etc.
# Changing it: Increase to make shift counts per day of week more even; decrease for more flexibility.
DOW_EQUITY_WEIGHT = 1

# Objective function weights
# Weight for weekly load balancing (penalizes deviations from workers' standard weekly hours).
# Higher value prioritizes meeting exact weekly loads; lower allows more variance if needed for other constraints.
OBJECTIVE_WEIGHT_LOAD = 1

OBJECTIVE_FLEX_WEIGHTS = [10000, 10000, 5000, 1000, 10, 1, 0.1, 0.01, 0.001, 0.0001, 100, 500, 500]
# Flexible rule weights in order of importance (higher index = lower priority):
# [0]: Saturday Preference - prioritize weekday (Mon-Fri) as first shift, else Saturday M1/M2 over Sunday/N.
# [1]: Three-Day Weekend Worker Minimization - minimize unique workers during 3-day weekends.
# [2]: Weekend Shift Limits - penalizes workers having both Saturday and Sunday shifts in non-3-day weeks.
# [3]: Consecutive Weekend Avoidance - penalizes consecutive weekends worked.
# [4]: M2 Priority - penalizes M1 shifts for 18-hour workers (prefers longer shifts).
# [5-9]: Unused in current code (placeholders for future objectives).
# [10]: Consecutive Shifts 48h - penalizes shifts with rest periods between 24-48 hours.
# [11]: Night Shift Min Interval - penalizes night shifts within 48h of each other.
# [12]: Consecutive Night Shift Avoidance - penalizes consecutive night shifts unless 96h apart (start to start).

# Solver and constraint parameters
SOLVER_TIMEOUT_SECONDS = 30.0
MIN_REST_HOURS = 24  # Minimum hours between shift ends/starts
CONSECUTIVE_SHIFT_PENALTY_RANGE = (24, 48)  # Penalize shifts with rest in [min, max) hours
MAX_STAT_VALUE = 10000  # Upper bound for stat variables in model

# Night shift spacing parameters (flexible rules)
NIGHT_SHIFT_MIN_INTERVAL_HOURS = 48  # Minimum hours between night shift starts to avoid penalty
NIGHT_SHIFT_CONSECUTIVE_MIN_HOURS = 96  # Minimum hours between starts to allow consecutive nights without penalty

# Worker and schedule parameters
WEEKLY_LOADS = [12, 18]  # Possible standard weekly hours
PAST_REPORT_WEEKS = 52  # Lookback weeks for reports

# Holidays (fixed and movable relative to Easter)
FIXED_HOLIDAYS = {
    1: [1],   # New Year's Day
    4: [25],  # Freedom Day
    5: [1],   # Labour Day
    6: [10],  # Portugal Day
    8: [15],  # Assumption of Mary
    10: [5],  # Republic Day
    11: [1],  # All Saints' Day
    12: [1, 8, 25]  # Restoration of Independence, Immaculate Conception, Christmas
}
MOVABLE_HOLIDAY_OFFSETS = {  # Days relative to Easter
    'carnival': -47,
    'good_friday': -2,
    'easter': 0,
    'corpus_christi': 60
}