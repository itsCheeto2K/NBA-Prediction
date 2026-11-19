"""Tests for Injury Ablation & Feature Enrichment (§7, §8, Issue 06)."""
import pytest
import numpy as np
import pandas as pd
from src.models.injury_ablation import enrich_dataset_with_injury_features


def test_enrich_dataset_with_injury_features_pre_game_basis():
    """Verify Issue 06: missing teammate minutes is computed from pre-game status / rolling minutes, not post-game boxscore."""
    # 2 teammates on BOS in game 1
    # Player 1: healthy (days_since=2, team_b2b=0), rolling min = 30.0
    # Player 2: returning from 15 days absence (own_is_questionable=1), rolling min = 20.0
    df = pd.DataFrame([
        {
            "player_id": 101,
            "game_id": "0022400001",
            "game_date": "2024-11-01",
            "team_abbreviation": "BOS",
            "opponent_abbr": "NYK",
            "team_b2b": 0,
            "min_roll_mean_5": 30.0,
            "fga_roll_mean_5": 15.0,
            "ast_roll_mean_5": 5.0,
            "pts_roll_mean_5": 20.0,
        },
        {
            "player_id": 102,
            "game_id": "0022400001",
            "game_date": "2024-11-01",
            "team_abbreviation": "BOS",
            "opponent_abbr": "NYK",
            "team_b2b": 0,
            "min_roll_mean_5": 20.0,
            "fga_roll_mean_5": 10.0,
            "ast_roll_mean_5": 2.0,
            "pts_roll_mean_5": 12.0,
        },
        # Opponent NYK has player 201
        {
            "player_id": 201,
            "game_id": "0022400001",
            "game_date": "2024-11-01",
            "team_abbreviation": "NYK",
            "opponent_abbr": "BOS",
            "team_b2b": 1,
            "min_roll_mean_5": 35.0,
            "fga_roll_mean_5": 18.0,
            "ast_roll_mean_5": 8.0,
            "pts_roll_mean_5": 25.0,
        },
    ])

    enriched = enrich_dataset_with_injury_features(df)

    assert "teammate_missing_minutes" in enriched.columns
    assert "teammate_missing_fga" in enriched.columns
    assert "teammate_missing_ast" in enriched.columns
    assert "teammate_missing_pts" in enriched.columns
    assert "teammate_top2_lost_minutes" in enriched.columns
    assert "opp_missing_minutes" in enriched.columns

    # Player 101's teammate is player 102
    p101 = enriched[enriched["player_id"] == 101].iloc[0]
    p102 = enriched[enriched["player_id"] == 102].iloc[0]

    # A boxscore alone is not evidence about pregame absences. Unknown must
    # stay unknown rather than constructing a number from target membership.
    assert pd.isna(p101["teammate_missing_minutes"])
    assert pd.isna(p102["teammate_missing_minutes"])
    assert not enriched["injury_snapshot_available"].any()
