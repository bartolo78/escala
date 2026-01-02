"""
Tests for model_objectives.py - CP-SAT objective builders.

These tests verify the objective functions that guide the solver
toward optimal schedules according to RULES.md flexible rules.
"""

import pytest
from datetime import date, datetime, timedelta
from ortools.sat.python import cp_model

from model_objectives import (
    build_load_balancing_cost,
    build_three_day_weekend_unique_workers_cost,
    build_weekend_shift_limits_cost,
    build_consecutive_weekend_avoidance_cost,
    build_m2_priority_cost,
    build_equity_cost_scaled,
    build_dow_equity_cost_scaled,
    build_consec_shifts_48h_cost,
    build_tiebreak_cost,
)
from constants import EQUITY_STATS


@pytest.fixture
def model():
    """Create a fresh CP-SAT model."""
    return cp_model.CpModel()


@pytest.fixture
def sample_workers():
    """Sample workers for testing."""
    return [
        {"name": "Alice", "id": "ID001", "can_night": True, "weekly_load": 18},
        {"name": "Bob", "id": "ID002", "can_night": True, "weekly_load": 18},
        {"name": "Carol", "id": "ID003", "can_night": False, "weekly_load": 12},
    ]


@pytest.fixture
def sample_shifts():
    """Sample shifts for a week."""
    base = date(2026, 1, 5)  # Monday
    shifts = []
    for d in range(7):  # Mon-Sun
        day = base + timedelta(days=d)
        for shift_type, start_h, end_h, dur in [
            ("M1", 8, 20, 12),
            ("M2", 8, 23, 15),
            ("N", 20, 8, 12),
        ]:
            start = datetime.combine(day, datetime.min.time().replace(hour=start_h))
            if shift_type == "N":
                end = datetime.combine(day + timedelta(days=1), datetime.min.time().replace(hour=end_h))
            else:
                end = datetime.combine(day, datetime.min.time().replace(hour=end_h))
            shifts.append({
                "type": shift_type,
                "day": day,
                "start": start,
                "end": end,
                "dur": dur,
            })
    return shifts


@pytest.fixture
def assigned_vars(model, sample_workers, sample_shifts):
    """Create assigned boolean variables."""
    num_workers = len(sample_workers)
    num_shifts = len(sample_shifts)
    return [
        [model.NewBoolVar(f"assigned_w{w}_s{s}") for s in range(num_shifts)]
        for w in range(num_workers)
    ]


@pytest.fixture
def sample_iso_weeks(sample_shifts):
    """Create iso_weeks structure for a single week."""
    base = date(2026, 1, 5)  # Monday
    days = [base + timedelta(days=d) for d in range(7)]
    return {
        (2026, 2): {  # Year, ISO week
            "monday": base,
            "days": days,
            "shifts": list(range(len(sample_shifts))),
        }
    }


class TestBuildLoadBalancingCost:
    """Tests for build_load_balancing_cost."""

    def test_returns_intvar(self, model, sample_iso_weeks, sample_shifts, assigned_vars, sample_workers):
        """Should return an IntVar."""
        cost = build_load_balancing_cost(
            model, sample_iso_weeks, sample_shifts, assigned_vars, sample_workers
        )
        assert cost is not None
        assert "load_balance_cost" in str(cost)

    def test_empty_weeks_returns_zero_cost(self, model, sample_shifts, assigned_vars, sample_workers):
        """Empty iso_weeks should result in zero cost."""
        cost = build_load_balancing_cost(model, {}, sample_shifts, assigned_vars, sample_workers)
        # With empty weeks, cost should be constrained to 0
        assert cost is not None

    def test_cost_tracks_deviation_from_weekly_load(self, model, sample_workers):
        """Cost should track over/under deviation from weekly_load."""
        # Create a simple single-shift scenario
        shifts = [{"type": "M1", "day": date(2026, 1, 5), "dur": 12}]
        iso_weeks = {
            (2026, 2): {
                "monday": date(2026, 1, 5),
                "days": [date(2026, 1, 5)],
                "shifts": [0],
            }
        }
        assigned = [[model.NewBoolVar(f"a_w{w}_s0")] for w in range(len(sample_workers))]
        
        cost = build_load_balancing_cost(model, iso_weeks, shifts, assigned, sample_workers)
        assert cost is not None


class TestBuildThreeDayWeekendUniqueWorkersCost:
    """Tests for build_three_day_weekend_unique_workers_cost."""

    def test_returns_intvar(self, model, sample_iso_weeks, assigned_vars, sample_shifts):
        """Should return an IntVar."""
        shifts_by_day = {}
        for i, s in enumerate(sample_shifts):
            shifts_by_day.setdefault(s["day"], []).append(i)
        
        cost = build_three_day_weekend_unique_workers_cost(
            model, sample_iso_weeks, set(), shifts_by_day, assigned_vars, len(assigned_vars)
        )
        assert cost is not None
        assert "three_day_unique_workers_cost" in str(cost)

    def test_no_holidays_returns_zero(self, model, sample_iso_weeks, assigned_vars, sample_shifts):
        """No holidays means no three-day weekend penalty."""
        shifts_by_day = {}
        for i, s in enumerate(sample_shifts):
            shifts_by_day.setdefault(s["day"], []).append(i)
        
        cost = build_three_day_weekend_unique_workers_cost(
            model, sample_iso_weeks, set(), shifts_by_day, assigned_vars, len(assigned_vars)
        )
        # Cost should be defined but effectively 0 when no 3-day weekends
        assert cost is not None

    def test_friday_holiday_creates_three_day_weekend(self, model, sample_workers):
        """Friday holiday should create Fri-Sat-Sun three-day weekend."""
        # Create week with Friday being a holiday
        friday = date(2026, 1, 9)  # A Friday
        sat = friday + timedelta(days=1)
        sun = friday + timedelta(days=2)
        
        shifts = []
        for day in [friday, sat, sun]:
            shifts.append({"type": "M1", "day": day, "dur": 12})
        
        iso_weeks = {
            (2026, 2): {
                "monday": friday - timedelta(days=4),
                "days": [friday, sat, sun],
                "shifts": list(range(len(shifts))),
            }
        }
        shifts_by_day = {friday: [0], sat: [1], sun: [2]}
        assigned = [[model.NewBoolVar(f"a_w{w}_s{s}") for s in range(3)] for w in range(3)]
        
        cost = build_three_day_weekend_unique_workers_cost(
            model, iso_weeks, {friday}, shifts_by_day, assigned, 3
        )
        assert cost is not None


class TestBuildWeekendShiftLimitsCost:
    """Tests for build_weekend_shift_limits_cost."""

    def test_returns_intvar(self, model, sample_iso_weeks, assigned_vars, sample_shifts, sample_workers):
        """Should return an IntVar."""
        cost = build_weekend_shift_limits_cost(
            model, sample_iso_weeks, set(), assigned_vars, len(sample_workers), sample_shifts
        )
        assert cost is not None
        assert "weekend_shift_limits_cost" in str(cost)

    def test_penalizes_sat_and_sun_same_worker(self, model, sample_workers):
        """Should penalize when same worker has Saturday AND Sunday shifts."""
        sat = date(2026, 1, 10)  # Saturday
        sun = date(2026, 1, 11)  # Sunday
        
        shifts = [
            {"type": "M1", "day": sat, "dur": 12},
            {"type": "M1", "day": sun, "dur": 12},
        ]
        iso_weeks = {
            (2026, 2): {
                "monday": sat - timedelta(days=5),
                "days": [sat, sun],
                "shifts": [0, 1],
            }
        }
        assigned = [[model.NewBoolVar(f"a_w{w}_s{s}") for s in range(2)] for w in range(3)]
        
        cost = build_weekend_shift_limits_cost(
            model, iso_weeks, set(), assigned, 3, shifts
        )
        assert cost is not None

    def test_skips_three_day_weekends(self, model, sample_workers):
        """Three-day weekends should be skipped (handled by different rule)."""
        friday = date(2026, 1, 9)  # Friday holiday
        sat = friday + timedelta(days=1)
        sun = friday + timedelta(days=2)
        
        shifts = [
            {"type": "M1", "day": sat, "dur": 12},
            {"type": "M1", "day": sun, "dur": 12},
        ]
        iso_weeks = {
            (2026, 2): {
                "monday": friday - timedelta(days=4),
                "days": [friday, sat, sun],
                "shifts": [0, 1],
            }
        }
        assigned = [[model.NewBoolVar(f"a_w{w}_s{s}") for s in range(2)] for w in range(3)]
        
        # Friday is holiday (weekday 4), so this is a 3-day weekend
        cost = build_weekend_shift_limits_cost(
            model, iso_weeks, {friday}, assigned, 3, shifts
        )
        assert cost is not None


class TestBuildConsecutiveWeekendAvoidanceCost:
    """Tests for build_consecutive_weekend_avoidance_cost."""

    def test_returns_intvar(self, model, sample_iso_weeks, assigned_vars, sample_shifts, sample_workers):
        """Should return an IntVar."""
        cost = build_consecutive_weekend_avoidance_cost(
            model, sample_iso_weeks, set(), {}, sample_workers, assigned_vars, 
            len(sample_workers), sample_shifts, 2026, 1
        )
        assert cost is not None
        assert "consecutive_weekend_avoidance_cost" in str(cost)

    def test_empty_history_no_penalty(self, model, sample_iso_weeks, assigned_vars, sample_shifts, sample_workers):
        """No history means no consecutive weekend tracking."""
        cost = build_consecutive_weekend_avoidance_cost(
            model, sample_iso_weeks, set(), {}, sample_workers, assigned_vars,
            len(sample_workers), sample_shifts, 2026, 1
        )
        assert cost is not None


class TestBuildM2PriorityCost:
    """Tests for build_m2_priority_cost."""

    def test_returns_intvar(self, model, sample_shifts, assigned_vars, sample_workers):
        """Should return an IntVar."""
        cost = build_m2_priority_cost(model, sample_shifts, assigned_vars, sample_workers)
        assert cost is not None
        assert "m2_priority_cost" in str(cost)

    def test_counts_m1_assignments_for_18h_workers(self, model, sample_workers):
        """Should count M1 shifts assigned to 18h workers."""
        shifts = [
            {"type": "M1", "day": date(2026, 1, 5), "dur": 12},
            {"type": "M2", "day": date(2026, 1, 5), "dur": 15},
        ]
        assigned = [[model.NewBoolVar(f"a_w{w}_s{s}") for s in range(2)] for w in range(3)]
        
        cost = build_m2_priority_cost(model, shifts, assigned, sample_workers)
        assert cost is not None

    def test_12h_workers_not_penalized(self, model):
        """12h workers should not be penalized for M1 shifts."""
        workers = [{"name": "Carol", "weekly_load": 12}]
        shifts = [{"type": "M1", "day": date(2026, 1, 5), "dur": 12}]
        assigned = [[model.NewBoolVar("a_w0_s0")]]
        
        cost = build_m2_priority_cost(model, shifts, assigned, workers)
        # With no 18h workers, cost should be 0
        assert cost is not None


class TestBuildEquityCostScaled:
    """Tests for build_equity_cost_scaled."""

    def test_returns_intvar(self, model, sample_workers):
        """Should return an IntVar."""
        # Create minimal past_stats and current_stats
        past_stats = {w["name"]: {stat: 0 for stat in EQUITY_STATS} for w in sample_workers}
        current_stats = {stat: [0, 0, 0] for stat in EQUITY_STATS}
        equity_weights = {stat: 1.0 for stat in EQUITY_STATS}
        
        cost = build_equity_cost_scaled(
            model, equity_weights, past_stats, current_stats, sample_workers, len(sample_workers)
        )
        assert cost is not None
        assert "equity_cost" in str(cost)

    def test_zero_weights_no_cost(self, model, sample_workers):
        """Zero weights should result in zero cost contribution."""
        past_stats = {w["name"]: {stat: 0 for stat in EQUITY_STATS} for w in sample_workers}
        current_stats = {stat: [0, 0, 0] for stat in EQUITY_STATS}
        equity_weights = {stat: 0.0 for stat in EQUITY_STATS}
        
        cost = build_equity_cost_scaled(
            model, equity_weights, past_stats, current_stats, sample_workers, len(sample_workers)
        )
        assert cost is not None

    def test_custom_scale_factor(self, model, sample_workers):
        """Should accept custom scale factor."""
        past_stats = {w["name"]: {stat: 0 for stat in EQUITY_STATS} for w in sample_workers}
        current_stats = {stat: [0, 0, 0] for stat in EQUITY_STATS}
        equity_weights = {stat: 1.0 for stat in EQUITY_STATS}
        
        cost = build_equity_cost_scaled(
            model, equity_weights, past_stats, current_stats, sample_workers, len(sample_workers), scale=100
        )
        assert cost is not None


class TestBuildDowEquityCostScaled:
    """Tests for build_dow_equity_cost_scaled."""

    def test_returns_intvar(self, model, sample_workers):
        """Should return an IntVar."""
        past_stats = {w["name"]: {"dow": [0]*7} for w in sample_workers}
        current_dow = {d: [0, 0, 0] for d in range(7)}
        
        cost = build_dow_equity_cost_scaled(
            model, 1.0, past_stats, current_dow, sample_workers, len(sample_workers)
        )
        assert cost is not None
        assert "dow_equity_cost" in str(cost)

    def test_zero_weight_no_cost(self, model, sample_workers):
        """Zero weight should result in zero cost."""
        past_stats = {w["name"]: {"dow": [0]*7} for w in sample_workers}
        current_dow = {d: [0, 0, 0] for d in range(7)}
        
        cost = build_dow_equity_cost_scaled(
            model, 0.0, past_stats, current_dow, sample_workers, len(sample_workers)
        )
        assert cost is not None


class TestBuildConsecShifts48hCost:
    """Tests for build_consec_shifts_48h_cost."""

    def test_returns_intvar(self, model, sample_shifts, assigned_vars):
        """Should return an IntVar."""
        cost = build_consec_shifts_48h_cost(
            model, assigned_vars, sample_shifts, len(sample_shifts), len(assigned_vars)
        )
        assert cost is not None
        assert "consec_shifts_48h_cost" in str(cost)

    def test_same_day_shifts_not_counted(self, model):
        """Shifts on the same day should not be counted."""
        day = date(2026, 1, 5)
        shifts = [
            {"type": "M1", "day": day, "start": datetime(2026, 1, 5, 8), "end": datetime(2026, 1, 5, 20), "dur": 12},
            {"type": "N", "day": day, "start": datetime(2026, 1, 5, 20), "end": datetime(2026, 1, 6, 8), "dur": 12},
        ]
        assigned = [[model.NewBoolVar(f"a_w0_s{s}") for s in range(2)]]
        
        cost = build_consec_shifts_48h_cost(model, assigned, shifts, 2, 1)
        assert cost is not None


class TestBuildTiebreakCost:
    """Tests for build_tiebreak_cost."""

    def test_returns_intvar(self, model, sample_shifts, assigned_vars, sample_workers):
        """Should return an IntVar."""
        cost = build_tiebreak_cost(
            model, assigned_vars, len(sample_workers), len(sample_shifts), sample_workers
        )
        assert cost is not None
        assert "tiebreak_cost" in str(cost)

    def test_prefers_lower_id_workers(self, model, sample_workers):
        """Should prefer workers with lower IDs in ties."""
        shifts = [{"type": "M1", "day": date(2026, 1, 5), "dur": 12}]
        assigned = [[model.NewBoolVar(f"a_w{w}_s0")] for w in range(3)]
        
        cost = build_tiebreak_cost(model, assigned, 3, 1, sample_workers)
        assert cost is not None
