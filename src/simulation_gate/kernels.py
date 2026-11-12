"""
Module: Numerical Reference Kernels (§12 of Review Spec)
Provides:
- pooled_delta: ratio-consistent pooled Brier difference estimator across stats
- season_mbb_indices: season-stratified non-overlapping moving-block bootstrap indices
- percentile_ci: empirical two-sided 95% percentile confidence interval
- wilson: Wilson score interval for binomial proportions
- final_decision: deterministic decision function for [L, U] vs delta margin
"""

from statistics import NormalDist
from typing import Tuple, Union
import numpy as np


def pooled_delta(sums: np.ndarray, counts: np.ndarray) -> float:
    """
    Computes pooled Brier gain ratio statistic across 3 stats (PTS, REB, AST) (§4, §12):
    Delta_hat = 1/3 sum_{s=1}^3 [ (sum_d S_ds) / (sum_d N_ds) ]
    """
    sums = np.asarray(sums, dtype=np.float64)
    counts = np.asarray(counts, dtype=np.float64)

    if sums.shape != counts.shape or sums.ndim != 2 or sums.shape[1] != 3:
        raise ValueError("Expected equal (T, 3) arrays")
    if not np.isfinite(sums).all() or not np.isfinite(counts).all():
        raise ValueError("Nonfinite values")
    if (counts < 0).any() or not np.equal(counts, np.floor(counts)).all():
        raise ValueError("Counts must be nonnegative integers")
    if ((counts == 0) & (sums != 0)).any():
        raise ValueError("Zero count requires zero sum")

    den = counts.sum(axis=0)
    if (den <= 0).any():
        raise ValueError("Every stat needs observations")

    return float(np.mean(sums.sum(axis=0) / den))


def season_mbb_indices(
    seasons: Union[list, np.ndarray],
    block_length: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """
    Generates season-stratified moving-block bootstrap indices without wrap-around (§5, §12).
    Enforces contiguous seasons and raises INVALID_BOOTSTRAP_SEGMENT if any season length < block_length.
    """
    seasons = np.asarray(seasons)
    n = len(seasons)
    if n == 0 or not isinstance(block_length, int) or block_length < 1:
        raise ValueError("Invalid bootstrap arguments")

    cuts = np.r_[0, np.flatnonzero(seasons[1:] != seasons[:-1]) + 1, n]
    labels = [seasons[a] for a in cuts[:-1]]
    if len(set(labels)) != len(labels):
        raise ValueError("Each season must be one contiguous segment")

    out = []
    for a, b in zip(cuts[:-1], cuts[1:]):
        size = int(b - a)
        if size < block_length:
            raise ValueError("INVALID_BOOTSTRAP_SEGMENT")
        starts = rng.integers(
            0,
            size - block_length + 1,
            size=(size + block_length - 1) // block_length,
        )
        idx = np.concatenate([a + j + np.arange(block_length) for j in starts])
        out.extend(idx[:size])

    return np.asarray(out, dtype=int)


def percentile_ci(
    sums: np.ndarray,
    counts: np.ndarray,
    seasons: Union[list, np.ndarray],
    reps: int = 10000,
    block_length: int = 14,
    seed: int = 20261109,
) -> Tuple[Tuple[float, float], np.ndarray]:
    """
    Computes two-sided 95% percentile confidence interval [L, U] via Season MBB (§5, §12).
    Quantiles use linear interpolation at [0.025, 0.975].
    """
    sums = np.asarray(sums, dtype=np.float64)
    counts = np.asarray(counts, dtype=np.float64)
    # Validate inputs through pooled_delta
    pooled_delta(sums, counts)

    if len(seasons) != len(sums) or reps < 2:
        raise ValueError("Invalid lengths/replications")

    rng = np.random.default_rng(seed)
    estimates = np.empty(reps, dtype=np.float64)

    for b in range(reps):
        idx = season_mbb_indices(seasons, block_length, rng)
        estimates[b] = pooled_delta(sums[idx], counts[idx])

    bounds = np.quantile(estimates, [0.025, 0.975], method="linear")
    return (float(bounds[0]), float(bounds[1])), estimates


def wilson(k: int, n: int, alpha: float = 0.05) -> Tuple[float, float]:
    """
    Computes exact Wilson score interval for binomial proportion k / n (§7, §12).
    Matches statsmodels proportion_confint(k, n, method='wilson').
    """
    if not (0 < alpha < 1) or n <= 0 or not (0 <= k <= n):
        raise ValueError("Invalid binomial summary")
    if int(k) != k or int(n) != n:
        raise ValueError("Expected integer counts")

    z = NormalDist().inv_cdf(1 - alpha / 2)
    phat = float(k) / float(n)
    den = 1.0 + (z * z) / float(n)
    center = (phat + (z * z) / (2.0 * float(n))) / den
    half = (z * np.sqrt((phat * (1.0 - phat)) / float(n) + (z * z) / (4.0 * float(n * n)))) / den

    return float(max(0.0, center - half)), float(min(1.0, center + half))


def final_decision(lower: float, upper: float, margin: float = 0.001) -> str:
    """
    Determines final hypothesis test decision from [lower, upper] CI bounds vs delta margin (§6, §12):
    - lower > margin -> ADOPT
    - upper < margin -> DO_NOT_ADOPT
    - otherwise -> INCONCLUSIVE
    """
    if not np.isfinite([lower, upper, margin]).all() or lower > upper:
        raise ValueError("CI_INVALID")
    if margin <= 0:
        raise ValueError("Margin must be positive")

    if lower > margin:
        return "ADOPT"
    if upper < margin:
        return "DO_NOT_ADOPT"
    return "INCONCLUSIVE"
