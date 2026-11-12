import math
import time
import pytest
import pandas as pd
from fastapi.testclient import TestClient

from src.client import CircuitBreaker, CircuitBreakerOpenException, CircuitState, NBAClient
from src.collectors.boxscore import (
    format_minutes_display,
    normalize_boxscore_traditional_v3,
    parse_iso_duration_to_minutes,
    parse_iso_duration_to_seconds,
)
from src.distribution.pricing import (
    american_to_decimal,
    calculate_ev,
    calculate_kelly_fraction,
    decimal_to_american,
    remove_vig_multiplicative,
)
from src.pipeline.backfill import audit_backfill_completeness
from src.collectors.sync import SyncLeaseLock, SyncJobStatus, get_job_manager
from src.api.main import app


# --------------------------------------------------------------------------
# Item 1: ISO Duration parsing, precision, unrounded minutes, and DNP vs played=0
# --------------------------------------------------------------------------
def test_iso_duration_parsing_unrounded_precision():
    # 'PT36M22.00S' = 36 * 60 + 22.0 = 2182.0 seconds
    secs = parse_iso_duration_to_seconds("PT36M22.00S")
    assert secs == 2182.0

    # Unrounded float minutes = 36 + 22.0 / 60.0 = 36.36666666666667
    mins = parse_iso_duration_to_minutes("PT36M22.00S")
    assert mins == pytest.approx(36.36666666666667, rel=1e-9)
    # Must NOT be rounded to 2 decimals (36.37)
    assert mins != 36.37

    # Display formatting should round for UI/CLI
    assert format_minutes_display(mins) == "36.37m"

    # MM:SS string parsing
    secs_mmss = parse_iso_duration_to_seconds("24:30")
    assert secs_mmss == 1470.0
    assert parse_iso_duration_to_minutes("24:30") == 24.5

    # DNP / Invalid values
    assert parse_iso_duration_to_seconds("DNP") is None
    assert parse_iso_duration_to_minutes(None) is None


def test_boxscore_dnp_vs_played_zero_pts_distinction():
    raw_df = pd.DataFrame([
        {
            "gameId": "0022600001",
            "teamId": 1610612738,
            "personId": 101,
            "comment": "DNP - Coach's Decision",
            "minutes": "PT00M00.00S",
            "points": 0,
        },
        {
            "gameId": "0022600001",
            "teamId": 1610612738,
            "personId": 102,
            "comment": "",
            "minutes": "PT15M30.00S",
            "points": 0,
        },
        {
            "gameId": "0022600001",
            "teamId": 1610612738,
            "personId": 103,
            "comment": "",
            "minutes": "PT00M20.00S",
            "points": 0,
        },
    ])

    norm_df = normalize_boxscore_traditional_v3(raw_df)

    # Player 101: DNP -> minutes is None or NaN, played == 0
    p101 = norm_df[norm_df["player_id"] == 101].iloc[0]
    assert p101["is_dnp"] is True or p101["is_dnp"] == 1
    assert pd.isna(p101["min"])
    assert pd.isna(p101["min_seconds"])
    assert p101["participation_status"] == "DNP"
    assert p101["played"] == 0

    # Player 102: Played 15.5m with 0 points -> played == 1
    p102 = norm_df[norm_df["player_id"] == 102].iloc[0]
    assert not p102["is_dnp"]
    assert p102["min"] == 15.5
    assert p102["min_seconds"] == 930.0
    assert p102["participation_status"] == "PLAYED_ZERO_PTS"
    assert p102["played"] == 1

    # Player 103: Played sub-minute (20s) with 0 points -> played == 1
    p103 = norm_df[norm_df["player_id"] == 103].iloc[0]
    assert not p103["is_dnp"]
    assert p103["min_seconds"] == 20.0
    assert p103["participation_status"] == "PLAYED_ZERO_PTS"
    assert p103["played"] == 1


# --------------------------------------------------------------------------
# Item 2: Backfill missing game / one-team-row audit detection
# --------------------------------------------------------------------------
def test_backfill_completeness_audit_detects_missing_and_one_team_row():
    # Schedule has 3 completed games
    schedule_df = pd.DataFrame([
        {"game_id": "0022600001", "game_status_text": "Final"},
        {"game_id": "0022600002", "game_status_text": "Final"},
        {"game_id": "0022600003", "game_status_text": "Final"},
    ])

    # Team logs:
    # Game 1 has 2 team rows (complete)
    # Game 2 has only 1 team row (defective)
    # Game 3 is missing entirely
    # Total rows = 3, but only 1 game is truly complete!
    team_logs_df = pd.DataFrame([
        {"game_id": "0022600001", "team_id": 1610612738},
        {"game_id": "0022600001", "team_id": 1610612744},
        {"game_id": "0022600002", "team_id": 1610612739},
    ])

    report = audit_backfill_completeness(schedule_df, team_logs_df)

    assert report["status"] == "PARTIAL"
    assert report["expected_completed_games"] == 3
    assert report["complete_completed_games"] == 1
    assert "0022600003" in report["missing_game_ids"]
    assert "0022600002" in report["mismatched_team_row_games"]


# --------------------------------------------------------------------------
# Item 3: CircuitBreaker & Single-Owner Lease Lock
# --------------------------------------------------------------------------
def test_circuit_breaker_transitions_and_guard():
    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=2.0)
    assert cb.state == CircuitState.CLOSED
    assert cb.can_execute() is True

    # 1st and 2nd transient failures -> remains CLOSED
    cb.record_failure(is_fatal=False)
    assert cb.state == CircuitState.CLOSED
    cb.record_failure(is_fatal=False)
    assert cb.state == CircuitState.CLOSED

    # 3rd transient failure -> trips to OPEN
    cb.record_failure(is_fatal=False)
    assert cb.state == CircuitState.OPEN
    assert cb.can_execute() is False

    with pytest.raises(CircuitBreakerOpenException):
        cb.check_and_guard()

    # Fast forward past cooldown
    cb.cooldown_until = time.time() - 0.1
    # Can execute probe in HALF_OPEN
    assert cb.can_execute() is True
    assert cb.state == CircuitState.HALF_OPEN

    # Probe success resets to CLOSED
    cb.record_success()
    assert cb.state == CircuitState.CLOSED
    assert cb.consecutive_failures == 0


def test_circuit_breaker_immediate_trip_on_fatal_429():
    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=600.0)
    # Immediate 429 fatal response trips breaker on attempt 1
    cb.record_failure(is_fatal=True, retry_after=600.0)
    assert cb.state == CircuitState.OPEN
    assert cb.can_execute() is False


def test_sync_single_owner_lease(tmp_path):
    lock_file = tmp_path / "test_sync_lock.json"
    lease_lock = SyncLeaseLock(lock_file=lock_file, lease_ttl_sec=10.0)

    # Worker A acquires
    assert lease_lock.acquire("worker_A") is True
    assert lease_lock.is_locked() is True

    # Worker B tries to acquire concurrently -> rejected
    assert lease_lock.acquire("worker_B") is False

    # Worker A releases
    lease_lock.release("worker_A")
    assert lease_lock.is_locked() is False

    # Worker B can now acquire
    assert lease_lock.acquire("worker_B") is True
    lease_lock.release("worker_B")


# --------------------------------------------------------------------------
# Item 4 & 5: API Async Sync 202 and Health Probes
# --------------------------------------------------------------------------
@pytest.fixture
def client():
    return TestClient(app)


def test_api_health_live_and_ready(client):
    # Liveness check (HTTP 200, lightweight)
    res_live = client.get("/api/health/live")
    assert res_live.status_code == 200
    data_live = res_live.json()
    assert data_live["status"] == "alive"
    assert "timestamp" in data_live

    # Readiness check
    res_ready = client.get("/api/health/ready")
    assert res_ready.status_code in (200, 503)
    data_ready = res_ready.json()
    assert "checks" in data_ready
    assert "sync_lock_active" in data_ready["checks"]


def test_api_async_sync_returns_202(client, monkeypatch):
    import src.collectors.sync as sync_mod
    monkeypatch.setattr(
        sync_mod,
        "sync_season_data",
        lambda season, force_refresh, job_id, client=None: {
            "status": "SUCCESS",
            "run_id": job_id,
            "season": season,
            "duration_sec": 0.05,
        },
    )
    res = client.post("/api/sync/run", json={"season": "2026-27", "force_refresh": False})
    assert res.status_code == 202
    data = res.json()
    assert "job_id" in data
    assert data["status"] in (SyncJobStatus.QUEUED.value, SyncJobStatus.RUNNING.value)

    # Query status
    job_id = data["job_id"]
    res_status = client.get(f"/api/sync/status/{job_id}")
    assert res_status.status_code == 200
    status_data = res_status.json()
    assert status_data["job_id"] == job_id


# --------------------------------------------------------------------------
# Item 8: American odds conversion, de-vig matching, and refund-adjusted Kelly
# --------------------------------------------------------------------------
def test_american_to_decimal_and_back():
    # Positive odds (+150) -> 1 + 150/100 = 2.50
    d_pos = american_to_decimal(150)
    assert d_pos == 2.50
    assert decimal_to_american(2.50) == 150

    # Negative odds (-110) -> 1 + 100/110 = 1.909091
    d_neg = american_to_decimal(-110)
    assert d_neg == pytest.approx(1.909091, rel=1e-5)
    assert decimal_to_american(d_neg) == -110

    # Negative odds (-200) -> 1 + 100/200 = 1.50
    assert american_to_decimal(-200) == 1.50
    assert decimal_to_american(1.50) == -200

    # Invalid: |a| < 100
    with pytest.raises(ValueError, match="Must satisfy |odds| >= 100"):
        american_to_decimal(50)
    with pytest.raises(ValueError, match="Must satisfy |odds| >= 100"):
        american_to_decimal(0)
    with pytest.raises(ValueError, match="Must satisfy |odds| >= 100"):
        american_to_decimal(-80)


def test_devig_multiplicative_matching_and_ev():
    # Symmetrical -110 / -110 (decimal ~1.909)
    d = american_to_decimal(-110)
    devig = remove_vig_multiplicative(odds_over=d, odds_under=d)
    assert devig["fair_over"] == 0.50
    assert devig["fair_under"] == 0.50
    assert devig["overround"] > 0.04

    # Mismatched lines check
    with pytest.raises(ValueError, match="Mismatched lines"):
        remove_vig_multiplicative(odds_over=1.9, odds_under=1.9, line_over=24.5, line_under=25.5)

    # EV with push/refund: prob_win * (d - 1) - prob_loss
    # For fair 50/50 and odds 2.10 (positive edge): 0.5 * 1.10 - 0.5 * 1.0 = 0.55 - 0.50 = +0.05
    ev = calculate_ev(prob_win=0.50, prob_loss=0.50, decimal_odds=2.10)
    assert ev == 0.05


def test_kelly_refund_formula_and_safety_guard():
    # Let d = 2.0 (even money), p_win = 0.55, p_loss = 0.40, p_push = 0.05
    # r = p_win / (p_win + p_loss) = 0.55 / 0.95 = 0.578947
    # f* = (d * r - 1) / (d - 1) = (2.0 * 0.578947 - 1) / 1.0 = 0.1579
    res_default = calculate_kelly_fraction(
        prob_win=0.55,
        prob_loss=0.40,
        decimal_odds=2.0,
        allow_recommendation=False,
    )
    # Default policy MUST hide recommendation
    assert res_default["kelly_recommendation"] is None
    assert res_default["reason"] == "STAKING_POLICY_UNVALIDATED"
    assert res_default["math_optimal_f"] == pytest.approx(0.1579, abs=1e-3)

    # When validated policy flag is True
    res_validated = calculate_kelly_fraction(
        prob_win=0.55,
        prob_loss=0.40,
        decimal_odds=2.0,
        allow_recommendation=True,
    )
    assert res_validated["kelly_recommendation"] == pytest.approx(0.1579, abs=1e-3)
    assert res_validated["reason"] == "VALIDATED_POLICY"


# --------------------------------------------------------------------------
# Item 9: Backend EV/Kelly guards in /api/predict
# --------------------------------------------------------------------------
def test_predict_endpoint_enforces_staking_guard_by_default(client):
    payload = {
        "player_id": 203999,  # Nikola Jokic
        "stat": "pts",
        "line": 26.5,
        "odds_over": 1.90,
        "odds_under": 1.90,
    }
    res = client.post("/api/predict", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert "pricing" in data
    if data["pricing"] is not None:
        pricing = data["pricing"]
        assert pricing["kelly_over"] is None
        assert pricing["kelly_under"] is None
        assert pricing["staking_reason"] == "STAKING_POLICY_UNVALIDATED"
        assert pricing["staking_policy_validated"] is False
        assert pricing["ev_type"] == "MODEL_IMPLIED"
