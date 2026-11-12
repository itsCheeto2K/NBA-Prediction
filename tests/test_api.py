import pytest
from fastapi.testclient import TestClient
from src.api.main import app

client = TestClient(app)

def test_api_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "models_loaded" in data

def test_api_players():
    response = client.get("/api/players?query=donovan")
    assert response.status_code == 200
    players = response.json()
    assert len(players) > 0
    assert any("Mitchell" in p["full_name"] for p in players)

def test_api_predict():
    payload = {
        "player_id": 1628378,  # Donovan Mitchell
        "stat": "pts",
        "line": 24.5,
        "odds_over": 1.90,
        "odds_under": 1.90,
    }
    response = client.post("/api/predict", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["player_id"] == 1628378
    assert data["stat"] == "PTS"
    assert "expected_value" in data
    assert data["expected_value"] > 0
    assert "median" in data
    assert "prediction_interval" in data
    assert "line_probabilities" in data
    assert data["line_probabilities"]["line"] == 24.5
    assert "pricing" in data
    assert len(data["pmf"]) > 20
    assert "condition" in data
    # Verify Supplement Plan features are exposed
    assert "schedule_context" in data
    assert data["schedule_context"] is not None
    assert "team_b2b" in data["schedule_context"]
    assert "rest_advantage_days" in data["schedule_context"]
    assert "opponent_context" in data
    assert data["opponent_context"] is not None
    assert "opp_def_rating_prev10" in data["opponent_context"]
    assert "opp_pace_prev10" in data["opponent_context"]

    # Test opponent override (e.g. user selects Hawks ATL)
    override_payload = {
        "player_id": 1628378,
        "stat": "pts",
        "opponent_override": "ATL",
    }
    res_override = client.post("/api/predict", json=override_payload)
    assert res_override.status_code == 200
    data_override = res_override.json()
    assert data_override["opponent_context"]["opponent_abbr"] == "ATL"
    assert data_override["upcoming_game_info"]["active_opponent"] == "ATL"

def test_api_sync_status():
    response = client.get("/api/sync/status")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert data["season"] == "2026-27"
    assert "latest_game_date" in data

def test_api_team_roster_complete_bench():
    """Verify that get_team_roster returns all players including bench (no 12-player cutoff)."""
    response = client.get("/api/teams/GSW/roster")
    assert response.status_code == 200
    roster = response.json()
    assert len(roster) > 12  # GSW has 15+ players
    # Verify both starters and deep bench players are present
    names = [p["player_name"] for p in roster]
    assert "Stephen Curry" in names
    assert any(p["min_avg"] < 10.0 for p in roster)  # Deep bench exists
    assert all("player_id" in p and "suggested_line" in p for p in roster)

def test_api_fastcheck_endpoint():
    response = client.get("/fastcheck")
    assert response.status_code == 200
    assert "FastCheck" in response.text
