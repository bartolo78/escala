"""
Tests for SchedulerService - the business logic layer.

These tests cover:
- Worker management (add, remove, list)
- Availability management (unavailable/required shifts)
- Holiday management
- Settings management
- Schedule generation
- History management
- Statistics and reporting
"""

import pytest
import os
import json
import tempfile
from datetime import date

from scheduler_service import (
    SchedulerService,
    Worker,
    ScheduleResult,
    WorkerStats,
    ImbalanceAlert,
)


class TestWorkerDataclass:
    """Tests for the Worker dataclass."""

    def test_worker_defaults(self):
        """Worker should have sensible defaults."""
        worker = Worker(name="Test", id="ID001")
        assert worker.name == "Test"
        assert worker.id == "ID001"
        assert worker.can_night is True
        assert worker.weekly_load == 18
        assert worker.color == "#000000"

    def test_worker_to_dict(self):
        """Worker.to_dict should return correct dictionary."""
        worker = Worker(name="Alice", id="ID001", color="#ff0000", can_night=False, weekly_load=12)
        d = worker.to_dict()
        assert d["name"] == "Alice"
        assert d["id"] == "ID001"
        assert d["color"] == "#ff0000"
        assert d["can_night"] is False
        assert d["weekly_load"] == 12

    def test_worker_from_dict(self):
        """Worker.from_dict should create correct worker."""
        data = {"name": "Bob", "id": "ID002", "color": "#00ff00", "can_night": True, "weekly_load": 18}
        worker = Worker.from_dict(data)
        assert worker.name == "Bob"
        assert worker.id == "ID002"
        assert worker.color == "#00ff00"
        assert worker.can_night is True
        assert worker.weekly_load == 18

    def test_worker_from_dict_with_missing_fields(self):
        """Worker.from_dict should use defaults for missing fields."""
        data = {"name": "Carol"}
        worker = Worker.from_dict(data)
        assert worker.name == "Carol"
        assert worker.id == "ID000"  # Default
        assert worker.can_night is True
        assert worker.weekly_load == 18


class TestScheduleResultDataclass:
    """Tests for the ScheduleResult dataclass."""

    def test_success_result(self):
        """ScheduleResult with schedule is feasible."""
        result = ScheduleResult(success=True, schedule={"2026-01-05": {"M1": "Alice"}})
        assert result.is_feasible is True

    def test_empty_schedule_not_feasible(self):
        """ScheduleResult with empty schedule is not feasible."""
        result = ScheduleResult(success=True, schedule={})
        assert result.is_feasible is False

    def test_failed_result_not_feasible(self):
        """ScheduleResult with success=False is not feasible."""
        result = ScheduleResult(success=False, schedule={"2026-01-05": {"M1": "Alice"}})
        assert result.is_feasible is False


class TestWorkerStats:
    """Tests for the WorkerStats dataclass."""

    def test_worker_stats_defaults(self):
        """WorkerStats should initialize with zero values."""
        stats = WorkerStats(name="Alice")
        assert stats.name == "Alice"
        assert stats.total_hours == 0
        assert stats.day_shifts == 0
        assert stats.night_shifts == 0
        assert stats.weekend_holiday_shifts == 0
        assert stats.sat_night == 0
        assert stats.sat_day == 0
        assert stats.sun_holiday_night == 0
        assert stats.sun_holiday_day == 0
        assert stats.fri_night == 0


class TestSchedulerServiceInit:
    """Tests for SchedulerService initialization."""

    def test_default_initialization(self):
        """Service should initialize with default workers."""
        service = SchedulerService()
        assert len(service.workers) == 15  # Default 15 workers
        assert len(service.worker_names) == 15

    def test_custom_config_path_nonexistent(self):
        """Service should handle non-existent config gracefully."""
        service = SchedulerService(config_path="/nonexistent/path.yaml")
        assert len(service.workers) == 15  # Falls back to defaults


class TestWorkerManagement:
    """Tests for worker CRUD operations."""

    @pytest.fixture
    def service(self):
        """Create a fresh service with default workers."""
        return SchedulerService()

    def test_workers_property_returns_copy(self, service):
        """Workers property should return a copy."""
        workers = service.workers
        workers.clear()
        assert len(service.workers) == 15  # Original unchanged

    def test_worker_names_property(self, service):
        """Worker names should include all workers."""
        names = service.worker_names
        assert "Tome" in names
        assert "Rosa" in names
        assert len(names) == 15

    def test_get_worker_exists(self, service):
        """get_worker should return worker if exists."""
        worker = service.get_worker("Tome")
        assert worker is not None
        assert worker.name == "Tome"

    def test_get_worker_not_exists(self, service):
        """get_worker should return None if not exists."""
        worker = service.get_worker("NonExistent")
        assert worker is None

    def test_add_worker(self, service):
        """add_worker should create a new worker."""
        worker = service.add_worker("NewWorker", can_night=False, weekly_load=12, color="#123456")
        assert worker.name == "NewWorker"
        assert worker.can_night is False
        assert worker.weekly_load == 12
        assert worker.color == "#123456"
        assert len(service.workers) == 16
        assert "NewWorker" in service.worker_names

    def test_add_worker_duplicate_raises(self, service):
        """add_worker should raise ValueError for duplicate name."""
        with pytest.raises(ValueError, match="already exists"):
            service.add_worker("Tome")  # Already exists

    def test_add_worker_auto_increments_id(self, service):
        """add_worker should auto-increment worker ID."""
        w1 = service.add_worker("Worker16")
        w2 = service.add_worker("Worker17")
        assert w1.id == "ID016"
        assert w2.id == "ID017"

    def test_remove_worker_exists(self, service):
        """remove_worker should return True and remove the worker."""
        result = service.remove_worker("Tome")
        assert result is True
        assert "Tome" not in service.worker_names
        assert len(service.workers) == 14

    def test_remove_worker_not_exists(self, service):
        """remove_worker should return False for non-existent worker."""
        result = service.remove_worker("NonExistent")
        assert result is False
        assert len(service.workers) == 15


class TestAvailabilityManagement:
    """Tests for unavailable/required shift management."""

    @pytest.fixture
    def service(self):
        return SchedulerService()

    def test_get_unavailable_empty(self, service):
        """get_unavailable should return empty list for worker."""
        unavail = service.get_unavailable("Tome")
        assert unavail == []

    def test_add_unavailable(self, service):
        """add_unavailable should add entry."""
        result = service.add_unavailable("Tome", "2026-01-15")
        assert result is True
        assert "2026-01-15" in service.get_unavailable("Tome")

    def test_add_unavailable_with_shift(self, service):
        """add_unavailable should accept date with shift."""
        result = service.add_unavailable("Tome", "2026-01-15 M1")
        assert result is True
        assert "2026-01-15 M1" in service.get_unavailable("Tome")

    def test_add_unavailable_duplicate(self, service):
        """add_unavailable should return False for duplicate."""
        service.add_unavailable("Tome", "2026-01-15")
        result = service.add_unavailable("Tome", "2026-01-15")
        assert result is False

    def test_add_unavailable_nonexistent_worker(self, service):
        """add_unavailable should return False for non-existent worker."""
        result = service.add_unavailable("NonExistent", "2026-01-15")
        assert result is False

    def test_add_required(self, service):
        """add_required should add entry."""
        result = service.add_required("Tome", "2026-01-20 N")
        assert result is True
        assert "2026-01-20 N" in service.get_required("Tome")

    def test_remove_unavailable(self, service):
        """remove_unavailable should remove entry by index."""
        service.add_unavailable("Tome", "2026-01-15")
        service.add_unavailable("Tome", "2026-01-16")
        result = service.remove_unavailable("Tome", 0)
        assert result is True
        unavail = service.get_unavailable("Tome")
        assert "2026-01-15" not in unavail
        assert "2026-01-16" in unavail

    def test_remove_unavailable_invalid_index(self, service):
        """remove_unavailable should return False for invalid index."""
        result = service.remove_unavailable("Tome", 0)  # Empty list
        assert result is False

    def test_remove_required(self, service):
        """remove_required should remove entry by index."""
        service.add_required("Tome", "2026-01-20 N")
        result = service.remove_required("Tome", 0)
        assert result is True
        assert service.get_required("Tome") == []


class TestHolidayManagement:
    """Tests for holiday management."""

    @pytest.fixture
    def service(self):
        return SchedulerService()

    def test_manual_holidays_initially_empty(self, service):
        """manual_holidays should start empty."""
        assert service.manual_holidays == []

    def test_add_manual_holiday(self, service):
        """add_manual_holiday should add day."""
        result = service.add_manual_holiday(15)
        assert result is True
        assert 15 in service.manual_holidays

    def test_add_manual_holiday_duplicate(self, service):
        """add_manual_holiday should return False for duplicate."""
        service.add_manual_holiday(15)
        result = service.add_manual_holiday(15)
        assert result is False

    def test_clear_manual_holidays(self, service):
        """clear_manual_holidays should remove all."""
        service.add_manual_holiday(15)
        service.add_manual_holiday(20)
        service.clear_manual_holidays()
        assert service.manual_holidays == []

    def test_get_holidays_combines_auto_and_manual(self, service):
        """get_holidays should combine auto and manual holidays."""
        service.add_manual_holiday(15)
        holidays = service.get_holidays(2026, 1)  # January 2026
        assert 1 in holidays  # New Year's Day (auto)
        assert 15 in holidays  # Manual
        assert holidays == sorted(holidays)  # Should be sorted

    def test_manual_holidays_returns_copy(self, service):
        """manual_holidays property should return a copy."""
        service.add_manual_holiday(15)
        holidays = service.manual_holidays
        holidays.clear()
        assert 15 in service.manual_holidays  # Original unchanged


class TestSettingsManagement:
    """Tests for settings/weights management."""

    @pytest.fixture
    def service(self):
        return SchedulerService()

    def test_equity_weights_default(self, service):
        """equity_weights should have defaults."""
        weights = service.equity_weights
        assert isinstance(weights, dict)
        assert len(weights) > 0

    def test_set_equity_weight(self, service):
        """set_equity_weight should update value."""
        service.set_equity_weight("weekend_shifts", 5.0)
        assert service.equity_weights["weekend_shifts"] == 5.0

    def test_dow_equity_weight(self, service):
        """dow_equity_weight getter/setter should work."""
        original = service.dow_equity_weight
        service.dow_equity_weight = 10.0
        assert service.dow_equity_weight == 10.0
        assert service.dow_equity_weight != original

    def test_lexicographic_mode(self, service):
        """lexicographic_mode getter/setter should work."""
        assert service.lexicographic_mode is True  # Default
        service.lexicographic_mode = False
        assert service.lexicographic_mode is False

    def test_thresholds_default(self, service):
        """thresholds should have defaults."""
        thresholds = service.thresholds
        assert isinstance(thresholds, dict)
        assert "weekend_shifts" in thresholds

    def test_set_threshold(self, service):
        """set_threshold should update value."""
        service.set_threshold("weekend_shifts", 10)
        assert service.thresholds["weekend_shifts"] == 10


class TestScheduleGeneration:
    """Tests for schedule generation."""

    @pytest.fixture
    def service(self):
        return SchedulerService()

    def test_generate_returns_schedule_result(self, service):
        """generate should return a ScheduleResult."""
        result = service.generate(2026, 1)
        assert isinstance(result, ScheduleResult)

    def test_generate_success_has_schedule(self, service):
        """Successful generation should have schedule data."""
        result = service.generate(2026, 1)
        if result.success:
            assert isinstance(result.schedule, dict)
            assert len(result.schedule) > 0

    def test_generate_success_has_assignments(self, service):
        """Successful generation should have assignments."""
        result = service.generate(2026, 1)
        if result.success:
            assert isinstance(result.assignments, list)
            assert len(result.assignments) > 0

    def test_generate_updates_history(self, service):
        """Successful generation should update history."""
        initial_history = len(service.history)
        result = service.generate(2026, 1)
        if result.success:
            assert len(service.history) > 0


class TestHistoryManagement:
    """Tests for history persistence."""

    @pytest.fixture
    def service(self):
        return SchedulerService()

    @pytest.fixture
    def temp_file(self):
        """Create a temporary file for testing."""
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        yield path
        if os.path.exists(path):
            os.remove(path)

    def test_history_initially_empty(self, service):
        """history should start empty."""
        assert service.history == {}

    def test_save_history_empty_returns_false(self, service, temp_file):
        """save_history should return False for empty history."""
        result = service.save_history(temp_file)
        assert result is False

    def test_save_and_load_history(self, service, temp_file):
        """save_history and load_history should round-trip."""
        # Generate a schedule to create history
        service.generate(2026, 1)
        if service.history:
            result = service.save_history(temp_file)
            assert result is True

            # Clear and reload
            original_history = dict(service.history)
            service.clear_history()
            assert service.history == {}

            result = service.load_history(temp_file)
            assert result is True
            assert len(service.history) > 0

    def test_load_history_invalid_json(self, service, temp_file):
        """load_history should return False for invalid JSON."""
        with open(temp_file, 'w') as f:
            f.write("not valid json {{{")
        result = service.load_history(temp_file)
        assert result is False

    def test_load_history_nonexistent_file(self, service):
        """load_history should return False for non-existent file."""
        result = service.load_history("/nonexistent/file.json")
        assert result is False

    def test_clear_history(self, service):
        """clear_history should remove all data."""
        service.generate(2026, 1)
        service.clear_history()
        assert service.history == {}


class TestStatistics:
    """Tests for statistics and reporting."""

    @pytest.fixture
    def service_with_history(self):
        """Create service with some history data."""
        service = SchedulerService()
        # Manually add some history for testing
        service._history = {
            "Tome": {
                "2026-01": [
                    {"date": "2026-01-05", "shift": "M1", "dur": 12},  # Monday
                    {"date": "2026-01-10", "shift": "N", "dur": 12},   # Saturday
                    {"date": "2026-01-11", "shift": "M2", "dur": 15},  # Sunday
                ]
            },
            "Rosa": {
                "2026-01": [
                    {"date": "2026-01-06", "shift": "M2", "dur": 15},  # Tuesday
                ]
            }
        }
        return service

    def test_get_worker_stats_empty_history(self):
        """get_worker_stats should return zeros for no history."""
        service = SchedulerService()
        stats = service.get_worker_stats("Tome")
        assert stats.name == "Tome"
        assert stats.total_hours == 0

    def test_get_worker_stats_with_history(self, service_with_history):
        """get_worker_stats should compute correctly."""
        stats = service_with_history.get_worker_stats("Tome")
        assert stats.name == "Tome"
        assert stats.total_hours == 39  # 12 + 12 + 15

    def test_get_worker_stats_counts_night_shifts(self, service_with_history):
        """get_worker_stats should count night shifts."""
        stats = service_with_history.get_worker_stats("Tome")
        assert stats.night_shifts == 1  # Jan 10 is N shift

    def test_get_worker_stats_counts_day_shifts(self, service_with_history):
        """get_worker_stats should count day shifts."""
        stats = service_with_history.get_worker_stats("Tome")
        assert stats.day_shifts == 2  # M1 and M2

    def test_generate_all_worker_stats(self, service_with_history):
        """generate_all_worker_stats should return stats for all workers."""
        all_stats = service_with_history.generate_all_worker_stats()
        assert len(all_stats) == 15  # All 15 workers
        names = [s.name for s in all_stats]
        assert "Tome" in names
        assert "Rosa" in names


class TestConfigPersistence:
    """Tests for configuration persistence."""

    @pytest.fixture
    def temp_config(self):
        """Create a temporary config file."""
        fd, path = tempfile.mkstemp(suffix=".yaml")
        os.close(fd)
        yield path
        if os.path.exists(path):
            os.remove(path)

    def test_save_config(self, temp_config):
        """save_config should write configuration to file."""
        service = SchedulerService(config_path=temp_config)
        service.add_worker("TestWorker")
        result = service.save_config()
        assert result is True
        assert os.path.exists(temp_config)

        # Verify content
        import yaml
        with open(temp_config, 'r') as f:
            config = yaml.safe_load(f)
        assert 'workers' in config
        assert any(w['name'] == 'TestWorker' for w in config['workers'])


class TestImbalanceDetection:
    """Tests for equity imbalance detection."""

    def test_check_imbalances_no_stats(self):
        """check_imbalances should return empty list without stats."""
        service = SchedulerService()
        alerts = service.check_imbalances()
        assert alerts == []

    def test_imbalance_alert_dataclass(self):
        """ImbalanceAlert should have correct structure."""
        alert = ImbalanceAlert(
            stat="weekend_shifts",
            imbalance=5,
            threshold=2,
            message="weekend_shifts: imbalance 5 > 2"
        )
        assert alert.stat == "weekend_shifts"
        assert alert.imbalance == 5
        assert alert.threshold == 2
