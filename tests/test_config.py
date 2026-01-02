"""
Tests for config file loading and saving
"""

import pytest
import tempfile
import os
import yaml
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestConfigLoading:
    """Tests for configuration file operations."""

    def test_yaml_worker_structure(self):
        """Worker YAML structure should be valid."""
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config.yaml"
        )
        
        if not os.path.exists(config_path):
            pytest.skip("config.yaml not found")
        
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        assert 'workers' in config
        assert isinstance(config['workers'], list)
        assert len(config['workers']) > 0

    def test_worker_has_required_fields(self):
        """Each worker should have required fields."""
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config.yaml"
        )
        
        if not os.path.exists(config_path):
            pytest.skip("config.yaml not found")
        
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        for worker in config['workers']:
            assert 'name' in worker, "Worker missing 'name'"
            # Optional fields that should have defaults
            # can_night, weekly_load, id, color

    def test_thresholds_structure(self):
        """Thresholds section should have valid structure."""
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config.yaml"
        )
        
        if not os.path.exists(config_path):
            pytest.skip("config.yaml not found")
        
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        if 'thresholds' in config:
            assert isinstance(config['thresholds'], dict)
            for key, value in config['thresholds'].items():
                assert isinstance(value, (int, float)), f"Threshold {key} should be numeric"

    def test_config_roundtrip(self):
        """Config should survive save/load cycle."""
        test_config = {
            'workers': [
                {'name': 'Test Worker', 'can_night': True, 'weekly_load': 18}
            ],
            'thresholds': {'weekend_shifts': 2}
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(test_config, f)
            temp_path = f.name
        
        try:
            with open(temp_path, 'r') as f:
                loaded = yaml.safe_load(f)
            
            assert loaded['workers'][0]['name'] == 'Test Worker'
            assert loaded['thresholds']['weekend_shifts'] == 2
        finally:
            os.unlink(temp_path)
