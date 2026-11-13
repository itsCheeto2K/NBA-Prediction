"""Tests for Defense vs Position (DvP) data contracts, smoothing, and API responses (§15 of Spec)."""
import pytest
import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from src.features.dvp_position import normalize_position_group, resolve_player_position
from src.features.dvp_ranks import smooth_dvp_volume, smooth_dvp_minute_rate, compute_log_relative
from src.api.main import app

client = TestClient(app)


def test_dvp_position_normalization():
    """Verify position mapping following §4 of Spec."""
    assert normalize_position_group("PG") == "guard"
    assert normalize_position_group("SG") == "guard"
    assert normalize_position_group("G") == "guard"
    assert normalize_position_group("point guard") == "guard"

    assert normalize_position_group("SF") == "wing"
    assert normalize_position_group("F") == "wing"
    assert normalize_position_group("G-F") == "wing"
    assert normalize_position_group("F-G") == "wing"

    assert normalize_position_group("PF") == "big"
    assert normalize_position_group("C") == "big"
    assert normalize_position_group("F-C") == "big"
    assert normalize_position_group("C-F") == "big"

    assert normalize_position_group(None) == "unknown"
    assert normalize_position_group("") == "unknown"
    assert normalize_position_group("XYZ") == "unknown"


def test_dvp_spec_numerical_example():
    """
    Verify exact numerical example from §15.1 of NBA_DVP_FEATURE_AND_UI_IMPLEMENTATION_SPEC.md:
    Team A: 600 PTS, 800 minutes, 1000 possessions.
    Team B: 500 PTS, 500 minutes, 1000 possessions.
    V0 = 55.0, tau = 500.0
    R0 = 0.8, beta = 500.0
    """
    # Volume shrinkage
    v_a, pw_va = smooth_dvp_volume(sum_y=600.0, sum_e=1000.0, v0=55.0, tau=500.0)
    v_b, pw_vb = smooth_dvp_volume(sum_y=500.0, sum_e=1000.0, v0=55.0, tau=500.0)

    assert pytest.approx(v_a, abs=1e-5) == (600.0 + 275.0) / 1500.0 * 100.0
    assert pytest.approx(v_b, abs=1e-5) == (500.0 + 275.0) / 1500.0 * 100.0

    # Minute-rate shrinkage
    r_a, pw_ra = smooth_dvp_minute_rate(sum_y=600.0, sum_m=800.0, r0=0.8, beta=500.0)
    r_b, pw_rb = smooth_dvp_minute_rate(sum_y=500.0, sum_m=500.0, r0=0.8, beta=500.0)

    assert pytest.approx(r_a, abs=1e-5) == (600.0 + 400.0) / 1300.0
    assert pytest.approx(r_b, abs=1e-5) == (500.0 + 400.0) / 1000.0


def test_api_team_defense_profile_has_dvp():
    """Verify /api/teams/{team_abbr}/defense-profile returns DvP breakdown for guard, wing, big."""
    res = client.get("/api/teams/MIA/defense-profile")
    assert res.status_code == 200
    data = res.json()
    assert "dvp" in data
    dvp = data["dvp"]
    assert dvp["team_abbr"] == "MIA"
    assert "groups" in dvp
    groups = dvp["groups"]
    assert "guard" in groups
    assert "wing" in groups
    assert "big" in groups

    for grp in ["guard", "wing", "big"]:
        for s in ["pts", "reb", "ast"]:
            assert s in groups[grp]
            assert "volume_per100" in groups[grp][s]
            assert "rank_asc" in groups[grp][s]
            assert 1.0 <= groups[grp][s]["rank_asc"] <= 30.0


def test_api_predict_returns_dvp_context():
    """Verify /api/predict returns calibrated DvP context matching player position group."""
    payload = {
        "player_id": 1628378,  # Donovan Mitchell (Guard)
        "stat": "pts",
        "line": 26.5,
        "opponent_override": "MIA",
    }
    res = client.post("/api/predict", json=payload)
    assert res.status_code == 200
    data = res.json()

    assert "dvp_context" in data
    dvp = data["dvp_context"]
    assert dvp is not None
    assert dvp["player_id"] == 1628378
    assert dvp["position_group"] == "guard"
    assert dvp["opponent_abbr"] == "MIA"
    assert "pts" in dvp
    assert "reb" in dvp
    assert "ast" in dvp
    assert dvp["pts"]["volume_per100"] > 0.0
    assert 1.0 <= dvp["pts"]["rank_asc"] <= 30.0


def test_compute_dvp_features_fallback():
    """Verify compute_dvp_features gracefully populates priors when team logs are absent."""
    from src.features.dvp_context import compute_dvp_features
    df_players = pd.DataFrame([
        {
            "season": "2024-25",
            "game_id": "001",
            "player_id": 1628378,
            "team_abbreviation": "CLE",
            "opponent_abbr": "DET",
            "game_date": "2024-10-23",
            "pts": 25,
            "reb": 5,
            "ast": 5,
            "min": 30.0,
        }
    ])
    res = compute_dvp_features(df_players, team_logs_df=None)
    
    expected_cols = [
        "dvp_pts_volume_per100", "dvp_pts_volume_rank_asc", "dvp_pts_volume_rel",
        "dvp_pts_minrate", "dvp_pts_minrate_rank_asc", "dvp_pts_minrate_rel",
        "dvp_reb_volume_per100", "dvp_reb_volume_rank_asc", "dvp_reb_volume_rel",
        "dvp_reb_minrate", "dvp_reb_minrate_rank_asc", "dvp_reb_minrate_rel",
        "dvp_ast_volume_per100", "dvp_ast_volume_rank_asc", "dvp_ast_volume_rel",
        "dvp_ast_minrate", "dvp_ast_minrate_rank_asc", "dvp_ast_minrate_rel",
        "dvp_supported",
    ]
    for col in expected_cols:
        assert col in res.columns, f"Missing column: {col}"
    assert bool(res.iloc[0]["dvp_supported"]) is False
    assert res.iloc[0]["dvp_pts_volume_rank_asc"] == 15.5
    assert res.iloc[0]["dvp_pts_volume_rel"] == 0.0


def test_compute_dvp_features_anti_leakage():
    """Verify strict anti-leakage: DvP profile on game_date only uses games strictly prior to game_date."""
    from src.features.dvp_context import compute_dvp_features

    df_players = pd.DataFrame([
        # Game 1: Oct 20 (Team A vs Team B)
        {"game_id": "G1", "season": "2024-25", "player_id": 1, "team_abbreviation": "B", "opponent_abbr": "A", "game_date": "2024-10-20", "pts": 40, "reb": 10, "ast": 10, "min": 35.0},
        # Game 2: Oct 22 (Team A vs Team B)
        {"game_id": "G2", "season": "2024-25", "player_id": 1, "team_abbreviation": "B", "opponent_abbr": "A", "game_date": "2024-10-22", "pts": 45, "reb": 12, "ast": 8, "min": 36.0},
    ])

    pos_df = pd.DataFrame([
        {"player_id": 1, "position_raw": "PG", "position_group": "guard"},
    ])

    df_teams = pd.DataFrame([
        {"game_id": "G1", "game_date": "2024-10-20", "team_abbreviation": "A", "fga": 80, "fta": 20, "oreb": 10, "dreb": 30, "tov": 15, "ast": 20, "pts": 100, "fg3a": 25},
        {"game_id": "G1", "game_date": "2024-10-20", "team_abbreviation": "B", "fga": 80, "fta": 20, "oreb": 10, "dreb": 30, "tov": 15, "ast": 20, "pts": 100, "fg3a": 25},
        {"game_id": "G2", "game_date": "2024-10-22", "team_abbreviation": "A", "fga": 85, "fta": 20, "oreb": 10, "dreb": 30, "tov": 12, "ast": 22, "pts": 105, "fg3a": 28},
        {"game_id": "G2", "game_date": "2024-10-22", "team_abbreviation": "B", "fga": 85, "fta": 20, "oreb": 10, "dreb": 30, "tov": 12, "ast": 22, "pts": 105, "fg3a": 28},
    ])

    res = compute_dvp_features(df_players, team_logs_df=df_teams, pos_df=pos_df)
    assert len(res) == 2
    # Row 0 (Oct 20) should have NO prior games for opponent A (strictly before Oct 20)
    assert bool(res.iloc[0]["dvp_supported"]) is False
    assert res.iloc[0]["dvp_pts_volume_rel"] == 0.0



def test_api_fastcheck_batch_predict_returns_dvp_rank():
    """Verify /api/fastcheck/predict-batch returns dvp_pts_rank for each player."""
    payload = [
        {"player_id": 1628378, "line": 26.5, "stat": "pts", "opponent_override": "MIA"},
        {"player_id": 203999, "line": 25.5, "stat": "pts", "opponent_override": "MIA"},
    ]
    res = client.post("/api/fastcheck/predict-batch", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 2
    for item in data:
        assert "dvp_pts_rank" in item
        assert item["dvp_pts_rank"] is not None
        assert 1.0 <= item["dvp_pts_rank"] <= 30.0


def test_ui_static_dvp_elements():
    """Verify Oracle index.html and FastCheck static scripts contain DvP rank UI bindings."""
    # Oracle page & JS
    r_idx = client.get("/")
    assert r_idx.status_code == 200
    assert "dvp-box" in r_idx.text
    assert "dvp-player-group" in r_idx.text
    assert "dvp-pts-rank" in r_idx.text

    r_app = client.get("/static/app.js")
    assert r_app.status_code == 200
    assert "dvp.position_group" in r_app.text
    assert "renderDvpStat" in r_app.text

    # FastCheck page & JS
    r_fc = client.get("/fastcheck")
    assert r_fc.status_code == 200

    r_fc_js = client.get("/static/fastcheck.js")
    assert r_fc_js.status_code == 200
    assert "dvp-badge-" in r_fc_js.text
    assert "renderDvpBadge" in r_fc_js.text

