"""Scheduler Service - Business logic layer between UI and scheduling engine.

This module provides a clean API for scheduling operations, decoupling the UI
from the underlying scheduling logic. All data operations, history management,
and scheduling calls go through this service.

Benefits:
- UI code becomes simpler (no direct imports from scheduling_engine, etc.)
- Easier to test business logic independently
- Enables future web UI or CLI without code changes
- Centralizes validation and error handling
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable, Optional

import yaml

from ortools.sat.python import cp_model

from constants import DOW_EQUITY_WEIGHT, EQUITY_STATS, EQUITY_WEIGHTS
from scheduling_engine import _compute_past_stats, generate_schedule, update_history
from utils import compute_holidays
from logger import get_logger

logger = get_logger('scheduler_service')


@dataclass
class Worker:
    """Represents a worker with scheduling attributes."""
    name: str
    id: str
    color: str = "#000000"
    can_night: bool = True
    weekly_load: int = 18

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "id": self.id,
            "color": self.color,
            "can_night": self.can_night,
            "weekly_load": self.weekly_load,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Worker":
        return cls(
            name=data["name"],
            id=data.get("id", "ID000"),
            color=data.get("color", "#000000"),
            can_night=data.get("can_night", True),
            weekly_load=data.get("weekly_load", 18),
        )


@dataclass
class ScheduleResult:
    """Result of a schedule generation operation."""
    success: bool
    schedule: dict[str, dict[str, str]] = field(default_factory=dict)
    weekly: dict = field(default_factory=dict)
    assignments: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    current_stats: dict = field(default_factory=dict)
    past_stats: dict = field(default_factory=dict)
    error_message: str = ""
    diagnostic_report: Any = None

    @property
    def is_feasible(self) -> bool:
        """Check if the schedule was feasible."""
        return self.success and bool(self.schedule)


@dataclass
class WorkerStats:
    """Statistics for a single worker."""
    name: str
    total_hours: int = 0
    day_shifts: int = 0
    night_shifts: int = 0
    weekend_holiday_shifts: int = 0
    sat_night: int = 0
    sat_day: int = 0
    sun_holiday_night: int = 0
    sun_holiday_day: int = 0
    fri_night: int = 0


class SchedulerService:
    """
    Service layer for shift scheduling operations.

    This class provides a clean API for:
    - Worker management (add, remove, list)
    - Availability management (unavailable/required shifts)
    - Schedule generation
    - History management (load, save, query)
    - Report generation
    - Configuration persistence
    """

    DEFAULT_CONFIG_FILE = "config.yaml"
    DEFAULT_THRESHOLDS = {
        'sun_holiday_m2': 2,        # Priority 1: Sunday or Holiday M2
        'sat_n': 2,                 # Priority 2: Saturday Night
        'sat_m2': 2,                # Priority 3: Saturday M2
        'sun_holiday_n': 2,         # Priority 4: Sunday or Holiday N (Sat holidays excluded)
        'sun_holiday_m1': 2,        # Priority 5: Sunday or Holiday M1
        'sat_m1': 2,                # Priority 6: Saturday M1
        'fri_night': 1,             # Priority 7: Friday N
        'weekday_not_fri_n': 2,     # Priority 8: Weekday (not Friday) N
        'monday_day': 2,            # Priority 9: Monday M1 or M2
        'weekday_not_mon_day': 3,   # Priority 10: Weekday (not Monday) M1 or M2
    }

    def __init__(self, config_path: Optional[str] = None):
        """Initialize the scheduler service.

        Args:
            config_path: Path to configuration file. If None, uses default.
        """
        self._config_path = config_path or self._get_default_config_path()
        self._workers: list[Worker] = []
        self._unavail: dict[str, list[str]] = {}
        self._req: dict[str, list[str]] = {}
        self._history: dict[str, dict[str, list[dict]]] = {}
        self._manual_holidays: list[int] = []
        self._equity_weights: dict[str, float] = EQUITY_WEIGHTS.copy()
        self._dow_equity_weight: float = DOW_EQUITY_WEIGHT
        self._thresholds: dict[str, int] = self.DEFAULT_THRESHOLDS.copy()
        self._lexicographic: bool = False  # Non-staged mode - more robust for constrained problems
        # Equity credits per worker: {worker_name: {stat: credit_value}}
        # Used to compensate for extended absences (medical leave, parental leave, etc.)
        # Positive credits reduce a worker's apparent "debt" from missing shifts
        self._equity_credits: dict[str, dict[str, int]] = {}

        # Cached stats from last schedule generation
        self._current_stats: Optional[dict] = None
        self._past_stats: Optional[dict] = None

        self._load_config()

    @staticmethod
    def _get_default_config_path() -> str:
        """Get the default config file path."""
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")

    # =========================================================================
    # Configuration Management
    # =========================================================================

    def _load_config(self) -> None:
        """Load configuration from file."""
        if not os.path.exists(self._config_path):
            logger.info(f"Config file not found at {self._config_path}, using defaults")
            self._workers = self._get_default_workers()
            self._init_availability_dicts()
            return

        try:
            with open(self._config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            if config and 'workers' in config:
                self._workers = [Worker.from_dict(w) for w in config['workers']]
            else:
                self._workers = self._get_default_workers()

            if config and 'thresholds' in config:
                self._thresholds.update(config['thresholds'])

            # Load equity credits for workers with extended absences
            if config and 'equity_credits' in config:
                self._equity_credits = config['equity_credits']

            self._init_availability_dicts()
            logger.info(f"Configuration loaded from {self._config_path}")

        except Exception as e:
            logger.warning(f"Could not load config file: {e}")
            self._workers = self._get_default_workers()
            self._init_availability_dicts()

    def _init_availability_dicts(self) -> None:
        """Initialize availability dictionaries for all workers."""
        for worker in self._workers:
            if worker.name not in self._unavail:
                self._unavail[worker.name] = []
            if worker.name not in self._req:
                self._req[worker.name] = []

    @staticmethod
    def _get_default_workers() -> list[Worker]:
        """Return default workers list."""
        defaults = [
            ("Tome", "ID001", "#ff0000", True, 12),
            ("Rosa", "ID002", "#ff5400", True, 18),
            ("Lucas", "ID003", "#ffaa00", True, 18),
            ("Bartolo", "ID004", "#ffff00", True, 18),
            ("Gilberto", "ID005", "#aaff00", True, 18),
            ("Pego", "ID006", "#ff0055", True, 18),
            ("Celeste", "ID007", "#00ff55", True, 12),
            ("Sofia", "ID008", "#00ffa9", True, 18),
            ("Lucilia", "ID009", "#00ffff", True, 12),
            ("Teresa", "ID010", "#00a9ff", True, 18),
            ("Fernando", "ID011", "#0054ff", False, 12),
            ("Rosario", "ID012", "#0000ff", True, 12),
            ("Nuno", "ID013", "#5400ff", True, 18),
            ("Filomena", "ID014", "#aa00ff", False, 12),
            ("Angela", "ID015", "#ff00ff", True, 18),
        ]
        return [Worker(name=n, id=i, color=c, can_night=cn, weekly_load=wl)
                for n, i, c, cn, wl in defaults]

    def save_config(self) -> bool:
        """Save current configuration to file.

        Returns:
            True if save was successful, False otherwise.
        """
        config = {
            'settings': {
                'solver_timeout_seconds': 30,
                'past_report_weeks': 52
            },
            'workers': [w.to_dict() for w in self._workers],
            'thresholds': self._thresholds
        }
        # Only save equity_credits if there are any
        if self._equity_credits:
            config['equity_credits'] = self._equity_credits

        try:
            with open(self._config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
            logger.info(f"Configuration saved to {self._config_path}")
            return True
        except Exception as e:
            logger.error(f"Could not save config file: {e}")
            return False

    # =========================================================================
    # Worker Management
    # =========================================================================

    @property
    def workers(self) -> list[Worker]:
        """Get list of all workers."""
        return self._workers.copy()

    @property
    def worker_names(self) -> list[str]:
        """Get list of worker names."""
        return [w.name for w in self._workers]

    def get_worker(self, name: str) -> Optional[Worker]:
        """Get a worker by name."""
        for w in self._workers:
            if w.name == name:
                return w
        return None

    def add_worker(self, name: str, can_night: bool = True, weekly_load: int = 18,
                   color: str = "#000000") -> Worker:
        """Add a new worker.

        Args:
            name: Worker's name (must be unique)
            can_night: Whether worker can work night shifts
            weekly_load: Standard weekly hours (12 or 18)
            color: Display color for the worker

        Returns:
            The newly created Worker

        Raises:
            ValueError: If worker name already exists
        """
        if any(w.name == name for w in self._workers):
            raise ValueError(f"Worker '{name}' already exists")

        next_num = max((int(w.id[2:]) for w in self._workers), default=0) + 1
        new_id = f"ID{next_num:03d}"

        worker = Worker(
            name=name,
            id=new_id,
            color=color,
            can_night=can_night,
            weekly_load=weekly_load
        )

        self._workers.append(worker)
        self._unavail[name] = []
        self._req[name] = []

        logger.info(f"Added worker: {name}")
        return worker

    def remove_worker(self, name: str) -> bool:
        """Remove a worker by name.

        Args:
            name: Name of worker to remove

        Returns:
            True if worker was removed, False if not found
        """
        for i, w in enumerate(self._workers):
            if w.name == name:
                self._workers.pop(i)
                self._unavail.pop(name, None)
                self._req.pop(name, None)
                logger.info(f"Removed worker: {name}")
                return True
        return False

    # =========================================================================
    # Availability Management
    # =========================================================================

    def get_unavailable(self, worker_name: str) -> list[str]:
        """Get unavailable entries for a worker."""
        return self._unavail.get(worker_name, []).copy()

    def get_required(self, worker_name: str) -> list[str]:
        """Get required entries for a worker."""
        return self._req.get(worker_name, []).copy()

    def add_unavailable(self, worker_name: str, entry: str) -> bool:
        """Add an unavailable entry for a worker.

        Args:
            worker_name: Name of the worker
            entry: Unavailability entry (e.g., "2026-01-15" or "2026-01-15 M1")

        Returns:
            True if added, False if already exists or worker not found
        """
        if worker_name not in self._unavail:
            return False
        if entry not in self._unavail[worker_name]:
            self._unavail[worker_name].append(entry)
            return True
        return False

    def add_required(self, worker_name: str, entry: str) -> bool:
        """Add a required entry for a worker.

        Args:
            worker_name: Name of the worker
            entry: Required entry (e.g., "2026-01-15" or "2026-01-15 M1")

        Returns:
            True if added, False if already exists or worker not found
        """
        if worker_name not in self._req:
            return False
        if entry not in self._req[worker_name]:
            self._req[worker_name].append(entry)
            return True
        return False

    def remove_unavailable(self, worker_name: str, index: int) -> bool:
        """Remove an unavailable entry by index."""
        if worker_name in self._unavail and 0 <= index < len(self._unavail[worker_name]):
            self._unavail[worker_name].pop(index)
            return True
        return False

    def remove_required(self, worker_name: str, index: int) -> bool:
        """Remove a required entry by index."""
        if worker_name in self._req and 0 <= index < len(self._req[worker_name]):
            self._req[worker_name].pop(index)
            return True
        return False

    # =========================================================================
    # Holiday Management
    # =========================================================================

    @property
    def manual_holidays(self) -> list[int]:
        """Get manually added holidays."""
        return self._manual_holidays.copy()

    def add_manual_holiday(self, day: int) -> bool:
        """Add a manual holiday (day of month)."""
        if day not in self._manual_holidays:
            self._manual_holidays.append(day)
            return True
        return False

    def clear_manual_holidays(self) -> None:
        """Clear all manual holidays."""
        self._manual_holidays.clear()

    def get_holidays(self, year: int, month: int) -> list[int]:
        """Get all holidays for a month (auto-computed + manual)."""
        auto_holidays = compute_holidays(year, month)
        return sorted(set(auto_holidays + self._manual_holidays))

    # =========================================================================
    # Settings Management
    # =========================================================================

    @property
    def equity_weights(self) -> dict[str, float]:
        """Get equity weights."""
        return self._equity_weights.copy()

    def set_equity_weight(self, stat: str, value: float) -> None:
        """Set an equity weight."""
        self._equity_weights[stat] = value

    @property
    def dow_equity_weight(self) -> float:
        """Get day-of-week equity weight."""
        return self._dow_equity_weight

    @dow_equity_weight.setter
    def dow_equity_weight(self, value: float) -> None:
        """Set day-of-week equity weight."""
        self._dow_equity_weight = value

    @property
    def lexicographic_mode(self) -> bool:
        """Get whether lexicographic optimization is enabled."""
        return self._lexicographic

    @lexicographic_mode.setter
    def lexicographic_mode(self, value: bool) -> None:
        """Set lexicographic optimization mode."""
        self._lexicographic = value

    @property
    def thresholds(self) -> dict[str, int]:
        """Get imbalance thresholds."""
        return self._thresholds.copy()

    def set_threshold(self, stat: str, value: int) -> None:
        """Set an imbalance threshold."""
        self._thresholds[stat] = value

    # =========================================================================
    # Equity Credits Management (for extended absences)
    # =========================================================================

    @property
    def equity_credits(self) -> dict[str, dict[str, int]]:
        """Get equity credits for all workers.
        
        Equity credits compensate for extended absences (medical leave, parental
        leave, prolonged vacations). They are added to a worker's past stats
        during schedule generation, preventing unfair "catch-up" assignments.
        
        Returns:
            Dict mapping worker_name -> {stat: credit_value}
        """
        return {w: credits.copy() for w, credits in self._equity_credits.items()}

    def get_worker_equity_credits(self, worker_name: str) -> dict[str, int]:
        """Get equity credits for a specific worker.
        
        Args:
            worker_name: Name of the worker
            
        Returns:
            Dict mapping stat -> credit_value (empty if no credits)
        """
        return self._equity_credits.get(worker_name, {}).copy()

    def set_worker_equity_credit(self, worker_name: str, stat: str, value: int) -> None:
        """Set an equity credit for a worker.
        
        Use this when a worker returns from extended absence to prevent the
        scheduler from over-assigning them undesirable shifts to "catch up".
        
        Example: Sofia was on 4-week parental leave. During that time, she
        would have typically received 1 Saturday night. Set her sat_n credit
        to 1 so she's not assigned extra Saturday nights upon return.
        
        Args:
            worker_name: Name of the worker
            stat: The equity stat (e.g., 'sat_n', 'sun_holiday_m2')
            value: Credit value to add to their apparent stat count
        """
        if worker_name not in self._equity_credits:
            self._equity_credits[worker_name] = {}
        if value == 0:
            # Remove zero credits to keep config clean
            self._equity_credits[worker_name].pop(stat, None)
            if not self._equity_credits[worker_name]:
                del self._equity_credits[worker_name]
        else:
            self._equity_credits[worker_name][stat] = value

    def add_absence_credits(self, worker_name: str, weeks_absent: int) -> dict[str, int]:
        """Calculate and set recommended equity credits for an absence period.
        
        This is a convenience method that estimates fair credits based on
        average shift distribution. For a more precise adjustment, use
        set_worker_equity_credit() directly.
        
        Args:
            worker_name: Name of the worker
            weeks_absent: Number of weeks the worker was/will be absent
            
        Returns:
            Dict of credits that were applied
        """
        # Average distribution per worker per week (15 workers, rough estimates)
        # These are approximations - adjust based on your actual workforce
        avg_per_week = {
            'sat_n': 0.07,          # ~1 per 15 weeks
            'sun_holiday_m2': 0.07,
            'sun_holiday_m1': 0.07,
            'sun_holiday_n': 0.07,
            'sat_m2': 0.07,
            'sat_m1': 0.07,
            'fri_night': 0.07,
            'weekday_not_fri_n': 0.20,  # ~3 per 15 weeks
            'monday_day': 0.07,
            'weekday_not_mon_day': 0.47,  # Most common
        }
        
        credits_applied = {}
        for stat, rate in avg_per_week.items():
            credit = round(rate * weeks_absent)
            if credit > 0:
                self.set_worker_equity_credit(worker_name, stat, 
                    self._equity_credits.get(worker_name, {}).get(stat, 0) + credit)
                credits_applied[stat] = credit
        
        return credits_applied

    def clear_worker_equity_credits(self, worker_name: str) -> None:
        """Clear all equity credits for a worker.
        
        Use this at the start of a new year or when credits are no longer needed.
        
        Args:
            worker_name: Name of the worker
        """
        self._equity_credits.pop(worker_name, None)

    def clear_all_equity_credits(self) -> None:
        """Clear all equity credits for all workers."""
        self._equity_credits.clear()

    # =========================================================================
    # Schedule Generation
    # =========================================================================

    def generate(self, year: int, month: int) -> ScheduleResult:
        """Generate a schedule for the given month.

        Args:
            year: Year to schedule
            month: Month to schedule (1-12)

        Returns:
            ScheduleResult with schedule data or error information
        """
        all_holidays = self.get_holidays(year, month)
        workers_dict = [w.to_dict() for w in self._workers]

        logger.info(f"Generating schedule for {month}/{year} with {len(self._workers)} workers")

        try:
            schedule, weekly, assignments, stats, current_stats = generate_schedule(
                year, month,
                self._unavail,
                self._req,
                self._history,
                workers_dict,
                holidays=all_holidays,
                equity_weights=self._equity_weights,
                dow_equity_weight=self._dow_equity_weight,
                lexicographic=self._lexicographic,
                equity_credits=self._equity_credits,
            )

            # Cache stats for later use
            self._current_stats = current_stats
            self._past_stats = _compute_past_stats(self._history, workers_dict)

            # Update history with new assignments
            if assignments:
                self._history = update_history(assignments, self._history)

            status = stats.get("status")
            success = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
            diagnostic_report = stats.get("diagnostic_report")

            if not success:
                logger.warning("No feasible schedule found")
                error_msg = stats.get("error") or "No feasible schedule found"
                if diagnostic_report:
                    error_msg += f". {diagnostic_report.summary}"
            else:
                logger.info(f"Schedule generated successfully with {len(assignments)} assignments")
                error_msg = ""

            return ScheduleResult(
                success=success,
                schedule=schedule,
                weekly=weekly,
                assignments=assignments,
                stats=stats,
                current_stats=current_stats,
                past_stats=self._past_stats,
                error_message=error_msg,
                diagnostic_report=diagnostic_report,
            )

        except Exception as e:
            logger.error(f"Error generating schedule: {e}", exc_info=True)
            return ScheduleResult(
                success=False,
                error_message=str(e)
            )

    def has_schedule_for_month(self, year: int, month: int) -> bool:
        """Check if a schedule already exists for the given month.

        Args:
            year: Year to check
            month: Month to check (1-12)

        Returns:
            True if any assignments exist for the month, False otherwise
        """
        from history_view import HistoryView
        history_view = HistoryView(self._history)
        
        # Check if any dates in the month have assignments
        from calendar import monthrange
        _, last_day = monthrange(year, month)
        
        for day in range(1, last_day + 1):
            date_str = f"{year:04d}-{month:02d}-{day:02d}"
            if date_str in history_view.scheduled_dates():
                return True
        
        return False

    # =========================================================================
    # Statistics and Reports
    # =========================================================================

    def get_worker_stats(self, worker_name: str) -> WorkerStats:
        """Get statistics for a specific worker from history.

        Args:
            worker_name: Name of the worker

        Returns:
            WorkerStats with aggregated statistics
        """
        stats = WorkerStats(name=worker_name)

        if worker_name not in self._history:
            return stats

        for month_year in self._history[worker_name]:
            try:
                year, month = map(int, month_year.split('-'))
            except ValueError:
                continue

            holidays = set(compute_holidays(year, month))

            for ass in self._history[worker_name][month_year]:
                try:
                    d = datetime.fromisoformat(ass['date'])
                    stats.total_hours += ass.get('dur', 0)

                    shift = ass.get('shift', '')
                    weekday = d.weekday()
                    day_num = d.day
                    is_holiday = day_num in holidays
                    is_weekend_hol = weekday >= 5 or is_holiday
                    is_day = shift in ['M1', 'M2']
                    is_night = shift == 'N'

                    if is_day:
                        stats.day_shifts += 1
                    if is_night:
                        stats.night_shifts += 1
                    if is_weekend_hol:
                        stats.weekend_holiday_shifts += 1
                    if weekday == 5:  # Saturday
                        if is_night:
                            stats.sat_night += 1
                        if is_day:
                            stats.sat_day += 1
                    if weekday == 6 or is_holiday:  # Sunday or holiday
                        if is_night:
                            stats.sun_holiday_night += 1
                        if is_day:
                            stats.sun_holiday_day += 1
                    if weekday == 4 and is_night:  # Friday night
                        stats.fri_night += 1

                except (ValueError, KeyError):
                    continue

        return stats

    def generate_all_worker_stats(self, weeks_lookback: int = 52) -> list[WorkerStats]:
        """Generate statistics for all workers within a date range.

        Args:
            weeks_lookback: Number of weeks to look back from most recent data

        Returns:
            List of WorkerStats for all workers
        """
        # Find the date range from history
        all_dates = []
        for worker_hist in self._history.values():
            for month_assignments in worker_hist.values():
                for ass in month_assignments:
                    if 'date' in ass:
                        all_dates.append(date.fromisoformat(ass['date']))

        if all_dates:
            current_date = max(all_dates)
            last_iso = current_date.isocalendar()
            monday_last = current_date - timedelta(days=last_iso[2] - 1)
            start_date = monday_last - timedelta(weeks=weeks_lookback)
        else:
            current_date = date.today()
            start_date = current_date - timedelta(weeks=weeks_lookback)

        results = []
        for worker in sorted(self._workers, key=lambda w: w.name):
            stats = WorkerStats(name=worker.name)

            if worker.name in self._history:
                for month_year in self._history[worker.name]:
                    try:
                        y, m = map(int, month_year.split('-'))
                    except ValueError:
                        continue

                    holidays = set(compute_holidays(y, m))

                    for ass in self._history[worker.name][month_year]:
                        ass_date_str = ass.get('date')
                        if not ass_date_str:
                            continue

                        ass_date = datetime.fromisoformat(ass_date_str).date()
                        if ass_date < start_date or ass_date > current_date:
                            continue

                        shift = ass.get('shift', '')
                        dur = ass.get('dur', 0)
                        weekday = ass_date.weekday()
                        is_holiday = ass_date.day in holidays
                        is_weekend_hol = weekday >= 5 or is_holiday
                        is_day = shift in ['M1', 'M2']
                        is_night = shift == 'N'

                        stats.total_hours += dur
                        if is_day:
                            stats.day_shifts += 1
                        if is_night:
                            stats.night_shifts += 1
                        if is_weekend_hol:
                            stats.weekend_holiday_shifts += 1
                        if weekday == 5:
                            if is_night:
                                stats.sat_night += 1
                            if is_day:
                                stats.sat_day += 1
                        if weekday == 6 or is_holiday:
                            if is_night:
                                stats.sun_holiday_night += 1
                            if is_day:
                                stats.sun_holiday_day += 1
                        if weekday == 4 and is_night:
                            stats.fri_night += 1

            results.append(stats)

        return results

    def get_equity_totals(self) -> dict[str, list[int]]:
        """Get combined equity totals (past + current) for all workers.

        Returns:
            Dict mapping stat name to list of totals per worker
        """
        if not self._current_stats or self._past_stats is None:
            return {}

        worker_names = [w.name for w in self._workers]
        result = {}

        for stat in EQUITY_STATS:
            totals = [
                self._past_stats[worker_names[i]][stat] + self._current_stats[stat][i]
                for i in range(len(self._workers))
            ]
            result[stat] = totals

        return result

    # =========================================================================
    # History Management
    # =========================================================================

    @property
    def history(self) -> dict:
        """Get the full history dictionary."""
        return self._history

    def load_history(self, file_path: str) -> bool:
        """Load history from a JSON file.

        Args:
            file_path: Path to the JSON file

        Returns:
            True if loaded successfully, False otherwise
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                loaded_history = json.load(f)

            # Merge loaded data
            for worker, worker_data in loaded_history.items():
                if worker not in self._history:
                    self._history[worker] = {}

                for month_year, assignments in worker_data.items():
                    if month_year not in self._history[worker]:
                        self._history[worker][month_year] = []

                    existing = {(ass['date'], ass['shift'])
                                for ass in self._history[worker][month_year]}

                    for ass in assignments:
                        key = (ass['date'], ass['shift'])
                        if key not in existing:
                            self._history[worker][month_year].append(ass)

            logger.info(f"History loaded from {file_path}")
            return True

        except json.JSONDecodeError:
            logger.error(f"Invalid JSON in {file_path}")
            return False
        except Exception as e:
            logger.error(f"Failed to load history: {e}")
            return False

    def save_history(self, file_path: str) -> bool:
        """Save history to a JSON file.

        Args:
            file_path: Path to save the JSON file

        Returns:
            True if saved successfully, False otherwise
        """
        if not self._history:
            logger.warning("No history to save")
            return False

        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(self._history, f, indent=4, default=str)
            logger.info(f"History saved to {file_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save history: {e}")
            return False

    def clear_history(self) -> None:
        """Clear all history data."""
        self._history.clear()
        self._current_stats = None
        self._past_stats = None
        logger.info("History cleared")

    # =========================================================================
    # Data Import
    # =========================================================================

    def import_workers_from_csv(self, file_path: str) -> int:
        """Import workers from a CSV file.

        Args:
            file_path: Path to CSV file (one name per line)

        Returns:
            Number of workers added
        """
        import csv

        added = 0
        try:
            with open(file_path, 'r') as f:
                reader = csv.reader(f)
                for row in reader:
                    if row:
                        name = row[0].strip()
                        if name and not any(w.name == name for w in self._workers):
                            self.add_worker(name)
                            added += 1
            logger.info(f"Imported {added} workers from {file_path}")
        except Exception as e:
            logger.error(f"Failed to import workers: {e}")

        return added

    def import_holidays_from_csv(self, file_path: str) -> int:
        """Import holidays from a CSV file.

        Args:
            file_path: Path to CSV file (one day number per line)

        Returns:
            Number of holidays added
        """
        import csv

        added = 0
        try:
            with open(file_path, 'r') as f:
                reader = csv.reader(f)
                for row in reader:
                    if row:
                        try:
                            day = int(row[0])
                            if self.add_manual_holiday(day):
                                added += 1
                        except ValueError:
                            continue
            logger.info(f"Imported {added} holidays from {file_path}")
        except Exception as e:
            logger.error(f"Failed to import holidays: {e}")

        return added
