import pytest
import pandas as pd
import numpy as np
from src.features.rolling import compute_player_rolling_features

def test_rolling_anti_leakage_guarantee():
    # Construct synthetic game log for a single player
    df = pd.DataFrame([
        {"player_id": 1, "game_date": "2024-11-01", "game_id": "0022400001", "pts": 10, "reb": 5, "ast": 3, "min": 30.0},
        {"player_id": 1, "game_date": "2024-11-03", "game_id": "0022400002", "pts": 20, "reb": 7, "ast": 4, "min": 32.0},
        {"player_id": 1, "game_date": "2024-11-05", "game_id": "0022400003", "pts": 30, "reb": 9, "ast": 5, "min": 34.0},
    ])
    
    features_orig = compute_player_rolling_features(df, windows=[5])
    
    # Now artificially alter pts of the 3rd game from 30 to 100
    df_altered = df.copy()
    df_altered.loc[2, "pts"] = 100
    features_altered = compute_player_rolling_features(df_altered, windows=[5])
    
    # The 3rd game's features MUST NOT CHANGE when changing its own stats!
    row3_orig = features_orig.iloc[2]
    row3_altered = features_altered.iloc[2]
    
    assert row3_orig["pts_roll_mean_5"] == row3_altered["pts_roll_mean_5"]
    # 3rd game rolling mean should be mean of games 1 & 2: (10 + 20) / 2 = 15.0
    assert row3_orig["pts_roll_mean_5"] == 15.0
    assert row3_orig["n_games_history"] == 2

def test_rolling_first_game():
    df = pd.DataFrame([
        {"player_id": 1, "game_date": "2024-11-01", "game_id": "0022400001", "pts": 25, "reb": 5, "ast": 5, "min": 30.0},
    ])
    features = compute_player_rolling_features(df, windows=[5])
    # First game has 0 past games
    assert features.iloc[0]["n_games_history"] == 0
    assert pd.isna(features.iloc[0]["pts_roll_mean_5"])
