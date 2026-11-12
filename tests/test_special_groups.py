"""
Tests for Special Groups & Review/Fix Spec:
Validates all requirements of NBA_SPECIAL_GROUPS_REVIEW_AND_FIX_SPEC.md:
- Precedence of operational states (§10)
- Return episode deterministic state machine (§6)
- Team continuous stint tracking and recent transfer flag (§7)
- Rate shrinkage with exposure > 0 not overridden to prior-only (§3)
- Rotation under 5 labels is unknown, not bench (§8.1)
- Trend 5v20 requires 20 appearances (§8.2)
- NB2 dispersion proof: median shift and tail probability (§4.1)
- Dispersion pooled default vs legacy mode (§5)
"""

import numpy as np
import pandas as pd
import pytest
from scipy.stats import nbinom

from src.distribution.special_groups import (
    assess_player_condition,
    calculate_return_episode_state,
    calculate_team_stint_state,
    adjust_dispersion_for_uncertainty,
)
from src.features.shrinkage import (
    ShrinkageConfig,
    PriorSnapshot,
    assign_role,
    compute_count_features,
)


def test_operational_state_precedence():
    """Validates §10 Precedence: INSUFFICIENT_DATA > SCENARIO_ONLY > READY."""
    # 1. Critical schema fail -> INSUFFICIENT_DATA
    row_no_id = pd.Series({"n_games_history": 20})
    cond_no_id = assess_player_condition(row_no_id, has_valid_model=True)
    assert cond_no_id["operational_state"] == "INSUFFICIENT_DATA"
    assert cond_no_id["forecast_status"] == "not_issued"
    assert "SCHEMA_OR_MODEL_UNAVAILABLE" in cond_no_id["reason_codes"]

    # 2. Player ruled OUT -> SCENARIO_ONLY with not_issued
    row_out = pd.Series({"player_id": 101, "n_games_history": 30, "injury_status": "OUT"})
    cond_out = assess_player_condition(row_out)
    assert cond_out["operational_state"] == "SCENARIO_ONLY"
    assert cond_out["forecast_status"] == "not_issued"
    assert "PLAYER_RULED_OUT" in cond_out["reason_codes"]

    # 3. Questionable status -> SCENARIO_ONLY with conditional_scenario
    row_quest = pd.Series({"player_id": 102, "n_games_history": 30, "injury_status": "QUESTIONABLE"})
    cond_quest = assess_player_condition(row_quest)
    assert cond_quest["operational_state"] == "SCENARIO_ONLY"
    assert cond_quest["forecast_status"] == "conditional_scenario"
    assert "QUESTIONABLE_INJURY_STATUS" in cond_quest["reason_codes"]

    # 4. Low history (<5 games) -> SCENARIO_ONLY with conditional_scenario
    row_low = pd.Series({"player_id": 103, "n_games_history": 3, "injury_status": "ACTIVE"})
    cond_low = assess_player_condition(row_low)
    assert cond_low["operational_state"] == "SCENARIO_ONLY"
    assert cond_low["forecast_status"] == "conditional_scenario"
    assert "LOW_HISTORY_COHORT" in cond_low["reason_codes"]

    # 5. Low minutes alone (<10 min) for veteran player does NOT reject, issues READY with bench conditioning
    row_bench = pd.Series({
        "player_id": 104,
        "n_games_history": 40,
        "min_roll_mean_5": 7.5,
        "injury_status": "ACTIVE",
    })
    cond_bench = assess_player_condition(row_bench)
    assert cond_bench["operational_state"] == "READY"
    assert cond_bench["forecast_status"] == "issued"
    assert "BENCH_LIMITED_ROTATION" in cond_bench["reason_codes"]

    # 6. Standard veteran -> READY with given_player_enters_game
    row_ready = pd.Series({
        "player_id": 105,
        "n_games_history": 40,
        "min_roll_mean_5": 32.0,
        "rest_days": 2,
        "injury_status": "ACTIVE",
    })
    cond_ready = assess_player_condition(row_ready)
    assert cond_ready["operational_state"] == "READY"
    assert cond_ready["forecast_status"] == "issued"
    assert cond_ready["conditioning"] == "given_player_enters_game"


def test_return_episode_state_machine():
    """Validates §6 deterministic return episode state machine."""
    # Day 0: 2024-01-01, Day 1: 2024-01-03
    # Player then misses 20 days until 2024-01-23 (target g0)
    base_dates = [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-03")]
    target_cutoff_g0 = pd.Timestamp("2024-01-23 18:00:00")

    # Target g0: after 20 days inactivity
    state_g0 = calculate_return_episode_state(base_dates, target_cutoff_g0)
    assert state_g0["long_absence_flag"] is True
    assert state_g0["return_candidate"] is True
    assert state_g0["return_games_observed"] == 0
    assert state_g0["return_episode_active"] is True

    # Exactly 14.0 days boundary check
    target_14d = pd.Timestamp("2024-01-17")  # 14 days from 2024-01-03
    state_14d = calculate_return_episode_state(base_dates, target_14d)
    assert state_14d["long_absence_flag"] is True
    assert state_14d["return_episode_active"] is True

    # 13.9 days boundary check -> not long absence
    target_13d = pd.Timestamp("2024-01-16 20:00:00")  # < 14 days
    state_13d = calculate_return_episode_state(base_dates, target_13d)
    assert state_13d["long_absence_flag"] is False
    assert state_13d["return_candidate"] is False

    # Target g1: Player actually played g0 on 2024-01-23 18:00!
    # Next game g1 is on 2024-01-25 18:00 (exactly 2 days later)
    played_after_g0 = base_dates + [pd.Timestamp("2024-01-23 18:00:00")]
    target_cutoff_g1 = pd.Timestamp("2024-01-25 18:00:00")

    state_g1 = calculate_return_episode_state(played_after_g0, target_cutoff_g1)
    assert state_g1["days_since_last_appearance"] == pytest.approx(2.0, 0.01)
    assert state_g1["long_absence_flag"] is False
    assert state_g1["return_candidate"] is False
    assert state_g1["return_games_observed"] == 1
    assert state_g1["return_episode_active"] is True  # Still active for game 2!

    # Target g2: Player played g1 on 2024-01-25 18:00. Next game on 2024-01-27 18:00
    played_after_g1 = played_after_g0 + [pd.Timestamp("2024-01-25 18:00:00")]
    target_cutoff_g2 = pd.Timestamp("2024-01-27 18:00:00")
    state_g2 = calculate_return_episode_state(played_after_g1, target_cutoff_g2)
    assert state_g2["return_games_observed"] == 2
    assert state_g2["return_episode_active"] is True  # Still active for game 3!

    # Target g3: Player played g2 on 2024-01-27 18:00. Next game on 2024-01-29 18:00
    played_after_g2 = played_after_g1 + [pd.Timestamp("2024-01-27 18:00:00")]
    target_cutoff_g3 = pd.Timestamp("2024-01-29 18:00:00")
    state_g3 = calculate_return_episode_state(played_after_g2, target_cutoff_g3)
    assert state_g3["return_games_observed"] == 3
    assert state_g3["return_episode_active"] is False  # Concluded after 3 appearances!


def test_team_stint_tracking_and_transfer_flag():
    """Validates §7 Team Stint tracking and recent transfer flag."""
    # 1. Player traded from BOS to DAL:
    # 40 games at BOS, then 5 games at DAL
    history = ["BOS"] * 40 + ["DAL"] * 5
    stint_5 = calculate_team_stint_state(history, current_team="DAL")
    assert stint_5["games_current_stint_observed"] == 5
    assert stint_5["team_change_observed"] is True
    assert stint_5["recent_transfer_flag"] is True  # < 10 appearances

    # After 10 games at DAL:
    history_10 = ["BOS"] * 40 + ["DAL"] * 10
    stint_10 = calculate_team_stint_state(history_10, current_team="DAL")
    assert stint_10["games_current_stint_observed"] == 10
    assert stint_10["recent_transfer_flag"] is False  # No longer recent transfer!

    # After 50 games at DAL:
    history_50 = ["BOS"] * 40 + ["DAL"] * 50
    stint_50 = calculate_team_stint_state(history_50, current_team="DAL")
    assert stint_50["games_current_stint_observed"] == 50
    assert stint_50["recent_transfer_flag"] is False

    # 2. True rookie playing only for GSW (20 games):
    rookie_hist = ["GSW"] * 20
    stint_rookie = calculate_team_stint_state(rookie_hist, current_team="GSW")
    assert stint_rookie["games_current_stint_observed"] == 20
    assert stint_rookie["team_change_observed"] is False
    assert stint_rookie["recent_transfer_flag"] is False

    # 3. Returning to former team in a new stint:
    # MIA -> LAL -> MIA (5 games in second stint)
    return_hist = ["MIA"] * 20 + ["LAL"] * 10 + ["MIA"] * 5
    stint_ret = calculate_team_stint_state(return_hist, current_team="MIA")
    assert stint_ret["games_current_stint_observed"] == 5  # Only current continuous stint!
    assert stint_ret["team_change_observed"] is True
    assert stint_ret["recent_transfer_flag"] is True


def test_shrinkage_two_games_with_exposure_not_prior_only():
    """Validates §3: 2 games with exposure > 0 must not be overridden to 100% prior."""
    # Section 3 numerical specification:
    # beta = 200 min, mu_prior = 0.50 PTS/min -> alpha_prior = 100.0
    # Player has weighted minutes E = 60, weighted points S = 48
    # personal_weight = 60 / (200 + 60) = 60/260 ≈ 0.230769
    # rate = (100 + 48) / 260 = 148 / 260 ≈ 0.569231
    cfg = ShrinkageConfig(beta_rate=200.0, half_life_days=20.0)
    origin = pd.Timestamp("2024-01-01")
    snapshot = PriorSnapshot(cfg, origin_utc=origin)

    # Mock league prior with mu = 0.50
    snapshot.league_counts["pts"] = {"x": 5000.0, "m": 10000.0, "players": set(range(50))}

    # History with 2 games
    hist_df = pd.DataFrame({
        "player_id": [999, 999],
        "game_end_dt": [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-01")],  # 0 days elapsed
        "min": [30.0, 30.0],  # E = 60 min
        "pts": [24.0, 24.0],  # S = 48 pts
        "position": ["PG", "PG"],
    })

    # Target df with cutoff 1 second after game end (age_days ≈ 0, weight = 1.0)
    target_df = pd.DataFrame({
        "player_id": [999],
        "prediction_cutoff_utc": [pd.Timestamp("2024-01-01 00:00:01")],
        "position": ["PG"],
    })

    res = compute_count_features(hist_df, target_df, snapshot, cfg, quantities=["pts"])
    assert len(res) == 1
    row = res.iloc[0]

    assert row["pts_exposure_minutes"] == pytest.approx(60.0, 0.01)
    assert row["pts_weighted_count"] == pytest.approx(48.0, 0.01)
    assert row["pts_personal_weight"] == pytest.approx(60.0 / 260.0, 1e-4)
    assert row["pts_prior_weight"] == pytest.approx(200.0 / 260.0, 1e-4)
    # Shrunk rate MUST be 148 / 260 ≈ 0.569231, NOT 0.50
    assert row["pts_rate_shrunk"] == pytest.approx(148.0 / 260.0, 1e-4)
    assert row["pts_rate_shrunk"] != 0.50


def test_rotation_under_5_started_labels_is_unknown():
    """Validates §8.1: Under 5 started labels must be classified as unknown, not bench."""
    # Player with only 3 appearances with started labels [0, 0, 0]
    hist_df = pd.DataFrame({
        "game_end_dt": pd.date_range("2024-01-01", periods=3, freq="D"),
        "team_abbreviation": ["BOS", "BOS", "BOS"],
        "started": [0, 0, 0],
        "position": ["PG", "PG", "PG"],
    })
    cutoff = pd.Timestamp("2024-01-05")
    role_ctx = assign_role(hist_df, current_team="BOS", cutoff_time=cutoff, position_hint="PG")

    assert role_ctx.rotation == "unknown"  # Must NOT be bench!
    assert role_ctx.leaf_group == ("guard", "unknown")

    # With 5 starts [1, 1, 1, 0, 0] (share = 3/5 = 0.60 >= 0.5) -> starter
    cutoff_5 = pd.Timestamp("2024-01-06")
    hist_5_starter = pd.DataFrame({
        "game_end_dt": pd.date_range("2024-01-01", periods=5, freq="D"),
        "team_abbreviation": ["BOS"] * 5,
        "started": [1, 1, 1, 0, 0],
        "position": ["PG"] * 5,
    })
    role_starter = assign_role(hist_5_starter, current_team="BOS", cutoff_time=cutoff_5, position_hint="PG")
    assert role_starter.rotation == "starter"

    # With 5 starts [0, 0, 0, 1, 0] (share = 1/5 = 0.20 < 0.5) -> bench
    hist_5_bench = pd.DataFrame({
        "game_end_dt": pd.date_range("2024-01-01", periods=5, freq="D"),
        "team_abbreviation": ["BOS"] * 5,
        "started": [0, 0, 0, 1, 0],
        "position": ["PG"] * 5,
    })
    role_bench = assign_role(hist_5_bench, current_team="BOS", cutoff_time=cutoff_5, position_hint="PG")
    assert role_bench.rotation == "bench"


def test_trend_5v20_requires_20_appearances():
    """Validates §8.2: minutes_trend_5v20 requires at least 20 appearances."""
    cfg = ShrinkageConfig()
    snapshot = PriorSnapshot(cfg, origin_utc=pd.Timestamp("2024-05-01"))
    snapshot.league_counts["pts"] = {"x": 5000.0, "m": 10000.0, "players": set(range(50))}

    # Case 1: 15 appearances (< 20)
    dates_15 = pd.date_range("2024-01-01", periods=15, freq="2D")
    hist_15 = pd.DataFrame({
        "player_id": [1] * 15,
        "game_end_dt": dates_15,
        "min": [30.0] * 15,
        "pts": [15.0] * 15,
        "position": ["SG"] * 15,
    })
    target_15 = pd.DataFrame({
        "player_id": [1],
        "prediction_cutoff_utc": [pd.Timestamp("2024-02-15")],
        "position": ["SG"],
    })
    res_15 = compute_count_features(hist_15, target_15, snapshot, cfg, quantities=["pts"])
    assert np.isnan(res_15.iloc[0]["minutes_trend_5v20"])
    assert res_15.iloc[0]["role_shift_candidate"] == 0

    # Case 2: 25 appearances with sharp minutes increase (prev5 avg 36m, prev20 avg 20m -> trend +16m)
    dates_25 = pd.date_range("2024-01-01", periods=25, freq="2D")
    mins_25 = [20.0] * 20 + [36.0] * 5
    hist_25 = pd.DataFrame({
        "player_id": [2] * 25,
        "game_end_dt": dates_25,
        "min": mins_25,
        "pts": [15.0] * 25,
        "position": ["SG"] * 25,
    })
    target_25 = pd.DataFrame({
        "player_id": [2],
        "prediction_cutoff_utc": [pd.Timestamp("2024-03-01")],
        "position": ["SG"],
    })
    res_25 = compute_count_features(hist_25, target_25, snapshot, cfg, quantities=["pts"])
    trend_val = res_25.iloc[0]["minutes_trend_5v20"]
    assert not np.isnan(trend_val)
    # mean(prev5)=36, mean(prev20)=(15*20 + 5*36)/20 = 24.0 -> trend = 36 - 24 = 12.0
    assert trend_val == pytest.approx(12.0, 0.1)
    assert res_25.iloc[0]["role_shift_candidate"] == 1


def test_scipy_nb2_median_shift_and_tail_proof():
    """
    Validates §4.1 SciPy proof:
    Increasing dispersion phi shifts the median and inflates tail probabilities,
    proving that ad-hoc dispersion inflation violates invariance and conservatism.
    """
    mu = 20.0
    # phi = 0.02
    size_02 = 1.0 / 0.02
    prob_02 = size_02 / (size_02 + mu)
    dist_02 = nbinom(size_02, prob_02)

    # phi = 0.12 (simulates +0.10 inflation)
    size_12 = 1.0 / 0.12
    prob_12 = size_12 / (size_12 + mu)
    dist_12 = nbinom(size_12, prob_12)

    assert dist_02.mean() == pytest.approx(20.0, 1e-4)
    assert dist_12.mean() == pytest.approx(20.0, 1e-4)

    # Median drops from 20 to 19!
    assert dist_02.ppf(0.5) == 20.0
    assert dist_12.ppf(0.5) == 19.0

    # Upper tail probability P(X > 35) increases tenfold!
    assert dist_02.sf(35) == pytest.approx(0.004528, 1e-4)
    assert dist_12.sf(35) == pytest.approx(0.045645, 1e-4)
    assert dist_12.sf(35) > dist_02.sf(35) * 9.0


def test_dispersion_modes():
    """Validates §5: Pooled default mode vs legacy manual inflation mode."""
    base_phi = 0.04

    # Default pooled mode returns base_phi directly without ad-hoc inflation
    phi_pooled = adjust_dispersion_for_uncertainty(base_phi, n_eff=1.0, is_returning=True, mode="pooled")
    assert phi_pooled == 0.04

    # Legacy mode retains manual inflation for comparison
    phi_legacy = adjust_dispersion_for_uncertainty(base_phi, n_eff=1.0, is_returning=True, mode="legacy_manual_inflation")
    # (5 - 1) * 0.02 = 0.08 + 0.04 (returning) = +0.12 -> 0.04 + 0.12 = 0.16
    assert phi_legacy == pytest.approx(0.16, 0.001)

    # Invalid mode raises ValueError
    with pytest.raises(ValueError):
        adjust_dispersion_for_uncertainty(base_phi, mode="invalid_mode")
