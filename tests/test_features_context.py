import pytest
import pandas as pd
from src.features.context import compute_matchup_context, compute_rest_and_b2b

def test_matchup_context_parsing():
    df = pd.DataFrame([
        {"player_id": 1, "matchup": "CLE vs. ORL"},
        {"player_id": 1, "matchup": "BOS @ MIA"},
        {"player_id": 2, "matchup": "LAL vs GSW"},
    ])
    result = compute_matchup_context(df)
    assert result.iloc[0]["is_home"] == 1
    assert result.iloc[0]["opponent_abbr"] == "ORL"
    assert result.iloc[1]["is_home"] == 0
    assert result.iloc[1]["opponent_abbr"] == "MIA"
    assert result.iloc[2]["is_home"] == 1
    assert result.iloc[2]["opponent_abbr"] == "GSW"

def test_rest_days_and_b2b():
    df = pd.DataFrame([
        {"player_id": 1, "game_date": "2024-11-01", "game_id": "0022400001"},
        {"player_id": 1, "game_date": "2024-11-02", "game_id": "0022400002"},  # Back to back!
        {"player_id": 1, "game_date": "2024-11-05", "game_id": "0022400003"},  # 3 days rest
    ])
    result = compute_rest_and_b2b(df)
    # 1st game: no prior game
    assert result.iloc[0]["is_b2b"] == 0
    assert pd.isna(result.iloc[0]["rest_days"])
    
    # 2nd game: 1 day difference -> is_b2b = 1
    assert result.iloc[1]["rest_days"] == 1
    assert result.iloc[1]["is_b2b"] == 1
    
    # 3rd game: 3 days difference -> is_b2b = 0
    assert result.iloc[2]["rest_days"] == 3
    assert result.iloc[2]["is_b2b"] == 0
