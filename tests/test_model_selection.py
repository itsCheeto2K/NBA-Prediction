"""
Unit tests for Stats-Only Model Selection & Verification Protocol (§10–11 of Plan & Review Spec).
Validates:
- 12 mandatory mean candidates and 48 composite distribution recipes (§4.1, §4.2)
- Contiguous chronological 40% D_warm, 30% D_phi, 30% D_G split (§6)
- Empirical scalar phi fitting via NB2 negative log-likelihood (§4, §6)
- 0.5% R_ref indifference band shortlist and deterministic tie-breaking (§7.2)
- Safety diagnostic distribution metric conflict gate (§7.3)
- Atomic ModelBundle serialization, deserialization, and distribution inference (§11)
- Fast selection pipeline execution
"""

import json
import math
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from scipy import stats

from src.models.selector import (
    MeanCandidateConfig,
    CompositeRecipe,
    ModelBundle,
    ModelSelector,
    get_mandatory_mean_candidates,
    build_composite_recipes,
    fit_dispersion_phi,
)
from src.distribution.calibration import PiecewiseLinearCDFCalibrator


def test_mandatory_mean_candidate_registry():
    """Validates the 12 mandatory mean candidates and 48 composite recipes (§4.1, §4.2)."""
    candidates = get_mandatory_mean_candidates(stat="pts")
    assert len(candidates) == 12

    # Verify candidate families
    families = [c.family for c in candidates]
    assert families.count("weighted_avg") == 3
    assert families.count("minutes_rate") == 1
    assert families.count("lgbm") == 4
    assert families.count("catboost") == 4

    # Verify objectives: both Poisson and Squared-Error (RMSE) present
    objectives = [c.objective for c in candidates]
    assert objectives.count("poisson") == 5  # 1 min_rate + 2 lgbm + 2 catboost
    assert objectives.count("squared_error") == 7  # 3 weighted_avg + 2 lgbm + 2 catboost

    # Verify expansion to 48 composite recipes
    recipes = build_composite_recipes(candidates)
    assert len(recipes) == 48

    # Each recipe has raw_family in {poisson, nb2} and calibrator in {identity, piecewise_linear}
    for r in recipes:
        assert r.raw_family in ("poisson", "nb2")
        assert r.calibrator_type in ("identity", "piecewise_linear")


def test_b0_temporal_contiguous_split():
    """Validates 40% D_warm, 30% D_phi, 30% D_G chronological split without date overlap (§6)."""
    # Create 50 unique game dates
    dates = pd.date_range("2023-10-24", periods=50, freq="D").strftime("%Y-%m-%d").tolist()
    records = []
    for d in dates:
        for p in range(5):
            records.append({"game_date": d, "player_id": p, "target_pts": 20.0})
    df_b0 = pd.DataFrame(records)

    selector = ModelSelector(stat="pts")
    df_warm, df_phi, df_g = selector.split_b0_chronological(df_b0)

    # 40% of 50 = 20 dates
    # 30% of 50 = 15 dates
    # 30% of 50 = 15 dates
    warm_dates = set(df_warm["game_date"].unique())
    phi_dates = set(df_phi["game_date"].unique())
    g_dates = set(df_g["game_date"].unique())

    assert len(warm_dates) == 20
    assert len(phi_dates) == 15
    assert len(g_dates) == 15

    # Check zero intersection between contiguous segments
    assert len(warm_dates.intersection(phi_dates)) == 0
    assert len(phi_dates.intersection(g_dates)) == 0
    assert len(warm_dates.intersection(g_dates)) == 0


def test_fit_dispersion_phi():
    """Validates empirical scalar phi fitting using NB2 NLL (§4, §6)."""
    np.random.seed(42)
    n = 2000
    true_mu = np.random.uniform(15.0, 30.0, size=n)
    true_phi = 0.08
    r = 1.0 / true_phi
    p = r / (r + true_mu)
    y_sim = stats.nbinom.rvs(r, p)

    fitted_phi = fit_dispersion_phi(y_true=y_sim, y_pred=true_mu)
    assert pytest.approx(fitted_phi, abs=0.03) == true_phi

    # When generated from Poisson (phi=0), fitted phi should be near 0
    y_pois = stats.poisson.rvs(true_mu)
    fitted_phi_pois = fit_dispersion_phi(y_true=y_pois, y_pred=true_mu)
    assert fitted_phi_pois < 0.02


def test_tie_break_with_indifference_band():
    """
    Validates Section 7.2 selection & tie-break:
    - R_best = min R_m
    - tol_s = max(1e-8, 0.005 * R_ref)
    - Shortlist = {m: R_m <= R_best + tol_s}
    - Deterministic tie-breaking prefers lower complexity in the band.
    """
    selector = ModelSelector(stat="pts")
    r_ref_val = 5.0
    tol = 0.005 * r_ref_val  # 0.025

    # Mock recipes
    mock_recipes = [
        # Recipe A: Complex model with best score 4.000
        {
            "recipe_id": "LGBM_Poisson_leaves63_pts__nb2__piecewise_linear",
            "candidate_id": "LGBM_Poisson_leaves63_pts",
            "mean_family": "lgbm",
            "mean_family_rank": 2,
            "raw_family_rank": 1,
            "calibrator_rank": 1,
            "size_rank": 1,
            "latency": 0.05,
            "mean_full_rps": 4.000,
            "mean_neg_log_score": 3.10,
        },
        # Recipe B: Simpler model with score 4.015 (within 4.000 + 0.025 = 4.025)
        # Lower family rank (MinutesRate = 1) -> must win tie-break!
        {
            "recipe_id": "MinutesRate_pts__poisson__identity",
            "candidate_id": "MinutesRate_pts",
            "mean_family": "minutes_rate",
            "mean_family_rank": 1,
            "raw_family_rank": 0,
            "calibrator_rank": 0,
            "size_rank": 0,
            "latency": 0.001,
            "mean_full_rps": 4.015,
            "mean_neg_log_score": 3.11,
        },
        # Recipe C: Simpler model with score 4.080 (OUTSIDE the band 4.025)
        {
            "recipe_id": "WeightedAvg_K5_pts__poisson__identity",
            "candidate_id": "WeightedAvg_K5_pts",
            "mean_family": "weighted_avg",
            "mean_family_rank": 0,
            "raw_family_rank": 0,
            "calibrator_rank": 0,
            "size_rank": 0,
            "latency": 0.001,
            "mean_full_rps": 4.080,
            "mean_neg_log_score": 3.25,
        },
    ]

    res = selector.select_best_recipe(mock_recipes, ref_recipe_id="MinutesRate_pts__poisson__identity")

    # In shortlist: Recipe A (4.000) and Recipe B (4.015). Recipe C (4.080) excluded!
    assert res["shortlist_count"] == 2
    assert "WeightedAvg_K5_pts__poisson__identity" not in res["shortlist_recipe_ids"]
    assert "MinutesRate_pts__poisson__identity" in res["shortlist_recipe_ids"]

    # Winner must be Recipe B due to lower complexity rank (family_rank 1 < 2)
    assert res["selected_winner"]["recipe_id"] == "MinutesRate_pts__poisson__identity"
    assert res["best_rps_recipe"]["recipe_id"] == "LGBM_Poisson_leaves63_pts__nb2__piecewise_linear"


def test_safety_diagnostic_distribution_metric_conflict():
    """Validates Section 7.3: flags DISTRIBUTION_METRIC_CONFLICT if finalist NLL is worse by > 1%."""
    selector = ModelSelector(stat="pts")

    mock_recipes = [
        # Best RPS recipe
        {
            "recipe_id": "LGBM_Poisson_leaves31_pts__nb2__identity",
            "candidate_id": "LGBM_Poisson_leaves31_pts",
            "mean_family": "lgbm",
            "mean_family_rank": 2,
            "raw_family_rank": 1,
            "calibrator_rank": 0,
            "size_rank": 0,
            "latency": 0.02,
            "mean_full_rps": 3.500,
            "mean_neg_log_score": 3.00,  # Best log score
        },
        # Recipe in shortlist, but has severely degraded log-score (3.20 > 3.00 * 1.01)
        {
            "recipe_id": "MinutesRate_pts__poisson__identity",
            "candidate_id": "MinutesRate_pts",
            "mean_family": "minutes_rate",
            "mean_family_rank": 1,
            "raw_family_rank": 0,
            "calibrator_rank": 0,
            "size_rank": 0,
            "latency": 0.001,
            "mean_full_rps": 3.505,  # In band (diff 0.005 < 0.0175)
            "mean_neg_log_score": 3.20,  # Degraded by > 6%!
        },
    ]

    res = selector.select_best_recipe(mock_recipes, ref_recipe_id="MinutesRate_pts__poisson__identity")
    assert res["distribution_metric_conflict"] is True


def test_model_bundle_serialization_and_inference(tmp_path):
    """Validates atomic ModelBundle serialization, deserialization, and DiscreteDistribution generation (§11)."""
    calibrator = PiecewiseLinearCDFCalibrator(eps_mix=0.001)
    knots = [float(k) for k in calibrator.c_knots]

    bundle = ModelBundle(
        bundle_id="bundle_pts_test_v1",
        stat="PTS",
        mean_family="weighted_avg",
        mean_config={"k": 5},
        feature_schema=["pts_roll_mean_5", "min_roll_mean_5"],
        numerical_projection_policy="max(1e-6, raw_pred)",
        raw_distribution_family="nb2",
        fitted_phi=0.05,
        calibrator_type="piecewise_linear",
        calibrator_knots=knots,
        metadata={"created_for": "unit_test"},
    )

    bundle_dir = tmp_path / "bundle_pts"
    bundle.save(bundle_dir)

    # Verify manifest file exists
    manifest_file = bundle_dir / "bundle_manifest.json"
    assert manifest_file.exists()

    # Load bundle atomically
    loaded_bundle = ModelBundle.load(bundle_dir)
    assert loaded_bundle.bundle_id == "bundle_pts_test_v1"
    assert loaded_bundle.stat == "PTS"
    assert loaded_bundle.fitted_phi == 0.05
    assert loaded_bundle.calibrator_type == "piecewise_linear"

    # Test prediction on a single row
    row_df = pd.DataFrame([{"pts_roll_mean_5": 24.5, "min_roll_mean_5": 32.0}])
    pred_mean = loaded_bundle.predict_mean(row_df)
    assert pytest.approx(pred_mean, 0.1) == 24.5

    dist = loaded_bundle.predict_distribution(row_df)
    assert dist.mu == pytest.approx(24.5, 0.1)
    assert dist.phi == 0.05

    # Check line probabilities on the generated distribution
    probs = dist.calculate_line_probabilities(24.5)
    assert probs["q_push"] == 0.0
    assert pytest.approx(probs["q_over"] + probs["q_under"], 1e-5) == 1.0


def test_fast_selection_pipeline_execution(tmp_path):
    """Tests ModelSelector.execute_selection_pipeline in fast mode on synthetic data."""
    # Build synthetic B0 and B1 datasets
    np.random.seed(42)
    dates_b0 = pd.date_range("2023-10-24", periods=30, freq="D").strftime("%Y-%m-%d").tolist()
    dates_b1 = pd.date_range("2024-10-24", periods=10, freq="D").strftime("%Y-%m-%d").tolist()

    features = ["pts_roll_mean_5", "pts_roll_mean_10", "min_roll_mean_5", "pts_rate_shrinkage"]

    def make_dataset(dates_list):
        rows = []
        for d in dates_list:
            for p in range(4):
                pts_base = 15.0 + p * 3.0
                rows.append({
                    "game_date": d,
                    "player_id": p,
                    "pts_roll_mean_5": pts_base,
                    "pts_roll_mean_10": pts_base - 0.5,
                    "min_roll_mean_5": 28.0,
                    "pts_rate_shrinkage": pts_base / 28.0,
                    "target_pts": float(np.random.poisson(pts_base)),
                })
        return pd.DataFrame(rows)

    df_b0 = make_dataset(dates_b0)
    df_b1 = make_dataset(dates_b1)

    selector = ModelSelector(
        stat="pts",
        models_dir=tmp_path / "models",
        reports_dir=tmp_path / "reports",
    )

    res = selector.execute_selection_pipeline(
        df_b0=df_b0,
        df_b1=df_b1,
        features=features,
        fast_mode=True,
    )

    assert res["stat"] == "PTS"
    assert res["total_recipes"] == 48  # 12 configs x 4 distribution wrappers
    assert "selected_winner" in res["selection_summary"]

    winner = res["selection_summary"]["selected_winner"]
    assert winner["recipe_id"] is not None
    assert winner["mean_full_rps"] > 0.0

    # Verify bundle directory and ledger
    bundle_path = Path(res["bundle_dir"]) / "bundle_manifest.json"
    assert bundle_path.exists()

    ledger_path = tmp_path / "reports" / "model_selection_ledger_pts.json"
    assert ledger_path.exists()
