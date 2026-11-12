import pytest
import pandas as pd
from src.features.schedule_context import compute_team_and_opponent_schedule_context, compute_player_workload_context

def test_team_and_opponent_schedule_context():
    # Team A plays on Nov 1, Nov 2 (B2B), Nov 4 (3 in 4!)
    # Team B plays on Oct 30, Nov 2
    team_logs = pd.DataFrame([
        {"team_abbreviation": "CLE", "game_id": "001", "game_date": "2024-11-01"},
        {"team_abbreviation": "ORL", "game_id": "000", "game_date": "2024-10-30"},
        {"team_abbreviation": "CLE", "game_id": "002", "game_date": "2024-11-02"},  # Game 002: CLE vs ORL
        {"team_abbreviation": "ORL", "game_id": "002", "game_date": "2024-11-02"},
        {"team_abbreviation": "CLE", "game_id": "003", "game_date": "2024-11-04"},  # Game 003: CLE vs MIL
        {"team_abbreviation": "MIL", "game_id": "003", "game_date": "2024-11-04"},
    ])
    
    player_df = pd.DataFrame([
        {"player_id": 1, "team_abbreviation": "CLE", "opponent_abbr": "ORL", "game_id": "002", "game_date": "2024-11-02"},
        {"player_id": 1, "team_abbreviation": "CLE", "opponent_abbr": "MIL", "game_id": "003", "game_date": "2024-11-04"},
    ])
    
    res = compute_team_and_opponent_schedule_context(player_df, team_logs)
    
    # For Game 002 (Nov 2):
    # CLE: prev game Nov 1 -> team_b2b = 1, team_rest_days = 0
    # ORL: prev game Oct 30 -> opp_b2b = 0, opp_rest_days = 2
    # rest_advantage_days: 0 - 2 = -2 (disadvantage)
    row_g2 = res[res["game_id"] == "002"].iloc[0]
    assert row_g2["team_b2b"] == 1
    assert row_g2["team_rest_days"] == 0
    assert row_g2["opp_b2b"] == 0
    assert row_g2["opp_rest_days"] == 2
    assert row_g2["rest_advantage_days"] == -2

    # For Game 003 (Nov 4):
    # CLE played Nov 1, Nov 2, Nov 4 -> 3 games in 4 days! (Nov 1, 2, 4 in [Nov 1..Nov 4])
    row_g3 = res[res["game_id"] == "003"].iloc[0]
    assert row_g3["team_3in4"] == 1

def test_player_workload_and_rested_b2b():
    # Player played game 1, sat out game 2 (DNP), team plays game 3 on B2B
    player_df = pd.DataFrame([
        {"player_id": 1, "team_abbreviation": "CLE", "game_id": "001", "game_date": "2024-11-01", "min": 35.0, "team_b2b": 0},
        {"player_id": 1, "team_abbreviation": "CLE", "game_id": "002", "game_date": "2024-11-02", "min": 0.0, "team_b2b": 1},  # DNP
        {"player_id": 1, "team_abbreviation": "CLE", "game_id": "003", "game_date": "2024-11-03", "min": 30.0, "team_b2b": 1}, # B2B for team!
    ])
    
    res = compute_player_workload_context(player_df)
    
    # For game 003:
    # Team is on B2B (Nov 2 -> Nov 3), but player did NOT play game 002 (min == 0)!
    # team_b2b_but_player_rested should be 1!
    row_g3 = res[res["game_id"] == "003"].iloc[0]
    assert row_g3["player_played_previous_team_game"] == 0
    assert row_g3["team_b2b_but_player_rested"] == 1
    assert row_g3["player_last_game_days"] == 2 # Last played Nov 1, now Nov 3
    assert row_g3["player_minutes_prev_game"] == 35.0
