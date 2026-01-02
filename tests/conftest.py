"""
Pytest fixtures and configuration for Shift Scheduler tests.
"""

import pytest
import sys
import os
from datetime import date

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def sample_workers():
    """Provide sample worker data for tests."""
    return [
        {"name": "Alice", "id": "ID001", "color": "#ff0000", "can_night": True, "weekly_load": 18},
        {"name": "Bob", "id": "ID002", "color": "#00ff00", "can_night": True, "weekly_load": 18},
        {"name": "Carol", "id": "ID003", "color": "#0000ff", "can_night": False, "weekly_load": 12},
    ]


@pytest.fixture
def sample_history():
    """Provide sample history data for tests."""
    return {
        "Alice": {
            "2026-01": [
                {"date": "2026-01-05", "shift": "M1", "dur": 12},
                {"date": "2026-01-10", "shift": "N", "dur": 12},
            ]
        },
        "Bob": {
            "2026-01": [
                {"date": "2026-01-06", "shift": "M2", "dur": 15},
            ]
        }
    }


@pytest.fixture
def sample_unavail():
    """Provide sample unavailability data for tests."""
    return {
        "Alice": ["2026-01-15", "2026-01-16 M1"],
        "Bob": ["2026-01-20 to 2026-01-22"],
        "Carol": [],
    }


@pytest.fixture
def sample_required():
    """Provide sample required shift data for tests."""
    return {
        "Alice": [],
        "Bob": ["2026-01-25 N"],
        "Carol": [],
    }


@pytest.fixture
def january_2026_days():
    """Provide list of days for January 2026."""
    return [date(2026, 1, d) for d in range(1, 32)]


@pytest.fixture
def empty_history():
    """Provide empty history dict."""
    return {}


@pytest.fixture
def empty_unavail(sample_workers):
    """Provide empty unavailability dict for sample workers."""
    return {w['name']: [] for w in sample_workers}


@pytest.fixture
def empty_required(sample_workers):
    """Provide empty required shift dict for sample workers."""
    return {w['name']: [] for w in sample_workers}
