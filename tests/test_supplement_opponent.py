import pytest
import pandas as pd
from src.features.opponent_context import compute_team_game_stats_extended, compute_opponent_p0_features

def test_team_game_stats_extended():
    # 2 teams in the same game
    team_logs = pd.DataFrame([
        {
            "game_id": "001",
            "game_date": "2024-11-01",
            "team_abbreviation": "CLE",
            "pts": 110,
            "fga": 85,
            "fta": 20,
            "oreb": 10,
            "dreb": 32,
            "tov": 12,
            "ast": 25,
            "fg3a": 30,
        },
        {
            "game_id": "001",
            "game_date": "2024-11-01",
            "team_abbreviation": "ORL",
            "pts": 100,
            "fga": 88,
            "fta": 18,
            "oreb": 8,
            "dreb": 30,
            "tov": 14,
            "ast": 20,
            "fg3a": 28,
        },
    ])
    
    ext = compute_team_game_stats_extended(team_logs)
    cle = ext[ext["team_abbreviation"] == "CLE"].iloc[0]
    
    # CLE allowed points is ORL pts (100)
    assert cle["pts_allowed"] == 100
    assert cle["ast_allowed"] == 20
    assert cle["opp_oreb"] == 8
    assert cle["possessions"] > 80

def test_opponent_p0_rolling_features():
    # Construct team logs across 3 games
    team_logs = pd.DataFrame([
        # Game 1: Nov 1 (ORL vs MIA)
        {"game_id": "001", "game_date": "2024-11-01", "team_abbreviation": "ORL", "pts": 100, "fga": 85, "fta": 20, "oreb": 10, "dreb": 30, "tov": 12, "ast": 20, "fg3a": 30},
        {"game_id": "001", "game_date": "2024-11-01", "team_abbreviation": "MIA", "pts": 95, "fga": 80, "fta": 18, "oreb": 8, "dreb": 32, "tov": 14, "ast": 22, "fg3a": 28},
        # Game 2: Nov 3 (CLE vs ORL)
        {"game_id": "002", "game_date": "2024-11-03", "team_abbreviation": "CLE", "pts": 115, "fga": 90, "fta": 25, "oreb": 12, "dreb": 35, "tov": 10, "ast": 28, "fg3a": 35},
        {"game_id": "002", "game_date": "2024-11-03", "team_abbreviation": "ORL", "pts": 105, "fga": 88, "fta": 22, "oreb": 9, "dreb": 31, "tov": 13, "ast": 24, "fg3a": 32},
    ])
    
    player_df = pd.DataFrame([
        {"player_id": 1, "game_id": "002", "game_date": "2024-11-03", "team_abbreviation": "CLE", "opponent_abbr": "ORL"},
    ])
    
    res = compute_opponent_p0_features(player_df, team_logs, window=10)
    row = res.iloc[0]
    
    # For CLE player facing ORL at Game 2 (Nov 3):
    # ORL's prior game was Game 1 (Nov 1): ORL allowed 95 pts to MIA!
    assert "opp_def_rating_prev10" in row
    assert "opp_pace_prev10" in row
    assert "opp_allowed_ast_per100_prev10" in row
    assert "opp_dreb_share_prev10" in row
    assert row["opp_sample_games"] == 1
    assert row["opp_feature_missing"] == 0
