"""Tests for input validation and error handling improvements."""

from datetime import date
import pytest
from scheduling_engine import (
    parse_unavail_or_req,
    update_history,
    generate_schedule,
)


class TestParseUnavailValidation:
    """Test validation improvements in parse_unavail_or_req."""
    
    def test_invalid_shift_type_logged(self, caplog):
        """Invalid shift types should be logged, not silently ignored."""
        result = parse_unavail_or_req(["2026-01-15 INVALID"])
        # Should not be in result
        assert (date(2026, 1, 15), "INVALID") not in result
        # Should be logged as warning
        assert "Invalid shift type 'INVALID'" in caplog.text
    
    def test_invalid_date_format_logged(self, caplog):
        """Invalid date formats should be logged."""
        result = parse_unavail_or_req(["not-a-date"])
        assert len(result) == 0
        assert "Failed to parse entry" in caplog.text
    
    def test_invalid_date_range_logged(self, caplog):
        """End date before start date should be logged."""
        result = parse_unavail_or_req(["2026-01-15 to 2026-01-10"])
        assert len(result) == 0
        assert "Invalid date range" in caplog.text or "end date before start date" in caplog.text
    
    def test_valid_entries_still_work(self):
        """Valid entries should still parse correctly."""
        result = parse_unavail_or_req([
            "2026-01-15",
            "2026-01-16 M1",
            "2026-01-20 to 2026-01-22"
        ])
        assert (date(2026, 1, 15), None) in result
        assert (date(2026, 1, 16), "M1") in result
        # 15 (date only), 16 M1, 20-22 (3 dates) = 5 total entries
        assert len(result) == 5


class TestUpdateHistoryValidation:
    """Test validation improvements in update_history."""
    
    def test_handles_invalid_assignment_type(self, caplog):
        """Should handle non-dict assignments gracefully."""
        history = {}
        assignments = ["not-a-dict", {"date": "2026-01-15", "worker": "Test"}]
        
        result = update_history(assignments, history)
        
        assert "Skipping invalid assignment (not a dict)" in caplog.text
        assert "Test" in result  # Valid one should be added
    
    def test_handles_missing_keys(self, caplog):
        """Should handle assignments missing required keys."""
        history = {}
        assignments = [
            {"worker": "Test"},  # Missing 'date'
            {"date": "2026-01-15", "worker": "Test"}  # Valid
        ]
        
        result = update_history(assignments, history)
        
        assert "missing required keys" in caplog.text
        assert "Test" in result
    
    def test_handles_invalid_date_format(self, caplog):
        """Should handle invalid date formats gracefully."""
        history = {}
        assignments = [
            {"date": "invalid-date", "worker": "Test", "shift": "M1"}
        ]
        
        result = update_history(assignments, history)
        
        assert "Failed to process assignment" in caplog.text
    
    def test_valid_assignments_still_work(self):
        """Valid assignments should work as before."""
        history = {}
        assignments = [
            {"date": "2026-01-15", "worker": "Worker1", "shift": "M1"},
            {"date": "2026-01-16", "worker": "Worker2", "shift": "N"}
        ]
        
        result = update_history(assignments, history)
        
        assert "Worker1" in result
        assert "Worker2" in result
        assert "2026-01" in result["Worker1"]


class TestGenerateScheduleValidation:
    """Test validation improvements in generate_schedule."""
    
    def test_empty_workers_list(self, caplog):
        """Empty workers list should return error."""
        schedule, weekly, assignments, stats, _ = generate_schedule(
            2026, 1, {}, {}, {}, []
        )
        
        assert schedule == {}
        assert "error" in stats
        assert "No workers provided" in caplog.text
    
    def test_invalid_worker_structure(self, caplog):
        """Invalid worker structure should return error."""
        workers = [{"name": "Test"}]  # Missing 'can_night'
        
        schedule, weekly, assignments, stats, _ = generate_schedule(
            2026, 1, {}, {}, {}, workers
        )
        
        assert schedule == {}
        assert "error" in stats
        assert "missing required key" in caplog.text
    
    def test_worker_not_dict(self, caplog):
        """Non-dict worker should return error."""
        workers = ["not-a-dict"]
        
        schedule, weekly, assignments, stats, _ = generate_schedule(
            2026, 1, {}, {}, {}, workers
        )
        
        assert schedule == {}
        assert "error" in stats
        assert "not a dict" in caplog.text


class TestBoundsChecking:
    """Test bounds checking improvements."""
    
    def test_weekday_bounds_check(self, caplog):
        """Day-of-week indexing should have bounds checking and not crash."""
        # This tests that the bounds check prevents crashes on edge cases
        from scheduling_engine import _compute_past_stats
        
        workers = [{"name": "Test"}]
        history = {
            "Test": {
                "2026-01": [
                    {"date": "2026-01-15", "shift": "M1"}  # Valid Thursday (weekday 3)
                ]
            }
        }
        
        # Should not crash and should increment the correct day
        stats = _compute_past_stats(history, workers)
        assert "Test" in stats
        # January 15, 2026 is a Thursday (weekday index 3)
        assert sum(stats["Test"]["dow"]) == 1  # Total of 1 shift counted
        assert stats["Test"]["dow"][3] == 1  # Thursday counter incremented
