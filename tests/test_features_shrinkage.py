import pytest
import pandas as pd
import numpy as np

from src.features.shrinkage import (
    ShrinkageConfig,
    PriorSnapshot,
    fit_prior_snapshot,
    assign_role,
    map_position,
    compute_count_features,
    compute_shooting_features,
    compute_gamma_poisson_rate,
)

# 1. Legacy Baseline Compatibility Tests
def test_shrinkage_zero_history():
    df = pd.DataFrame([
        {"player_id": 1, "game_date": "2024-11-01", "game_id": "0022400001", "pts": 30, "min": 35.0},
    ])
    res = compute_gamma_poisson_rate(df, stat="pts", alpha_prior=25.0, beta_prior=50.0)
    assert res.iloc[0]["pts_rate_shrinkage"] == 0.5
    assert res.iloc[0]["pts_n_eff"] == 0.0
    assert res.iloc[0]["pts_exposure"] == 0.0

def test_shrinkage_calculation_and_anti_leakage():
    df = pd.DataFrame([
        {"player_id": 1, "game_date": "2024-11-01", "game_id": "0022400001", "pts": 10, "min": 20.0},
        {"player_id": 1, "game_date": "2024-11-03", "game_id": "0022400002", "pts": 20, "min": 20.0},
        {"player_id": 1, "game_date": "2024-11-05", "game_id": "0022400003", "pts": 40, "min": 30.0},
    ])
    res = compute_gamma_poisson_rate(df, stat="pts", alpha_prior=20.0, beta_prior=40.0, decay_halflife=None)
    assert res.iloc[1]["pts_rate_shrinkage"] == 0.5
    assert res.iloc[1]["pts_exposure"] == 20.0
    assert res.iloc[1]["pts_n_eff"] == 1.0

    assert res.iloc[2]["pts_rate_shrinkage"] == 0.625
    assert res.iloc[2]["pts_exposure"] == 40.0
    assert res.iloc[2]["pts_n_eff"] == 2.0

    df_altered = df.copy()
    df_altered.loc[2, "pts"] = 100
    res_altered = compute_gamma_poisson_rate(df_altered, stat="pts", alpha_prior=20.0, beta_prior=40.0, decay_halflife=None)
    assert res_altered.iloc[2]["pts_rate_shrinkage"] == res.iloc[2]["pts_rate_shrinkage"]

# 2. Section 14 Exact Numerical Verifications (§14.1, §14.2, §14.3)
def test_section_14_1_numerical_match():
    """
    Test exact numerical recipe from §14.1:
    League rate = 0.50, Position: T=2400, E=4000, tau=2000.
    mu_pos = (2400 + 2000*0.50) / (4000 + 2000) = 0.5666666667
    beta = 200 -> alpha = 113.3333333333
    Personal: S=60, E=100 -> rate = (113.3333333333 + 60) / (200 + 100) = 0.5777777778
    personal_weight = 1/3, prior_weight = 2/3
    """
    cfg = ShrinkageConfig(
        beta_rate=200.0,
        tau_group_minutes=2000.0,
        group_count_coverage_min_minutes=1000.0,
        group_count_coverage_min_players=5,
        league_count_coverage_min_minutes=1000.0,
        league_count_coverage_min_players=5,
    )
    snapshot = PriorSnapshot(cfg, origin_utc=pd.Timestamp("2026-11-10"))

    # Synthesize pool data
    snapshot.league_counts["pts"] = {"x": 5000.0, "m": 10000.0, "players": set(range(100))}  # 5000/10000 = 0.50
    snapshot.position_counts["guard"] = {
        "pts": {"x": 2400.0, "m": 4000.0, "players": set(range(50))}
    }

    alpha, beta, mu_final, fallback = snapshot.get_count_prior(
        player_id=999,
        position="guard",
        rotation="starter",
        stat="pts",
    )

    expected_mu_pos = (2400.0 + 2000.0 * 0.50) / (4000.0 + 2000.0)
    assert pytest.approx(mu_final, abs=1e-9) == expected_mu_pos
    assert pytest.approx(alpha, abs=1e-9) == 200.0 * expected_mu_pos
    assert beta == 200.0
    assert fallback == "position"

    # Personal: S=60, E=100
    s_personal = 60.0
    e_personal = 100.0
    rate = (alpha + s_personal) / (beta + e_personal)
    expected_rate = (113.33333333333333 + 60.0) / (200.0 + 100.0)
    assert pytest.approx(rate, abs=1e-9) == expected_rate
    assert pytest.approx(rate, abs=1e-9) == 0.5777777777777777
    assert pytest.approx(e_personal / (beta + e_personal), abs=1e-9) == 1.0 / 3.0
    assert pytest.approx(beta / (beta + e_personal), abs=1e-9) == 2.0 / 3.0

def test_section_14_2_inactivity_decay():
    """
    Test exact inactivity decay from §14.2:
    After 20 days with H=20, all weights scale by 0.5 -> S=30, E=50
    rate = (113.3333333333 + 30) / (200 + 50) = 0.5733333333
    prior_weight increases from 2/3 to 0.8; ESS unchanged!
    """
    alpha = 113.33333333333333
    beta = 200.0
    s_decayed = 30.0
    e_decayed = 50.0

    rate_inactivity = (alpha + s_decayed) / (beta + e_decayed)
    expected_rate = 143.33333333333333 / 250.0
    assert pytest.approx(rate_inactivity, abs=1e-9) == expected_rate
    assert pytest.approx(rate_inactivity, abs=1e-9) == 0.5733333333333334
    assert pytest.approx(beta / (beta + e_decayed), abs=1e-9) == 0.8

def test_section_14_3_accuracy_beta_smoothing():
    """
    Test exact shooting accuracy from §14.3:
    Prior p_g = 0.35, kappa = 100 -> a = 35, b = 65
    Weighted made = 12, weighted attempts = 30
    p_hat = (35 + 12) / (100 + 30) = 47 / 130 = 0.3615384615
    """
    p_g = 0.35
    kappa = 100.0
    w_made = 12.0
    w_att = 30.0

    p_hat = (kappa * p_g + w_made) / (kappa + w_att)
    assert pytest.approx(p_hat, abs=1e-9) == 47.0 / 130.0
    assert pytest.approx(p_hat, abs=1e-9) == 0.36153846153846153

# 3. Data Contract & Input Guardrail Tests (§4)
def test_input_guards_negative_and_nonfinite():
    snapshot = PriorSnapshot(ShrinkageConfig(), origin_utc=pd.Timestamp("2026-11-10"))

    # Negative stat
    df_neg = pd.DataFrame([
        {"player_id": 1, "game_date": "2024-11-01", "game_id": "G1", "pts": -10, "min": 20.0}
    ])
    with pytest.raises(ValueError, match="negative"):
        compute_count_features(df_neg, pd.DataFrame([{"player_id": 1, "game_date": "2024-11-05"}]), snapshot)

    # Non-finite minutes
    df_inf = pd.DataFrame([
        {"player_id": 1, "game_date": "2024-11-01", "game_id": "G1", "pts": 10, "min": np.inf}
    ])
    with pytest.raises(ValueError, match="non-finite"):
        compute_count_features(df_inf, pd.DataFrame([{"player_id": 1, "game_date": "2024-11-05"}]), snapshot)

    # Invalid half life <= 0
    with pytest.raises(ValueError, match="half_life_days"):
        cfg_bad = ShrinkageConfig(half_life_days=0)
        cfg_bad.validate()

    with pytest.raises(ValueError, match="beta_rate"):
        cfg_bad_beta = ShrinkageConfig(beta_rate=-5.0)
        cfg_bad_beta.validate()

# 4. Position & Role Hierarchy Tests (§6)
def test_position_and_role_mapping():
    assert map_position("PG") == "guard"
    assert map_position("SG") == "guard"
    assert map_position("SF") == "wing"
    assert map_position("PF") == "big"
    assert map_position("C") == "big"
    assert map_position("Unknown_Pos") == "unknown"

    # Role assignment: >= 5 starts out of 10
    history = pd.DataFrame([
        {"game_date": f"2024-11-0{i}", "team_abbreviation": "LAL", "started": 1 if i <= 6 else 0}
        for i in range(1, 10)
    ])
    role_starter = assign_role(history, current_team="LAL", cutoff_time=pd.Timestamp("2024-11-15"), position_hint="PG")
    assert role_starter.position == "guard"
    assert role_starter.rotation == "starter"
    assert role_starter.start_share > 0.5

    # Role assignment: < 5 games -> unknown
    history_short = history.head(3)
    role_unk = assign_role(history_short, current_team="LAL", cutoff_time=pd.Timestamp("2024-11-15"), position_hint="SF")
    assert role_unk.position == "wing"
    assert role_unk.rotation == "unknown"

# 5. Temporal Independence & Leave-Player-Out Subtraction Tests (§7 & §13)
def test_leave_player_out_subtraction():
    cfg = ShrinkageConfig(
        group_count_coverage_min_minutes=50.0,
        group_count_coverage_min_players=1,
        league_count_coverage_min_minutes=50.0,
        league_count_coverage_min_players=1,
    )
    # 2 players in guard position
    df_train = pd.DataFrame([
        {"player_id": 1, "game_date": "2024-11-01", "game_id": "G1", "position": "PG", "pts": 50, "min": 100.0, "started": 1},
        {"player_id": 2, "game_date": "2024-11-01", "game_id": "G2", "position": "SG", "pts": 100, "min": 200.0, "started": 1},
    ])
    snapshot = fit_prior_snapshot(df_train, origin_utc=pd.Timestamp("2024-11-05"), config=cfg)

    # For player 1: leave player 1 out -> only player 2 remains (pts=100, min=200 -> rate = 0.5)
    alpha_1, beta_1, mu_1, _ = snapshot.get_count_prior(player_id=1, position="guard", rotation="starter", stat="pts")
    assert pytest.approx(mu_1, abs=1e-5) == 100.0 / 200.0

    # For player 2: leave player 2 out -> only player 1 remains (pts=50, min=100 -> rate = 0.5)
    alpha_2, beta_2, mu_2, _ = snapshot.get_count_prior(player_id=2, position="guard", rotation="starter", stat="pts")
    assert pytest.approx(mu_2, abs=1e-5) == 50.0 / 100.0
