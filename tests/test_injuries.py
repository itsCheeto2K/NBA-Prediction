import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.collectors.injuries import (
    normalize_text,
    get_player_injury,
    get_team_injuries,
    ESPN_TEAM_TO_TRICODE,
)

client = TestClient(app)

def test_normalize_text():
    assert normalize_text("Luka Dončić") == "luka doncic"
    assert normalize_text("Nikola Jokić") == "nikola jokic"
    assert normalize_text("  LeBron James  ") == "lebron james"

def test_team_tricodes_mapping():
    assert ESPN_TEAM_TO_TRICODE["Atlanta Hawks"] == "ATL"
    assert ESPN_TEAM_TO_TRICODE["Los Angeles Lakers"] == "LAL"
    assert ESPN_TEAM_TO_TRICODE["Dallas Mavericks"] == "DAL"
    assert ESPN_TEAM_TO_TRICODE["Boston Celtics"] == "BOS"

def test_get_player_and_team_injuries():
    sample_data = {
        "teams": {
            "LAL": [
                {
                    "player_name": "Luka Doncic",
                    "status": "Day-To-Day",
                    "short_comment": "Back tightness",
                    "team_abbr": "LAL",
                }
            ],
            "ATL": [
                {
                    "player_name": "Asa Newell",
                    "status": "Out",
                    "short_comment": "Toe",
                    "team_abbr": "ATL",
                }
            ],
        },
        "players": {
            "luka doncic": {
                "player_name": "Luka Doncic",
                "status": "Day-To-Day",
                "short_comment": "Back tightness",
                "team_abbr": "LAL",
            }
        },
    }

    # Match exact or with accents
    inj = get_player_injury("Luka Dončić", sample_data)
    assert inj is not None
    assert inj["status"] == "Day-To-Day"

    inj_none = get_player_injury("Healthy Player", sample_data)
    assert inj_none is None

    lal_injs = get_team_injuries("LAL", sample_data)
    assert len(lal_injs) == 1
    assert lal_injs[0]["player_name"] == "Luka Doncic"

def test_api_injuries_endpoint():
    response = client.get("/api/injuries?team=LAL")
    assert response.status_code == 200
    data = response.json()
    assert "team" in data
    assert data["team"] == "LAL"
    assert "injuries" in data

def test_participation_model():
    from src.features.participation import ParticipationModel
    model = ParticipationModel()

    # Out is 0.0
    assert model.predict_p_play("Out") == 0.0
    assert model.predict_p_play("SUSPENDED") == 0.0

    # Probable is high
    assert model.predict_p_play("Probable") >= 0.90

    # Questionable / Day-to-Day is moderate
    q_rate = model.predict_p_play("Questionable")
    assert 0.40 <= q_rate <= 0.65

    # B2B fatigue penalty
    q_b2b = model.predict_p_play("Questionable", is_b2b=True)
    assert q_b2b < q_rate

def test_settlement_and_readiness():
    from src.distribution.settlement import compute_conditional_line_probabilities, compute_unconditional_settlement, evaluate_injury_readiness
    import numpy as np

    # Synthetic Poisson CDF
    cdf = np.array([0.05, 0.15, 0.35, 0.65, 0.85, 0.95, 1.0])
    cond_probs = compute_conditional_line_probabilities(cdf, line=2.5)
    assert "q_over" in cond_probs
    assert "q_under" in cond_probs
    assert cond_probs["q_push"] == 0.0  # half line

    # Unconditional settlement
    pi = 0.80
    uncond = compute_unconditional_settlement(cond_probs, pi_participate=pi)
    assert uncond["pi_participate"] == 0.80
    assert uncond["p_void"] == 0.20
    # Sum must equal 1.0
    tot = uncond["p_over"] + uncond["p_under"] + uncond["p_push"] + uncond["p_void"]
    assert pytest.approx(tot, abs=1e-4) == 1.0

    # Readiness states
    r_out = evaluate_injury_readiness("Out", n_games_history=15, days_since_last=2)
    assert r_out["status"] == "OUT"

    r_quest = evaluate_injury_readiness("Questionable", n_games_history=15, days_since_last=2)
    assert r_quest["status"] == "SCENARIO_ONLY"

    r_ready = evaluate_injury_readiness("not_listed", n_games_history=15, days_since_last=2)
    assert r_ready["status"] == "READY"
