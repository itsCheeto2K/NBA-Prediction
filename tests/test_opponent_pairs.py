import pytest
import pandas as pd
import numpy as np
from src.features.opponent_pairs import build_team_game_pairs, calculate_possessions

def test_calculate_possessions():
    # FGA=86, FTA=32, OREB=14, TOV=17
    # 86 + 0.44*32 - 14 + 17 = 86 + 14.08 - 14 + 17 = 103.08
    poss = calculate_possessions(fga=86, fta=32, oreb=14, tov=17)
    assert abs(poss - 103.08) < 1e-4

def test_build_team_game_pairs():
    # Mock two teams in 1 game
    logs = pd.DataFrame([
        {
            "game_id": "001",
            "team_id": 10,
            "team_abbreviation": "DET",
            "game_date": "2026-10-20",
            "fga": 86, "fgm": 39, "fta": 32, "oreb": 14, "dreb": 35, "reb": 49,
            "ast": 27, "blk": 5, "tov": 17, "pts": 121, "fg3a": 40, "fg3m": 15
        },
        {
            "game_id": "001",
            "team_id": 20,
            "team_abbreviation": "BOS",
            "game_date": "2026-10-20",
            "fga": 88, "fgm": 40, "fta": 21, "oreb": 12, "dreb": 27, "reb": 39,
            "ast": 28, "blk": 6, "tov": 14, "pts": 113, "fg3a": 42, "fg3m": 17
        }
    ])

    pairs = build_team_game_pairs(logs)
    assert len(pairs) == 2
    
    det = pairs[pairs["team_abbreviation"] == "DET"].iloc[0]
    assert det["opponent_abbr"] == "BOS"
    assert det["pts_allowed"] == 113  # BOS points
    assert det["blocks_made"] == 5    # DET blk
    assert det["blocks_allowed"] == 6 # BOS blk
    assert det["missed_fga"] == 86 - 39  # 47
    assert det["possessions_own"] > 90
    assert det["possessions_foe"] > 90
    assert det["possessions_game_common"] == (det["possessions_own"] + det["possessions_foe"]) / 2
