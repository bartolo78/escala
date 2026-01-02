"""History access adapter.

The application stores history as:
  history[worker_name]["YYYY-MM"] -> list[{date, shift, dur, ...}]

This module provides read/query helpers so scheduling logic doesn't have to know
about that schema everywhere.

Behavior is intentionally aligned with prior logic_g4.py helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple


Assignment = Dict[str, Any]
History = Dict[str, Dict[str, List[Assignment]]]


@dataclass(frozen=True)
class HistoryView:
    history: History

    def iter_assignments(self) -> Iterator[Tuple[str, str, Assignment]]:
        for worker_name, months in (self.history or {}).items():
            if not isinstance(months, dict):
                continue
            for month_key, ass_list in months.items():
                if not isinstance(ass_list, list):
                    continue
                for ass in ass_list:
                    if isinstance(ass, dict):
                        yield worker_name, month_key, ass

    def scheduled_iso_weeks(self) -> set[Tuple[int, int]]:
        """ISO weeks that have any assignment in history."""
        scheduled: set[Tuple[int, int]] = set()
        for _worker, _month, ass in self.iter_assignments():
            d_str = ass.get("date")
            if not d_str:
                continue
            try:
                d = date.fromisoformat(d_str)
            except (ValueError, TypeError):
                continue
            iso = d.isocalendar()
            scheduled.add((iso[0], iso[1]))
        return scheduled

    def fixed_shift_for(self, worker_name: str, day: date) -> Optional[str]:
        """Return shift type if the worker has a historical assignment for this day."""
        month_key = day.strftime("%Y-%m")
        day_str = str(day)
        for ass in (self.history or {}).get(worker_name, {}).get(month_key, []) or []:
            if not isinstance(ass, dict):
                continue
            if ass.get("date") == day_str:
                sh = ass.get("shift")
                return sh if isinstance(sh, str) else None
        return None

    def assignments_by_date(self) -> Dict[str, List[Dict[str, Any]]]:
        """Return mapping date_str -> list[{worker, shift, dur}]."""
        by_date: Dict[str, List[Dict[str, Any]]] = {}
        for worker_name, _month, ass in self.iter_assignments():
            d_str = ass.get("date")
            sh = ass.get("shift")
            if not d_str or not sh:
                continue
            by_date.setdefault(d_str, []).append(
                {
                    "worker": worker_name,
                    "shift": sh,
                    "dur": ass.get("dur", 0),
                }
            )
        return by_date
