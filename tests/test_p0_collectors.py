import json
import pytest
import pandas as pd
from unittest.mock import MagicMock
from src.collectors.static import get_all_players_df, get_all_teams_df
from src.collectors.schedule import normalize_schedule_df
from src.collectors.gamelogs import parse_minutes_to_float, normalize_player_gamelogs_df
from src.collectors.sync import SyncLeaseLock, get_last_sync_info

def test_static_players_and_teams():
    players_df = get_all_players_df()
    assert not players_df.empty
    assert "player_id" in players_df.columns
    assert "full_name" in players_df.columns
    assert "is_active" in players_df.columns
    # Check LeBron James exists
    lebron = players_df[players_df["full_name"] == "LeBron James"]
    assert not lebron.empty
    assert lebron.iloc[0]["player_id"] == 2544
    
    teams_df = get_all_teams_df()
    assert len(teams_df) == 30
    assert "team_id" in teams_df.columns
    assert "abbreviation" in teams_df.columns
    assert "LAL" in teams_df["abbreviation"].values

def test_parse_minutes_to_float():
    assert parse_minutes_to_float("34:30") == 34.5
    assert parse_minutes_to_float("34:15") == 34.25
    assert parse_minutes_to_float("12:00") == 12.0
    assert parse_minutes_to_float(25.5) == 25.5
    assert parse_minutes_to_float(None) is None
    assert parse_minutes_to_float("") is None
    assert parse_minutes_to_float("DNP") is None

def test_normalize_schedule_df():
    sample_raw = pd.DataFrame([{
        "gameId": 22400061,  # Note int format from raw API sometimes
        "seasonYear": "2024-25",
        "gameDateEst": "2024-11-01T00:00:00Z",
        "gameDateTimeUTC": "2024-11-01T23:00:00Z",
        "homeTeamId": 1610612739,
        "awayTeamId": 1610612753,
        "gameStatus": 3,
        "gameStatusText": "Final"
    }])
    
    normalized = normalize_schedule_df(sample_raw)
    assert normalized.iloc[0]["game_id"] == "0022400061"
    assert isinstance(normalized.iloc[0]["game_id"], str)
    assert normalized.iloc[0]["season"] == "2024-25"
    assert normalized.iloc[0]["home_team_id"] == 1610612739

def test_normalize_player_gamelogs():
    sample_gamelog = pd.DataFrame([{
        "SEASON_YEAR": "2024-25",
        "PLAYER_ID": 1628378,
        "PLAYER_NAME": "Donovan Mitchell",
        "GAME_ID": 22400061,
        "GAME_DATE": "2024-11-01",
        "TEAM_ID": 1610612739,
        "TEAM_ABBREVIATION": "CLE",
        "MATCHUP": "CLE vs. ORL",
        "WL": "W",
        "MIN": "34:12",
        "PTS": 30,
        "REB": 4,
        "AST": 5,
        "FGA": 20,
        "FTA": 6,
        "FG3A": 11
    }])
    
    normalized = normalize_player_gamelogs_df(sample_gamelog)
    assert normalized.iloc[0]["game_id"] == "0022400061"
    assert isinstance(normalized.iloc[0]["game_id"], str)
    assert pytest.approx(normalized.iloc[0]["min"], 0.01) == 34.2
    assert normalized.iloc[0]["pts"] == 30


def test_sync_lease_lock_acquire_heartbeat_release(tmp_path):
    lock_file = tmp_path / "sync_lock.json"
    lock = SyncLeaseLock(lock_file=lock_file, lease_ttl_sec=10.0)
    
    assert lock.is_locked() is False
    assert lock.acquire("run_1") is True
    assert lock.is_locked() is True
    assert lock.is_owner("run_1") is True
    assert lock.is_owner("run_2") is False

    # Second worker cannot acquire
    assert lock.acquire("run_2") is False

    # Same worker can re-acquire
    assert lock.acquire("run_1") is True

    # Release
    lock.release("run_1")
    assert lock.is_locked() is False


def test_sync_status_last_sync_time_fallback(tmp_path, monkeypatch):
    status_file = tmp_path / "sync_status.json"
    import src.collectors.sync as sync_mod
    monkeypatch.setattr(sync_mod, "SYNC_STATUS_FILE", status_file)

    # Legacy record with finished_at but no last_sync_time
    legacy_record = {
        "status": "SUCCESS",
        "started_at": "2026-11-16T10:00:00Z",
        "finished_at": "2026-11-16T10:02:00Z",
    }
    with open(status_file, "w", encoding="utf-8") as f:
        json.dump(legacy_record, f)

    info = get_last_sync_info()
    assert info["status"] == "SUCCESS"
    assert info["last_sync_time"] == "2026-11-16T10:02:00Z"


def test_sync_lease_lock_expired_owner_and_fencing(tmp_path):
    """Verify Issue 23: expired lease returns is_owner=False, and fencing token validation works."""
    import time
    lock_file = tmp_path / "sync_lock_ttl.json"
    lock = SyncLeaseLock(lock_file=lock_file, lease_ttl_sec=0.3)

    assert lock.acquire("worker_1") is True
    token1 = lock.get_fencing_token("worker_1")
    assert token1 is not None
    assert lock.validate_fence("worker_1", fencing_token=token1) is True
    assert lock.validate_fence("worker_1", fencing_token=999999999) is False

    # Stop heartbeat to allow expiration
    if "worker_1" in lock._heartbeat_threads:
        lock._heartbeat_threads["worker_1"].set()

    time.sleep(0.4)
    # Lease is now expired
    assert lock.is_locked() is False
    assert lock.is_owner("worker_1") is False
    assert lock.validate_fence("worker_1", fencing_token=token1) is False

    # Worker 2 acquires new epoch with higher fencing token
    assert lock.acquire("worker_2") is True
    token2 = lock.get_fencing_token("worker_2")
    assert token2 > token1
    assert lock.validate_fence("worker_2", fencing_token=token2) is True
    assert lock.validate_fence("worker_1", fencing_token=token1) is False
    lock.release("worker_2")


