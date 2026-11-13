import pytest
import numpy as np
import pandas as pd
from src.features.opponent_ranks import (
    compute_smoothed_rate,
    compute_log_relative,
    compute_percentile_ranks,
    DEFAULT_LEAGUE_PRIORS,
    TAU_POSSESSIONS
)

def test_smoothing_formula_numerical_example():
    # Exactly from Spec §17.1:
    # Y = 1120, E = 1000, R0 = 110.0, tau = 500.0
    # R_raw = 112.0, R_shrunk = 100 * (1120 + 500 * 1.1) / (1000 + 500) = 111.333333
    r_shrunk, prior_weight = compute_smoothed_rate(sum_y=1120.0, sum_e=1000.0, r0=110.0, tau=500.0)
    assert abs(r_shrunk - 111.3333333333) < 1e-6
    assert abs(prior_weight - (1.0 / 3.0)) < 1e-6

def test_compute_log_relative():
    log_rel = compute_log_relative(111.333333, 110.0)
    expected = np.log(111.333333 / 110.0)
    assert abs(log_rel - expected) < 1e-6

def test_rank_ties_numerical_example():
    # Exactly from Spec §17.2:
    # 3 teams with values 110, 110, 120 -> rank 1.5, 1.5, 3; pct 0.25, 0.25, 1.0
    series = pd.Series([110.0, 110.0, 120.0], index=["A", "B", "C"])
    ranks, pcts = compute_percentile_ranks(series)
    assert list(ranks) == [1.5, 1.5, 3.0]
    assert list(pcts) == [0.25, 0.25, 1.0]

def test_equal_values_all_pct_half():
    series = pd.Series([100.0, 100.0, 100.0])
    ranks, pcts = compute_percentile_ranks(series)
    assert list(ranks) == [2.0, 2.0, 2.0]
    assert list(pcts) == [0.5, 0.5, 0.5]
