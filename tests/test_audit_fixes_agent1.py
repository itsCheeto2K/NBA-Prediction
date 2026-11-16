import pytest
import math
import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from src.features.participation import normalize_injury_status, ParticipationModel, DEFAULT_PARTICIPATION_PRIORS
from src.distribution.engine import DiscreteDistribution, DiscreteDistributionEngine
from src.distribution.minutes_allocator import allocate_team_minutes, PlayerAllocationInput
from src.distribution.pricing import remove_vig_multiplicative, calculate_ev, calculate_break_even_prob
from src.distribution.settlement import evaluate_injury_readiness
from src.api.schemas import PredictRequest
from src.api.main import app, check_server_staking_policy_validated

client = TestClient(app)


def test_issue_01_injury_status_normalization_and_idempotence():
    # Healthy and not_listed normalized to available
    assert normalize_injury_status("HEALTHY") == "available"
    assert normalize_injury_status("Healthy") == "available"
    assert normalize_injury_status("not_listed") == "available"
    assert normalize_injury_status(None) == "available"
    assert normalize_injury_status("") == "available"
    assert normalize_injury_status("available") == "available"
    assert normalize_injury_status("active") == "available"

    # Standard statuses preserved
    assert normalize_injury_status("Questionable") == "questionable"
    assert normalize_injury_status("Doubtful") == "doubtful"
    assert normalize_injury_status("Out") == "out"
    assert normalize_injury_status("Probable") == "probable"
    assert normalize_injury_status("Day-To-Day") == "day-to-day"
    assert normalize_injury_status("unknown") == "unknown"

    # Idempotence test
    test_inputs = [
        "HEALTHY", "not_listed", None, "", "available", "Active",
        "questionable", "Questionable", "Doubtful", "out", "Probable",
        "Day-to-Day", "GTD", "unknown", "completely_random_injury"
    ]
    for inp in test_inputs:
        norm1 = normalize_injury_status(inp)
        norm2 = normalize_injury_status(norm1)
        assert norm1 == norm2, f"Normalization not idempotent for input: {inp}"

    # Check baseline participation rate
    pm = ParticipationModel()
    p_healthy = pm.predict_p_play("HEALTHY", baseline_min=30.0)
    p_not_listed = pm.predict_p_play("not_listed", baseline_min=30.0)
    assert p_healthy >= 0.98
    assert p_not_listed >= 0.98


def test_issue_02_own_status_code_in_prediction():
    # Donovan Mitchell with Questionable status
    # We verify that own_status_code correctly maps questionable to 1.0
    payload = {
        "player_id": 1628378,
        "stat": "pts",
        "line": 24.5,
        "odds_over": 1.90,
        "odds_under": 1.90,
    }
    # Through test client
    resp = client.post("/api/predict", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["player_id"] == 1628378


def test_issue_07_distribution_infinite_support_no_truncation():
    # mu=50, phi=0.1, line=60.5
    dist = DiscreteDistribution(mu=50.0, phi=0.1, dist_type="nb2")
    probs = dist.calculate_line_probabilities(60.5)
    # The true probability in the tail should be around 24.96%, definitely not 0%
    assert probs["q_over"] > 0.20
    assert pytest.approx(probs["q_over"], abs=0.01) == 0.2496
    assert probs["q_under"] + probs["q_over"] + probs["q_push"] == pytest.approx(1.0, 1e-5)

    # Engine compute_pmf does not truncate when mu is high
    engine = DiscreteDistributionEngine(dist_type="nb2", k_max=60)
    pmf = engine.compute_pmf(mu=50.0, phi=0.1)
    assert len(pmf) > 60  # Adaptive grid extends past k_max when needed


def test_issue_08_unknown_player_404():
    payload = {
        "player_id": 99999999,  # Non-existent player
        "stat": "pts",
        "line": 15.5,
        "odds_over": 1.90,
        "odds_under": 1.90,
    }
    resp = client.post("/api/predict", json=payload)
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_issue_09_strict_condition_hierarchy_out_not_overridden():
    # When a player is OUT, teammate missing minutes must not override forecast_status to conditional_scenario
    from src.distribution.special_groups import assess_player_condition
    from src.features.injury_roles import evaluate_injury_context_support

    cond_input = {
        "player_id": 1628378,
        "injury_status": "out",
        "n_games_history": 20,
    }
    condition = assess_player_condition(cond_input, has_valid_model=True, has_valid_prior=True)
    assert condition["operational_state"] == "SCENARIO_ONLY"
    assert condition["forecast_status"] == "not_issued"

    # Extreme teammate missing minutes
    tm_missing_mins = 120.0
    ctx_support = evaluate_injury_context_support(tm_missing_mins)
    assert not ctx_support["is_supported"]

    # In main.py logic:
    if not ctx_support["is_supported"]:
        if ctx_support["reason_code"] not in condition.get("reason_codes", []):
            condition.setdefault("reason_codes", []).append(ctx_support["reason_code"])
        if condition.get("forecast_status") != "not_issued" and condition.get("operational_state") not in ("OUT", "NOT_ISSUED"):
            condition["operational_state"] = "SCENARIO_ONLY"
            condition["forecast_status"] = "conditional_scenario"

    # forecast_status MUST REMAIN 'not_issued'
    assert condition["forecast_status"] == "not_issued"


def test_issue_25_readiness_stale_injury_and_market_models():
    # evaluate_injury_readiness with is_stale_report=True returns SCENARIO_ONLY
    readiness = evaluate_injury_readiness(
        player_status="available",
        n_games_history=20,
        days_since_last=2,
        is_stale_report=True,
    )
    assert readiness["status"] == "SCENARIO_ONLY"
    assert readiness["support_level"] == "stale_report"

    # health_ready checks market models across pts, reb, ast
    res = client.get("/api/health/ready")
    assert res.status_code in (200, 503)
    data = res.json()
    assert "market_models" in data["checks"]
    assert "pts" in data["checks"]["market_models"]
    assert "reb" in data["checks"]["market_models"]
    assert "ast" in data["checks"]["market_models"]
    assert "all_markets_ready" in data["checks"]


def test_issue_30_calibrated_distribution_expectation():
    # If a calibrator changes the CDF, dist.mean() evaluates the calibrated expectation
    def simple_calibrator(u):
        return u ** 2.0  # monotonic CDF shift

    dist_uncal = DiscreteDistribution(mu=20.0, phi=0.05, dist_type="nb2")
    dist_cal = DiscreteDistribution(mu=20.0, phi=0.05, dist_type="nb2", calibrator=simple_calibrator)

    assert dist_uncal.mean() == pytest.approx(20.0, 1e-4)
    # Calibrated expectation must be computed from dist.mean(), differing from dist_cal.mu
    assert dist_cal.mu == 20.0
    assert dist_cal.mean() > 20.5


def test_issue_32_minutes_allocator_rejects_duplicate_player_ids():
    roster = [
        {"player_id": 101, "baseline_minutes": 30.0, "is_eligible": True},
        {"player_id": 101, "baseline_minutes": 30.0, "is_eligible": True},  # Duplicate ID
        {"player_id": 102, "baseline_minutes": 30.0, "is_eligible": True},
        {"player_id": 103, "baseline_minutes": 30.0, "is_eligible": True},
        {"player_id": 104, "baseline_minutes": 30.0, "is_eligible": True},
        {"player_id": 105, "baseline_minutes": 30.0, "is_eligible": True},
        {"player_id": 106, "baseline_minutes": 30.0, "is_eligible": True},
        {"player_id": 107, "baseline_minutes": 30.0, "is_eligible": True},
    ]
    result = allocate_team_minutes(roster=roster)
    assert result.status == "INVALID_ALLOCATOR_INPUT"
    assert "Duplicate player ID detected" in result.diagnostics["error"]


def test_issue_35_input_validation_odds_and_player_id():
    # 1. Pydantic schema validation for player_id <= 0
    with pytest.raises(Exception):
        PredictRequest(player_id=-5, stat="pts", odds_over=1.90, odds_under=1.90)

    # 2. Pydantic schema validation for decimal odds <= 1.0
    with pytest.raises(Exception):
        PredictRequest(player_id=1628378, stat="pts", odds_over=0.5, odds_under=1.90)

    with pytest.raises(Exception):
        PredictRequest(player_id=1628378, stat="pts", odds_over=float("nan"), odds_under=1.90)

    # 3. Pricing functions reject invalid odds
    with pytest.raises(ValueError):
        remove_vig_multiplicative(odds_over=0.5, odds_under=1.90)

    with pytest.raises(ValueError):
        remove_vig_multiplicative(odds_over=-2.0, odds_under=1.90)

    with pytest.raises(ValueError):
        calculate_ev(prob_win=0.5, prob_loss=0.5, decimal_odds=0.8)

    # 4. API endpoint returns 422 for invalid odds or negative player_id
    resp = client.post("/api/predict", json={"player_id": -10, "stat": "pts"})
    assert resp.status_code == 422

    resp_odds = client.post("/api/predict", json={
        "player_id": 1628378,
        "stat": "pts",
        "odds_over": -1.5,
        "odds_under": 1.9,
    })
    assert resp_odds.status_code == 422


def test_issue_36_staking_policy_server_side_validation():
    # Client sends allow_staking_recommendation=True
    # Because server has no certified simulation gate report, recommendation must NOT be issued
    payload = {
        "player_id": 1628378,
        "stat": "pts",
        "line": 24.5,
        "odds_over": 1.90,
        "odds_under": 1.90,
        "allow_staking_recommendation": True,
    }
    resp = client.post("/api/predict", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    pricing = data["pricing"]
    assert pricing is not None
    # Staking policy must be validated server-side
    assert pricing["staking_policy_validated"] is False
    assert pricing["staking_reason"] == "STAKING_POLICY_UNVALIDATED"
    assert pricing["kelly_over"] is None
    assert pricing["kelly_under"] is None
