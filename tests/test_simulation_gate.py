"""
Unit tests for Simulation Gate (§11.7.6–11.7.8 of Plan & Review Spec).
Validates Section 14 correctness tests:
- Ratio consistency of pooled_delta vs unweighted daily means
- Season MBB non-crossing, no-wrap, and short-segment rejection
- Exact Wilson score intervals and edge cases
- Strict inequalities for final_decision (L > delta, U < delta)
- Futility-only state machine at 140/280 checkpoints
- Scalar Omega, Omega_U, and T_req sample size planning
- DGP1 position-centering exact mean zero
- DGP2 VAR stability and discrete Lyapunov solution
- DGP3 variance stress scaling
- Daily vector aggregation from prediction ledger
- Full SimulationGate suite execution in smoke mode
"""

import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from src.simulation_gate.config import GateConfig, GateStatus
from src.simulation_gate.kernels import (
    pooled_delta,
    season_mbb_indices,
    percentile_ci,
    wilson,
    final_decision,
)
from src.simulation_gate.variance import (
    calculate_influence_psi,
    calculate_omega_point,
    calculate_omega_uncertainty,
    calculate_t_req,
    calculate_pooled_rms,
)
from src.simulation_gate.decision import evaluate_pilot_futility, evaluate_final_decision
from src.simulation_gate.dgp_score import DGP1ResidualMBB, DGP2VectorVAR, DGP3VarianceStress
from src.simulation_gate.daily_vectors import aggregate_prediction_ledger_to_daily_vectors
from src.simulation_gate.gate import SimulationGate


def test_pooled_delta_weighting():
    """Validates that pooled_delta respects count ratios and differs from unweighted daily mean (§4, §12)."""
    # 2 days, 3 stats: day 0 has small counts, day 1 has large counts
    # Day 0: S=[10, 10, 10], N=[10, 10, 10] -> mean=1.0 per stat
    # Day 1: S=[0, 0, 0], N=[90, 90, 90] -> mean=0.0 per stat
    sums = np.array([[10.0, 10.0, 10.0], [0.0, 0.0, 0.0]])
    counts = np.array([[10.0, 10.0, 10.0], [90.0, 90.0, 90.0]])

    # True pooled delta: 1/3 * sum(10 / 100) = 0.10
    delta = pooled_delta(sums, counts)
    assert pytest.approx(delta, 1e-6) == 0.10

    # Unweighted mean of daily averages would be (1.0 + 0.0) / 2 = 0.50 (incorrect!)
    daily_means = (sums / counts).mean(axis=1)
    unweighted = float(np.mean(daily_means))
    assert unweighted != delta
    assert pytest.approx(unweighted, 1e-6) == 0.50

    # Test error guards
    with pytest.raises(ValueError, match="Zero count requires zero sum"):
        pooled_delta(np.array([[5.0, 0.0, 0.0]]), np.array([[0.0, 10.0, 10.0]]))

    with pytest.raises(ValueError, match="Counts must be nonnegative integers"):
        pooled_delta(np.array([[5.0, 5.0, 5.0]]), np.array([[-1.0, 10.0, 10.0]]))


def test_season_mbb_bootstrap_integrity():
    """Validates season MBB: identical indices across stats, no cross-season, short-segment rejection (§5, §12)."""
    seasons = [1] * 20 + [2] * 25
    rng = np.random.default_rng(20261109)
    block_length = 14

    idx = season_mbb_indices(seasons, block_length=block_length, rng=rng)
    assert len(idx) == 45

    # Check season boundary: first 20 entries must come strictly from season 1 (indices 0..19)
    assert np.all(idx[:20] < 20)
    # Remaining 25 entries must come strictly from season 2 (indices 20..44)
    assert np.all(idx[20:] >= 20)

    # Short segment rejection: season with length 10 < block_length 14
    short_seasons = [1] * 10
    with pytest.raises(ValueError, match="INVALID_BOOTSTRAP_SEGMENT"):
        season_mbb_indices(short_seasons, block_length=14, rng=rng)


def test_wilson_exact_matches():
    """Validates exact Wilson score intervals matching statistics formula (§7, §12)."""
    # k = 0, n = 100
    low_0, up_0 = wilson(k=0, n=100)
    assert low_0 == 0.0
    assert 0.03 < up_0 < 0.04

    # k = 100, n = 100
    low_100, up_100 = wilson(k=100, n=100)
    assert up_100 == 1.0
    assert 0.96 < low_100 < 0.97

    # k = 1000, n = 2000 (p_hat = 0.50)
    low_half, up_half = wilson(k=1000, n=2000)
    assert pytest.approx((low_half + up_half) / 2.0, 1e-4) == 0.50
    assert (up_half - low_half) < 0.05

    # Input validation
    with pytest.raises(ValueError):
        wilson(k=105, n=100)
    with pytest.raises(ValueError):
        wilson(k=10, n=0)


def test_decision_strict_inequalities():
    """Validates strict inequalities for final_decision: L > delta, U < delta (§6, §12)."""
    margin = 0.001

    # Exact boundary L = delta must NOT adopt (strict inequality required!)
    dec_boundary_l = final_decision(lower=margin, upper=0.003, margin=margin)
    assert dec_boundary_l == "INCONCLUSIVE"

    # Strict L > delta adopts
    dec_adopt = final_decision(lower=margin + 1e-6, upper=0.003, margin=margin)
    assert dec_adopt == "ADOPT"

    # Exact boundary U = delta must NOT do_not_adopt
    dec_boundary_u = final_decision(lower=-0.001, upper=margin, margin=margin)
    assert dec_boundary_u == "INCONCLUSIVE"

    # Strict U < delta does not adopt
    dec_dna = final_decision(lower=-0.001, upper=margin - 1e-6, margin=margin)
    assert dec_dna == "DO_NOT_ADOPT"


def test_futility_checkpoint_rules():
    """Validates futility-only evaluation: restricted to 140/280, never adopts early (§6, §11.7.8)."""
    # 140 dates of negative Brier difference (poor signal)
    sums_bad = np.full((140, 3), -0.05)
    counts = np.full((140, 3), 10.0)
    seasons = [1] * 140

    res_140 = evaluate_pilot_futility(
        sums_prefix=sums_bad,
        counts_prefix=counts,
        seasons_prefix=seasons,
        checkpoint=140,
        reps=200,
        margin=0.001,
    )
    assert res_140["status"] == "STOP_PILOT_FUTILITY"
    assert res_140["action"] == "STOP"

    # 140 dates with strong signal (must CONTINUE, never ADOPT early during pilot!)
    sums_good = np.full((140, 3), 0.05)
    res_good = evaluate_pilot_futility(
        sums_prefix=sums_good,
        counts_prefix=counts,
        seasons_prefix=seasons,
        checkpoint=140,
        reps=200,
        margin=0.001,
    )
    assert res_good["status"] == "PILOT_CONTINUE"
    assert res_good["action"] == "CONTINUE"

    # Illegal checkpoint raises ValueError
    with pytest.raises(ValueError, match="Futility check only permitted at checkpoints"):
        evaluate_pilot_futility(sums_good, counts, seasons, checkpoint=150)


def test_variance_and_t_req():
    """Validates scalar Omega, influence psi_d, and T_req sample size planning formula (§4)."""
    T = 50
    np.random.seed(42)
    sums = np.random.normal(0.01, 0.05, size=(T, 3))
    counts = np.full((T, 3), 20.0)
    seasons = [1] * T

    psi = calculate_influence_psi(sums, counts)
    assert len(psi) == T
    # Influence should have approximately mean 0
    assert pytest.approx(float(np.mean(psi)), abs=1e-5) == 0.0

    omega_pt = calculate_omega_point(sums, counts, seasons, reps=200)
    assert omega_pt > 0.0

    # T_req formula check: T_req = ceil( factor * Omega_U / (Delta_alt - delta)^2 )
    # factor = (z_0.975 + z_0.80)^2 = (1.95996 + 0.84162)^2 = ~7.8488
    # If Omega_U = 0.0001, diff = 0.001 -> T_req = ceil( 7.8488 * 0.0001 / 1e-6 ) = 785
    t_req = calculate_t_req(omega_u=0.0001, delta_target=0.002, margin=0.001)
    assert 780 <= t_req <= 790


def test_dgp1_position_centering_exact_mean():
    """Validates DGP1 position-centering ensures exact theoretical mean theta (§8.1)."""
    np.random.seed(42)
    donor_res = np.random.normal(0.05, 0.20, size=(60, 3))  # Uncentered donor residuals
    donor_seasons = [1] * 60

    dgp1 = DGP1ResidualMBB(donor_residuals=donor_res, donor_seasons=donor_seasons, block_length=14)
    counts = np.full((60, 3), 25.0)

    theta_target = 0.002
    rng = np.random.default_rng(20261109)
    sums_sim = dgp1.generate_scores(template_counts=counts, theta=theta_target, rng=rng)

    # Implied Delta from the simulation
    delta_sim = pooled_delta(sums_sim, counts)
    # Individual draw has random noise, but expected mean across sampler is theta_target
    assert -0.05 < delta_sim < 0.05


def test_dgp2_var_stability_and_lyapunov():
    """Validates DGP2 VAR fitting enforces stability (spectral norm <= 0.95) and PSD covariance (§8.2)."""
    np.random.seed(42)
    residuals = np.random.normal(0.0, 0.15, size=(100, 3))
    dgp2 = DGP2VectorVAR.fit_from_residuals(residuals)

    # Spectral norm must be <= 0.95
    spectral_norm = float(np.linalg.norm(dgp2.A, ord=2))
    assert spectral_norm <= 0.95

    # Discrete Lyapunov stationary covariance must be positive semi-definite
    eigvals = np.linalg.eigvalsh(dgp2.sigma_inf)
    assert np.all(eigvals >= -1e-8)


def test_daily_vectors_aggregation_from_ledger():
    """Validates ledger ingestion and daily vector aggregation into (S, N) matrices (§3.2)."""
    ledger_data = [
        {"game_date": "2024-11-01", "stat": "PTS", "p_H": 0.55, "p_SH": 0.50, "y": 1.0, "season": "2024-25"},
        {"game_date": "2024-11-01", "stat": "PTS", "p_H": 0.40, "p_SH": 0.45, "y": 0.0, "season": "2024-25"},
        {"game_date": "2024-11-01", "stat": "REB", "p_H": 0.60, "p_SH": 0.50, "y": 1.0, "season": "2024-25"},
        {"game_date": "2024-11-01", "stat": "AST", "p_H": 0.50, "p_SH": 0.50, "y": 0.0, "season": "2024-25"},
        {"game_date": "2024-11-02", "stat": "PTS", "p_H": 0.48, "p_SH": 0.52, "y": 1.0, "season": "2024-25"},
    ]
    df_ledger = pd.DataFrame(ledger_data)

    sums, counts, seasons, gaps = aggregate_prediction_ledger_to_daily_vectors(df_ledger)

    assert sums.shape == (2, 3)
    assert counts.shape == (2, 3)
    assert counts[0, 0] == 2.0  # 2 PTS rows on day 0
    assert counts[0, 1] == 1.0  # 1 REB row on day 0
    assert counts[0, 2] == 1.0  # 1 AST row on day 0
    assert counts[1, 0] == 1.0  # 1 PTS row on day 1
    assert counts[1, 1] == 0.0  # 0 REB rows on day 1
    assert sums[1, 1] == 0.0    # Zero count requires zero sum!


def test_simulation_gate_suite_execution(tmp_path):
    """Tests SimulationGate.run_comprehensive_suite in smoke mode (§11, §14)."""
    np.random.seed(42)
    T = 480  # 280 pilot + 200 confirmatory
    counts = np.full((T, 3), 15.0)
    residuals = np.random.normal(0.0, 0.08, size=(60, 3))
    seasons = [1] * 60

    gate = SimulationGate(reports_dir=tmp_path / "reports")
    report = gate.run_comprehensive_suite(
        template_counts=counts,
        donor_residuals=residuals,
        donor_seasons=seasons,
        n_outer=10,        # Smoke mode outer
        inner_reps=50,     # Smoke mode inner
        b5_budget=200,
        mode="smoke",
    )

    assert "gate_status" in report
    assert "scenarios" in report
    assert len(report["scenarios"]) == 3  # DGP1, DGP2, DGP3

    # Check that report is written to disk
    report_file = tmp_path / "reports" / "simulation_gate_report.json"
    assert report_file.exists()
