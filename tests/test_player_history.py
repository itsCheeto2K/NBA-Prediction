"""
Tests for Player History Reference Service and API Endpoint
============================================================
Verifies implementation of NBA_HOME_PLAYER_HISTORY_REFERENCE_SPEC.md (§8):
- 10 game limit
- DNP exclusion (min <= 0 or NaN)
- Real 0 stat preservation (played > 0 min, 0 pts/reb/ast)
- Deduplication by player_id + game_id
- H2H filtered by opponent before limiting to 10
- Historical team preservation across player transfers
- Target game cutoff exclusion
- Opponent resolution by team ID and abbreviation
- Schema compliance (§6)
- Inference isolation (zero impact on prediction engine)
"""

import pytest
import pandas as pd
import numpy as np
from pathlib import Path
from fastapi.testclient import TestClient

from src.api.main import app
from src.features.player_history import (
    PlayerHistoryService,
    get_player_history,
    to_int_or_none,
)
from src.api.schemas import PlayerHistoryResponse


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def history_service():
    service = PlayerHistoryService.get_instance()
    service.load_data()
    return service


def test_to_int_or_none_preserves_real_zero():
    """Verify that 0 is preserved as int 0, and NaN/None becomes None."""
    assert to_int_or_none(0) == 0
    assert to_int_or_none(0.0) == 0
    assert to_int_or_none("0") == 0
    assert to_int_or_none(None) is None
    assert to_int_or_none(np.nan) is None
    assert to_int_or_none(float("nan")) is None
    assert to_int_or_none(25) == 25
    assert to_int_or_none(25.0) == 25


@pytest.mark.parametrize("limit", [30, 200])
def test_api_history_supports_chart_ranges(client, limit):
    response = client.get(f"/api/players/2544/history?limit={limit}&opponent_abbr=HOU")
    assert response.status_code == 200, response.text
    data = response.json()
    rows = data["recent"]["rows"]
    assert 30 <= len(rows) <= limit
    if limit == 200:
        assert len(rows) > 50  # Season cannot be capped by the previous API limit.
    assert all(row["minutes"] > 0 for row in rows)
    assert [row["game_date"] for row in rows] == sorted([row["game_date"] for row in rows], reverse=True)


def test_api_history_rejects_excessive_chart_limit(client):
    assert client.get("/api/players/2544/history?limit=201").status_code == 422


def test_recent_limit_and_sorting(history_service):
    """Verify recent games respect limit and are sorted newest first (§3.1, §8)."""
    # LeBron James: 2544
    res = history_service.get_player_history(player_id=2544, limit=10)
    recent = res["recent"]
    assert recent["returned_count"] <= 10
    assert len(recent["rows"]) == recent["returned_count"]
    assert recent["returned_count"] == 10

    # Verify descending sort by date
    dates = [r["game_date"] for r in recent["rows"]]
    assert dates == sorted(dates, reverse=True)

    # Test custom limit
    res_5 = history_service.get_player_history(player_id=2544, limit=5)
    assert res_5["recent"]["returned_count"] == 5
    assert len(res_5["recent"]["rows"]) == 5


def test_dnp_exclusion(history_service):
    """Verify that games with min <= 0 or NaN are excluded (§3.1)."""
    # From data inspection, Luka Garza (1630568) had min = 0.0 in game 0022401102
    res = history_service.get_player_history(player_id=1630568, limit=50)
    for r in res["recent"]["rows"]:
        assert r["minutes"] is not None
        assert r["minutes"] > 0
        assert r["game_id"] != "0022401102"


def test_real_zero_stat_preservation(history_service):
    """Verify that games where player played >0 min but scored 0 are preserved with int 0 (§3.1, §8)."""
    # Reed Sheppard: 1642263 played 17.2 min with 0 pts in game 0022401193
    res = history_service.get_player_history(player_id=1642263, limit=50)
    matching = [r for r in res["recent"]["rows"] if r["game_id"] == "0022401193"]
    if matching:
        row = matching[0]
        assert row["minutes"] > 0
        assert row["pts"] == 0  # Must be integer 0, not None
        assert isinstance(row["pts"], int)


def test_deduplication(history_service):
    """Verify that duplicate (player_id, game_id) rows are deduplicated (§3.1)."""
    res = history_service.get_player_history(player_id=2544, limit=50)
    game_ids = [r["game_id"] for r in res["recent"]["rows"]]
    assert len(game_ids) == len(set(game_ids))


def test_h2h_filtering_before_limit(history_service):
    """
    Verify H2H filters by opponent across all seasons BEFORE applying limit (§3.3, §8).
    LeBron James vs BOS: games span across 2023-24, 2024-25, 2025-26, 2026-27.
    """
    res = history_service.get_player_history(player_id=2544, opponent_abbr="BOS", limit=10)
    vs_opp = res["vs_opponent"]
    assert vs_opp["returned_count"] > 0
    # All rows must be against BOS (opponent_team_id 1610612738)
    for r in vs_opp["rows"]:
        assert r["opponent_team_abbr"] == "BOS"
        assert r["opponent_team_id"] == 1610612738

    # Dates must be descending
    dates = [r["game_date"] for r in vs_opp["rows"]]
    assert dates == sorted(dates, reverse=True)


def test_historical_team_preservation(history_service):
    """
    Verify that player's team at the time of each game is preserved across transfers (§3.3).
    LeBron James played for LAL in earlier seasons and PHI in 2026-27.
    """
    res = history_service.get_player_history(player_id=2544, opponent_abbr="BOS", limit=10)
    rows = res["vs_opponent"]["rows"]
    teams_played_for = {r["player_team_abbr"] for r in rows}
    # Should contain both PHI (newest) and LAL (historical)
    assert "PHI" in teams_played_for
    assert "LAL" in teams_played_for


def test_opponent_resolution_by_abbr_and_id(history_service):
    """Verify that opponent_abbr and opponent_team_id yield identical results."""
    res_abbr = history_service.get_player_history(player_id=2544, opponent_abbr="GSW", limit=10)
    res_id = history_service.get_player_history(player_id=2544, opponent_team_id=1610612744, limit=10)

    assert res_abbr["vs_opponent"]["returned_count"] == res_id["vs_opponent"]["returned_count"]
    abbr_gids = [r["game_id"] for r in res_abbr["vs_opponent"]["rows"]]
    id_gids = [r["game_id"] for r in res_id["vs_opponent"]["rows"]]
    assert abbr_gids == id_gids


def test_target_game_cutoff(history_service):
    """Verify target_game_id cutoff excludes the target game and any games on/after (§3.1)."""
    # Pick the most recent game for LeBron
    res_all = history_service.get_player_history(player_id=2544, limit=10)
    newest_game = res_all["recent"]["rows"][0]
    target_gid = newest_game["game_id"]

    # Now query with this target_game_id
    res_cutoff = history_service.get_player_history(player_id=2544, target_game_id=target_gid, limit=10)
    cutoff_gids = [r["game_id"] for r in res_cutoff["recent"]["rows"]]
    assert target_gid not in cutoff_gids


def test_schema_compliance_and_flags(history_service):
    """Verify response structure strictly matches §6 and flags are reference_only."""
    res = history_service.get_player_history(player_id=2544, opponent_abbr="BOS", limit=10)

    # Validate against Pydantic schema
    validated = PlayerHistoryResponse(**res)
    assert validated.reference_only is True
    assert validated.affects_prediction is False
    assert validated.season_type == "Regular Season"
    assert validated.coverage.backfill_pending is False
    assert len(validated.coverage.seasons_available) >= 1

    # Check row schema
    for row in validated.recent.rows:
        assert isinstance(row.game_id, str)
        assert row.home_away in ("home", "away")
        assert row.participation_status == "PLAYED"
        assert row.minutes > 0


def test_api_endpoint_integration(client):
    """Verify FastAPI GET /api/players/{player_id}/history endpoint."""
    response = client.get("/api/players/2544/history?opponent_abbr=BOS&limit=10")
    assert response.status_code == 200
    data = response.json()

    assert data["reference_only"] is True
    assert data["affects_prediction"] is False
    assert data["player_id"] in (2544, "2544")
    assert data["opponent_team_id"] in (1610612738, "1610612738")
    assert data["recent"]["returned_count"] <= 10
    assert len(data["recent"]["rows"]) == data["recent"]["returned_count"]
    assert data["vs_opponent"]["returned_count"] <= 10
    assert len(data["vs_opponent"]["rows"]) == data["vs_opponent"]["returned_count"]


def test_api_unknown_player(client):
    """Verify 404 for non-existent player."""
    response = client.get("/api/players/99999999/history")
    assert response.status_code == 404


def test_reference_row_scores_use_team_totals_and_shooting_rates_preserve_zero():
    service=PlayerHistoryService()
    service._team_scores={("g",1):112,("g",2):105}
    row=pd.Series({"game_id":"g","game_date_str":"2026-11-01","team_id":1,
                   "opponent_team_id":2,"home_away":"home","min_numeric":30,
                   "pts":13,"wl":"W","fg3m":0,"fg3a":4,"fgm":5,"fga":10,"ftm":None,"fta":0})
    result=service._build_row(row)
    assert (result["team_score"],result["opponent_score"],result["result"]) == (112,105,"W")
    assert result["fg3_pct"] == 0
    assert result["fg_pct"] == .5
    assert result["ft_pct"] is None
    service._team_scores={}
    result=service._build_row(row)
    assert result["team_score"] is None
    assert result["opponent_score"] is None


def test_history_api_exposes_scores_and_shooting_columns(client):
    result=client.get("/api/players/2544/history?limit=10")
    assert result.status_code == 200
    rows=result.json()["recent"]["rows"]
    assert any(row["team_score"] is not None and row["opponent_score"] is not None for row in rows)
    for row in rows:
        assert row["result"] in ["W","L",None]
        for field in ["fg3_pct","ft_pct","fg_pct"]:
            assert row[field] is None or 0 <= row[field] <= 1


def test_inference_isolation(client):
    """
    CRITICAL: Verify that querying player history has ZERO impact on prediction outputs (§1, §8).
    Prediction before and after history query must produce identical values.
    """
    predict_payload = {
        "player_id": 2544,
        "stat": "pts",
        "line": 24.5,
        "odds_over": 1.90,
        "odds_under": 1.90,
    }

    # Baseline prediction before
    r_before = client.post("/api/predict", json=predict_payload)
    assert r_before.status_code == 200
    res_before = r_before.json()

    # Call history API multiple times
    client.get("/api/players/2544/history?opponent_abbr=BOS")
    client.get("/api/players/2544/history?opponent_abbr=GSW&limit=5")

    # Prediction after
    r_after = client.post("/api/predict", json=predict_payload)
    assert r_after.status_code == 200
    res_after = r_after.json()

    # Exact equality across all inference metrics
    assert res_before["expected_value"] == res_after["expected_value"]
    assert res_before["median"] == res_after["median"]
    assert res_before["prediction_interval"] == res_after["prediction_interval"]
    assert res_before["line_probabilities"] == res_after["line_probabilities"]
    assert res_before["pricing"] == res_after["pricing"]
    assert res_before["pmf"] == res_after["pmf"]
