import pytest
import pandas as pd
from unittest.mock import MagicMock
from src.collectors.static import get_all_players_df, get_all_teams_df
from src.collectors.schedule import normalize_schedule_df
from src.collectors.gamelogs import parse_minutes_to_float, normalize_player_gamelogs_df

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
