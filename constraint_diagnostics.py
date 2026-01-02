"""Constraint violation diagnostics for schedule infeasibility analysis.

When the solver returns INFEASIBLE, this module helps identify which constraints
are causing the problem by:
1. Analyzing the input data for obvious conflicts
2. Running diagnostic solves with relaxed constraints
3. Reporting detailed violation information

This aids debugging and helps users understand why a schedule cannot be generated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from ortools.sat.python import cp_model

from constants import MIN_REST_HOURS, SHIFT_TYPES, SHIFTS


@dataclass
class ConstraintViolation:
    """Represents a single constraint violation or conflict."""
    category: str  # e.g., "availability", "coverage", "rest_interval"
    severity: str  # "error" (infeasible), "warning" (tight)
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"[{self.severity.upper()}] {self.category}: {self.message}"


@dataclass
class DiagnosticReport:
    """Complete diagnostic report for constraint analysis."""
    is_feasible: bool
    violations: list[ConstraintViolation] = field(default_factory=list)
    relaxation_results: dict[str, bool] = field(default_factory=dict)
    summary: str = ""

    def add_violation(self, violation: ConstraintViolation) -> None:
        self.violations.append(violation)

    def get_errors(self) -> list[ConstraintViolation]:
        return [v for v in self.violations if v.severity == "error"]

    def get_warnings(self) -> list[ConstraintViolation]:
        return [v for v in self.violations if v.severity == "warning"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_feasible": self.is_feasible,
            "violations": [
                {
                    "category": v.category,
                    "severity": v.severity,
                    "message": v.message,
                    "details": v.details,
                }
                for v in self.violations
            ],
            "relaxation_results": self.relaxation_results,
            "summary": self.summary,
        }

    def format_report(self) -> str:
        """Format the report as a human-readable string."""
        lines = ["=" * 60, "CONSTRAINT DIAGNOSTIC REPORT", "=" * 60, ""]

        if self.is_feasible:
            lines.append("✓ Schedule is FEASIBLE")
        else:
            lines.append("✗ Schedule is INFEASIBLE")

        lines.append("")

        errors = self.get_errors()
        warnings = self.get_warnings()

        if errors:
            lines.append(f"ERRORS ({len(errors)}):")
            lines.append("-" * 40)
            for v in errors:
                lines.append(f"  • [{v.category}] {v.message}")
                if v.details:
                    for k, val in v.details.items():
                        lines.append(f"      {k}: {val}")
            lines.append("")

        if warnings:
            lines.append(f"WARNINGS ({len(warnings)}):")
            lines.append("-" * 40)
            for v in warnings:
                lines.append(f"  • [{v.category}] {v.message}")
            lines.append("")

        if self.relaxation_results:
            lines.append("RELAXATION ANALYSIS:")
            lines.append("-" * 40)
            for constraint, feasible in self.relaxation_results.items():
                status = "✓ feasible" if feasible else "✗ still infeasible"
                lines.append(f"  Without '{constraint}': {status}")
            lines.append("")

        if self.summary:
            lines.append("SUMMARY:")
            lines.append("-" * 40)
            lines.append(f"  {self.summary}")
            lines.append("")

        lines.append("=" * 60)
        return "\n".join(lines)


class ConstraintDiagnostics:
    """Analyzes scheduling constraints to identify infeasibility causes."""

    def __init__(
        self,
        workers: list[dict],
        days: list[date],
        shifts: list[dict],
        shifts_by_day: dict[date, list[int]],
        iso_weeks: dict,
        unav_parsed: list[set],
        req_parsed: list[set],
        holiday_set: set[date],
    ):
        self.workers = workers
        self.days = days
        self.shifts = shifts
        self.shifts_by_day = shifts_by_day
        self.iso_weeks = iso_weeks
        self.unav_parsed = unav_parsed
        self.req_parsed = req_parsed
        self.holiday_set = holiday_set
        self.num_workers = len(workers)
        self.num_shifts = len(shifts)

    def analyze_pre_solve(self) -> DiagnosticReport:
        """Analyze constraints before solving to detect obvious issues."""
        report = DiagnosticReport(is_feasible=True)

        self._check_shift_coverage(report)
        self._check_worker_availability(report)
        self._check_night_shift_coverage(report)
        self._check_required_shift_conflicts(report)
        self._check_weekly_participation_feasibility(report)

        # Update feasibility based on errors found
        if report.get_errors():
            report.is_feasible = False
            report.summary = f"Found {len(report.get_errors())} constraint violations that may cause infeasibility."
        else:
            report.summary = "No obvious constraint violations detected."

        return report

    def _check_shift_coverage(self, report: DiagnosticReport) -> None:
        """Check if there are enough available workers for each shift."""
        for day in self.days:
            if day not in self.shifts_by_day:
                continue

            for s_idx in self.shifts_by_day[day]:
                shift = self.shifts[s_idx]
                shift_type = shift["type"]
                is_night = shift.get("night", False)

                available_workers = []
                for w_idx, worker in enumerate(self.workers):
                    # Check unavailability
                    if (day, None) in self.unav_parsed[w_idx]:
                        continue
                    if (day, shift_type) in self.unav_parsed[w_idx]:
                        continue
                    # Check night capability
                    if is_night and not worker.get("can_night", True):
                        continue
                    available_workers.append(worker["name"])

                if len(available_workers) == 0:
                    report.add_violation(ConstraintViolation(
                        category="coverage",
                        severity="error",
                        message=f"No workers available for {shift_type} shift on {day}",
                        details={
                            "date": str(day),
                            "shift_type": shift_type,
                            "is_night": is_night,
                            "reason": "All workers are either unavailable or cannot work nights",
                        }
                    ))
                elif len(available_workers) == 1:
                    report.add_violation(ConstraintViolation(
                        category="coverage",
                        severity="warning",
                        message=f"Only 1 worker available for {shift_type} on {day}: {available_workers[0]}",
                        details={"date": str(day), "shift_type": shift_type, "worker": available_workers[0]}
                    ))

    def _check_worker_availability(self, report: DiagnosticReport) -> None:
        """Check if workers have reasonable availability."""
        for w_idx, worker in enumerate(self.workers):
            unavail_days = sum(1 for d in self.days if (d, None) in self.unav_parsed[w_idx])
            total_days = len(self.days)
            avail_ratio = (total_days - unavail_days) / total_days if total_days > 0 else 0

            if avail_ratio < 0.1:
                report.add_violation(ConstraintViolation(
                    category="availability",
                    severity="warning",
                    message=f"Worker '{worker['name']}' has very low availability ({avail_ratio:.0%})",
                    details={
                        "worker": worker["name"],
                        "unavailable_days": unavail_days,
                        "total_days": total_days,
                    }
                ))

    def _check_night_shift_coverage(self, report: DiagnosticReport) -> None:
        """Check if there are enough night-capable workers."""
        night_capable = [w for w in self.workers if w.get("can_night", True)]

        if len(night_capable) == 0:
            report.add_violation(ConstraintViolation(
                category="night_coverage",
                severity="error",
                message="No workers can work night shifts, but night shifts exist",
                details={"night_capable_count": 0}
            ))
        elif len(night_capable) < 3:
            report.add_violation(ConstraintViolation(
                category="night_coverage",
                severity="warning",
                message=f"Only {len(night_capable)} workers can work nights (recommended: at least 3)",
                details={
                    "night_capable_workers": [w["name"] for w in night_capable],
                }
            ))

    def _check_required_shift_conflicts(self, report: DiagnosticReport) -> None:
        """Check for conflicts between required shifts and unavailability."""
        for w_idx, worker in enumerate(self.workers):
            for d, sh in self.req_parsed[w_idx]:
                # Check if required shift conflicts with unavailability
                if (d, None) in self.unav_parsed[w_idx]:
                    report.add_violation(ConstraintViolation(
                        category="conflict",
                        severity="error",
                        message=f"Worker '{worker['name']}' has required shift on {d} but is marked unavailable",
                        details={
                            "worker": worker["name"],
                            "date": str(d),
                            "required_shift": sh or "any",
                        }
                    ))
                elif sh and (d, sh) in self.unav_parsed[w_idx]:
                    report.add_violation(ConstraintViolation(
                        category="conflict",
                        severity="error",
                        message=f"Worker '{worker['name']}' has required {sh} shift on {d} but is unavailable for that shift",
                        details={
                            "worker": worker["name"],
                            "date": str(d),
                            "shift_type": sh,
                        }
                    ))

                # Check if night-incapable worker is required for night shift
                if sh == "N" and not worker.get("can_night", True):
                    report.add_violation(ConstraintViolation(
                        category="conflict",
                        severity="error",
                        message=f"Worker '{worker['name']}' cannot work nights but has required N shift on {d}",
                        details={"worker": worker["name"], "date": str(d)}
                    ))

    def _check_weekly_participation_feasibility(self, report: DiagnosticReport) -> None:
        """Check if weekly participation constraint can be satisfied."""
        for key, week in self.iso_weeks.items():
            weekdays = week.get("weekdays_for_distribution", [])
            week_shifts = week.get("shifts", [])

            # Count workers with at least one available weekday
            eligible_workers = []
            for w_idx, worker in enumerate(self.workers):
                avail_weekdays = [wd for wd in weekdays if (wd, None) not in self.unav_parsed[w_idx]]
                if avail_weekdays:
                    eligible_workers.append(worker["name"])

            # Each eligible worker needs at least one shift
            # Total shifts in week = len(week_shifts)
            if len(eligible_workers) > len(week_shifts):
                report.add_violation(ConstraintViolation(
                    category="weekly_participation",
                    severity="error",
                    message=f"ISO week {key}: {len(eligible_workers)} eligible workers but only {len(week_shifts)} shifts",
                    details={
                        "iso_week": key,
                        "eligible_workers": len(eligible_workers),
                        "total_shifts": len(week_shifts),
                        "workers": eligible_workers,
                    }
                ))

    def run_relaxation_analysis(self, logger=None) -> DiagnosticReport:
        """Run diagnostic solves with relaxed constraints to identify the cause."""
        report = self.analyze_pre_solve()

        # Define constraint groups to test relaxation
        constraint_groups = [
            ("weekly_participation", self._build_model_without_weekly_participation),
            ("24h_rest_interval", self._build_model_without_rest_interval),
            ("one_shift_per_day", self._build_model_without_one_per_day),
            ("night_restrictions", self._build_model_without_night_restrictions),
        ]

        for constraint_name, builder_func in constraint_groups:
            try:
                model, assigned = builder_func()
                solver = cp_model.CpSolver()
                solver.parameters.max_time_in_seconds = 5.0
                solver.parameters.log_search_progress = False
                status = solver.Solve(model)
                is_feasible = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
                report.relaxation_results[constraint_name] = is_feasible

                if is_feasible and logger:
                    logger.info(f"Relaxation test: removing '{constraint_name}' makes model feasible")
            except Exception as e:
                report.relaxation_results[constraint_name] = False
                if logger:
                    logger.warning(f"Relaxation test for '{constraint_name}' failed: {e}")

        # Update summary based on relaxation results
        feasible_when_relaxed = [k for k, v in report.relaxation_results.items() if v]
        if feasible_when_relaxed:
            report.summary = f"Model becomes feasible when relaxing: {', '.join(feasible_when_relaxed)}"
        elif report.get_errors():
            report.summary = "Pre-solve analysis found constraint violations. See errors above."
        else:
            report.summary = "Could not identify specific constraint causing infeasibility."

        return report

    def _build_base_model(self):
        """Build a base model with only shift coverage constraints."""
        model = cp_model.CpModel()
        assigned = [
            [model.NewBoolVar(f"diag_ass_w{w}_s{s}") for s in range(self.num_shifts)]
            for w in range(self.num_workers)
        ]

        # Each shift exactly one worker (always required)
        for s in range(self.num_shifts):
            model.AddExactlyOne(assigned[w][s] for w in range(self.num_workers))

        # Unavailability constraints (always required)
        for w in range(self.num_workers):
            for d, sh in self.unav_parsed[w]:
                if sh is None:
                    if d in self.shifts_by_day:
                        for s in self.shifts_by_day[d]:
                            model.Add(assigned[w][s] == 0)
                else:
                    if d in self.shifts_by_day:
                        for s in self.shifts_by_day[d]:
                            if self.shifts[s]["type"] == sh:
                                model.Add(assigned[w][s] == 0)

        return model, assigned

    def _build_model_without_weekly_participation(self):
        """Build model without weekly participation constraints."""
        model, assigned = self._build_base_model()

        # Add all constraints except weekly participation
        self._add_one_shift_per_day(model, assigned)
        self._add_night_restrictions(model, assigned)
        self._add_rest_interval(model, assigned)

        return model, assigned

    def _build_model_without_rest_interval(self):
        """Build model without 24h rest interval constraints."""
        model, assigned = self._build_base_model()

        self._add_one_shift_per_day(model, assigned)
        self._add_night_restrictions(model, assigned)
        self._add_weekly_participation(model, assigned)

        return model, assigned

    def _build_model_without_one_per_day(self):
        """Build model without one-shift-per-day constraints."""
        model, assigned = self._build_base_model()

        self._add_night_restrictions(model, assigned)
        self._add_rest_interval(model, assigned)
        self._add_weekly_participation(model, assigned)

        return model, assigned

    def _build_model_without_night_restrictions(self):
        """Build model without night shift restrictions."""
        model, assigned = self._build_base_model()

        self._add_one_shift_per_day(model, assigned)
        self._add_rest_interval(model, assigned)
        self._add_weekly_participation(model, assigned)

        return model, assigned

    def _add_one_shift_per_day(self, model, assigned):
        """Add constraint: max one shift per worker per day."""
        for w in range(self.num_workers):
            for d in self.shifts_by_day:
                model.Add(sum(assigned[w][s] for s in self.shifts_by_day[d]) <= 1)

    def _add_night_restrictions(self, model, assigned):
        """Add constraint: some workers cannot work nights."""
        for w in range(self.num_workers):
            if not self.workers[w].get("can_night", True):
                for s in range(self.num_shifts):
                    if self.shifts[s].get("night", False):
                        model.Add(assigned[w][s] == 0)

    def _add_rest_interval(self, model, assigned):
        """Add constraint: 24h rest between shifts."""
        for w in range(self.num_workers):
            for i in range(self.num_shifts):
                for j in range(i + 1, self.num_shifts):
                    si = self.shifts[i]
                    sj = self.shifts[j]
                    start_i, end_i = si["start"], si["end"]
                    start_j, end_j = sj["start"], sj["end"]

                    if max(start_i, start_j) < min(end_i, end_j):
                        model.AddBoolOr(assigned[w][i].Not(), assigned[w][j].Not())
                    else:
                        if start_j >= end_i:
                            delta = (start_j - end_i).total_seconds() / 3600
                            if delta < MIN_REST_HOURS:
                                model.AddBoolOr(assigned[w][i].Not(), assigned[w][j].Not())
                        elif start_i >= end_j:
                            delta = (start_i - end_j).total_seconds() / 3600
                            if delta < MIN_REST_HOURS:
                                model.AddBoolOr(assigned[w][i].Not(), assigned[w][j].Not())

    def _add_weekly_participation(self, model, assigned):
        """Add constraint: each eligible worker gets at least one shift per week."""
        for key, week in self.iso_weeks.items():
            weekdays = week.get("weekdays_for_distribution", [])
            week_shifts = week.get("shifts", [])

            for w in range(self.num_workers):
                avail_weekdays = [wd for wd in weekdays if (wd, None) not in self.unav_parsed[w]]
                if avail_weekdays:
                    model.Add(sum(assigned[w][s] for s in week_shifts) >= 1)


def run_diagnostics(
    workers: list[dict],
    days: list[date],
    shifts: list[dict],
    shifts_by_day: dict[date, list[int]],
    iso_weeks: dict,
    unav_parsed: list[set],
    req_parsed: list[set],
    holiday_set: set[date],
    logger=None,
    full_analysis: bool = True,
) -> DiagnosticReport:
    """
    Run constraint diagnostics and return a report.

    Args:
        workers: List of worker dictionaries
        days: List of dates to schedule
        shifts: List of shift dictionaries
        shifts_by_day: Mapping of date to shift indices
        iso_weeks: ISO week information
        unav_parsed: Parsed unavailability per worker
        req_parsed: Parsed required shifts per worker
        holiday_set: Set of holiday dates
        logger: Optional logger for output
        full_analysis: If True, run relaxation analysis (slower but more informative)

    Returns:
        DiagnosticReport with violations and analysis results
    """
    diagnostics = ConstraintDiagnostics(
        workers=workers,
        days=days,
        shifts=shifts,
        shifts_by_day=shifts_by_day,
        iso_weeks=iso_weeks,
        unav_parsed=unav_parsed,
        req_parsed=req_parsed,
        holiday_set=holiday_set,
    )

    if full_analysis:
        report = diagnostics.run_relaxation_analysis(logger)
    else:
        report = diagnostics.analyze_pre_solve()

    if logger:
        for violation in report.get_errors():
            logger.error(str(violation))
        for violation in report.get_warnings():
            logger.warning(str(violation))

    return report
