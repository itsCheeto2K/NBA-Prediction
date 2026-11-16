import pytest
import pandas as pd
from pathlib import Path
from src.storage.manifest import CheckpointManager
from src.pipeline.backfill import audit_backfill_completeness

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


def test_audit_backfill_completeness_ignores_preseason():
    # Schedule with 1 preseason game (001...) and 1 regular season game (002...)
    sched = pd.DataFrame([
        {"game_id": "0012400001", "game_status_text": "Final", "home_team_id": 1, "away_team_id": 2},
        {"game_id": "0022400001", "game_status_text": "Final", "home_team_id": 1, "away_team_id": 2},
    ])
    # Team logs only contain regular season game 0022400001
    teams = pd.DataFrame([
        {"game_id": "0022400001", "team_id": 1},
        {"game_id": "0022400001", "team_id": 2},
    ])
    players = pd.DataFrame([
        {"game_id": "0022400001", "player_id": 101},
        {"game_id": "0022400001", "player_id": 102},
    ])
    res = audit_backfill_completeness(sched, teams, players)
    assert res["status"] == "COMPLETE"
    assert res["expected_completed_games"] == 1
    assert len(res["missing_game_ids"]) == 0


def test_audit_backfill_completeness_detects_wrong_team_ids():
    # Schedule has teams 1 and 2
    sched = pd.DataFrame([
        {"game_id": "0022400001", "game_status_text": "Final", "home_team_id": 1, "away_team_id": 2},
    ])
    # Team logs has team 1 and rogue team 99
    teams = pd.DataFrame([
        {"game_id": "0022400001", "team_id": 1},
        {"game_id": "0022400001", "team_id": 99},
    ])
    players = pd.DataFrame([
        {"game_id": "0022400001", "player_id": 101},
    ])
    res = audit_backfill_completeness(sched, teams, players)
    assert res["status"] == "PARTIAL"
    assert "0022400001" in res["mismatched_team_row_games"]


def test_audit_backfill_completeness_fails_on_duplicate_rows():
    sched = pd.DataFrame([
        {"game_id": "0022400001", "game_status_text": "Final", "home_team_id": 1, "away_team_id": 2},
    ])
    # Team logs has duplicate team 1
    teams_dup = pd.DataFrame([
        {"game_id": "0022400001", "team_id": 1},
        {"game_id": "0022400001", "team_id": 1},
    ])
    res_team_dup = audit_backfill_completeness(sched, teams_dup)
    assert res_team_dup["status"] == "PARTIAL"
    assert res_team_dup["duplicate_team_rows_count"] == 1

    # Player logs has duplicate player
    teams = pd.DataFrame([
        {"game_id": "0022400001", "team_id": 1},
        {"game_id": "0022400001", "team_id": 2},
    ])
    players_dup = pd.DataFrame([
        {"game_id": "0022400001", "player_id": 101},
        {"game_id": "0022400001", "player_id": 101},
    ])
    res_player_dup = audit_backfill_completeness(sched, teams, players_dup)
    assert res_player_dup["status"] == "PARTIAL"
    assert res_player_dup["duplicate_player_rows_count"] == 1


def test_audit_backfill_completeness_fails_on_missing_player_logs():
    sched = pd.DataFrame([
        {"game_id": "0022400001", "game_status_text": "Final", "home_team_id": 1, "away_team_id": 2},
        {"game_id": "0022400002", "game_status_text": "Final", "home_team_id": 3, "away_team_id": 4},
    ])
    teams = pd.DataFrame([
        {"game_id": "0022400001", "team_id": 1},
        {"game_id": "0022400001", "team_id": 2},
        {"game_id": "0022400002", "team_id": 3},
        {"game_id": "0022400002", "team_id": 4},
    ])
    # Players only present for game 0022400001, missing game 0022400002
    players = pd.DataFrame([
        {"game_id": "0022400001", "player_id": 101},
    ])
    res = audit_backfill_completeness(sched, teams, players)
    assert res["status"] == "PARTIAL"
    assert "0022400002" in res["missing_player_log_games"]

