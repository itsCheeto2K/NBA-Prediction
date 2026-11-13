"""Tests for Defense vs Position (DvP) data contracts, smoothing, and API responses (§15 of Spec)."""
import pytest
import numpy as np
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
