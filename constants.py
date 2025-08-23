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
EQUITY_STATS = [
    'weekend_shifts', 'sat_shifts', 'sun_shifts', 'weekend_day',
    'weekend_night', 'weekday_day', 'weekday_night', 'total_night',
    'fri_night'  # Added based on weights and stat indices
]

# Weights for equity objectives in the optimization model.
# Each weight multiplies the imbalance (max - min) for the corresponding stat in EQUITY_STATS.
# Higher weight means the solver will prioritize balancing that stat more strongly (i.e., penalize imbalances more).
# Lowering a weight reduces the importance of balancing that stat, allowing more imbalance if it helps other objectives.
# If changed:
# - Increasing a weight: Makes the schedule fairer for that specific metric but may worsen other aspects like load balancing.
# - Decreasing a weight: Allows more flexibility in assignments, potentially improving overall feasibility or other objectives, but may lead to unfair distributions.
EQUITY_WEIGHTS = {
    'weekend_shifts': 200,      # Balances total weekend shifts (higher weight prioritizes even distribution of weekends)
    'sat_shifts': 1,           # Balances Saturday shifts
    'sun_shifts': 1,           # Balances Sunday shifts
    'weekend_day': 0.1,        # Balances weekend day shifts (low weight means less emphasis)
    'weekend_night': 100,       # Balances weekend night shifts (significant emphasis on fairness)
    'weekday_day': 1,       # Balances weekday day shifts (very low weight, minimal enforcement)
    'weekday_night': 10,       # Balances weekday night shifts
    'fri_night': 50,           # Balances Friday night shifts (high weight to avoid overloading individuals)
    'total_night': 100         # Balances total night shifts (highest weight, strong focus on night shift equity)
}

# Weight for day-of-week equity (balances shifts per specific weekday across workers).
# Similar to EQUITY_WEIGHTS: higher value penalizes imbalances in shifts on Mondays, Tuesdays, etc.
# Changing it: Increase to make shift counts per day of week more even; decrease for more flexibility.
DOW_EQUITY_WEIGHT = 1

# Objective function weights
# Weight for weekly load balancing (penalizes deviations from workers' standard weekly hours).
# Higher value prioritizes meeting exact weekly loads; lower allows more variance if needed for other constraints.
OBJECTIVE_WEIGHT_LOAD = 1

OBJECTIVE_FLEX_WEIGHTS = [10000, 1000, 100, 10, 1, 0.1, 0.01, 0.001, 0.0001, 0.00001, 0.000001]  # Removed [0]:100000 (redundant Sat night penalty)
# Specific uses (based on code indices, now shifted down by 1):
# [0]: Penalizes assigning shifts during 3-day weekend periods created by holidays.
# [1]: Penalizes workers having both Saturday and Sunday shifts in non-3-day weeks.
# [2]: Penalizes consecutive weekends (working a weekend after working the previous one).
# [3]: Penalizes assigning M1 shifts to workers with 18-hour weekly loads (prefers longer shifts for them).
# [4-8]: Unused in current code (placeholders for future objectives).
# [9]: Penalizes consecutive shifts with rest periods between 24-48 hours.
# [10]: Saturday preference penalty (from new _add_saturday_preference_objective)

# Solver and constraint parameters
SOLVER_TIMEOUT_SECONDS = 30.0
MIN_REST_HOURS = 24  # Minimum hours between shift ends/starts
CONSECUTIVE_SHIFT_PENALTY_RANGE = (24, 48)  # Penalize shifts with rest in [min, max) hours
MAX_STAT_VALUE = 10000  # Upper bound for stat variables in model

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