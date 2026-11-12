import pytest
import numpy as np
import scipy.stats as stats
from src.distribution.engine import DiscreteDistributionEngine, DiscreteDistribution
from src.distribution.calibration import (
    IsotonicCDFCalibrator,
    PiecewiseLinearCDFCalibrator,
    calculate_full_rps,
    calculate_finite_grid_rps,
)
from src.distribution.pricing import remove_vig_multiplicative, calculate_ev


def test_discrete_distribution_engine_poisson():
    engine = DiscreteDistributionEngine(dist_type="poisson")
    mu = 25.0
    pmf = engine.compute_pmf(mu)
    assert len(pmf) > 50
    assert pytest.approx(np.sum(pmf), 0.0001) == 1.0

    # CDF check
    cdf = engine.compute_cdf(pmf)
    assert cdf[0] > 0
    assert pytest.approx(cdf[-1], 0.0001) == 1.0
    assert np.all(np.diff(cdf) >= 0)  # Monotonic non-decreasing

    # Half-point line 24.5
    probs_half = engine.calculate_line_probabilities(cdf, pmf, line=24.5)
    assert probs_half["q_push"] == 0.0
    assert pytest.approx(probs_half["q_over"] + probs_half["q_under"], 0.0001) == 1.0

    # Whole-number line 25.0
    probs_whole = engine.calculate_line_probabilities(cdf, pmf, line=25.0)
    assert probs_whole["q_push"] > 0.0
    assert pytest.approx(probs_whole["q_over"] + probs_whole["q_under"] + probs_whole["q_push"], 0.0001) == 1.0


def test_prediction_interval_and_median():
    engine = DiscreteDistributionEngine(dist_type="poisson")
    pmf = engine.compute_pmf(mu=20.0)
    cdf = engine.compute_cdf(pmf)

    median = engine.compute_median(cdf)
    assert median in (19, 20)

    interval = engine.compute_prediction_interval(pmf, coverage=0.90)
    assert interval["lower"] < median < interval["upper"]
    assert interval["coverage"] >= 0.90


def test_full_rps_calculation():
    # True outcome is 20
    engine = DiscreteDistributionEngine(dist_type="poisson")
    pmf = engine.compute_pmf(mu=20.0)
    cdf = engine.compute_cdf(pmf)
    rps = calculate_full_rps(cdf, actual_y=20)
    assert rps >= 0.0

    # An inaccurate prediction has higher RPS
    pmf_bad = engine.compute_pmf(mu=10.0)
    cdf_bad = engine.compute_cdf(pmf_bad)
    rps_bad = calculate_full_rps(cdf_bad, actual_y=20)
    assert rps_bad > rps


def test_pricing_and_ev():
    # Standard -110 / -110 odds (1.909 decimal)
    devig = remove_vig_multiplicative(odds_over=1.909, odds_under=1.909)
    assert pytest.approx(devig["fair_over"], 0.01) == 0.50
    assert pytest.approx(devig["fair_under"], 0.01) == 0.50

    # EV calculation: If model has 60% Over at 1.909 odds, EV must be positive!
    # EV = 0.60 * (1.909 - 1) - 0.40 * 1 = 0.60 * 0.909 - 0.40 = 0.5454 - 0.40 = +0.1454
    ev_over = calculate_ev(prob_win=0.60, prob_loss=0.40, decimal_odds=1.909)
    assert ev_over > 0.10

    # If model has 40% Over, EV must be negative
    ev_under = calculate_ev(prob_win=0.40, prob_loss=0.60, decimal_odds=1.909)
    assert ev_under < 0.0


# =========================================================================
# Section 14.1 Review & Fix Specification Compliance Tests
# =========================================================================

def test_discrete_distribution_poisson_and_nb2_edge_policies():
    """Validates boundary handling, Poisson limit at phi=0, and non-finite rejection (§6, §14.1)."""
    # Reject negative mu or phi
    with pytest.raises(ValueError):
        DiscreteDistribution(mu=-5.0, phi=0.0)
    with pytest.raises(ValueError):
        DiscreteDistribution(mu=15.0, phi=-0.05)
    with pytest.raises(ValueError):
        DiscreteDistribution(mu=float("nan"), phi=0.0)
    with pytest.raises(ValueError):
        DiscreteDistribution(mu=15.0, phi=float("inf"))

    # phi=0 acts as Poisson limit
    dist_zero_phi = DiscreteDistribution(mu=20.0, phi=0.0, dist_type="nb2")
    dist_poisson = DiscreteDistribution(mu=20.0, phi=0.0, dist_type="poisson")
    assert pytest.approx(dist_zero_phi.pmf(20), 1e-6) == dist_poisson.pmf(20)
    assert pytest.approx(dist_zero_phi.cdf(20), 1e-6) == dist_poisson.cdf(20)


def test_nb2_pmf_and_cdf_match_scipy():
    """Validates NB2 PMF, CDF, SF, and moments against scipy.stats.nbinom (§4, §14.1)."""
    mu = 25.0
    phi = 0.08
    r = 1.0 / phi  # 12.5
    p = r / (r + mu)  # 12.5 / 37.5 = 1/3

    dist = DiscreteDistribution(mu=mu, phi=phi, dist_type="nb2")
    scipy_dist = stats.nbinom(r, p)

    # Moments: Var(X) = mu + phi * mu^2 = 25 + 0.08 * 625 = 75.0
    var = scipy_dist.var()
    assert pytest.approx(var, 1e-6) == 75.0
    assert pytest.approx(dist.mean(), 1e-6) == 25.0

    for k in [0, 5, 20, 25, 35, 50]:
        assert pytest.approx(dist.pmf(k), 1e-6) == scipy_dist.pmf(k)
        assert pytest.approx(dist.cdf(k), 1e-6) == scipy_dist.cdf(k)
        assert pytest.approx(dist.sf(k), 1e-6) == scipy_dist.sf(k)


def test_prefix_pmf_and_tail_mass_accounting():
    """
    Validates mass identity sum(prefix_pmf(K)) + tail_mass(K) == 1.0 (§5, §6).
    Confirms tail mass is NOT lumped into atom K, and lines > K evaluate accurately.
    """
    dist = DiscreteDistribution(mu=35.0, phi=0.10, dist_type="nb2")
    K = 70
    prefix = dist.prefix_pmf(K)
    tail = dist.tail_mass(K)

    assert len(prefix) == K + 1
    # Prefix sum must be strictly < 1.0 due to tail
    assert np.sum(prefix) < 1.0
    assert tail > 0.0
    # Mass accounting identity
    assert pytest.approx(np.sum(prefix) + tail, 1e-7) == 1.0

    # Verify atom 70 does not lump the tail mass
    assert prefix[70] == pytest.approx(dist.pmf(70), 1e-7)
    assert prefix[70] < dist.pmf(70) + tail

    # Infinite support queries beyond 70
    probs_70_5 = dist.calculate_line_probabilities(70.5)
    assert probs_70_5["q_over"] > 0.0
    assert pytest.approx(probs_70_5["q_over"] + probs_70_5["q_under"], 1e-5) == 1.0

    probs_75 = dist.calculate_line_probabilities(75.0)
    assert probs_75["q_over"] > 0.0
    assert probs_75["q_push"] > 0.0
    assert pytest.approx(probs_75["q_over"] + probs_75["q_under"] + probs_75["q_push"], 1e-5) == 1.0

    probs_100 = dist.calculate_line_probabilities(100.0)
    assert probs_100["q_under"] > 0.999
    assert pytest.approx(probs_100["q_over"] + probs_100["q_under"] + probs_100["q_push"], 1e-5) == 1.0


def test_section_5_1_numerical_match():
    """
    Exact numerical verification of Section 5.1 table in review spec:
    Raw NB2: mu = 40.0, phi = 0.10, K = 70
    - P(X > 70) ≈ 0.0287175673
    - p(X = 70) ≈ 0.0034679171
    - Push70 if lumped ≈ 0.0321854844
    - P(X > 60.5) ≈ 0.0845353956
    - P(X > 60.5) if truncated/renormalized ≈ 0.0574681745
    """
    dist = DiscreteDistribution(mu=40.0, phi=0.10, dist_type="nb2")

    # True tail mass P(X > 70)
    p_gt_70 = dist.tail_mass(70)
    assert pytest.approx(p_gt_70, 1e-5) == 0.0287175673

    # True PMF atom p(X = 70)
    p_eq_70 = dist.pmf(70)
    assert pytest.approx(p_eq_70, 1e-5) == 0.0034679171

    # In our engine, Push at 70 must be p_eq_70, NOT the lumped mass
    probs_70 = dist.calculate_line_probabilities(70.0)
    assert pytest.approx(probs_70["q_push"], 1e-4) == 0.003468
    assert probs_70["q_push"] < 0.02  # Far below the lumped 0.032185

    # True P(X > 60.5) = sf(60)
    probs_60_5 = dist.calculate_line_probabilities(60.5)
    assert pytest.approx(probs_60_5["q_over"], 1e-4) == 0.084535
    # Must NOT be truncated/renormalized value 0.057468
    assert probs_60_5["q_over"] > 0.075


def test_section_8_point_mass_70_observed_75():
    """
    Verifies Section 8 counterexample:
    Forecast point-mass at 70, observed actual_y = 75.
    - True Full RPS = 5.0
    - Finite grid RPS_70 = 1.0
    - Clipping actual_y 75 -> 70 would falsely give 0.0!
    """
    # Construct CDF for point mass at 70: F(k) = 0 for k < 70, 1 for k >= 70
    k_max = 70
    cdf_70 = np.zeros(k_max + 1, dtype=np.float64)
    cdf_70[70] = 1.0

    # Finite-grid score up to K=70
    score_k70 = calculate_finite_grid_rps(cdf_70, actual_y=75, K=70)
    assert pytest.approx(score_k70, 1e-6) == 1.0

    # If actual_y were falsely clipped 75 -> 70
    clipped_score = calculate_finite_grid_rps(cdf_70, actual_y=70, K=70)
    assert pytest.approx(clipped_score, 1e-6) == 0.0  # Demonstrates why clipping is fatal!

    # True Full RPS: expands beyond grid to outcome y=75
    full_rps = calculate_full_rps(cdf_70, actual_y=75)
    # Sum over k=0..69: 0, k=70..74 (5 terms): (1 - 0)^2 = 1.0 * 5 = 5.0, k>=75: (1 - 1)^2 = 0
    assert pytest.approx(full_rps, 1e-6) == 5.0


def test_piecewise_linear_calibrator_hard_endpoints_and_monotonicity():
    """
    Validates PiecewiseLinearCDFCalibrator (§11, §12):
    - Strict hard endpoints G(0) = 0.0, G(1) = 1.0
    - Monotonicity on dense grid
    - Minimum slope >= eps_mix = 0.001
    - Preserves positive support
    """
    calibrator = PiecewiseLinearCDFCalibrator(eps_mix=0.001)

    # Hard endpoints
    assert calibrator(0.0) == 0.0
    assert calibrator(1.0) == 1.0
    assert calibrator(-0.2) == 0.0
    assert calibrator(1.5) == 1.0

    # Dense grid evaluation
    dense_u = np.linspace(0.0, 1.0, 500)
    g_dense = calibrator(dense_u)
    diffs = np.diff(g_dense)
    assert np.all(diffs > 0)  # Strictly increasing everywhere

    step_size = dense_u[1] - dense_u[0]
    min_slope = float(np.min(diffs)) / step_size
    assert min_slope >= 0.001 - 1e-6


def test_piecewise_linear_calibrator_fit_and_mass_preservation():
    """Tests fitting PiecewiseLinearCDFCalibrator via SLSQP and verifying hard constraints (§12)."""
    np.random.seed(42)
    engine = DiscreteDistributionEngine(dist_type="nb2")
    n_samples = 30
    K = 50
    raw_cdfs = []
    actual_ys = []

    for _ in range(n_samples):
        mu = np.random.uniform(15.0, 30.0)
        pmf = engine.compute_pmf(mu=mu, phi=0.08)
        cdf = engine.compute_cdf(pmf)[:K + 1]
        raw_cdfs.append(cdf)
        actual_ys.append(np.random.choice(len(pmf), p=pmf))

    raw_cdfs = np.array(raw_cdfs)
    actual_ys = np.array(actual_ys)

    calibrator = PiecewiseLinearCDFCalibrator(eps_mix=0.001, lambda_reg=1e-4)
    calibrator.fit(raw_cdfs, actual_ys)

    assert calibrator.is_fitted
    # Knots satisfy hard constraints
    assert calibrator.c_knots[0] == 0.0
    assert calibrator.c_knots[20] == 1.0
    assert np.all(np.diff(calibrator.c_knots) >= -1e-10)


def test_calibrated_distribution_line_probabilities_sum_to_one():
    """
    Validates calibrated distribution line probabilities sum exactly to 1.0
    across integer, half-point, zero, large, and negative lines (§7, §14.1).
    """
    calibrator = PiecewiseLinearCDFCalibrator(eps_mix=0.001)
    # Give calibrator a mild S-curve to test non-identity calibration
    test_knots = np.linspace(0.0, 1.0, 21) ** 1.2
    test_knots[0] = 0.0
    test_knots[-1] = 1.0
    calibrator.c_knots = test_knots

    dist = DiscreteDistribution(mu=28.0, phi=0.08, dist_type="nb2", calibrator=calibrator)

    test_lines = [-1.0, 0.0, 0.5, 15.0, 27.5, 28.0, 50.0, 70.0, 70.5, 85.0]
    for line in test_lines:
        probs = dist.calculate_line_probabilities(line)
        total = probs["q_over"] + probs["q_under"] + probs["q_push"]
        assert pytest.approx(total, 1e-5) == 1.0

        if abs(line - round(line)) < 1e-6:
            # Whole line must have push equal to pmf within decimal precision
            assert pytest.approx(probs["q_push"], abs=1e-5) == dist.pmf(line)
        else:
            # Half line must have zero push
            assert probs["q_push"] == 0.0

    # Calibrated mean with error bound
    mean_info = dist.mean_with_error_bound(tol=1e-6)
    assert mean_info["converged"]
    assert mean_info["mean"] > 0.0
    assert mean_info["tail_error_bound"] < 1e-3


def test_monotonicity_audit_and_tolerance():
    """Validates numerical tolerance 1e-12 repair vs failure on severe violations (§13)."""
    calibrator = PiecewiseLinearCDFCalibrator(eps_mix=0.001)

    # Valid CDF with tiny numerical float jitter (-1e-13)
    valid_cdf = np.array([0.1, 0.3, 0.3 - 1e-13, 0.7, 1.0])
    cal_cdf = calibrator.calibrate_cdf(valid_cdf)
    assert np.all(np.diff(cal_cdf) >= 0.0)
    assert cal_cdf[-1] == 1.0

    # Severe monotonicity violation (> 1e-6) must raise ValueError
    invalid_cdf = np.array([0.1, 0.6, 0.2, 0.8, 1.0])
    with pytest.raises(ValueError, match="Severe CDF monotonicity violation detected"):
        calibrator.calibrate_cdf(invalid_cdf)
