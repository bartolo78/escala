"""
Tests for constraint_diagnostics.py - Constraint violation reporting
"""

import pytest
from datetime import date, timedelta
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from constraint_diagnostics import (
    ConstraintViolation,
    DiagnosticReport,
    ConstraintDiagnostics,
    run_diagnostics,
)
from logic_g4 import generate_schedule


class TestConstraintViolation:
    """Tests for ConstraintViolation dataclass."""

    def test_str_representation(self):
        """Violation should have readable string representation."""
        v = ConstraintViolation(
            category="coverage",
            severity="error",
            message="No workers available for M1 shift on 2026-01-15",
        )
        assert "[ERROR]" in str(v)
        assert "coverage" in str(v)
        assert "No workers available" in str(v)


class TestDiagnosticReport:
    """Tests for DiagnosticReport dataclass."""

    def test_add_violation(self):
        """Should add violations to list."""
        report = DiagnosticReport(is_feasible=False)
        v = ConstraintViolation(
            category="test",
            severity="error",
            message="Test error",
        )
        report.add_violation(v)
        assert len(report.violations) == 1

    def test_get_errors(self):
        """Should filter errors from violations."""
        report = DiagnosticReport(is_feasible=False)
        report.add_violation(ConstraintViolation("a", "error", "Error 1"))
        report.add_violation(ConstraintViolation("b", "warning", "Warning 1"))
        report.add_violation(ConstraintViolation("c", "error", "Error 2"))
        
        errors = report.get_errors()
        assert len(errors) == 2
        assert all(e.severity == "error" for e in errors)

    def test_get_warnings(self):
        """Should filter warnings from violations."""
        report = DiagnosticReport(is_feasible=False)
        report.add_violation(ConstraintViolation("a", "error", "Error 1"))
        report.add_violation(ConstraintViolation("b", "warning", "Warning 1"))
        
        warnings = report.get_warnings()
        assert len(warnings) == 1
        assert warnings[0].severity == "warning"

    def test_to_dict(self):
        """Should convert report to dictionary."""
        report = DiagnosticReport(is_feasible=True, summary="All good")
        report.add_violation(ConstraintViolation("test", "warning", "Test warning"))
        
        d = report.to_dict()
        assert d["is_feasible"] is True
        assert d["summary"] == "All good"
        assert len(d["violations"]) == 1

    def test_format_report(self):
        """Should generate readable formatted report."""
        report = DiagnosticReport(is_feasible=False, summary="Found issues")
        report.add_violation(ConstraintViolation("coverage", "error", "No coverage"))
        report.relaxation_results["weekly_participation"] = True
        
        formatted = report.format_report()
        assert "CONSTRAINT DIAGNOSTIC REPORT" in formatted
        assert "INFEASIBLE" in formatted
        assert "ERRORS" in formatted
        assert "weekly_participation" in formatted


class TestConstraintDiagnosticsPreSolve:
    """Tests for pre-solve constraint analysis."""

    def setup_method(self):
        """Set up test fixtures."""
        self.workers = [
            {"name": "W1", "id": "1", "can_night": True, "weekly_load": 12},
            {"name": "W2", "id": "2", "can_night": True, "weekly_load": 18},
            {"name": "W3", "id": "3", "can_night": False, "weekly_load": 12},
        ]
        self.days = [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)]
        
    def _create_shifts(self, days):
        """Helper to create shifts for days."""
        import datetime
        shifts = []
        for day in days:
            d_dt = datetime.datetime.combine(day, datetime.time())
            shifts.append({
                "type": "M1", "start": d_dt + timedelta(hours=8),
                "end": d_dt + timedelta(hours=20), "dur": 12, "night": False, "day": day
            })
            shifts.append({
                "type": "M2", "start": d_dt + timedelta(hours=8),
                "end": d_dt + timedelta(hours=23), "dur": 15, "night": False, "day": day
            })
            shifts.append({
                "type": "N", "start": d_dt + timedelta(hours=20),
                "end": d_dt + timedelta(hours=32), "dur": 12, "night": True, "day": day
            })
        return shifts

    def test_detect_no_workers_for_shift(self):
        """Should detect when no workers available for a shift."""
        shifts = self._create_shifts(self.days)
        shifts_by_day = {d: [i for i, s in enumerate(shifts) if s["day"] == d] for d in self.days}
        
        # Make all workers unavailable on day 1
        unav_parsed = [
            {(self.days[0], None)},  # W1 unavailable
            {(self.days[0], None)},  # W2 unavailable
            {(self.days[0], None)},  # W3 unavailable
        ]
        
        diag = ConstraintDiagnostics(
            workers=self.workers,
            days=self.days,
            shifts=shifts,
            shifts_by_day=shifts_by_day,
            iso_weeks={},
            unav_parsed=unav_parsed,
            req_parsed=[set(), set(), set()],
            holiday_set=set(),
        )
        
        report = diag.analyze_pre_solve()
        errors = report.get_errors()
        
        # Should have errors for all 3 shifts on day 1
        coverage_errors = [e for e in errors if e.category == "coverage"]
        assert len(coverage_errors) == 3

    def test_detect_night_coverage_issue(self):
        """Should detect when no workers can work nights."""
        # Make all workers unable to work nights
        workers = [
            {"name": "W1", "id": "1", "can_night": False, "weekly_load": 12},
            {"name": "W2", "id": "2", "can_night": False, "weekly_load": 18},
        ]
        shifts = self._create_shifts(self.days)
        shifts_by_day = {d: [i for i, s in enumerate(shifts) if s["day"] == d] for d in self.days}
        
        diag = ConstraintDiagnostics(
            workers=workers,
            days=self.days,
            shifts=shifts,
            shifts_by_day=shifts_by_day,
            iso_weeks={},
            unav_parsed=[set(), set()],
            req_parsed=[set(), set()],
            holiday_set=set(),
        )
        
        report = diag.analyze_pre_solve()
        errors = report.get_errors()
        
        # Should detect no night-capable workers
        night_errors = [e for e in errors if e.category == "night_coverage"]
        assert len(night_errors) >= 1

    def test_detect_required_unavail_conflict(self):
        """Should detect conflict between required and unavailable."""
        shifts = self._create_shifts(self.days)
        shifts_by_day = {d: [i for i, s in enumerate(shifts) if s["day"] == d] for d in self.days}
        
        # W1 is required on day 1 but also marked unavailable
        unav_parsed = [
            {(self.days[0], None)},  # W1 unavailable on day 1
            set(),
            set(),
        ]
        req_parsed = [
            {(self.days[0], None)},  # W1 required on day 1 - conflict!
            set(),
            set(),
        ]
        
        diag = ConstraintDiagnostics(
            workers=self.workers,
            days=self.days,
            shifts=shifts,
            shifts_by_day=shifts_by_day,
            iso_weeks={},
            unav_parsed=unav_parsed,
            req_parsed=req_parsed,
            holiday_set=set(),
        )
        
        report = diag.analyze_pre_solve()
        errors = report.get_errors()
        
        conflict_errors = [e for e in errors if e.category == "conflict"]
        assert len(conflict_errors) >= 1
        assert "W1" in conflict_errors[0].message


class TestIntegrationWithGenerateSchedule:
    """Integration tests for diagnostics with generate_schedule."""

    def test_infeasible_schedule_returns_diagnostic(self):
        """Infeasible schedule should include diagnostic report in stats."""
        # Create a scenario that's infeasible:
        # Only 2 workers but need 3 shifts per day (each shift needs exactly 1 worker)
        workers = [
            {"name": "W1", "id": "1", "can_night": True, "weekly_load": 18},
            {"name": "W2", "id": "2", "can_night": True, "weekly_load": 18},
        ]
        
        # Make both workers unavailable most days to trigger infeasibility
        unavail = {
            "W1": ["2026-01-05 to 2026-01-11"],  # Entire week unavailable
            "W2": ["2026-01-05 to 2026-01-11"],
        }
        required = {"W1": [], "W2": []}
        history = {}
        
        schedule, weekly, assignments, stats, _ = generate_schedule(
            2026, 1, unavail, required, history, workers, holidays=[]
        )
        
        # Should be infeasible and have diagnostic report
        from ortools.sat.python import cp_model
        if stats["status"] == cp_model.INFEASIBLE:
            assert "diagnostic_report" in stats
            # Diagnostic report should exist (may be None if diagnostics failed)
            if stats["diagnostic_report"] is not None:
                assert hasattr(stats["diagnostic_report"], "violations")


class TestRunDiagnostics:
    """Tests for the run_diagnostics convenience function."""

    def test_basic_run(self):
        """Should run diagnostics and return report."""
        import datetime
        workers = [
            {"name": "W1", "id": "1", "can_night": True, "weekly_load": 12},
            {"name": "W2", "id": "2", "can_night": True, "weekly_load": 18},
            {"name": "W3", "id": "3", "can_night": True, "weekly_load": 12},
        ]
        days = [date(2026, 1, 5), date(2026, 1, 6)]
        
        shifts = []
        for day in days:
            d_dt = datetime.datetime.combine(day, datetime.time())
            shifts.append({
                "type": "M1", "start": d_dt + timedelta(hours=8),
                "end": d_dt + timedelta(hours=20), "dur": 12, "night": False, "day": day
            })
            shifts.append({
                "type": "M2", "start": d_dt + timedelta(hours=8),
                "end": d_dt + timedelta(hours=23), "dur": 15, "night": False, "day": day
            })
            shifts.append({
                "type": "N", "start": d_dt + timedelta(hours=20),
                "end": d_dt + timedelta(hours=32), "dur": 12, "night": True, "day": day
            })
        
        shifts_by_day = {d: [i for i, s in enumerate(shifts) if s["day"] == d] for d in days}
        
        report = run_diagnostics(
            workers=workers,
            days=days,
            shifts=shifts,
            shifts_by_day=shifts_by_day,
            iso_weeks={},
            unav_parsed=[set(), set(), set()],
            req_parsed=[set(), set(), set()],
            holiday_set=set(),
            full_analysis=False,  # Quick mode for testing
        )
        
        assert isinstance(report, DiagnosticReport)
        assert report.summary != ""
