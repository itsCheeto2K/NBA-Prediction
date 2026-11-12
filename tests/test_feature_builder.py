import pytest
import pandas as pd
from src.features.builder import build_feature_dataset

def test_feature_builder_pipeline():
    # Sample player game logs with multiple games
    df_players = pd.DataFrame([
        {
            "season": "2024-25",
            "game_id": "0022400001",
            "player_id": 1628378,
            "player_name": "Donovan Mitchell",
            "team_id": 1610612739,
            "team_abbreviation": "CLE",
            "game_date": "2024-10-23",
            "matchup": "CLE @ TOR",
            "wl": "W",
            "min": 28.0,
            "pts": 21,
            "reb": 2,
            "ast": 3,
            "fga": 14,
            "fta": 2,
            "fg3a": 5,
        },
        {
            "season": "2024-25",
            "game_id": "0022400002",
            "player_id": 1628378,
            "player_name": "Donovan Mitchell",
            "team_id": 1610612739,
            "team_abbreviation": "CLE",
            "game_date": "2024-10-25",
            "matchup": "CLE vs. DET",
            "wl": "W",
            "min": 35.0,
            "pts": 30,
            "reb": 4,
            "ast": 5,
            "fga": 18,
            "fta": 4,
            "fg3a": 8,
        },
        {
            "season": "2024-25",
            "game_id": "0022400003",
            "player_id": 1628378,
            "player_name": "Donovan Mitchell",
            "team_id": 1610612739,
            "team_abbreviation": "CLE",
            "game_date": "2024-10-26",
            "matchup": "CLE @ WAS",
            "wl": "W",
            "min": 30.0,
            "pts": 28,
            "reb": 5,
            "ast": 4,
            "fga": 16,
            "fta": 6,
            "fg3a": 7,
        },
    ])
    
    features_df = build_feature_dataset(df_players, team_logs_df=None)
    
    assert not features_df.empty
    assert len(features_df) == 3
    
    # Check context columns
    assert "is_home" in features_df.columns
    assert "is_b2b" in features_df.columns
    assert features_df.iloc[1]["is_home"] == 1
    assert features_df.iloc[2]["is_b2b"] == 1  # Oct 25 -> Oct 26
    
    # Check rolling columns
    assert "pts_roll_mean_5" in features_df.columns
    assert "ast_roll_mean_5" in features_df.columns
    
    # Check shrinkage columns
    assert "pts_rate_shrinkage" in features_df.columns
    assert "reb_rate_shrinkage" in features_df.columns
    assert "ast_rate_shrinkage" in features_df.columns
    
    # Check data quality flags
    assert "insufficient_data" in features_df.columns
    assert bool(features_df.iloc[0]["insufficient_data"]) is True  # history < 5
