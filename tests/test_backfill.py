import pytest
import pandas as pd
from pathlib import Path
from src.storage.manifest import CheckpointManager

def test_checkpoint_lifecycle(tmp_path):
    manifest_path = tmp_path / "checkpoints.json"
    mgr = CheckpointManager(manifest_path=manifest_path)
    
    task_key = "playergamelogs_2024-25"
    assert mgr.is_completed(task_key) is False
    
    mgr.mark_in_progress(task_key)
    assert mgr.get_status(task_key) == "IN_PROGRESS"
    
    mgr.mark_completed(task_key, rows_count=15000, metadata={"season": "2024-25"})
    assert mgr.is_completed(task_key) is True
    assert mgr.get_rows_count(task_key) == 15000
    
    # Check persistence by reloading manager
    new_mgr = CheckpointManager(manifest_path=manifest_path)
    assert new_mgr.is_completed(task_key) is True
    assert new_mgr.get_rows_count(task_key) == 15000

def test_checkpoint_failure(tmp_path):
    manifest_path = tmp_path / "checkpoints.json"
    mgr = CheckpointManager(manifest_path=manifest_path)
    task_key = "failing_task"
    
    mgr.mark_failed(task_key, "Network timeout 500")
    assert mgr.is_completed(task_key) is False
    assert mgr.get_status(task_key) == "FAILED"
    assert "Network timeout" in mgr.get_error(task_key)
