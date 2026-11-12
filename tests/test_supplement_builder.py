import pytest
import pandas as pd
from src.features.builder import build_feature_dataset

def test_builder_includes_all_supplement_features():
    df_players = pd.DataFrame([
        {
            "season": "2024-25",
            "game_id": "001",
            "player_id": 1628378,
            "player_name": "Donovan Mitchell",
            "team_abbreviation": "CLE",
            "game_date": "2024-10-23",
            "matchup": "CLE vs. DET",
            "min": 30.0,
            "pts": 25,
            "reb": 5,
            "ast": 5,
        },
        {
            "season": "2024-25",
            "game_id": "002",
            "player_id": 1628378,
            "player_name": "Donovan Mitchell",
            "team_abbreviation": "CLE",
            "game_date": "2024-10-24",
            "matchup": "CLE @ TOR",
            "min": 32.0,
            "pts": 30,
            "reb": 6,
            "ast": 6,
        },
    ])
    
    df_teams = pd.DataFrame([
        {"game_id": "001", "game_date": "2024-10-23", "team_abbreviation": "CLE", "pts": 110, "fga": 85, "fta": 20, "oreb": 10, "dreb": 30, "tov": 12, "ast": 25, "fg3a": 30},
        {"game_id": "001", "game_date": "2024-10-23", "team_abbreviation": "DET", "pts": 100, "fga": 80, "fta": 18, "oreb": 8, "dreb": 32, "tov": 14, "ast": 20, "fg3a": 28},
        {"game_id": "002", "game_date": "2024-10-24", "team_abbreviation": "CLE", "pts": 115, "fga": 88, "fta": 22, "oreb": 11, "dreb": 33, "tov": 10, "ast": 26, "fg3a": 32},
        {"game_id": "002", "game_date": "2024-10-24", "team_abbreviation": "TOR", "pts": 108, "fga": 85, "fta": 20, "oreb": 9, "dreb": 31, "tov": 13, "ast": 22, "fg3a": 29},
    ])
    
    out = build_feature_dataset(df_players, team_logs_df=df_teams)
    
    # Check new supplement features are present
    assert "team_b2b" in out.columns
    assert "opp_b2b" in out.columns
    assert "rest_advantage_days" in out.columns
    assert "team_3in4" in out.columns
    assert "team_b2b_but_player_rested" in out.columns
    assert "player_minutes_last7days" in out.columns
    assert "opp_def_rating_prev10" in out.columns
    assert "opp_pace_prev10" in out.columns
    assert "opp_allowed_ast_per100_prev10" in out.columns
    assert "opp_dreb_share_prev10" in out.columns
