"""
Module: Variance, Influence Diagnostics & Sample Size Planning (§4 of Review Spec)
Provides:
- Influence function psi_d for pooled ratio statistic
- Scalar long-run variance Omega_point via bootstrap variance
- Omega_U upper quantile from outer resamples
- T_req sample size planning formula
- Pooled RMS feasibility diagnostic
"""

import math
from statistics import NormalDist
from typing import Dict, Optional, Tuple, Union
import numpy as np

from src.simulation_gate.kernels import pooled_delta, season_mbb_indices


def calculate_influence_psi(sums: np.ndarray, counts: np.ndarray) -> np.ndarray:
    """
    Computes daily influence values psi_d for stationary diagnostic approximation (§4):
    psi_d = 1/3 sum_{s=1}^3 [ (S_ds - mu_s * N_ds) / nbar_s ]
    """
    sums = np.asarray(sums, dtype=np.float64)
    counts = np.asarray(counts, dtype=np.float64)
    T, n_stats = sums.shape

    total_counts = counts.sum(axis=0)
    total_sums = sums.sum(axis=0)

    mu_s = total_sums / total_counts
    nbar_s = total_counts / float(T)

    # Compute psi_d for each day d
    psi_d = np.zeros(T, dtype=np.float64)
    for s in range(n_stats):
        if nbar_s[s] > 0:
            psi_d += (sums[:, s] - mu_s[s] * counts[:, s]) / (3.0 * nbar_s[s])

    return psi_d


def calculate_omega_point(
    sums: np.ndarray,
    counts: np.ndarray,
    seasons: Union[list, np.ndarray],
    reps: int = 1000,
    block_length: int = 14,
    seed: int = 20261109,
) -> float:
    """
    Computes empirical scalar long-run variance Omega_point (§4):
    Omega_point = T * Var_boot(Delta_hat*) with ddof=1.
    """
    T = len(sums)
    rng = np.random.default_rng(seed)
    deltas = np.empty(reps, dtype=np.float64)

    for b in range(reps):
        idx = season_mbb_indices(seasons, block_length, rng)
        deltas[b] = pooled_delta(sums[idx], counts[idx])

    var_boot = float(np.var(deltas, ddof=1))
    omega = float(T * var_boot)
    return max(1e-10, omega)


def calculate_omega_uncertainty(
    sums: np.ndarray,
    counts: np.ndarray,
    seasons: Union[list, np.ndarray],
    outer_reps: int = 100,
    inner_reps: int = 200,
    block_length: int = 14,
    seed: int = 20261109,
) -> Tuple[float, float, np.ndarray]:
    """
    Computes Omega distribution across outer resamples and extracts Omega_U (§4):
    Omega_U = quantile_0.95(Omega_b).
    """
    rng = np.random.default_rng(seed)
    omega_b_list = np.empty(outer_reps, dtype=np.float64)

    for b_out in range(outer_reps):
        # Outer resample of the study window
        idx_outer = season_mbb_indices(seasons, block_length, rng)
        sums_outer = sums[idx_outer]
        counts_outer = counts[idx_outer]
        seasons_outer = [seasons[i] for i in idx_outer]

        omega_b = calculate_omega_point(
            sums=sums_outer,
            counts=counts_outer,
            seasons=seasons_outer,
            reps=inner_reps,
            block_length=block_length,
            seed=int(rng.integers(1, 100000000)),
        )
        omega_b_list[b_out] = omega_b

    omega_u = float(np.quantile(omega_b_list, 0.95))
    omega_median = float(np.median(omega_b_list))
    return omega_u, omega_median, omega_b_list


def calculate_t_req(
    omega_u: float,
    delta_target: float = 0.002,
    margin: float = 0.001,
) -> int:
    """
    Computes required number of scheduled game dates T_req (§4):
    T_req = ceil[ (z_0.975 + z_0.80)^2 * Omega_U / (Delta_target - delta)^2 ]
    """
    if omega_u <= 0 or delta_target <= margin:
        raise ValueError("Invalid parameters for T_req calculation")

    z_alpha = NormalDist().inv_cdf(0.975)  # ~1.95996
    z_beta = NormalDist().inv_cdf(0.80)   # ~0.84162
    factor = (z_alpha + z_beta) ** 2      # ~7.8488

    diff = delta_target - margin
    t_float = factor * omega_u / (diff ** 2)
    return int(math.ceil(t_float))


def calculate_pooled_rms(
    p_sh: np.ndarray,
    p_h: np.ndarray,
    stat_labels: np.ndarray,
) -> float:
    """
    Computes pooled root-mean-square difference across stats (§4.1):
    rms_pool = sqrt[ 1/3 sum_s mean_i((p_i - q_i)^2) ]
    """
    p_sh = np.asarray(p_sh, dtype=np.float64)
    p_h = np.asarray(p_h, dtype=np.float64)
    stats = np.asarray(stat_labels)

    unique_stats = np.unique(stats)
    mse_per_stat = []

    for s in unique_stats:
        mask = stats == s
        diff_sq = (p_sh[mask] - p_h[mask]) ** 2
        mse_per_stat.append(float(np.mean(diff_sq)))

    if len(mse_per_stat) == 0:
        return 0.0

    return float(np.sqrt(np.mean(mse_per_stat)))
