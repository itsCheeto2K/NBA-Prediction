"""
Module: Score-Surrogate DGPs with Exact Known Truths (§8 of Review Spec)
Provides:
- DGP1: Season-stratified residual MBB with position-centering
- DGP2: Vector autoregressive VAR(1) with calendar-gap decay and season reset
- DGP3: Variance and persistence stress testing with target Omega scaling
"""

from typing import Dict, List, Optional, Tuple, Union
import numpy as np
from scipy import linalg

from src.simulation_gate.kernels import season_mbb_indices


class BaseScoreDGP:
    """Base class for score-surrogate DGP generators (§8)."""

    def generate_scores(
        self,
        template_counts: np.ndarray,
        theta: float,
        rng: np.random.Generator,
        seasons: Optional[List[Any]] = None,
        gap_days: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        raise NotImplementedError


class DGP1ResidualMBB(BaseScoreDGP):
    """
    DGP1: Season-stratified moving-block residual simulation with exact position-centering (§8.1).
    Ensures E[e_ds] = 0 across the donor sampler, so Delta_true = theta exactly.
    """

    def __init__(
        self,
        donor_residuals: np.ndarray,
        donor_seasons: List[Any],
        block_length: int = 14,
    ):
        self.donor_residuals = np.asarray(donor_residuals, dtype=np.float64)
        self.donor_seasons = donor_seasons
        self.block_length = block_length
        self._compute_position_means()

    def _compute_position_means(self):
        """Computes expected residual E_J[r_{J_d}] across valid starts for position-centering."""
        n_donor = len(self.donor_residuals)
        l = self.block_length
        n_starts = max(1, n_donor - l + 1)
        start_matrix = np.array([self.donor_residuals[i : i + l] for i in range(n_starts)])
        # Shape: (n_starts, l, 3) -> mean across starts: (l, 3)
        self.offset_means = np.mean(start_matrix, axis=0)

    def generate_scores(
        self,
        template_counts: np.ndarray,
        theta: float,
        rng: np.random.Generator,
        seasons: Optional[List[Any]] = None,
        gap_days: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        counts = np.asarray(template_counts, dtype=np.float64)
        T, n_stats = counts.shape
        target_seasons = seasons if seasons is not None else [1] * T

        # Resample donor residuals using Season MBB
        resample_idx = season_mbb_indices(self.donor_seasons, self.block_length, rng)
        # Match length T
        if len(resample_idx) < T:
            repeats = (T // len(resample_idx)) + 1
            resample_idx = np.tile(resample_idx, repeats)[:T]
        else:
            resample_idx = resample_idx[:T]

        raw_e = self.donor_residuals[resample_idx]

        # Apply position-centering: e_d = r - offset_mean
        offsets = np.arange(T) % self.block_length
        centered_e = raw_e - self.offset_means[offsets]

        # S_ds = N_ds * theta + sqrt(N_ds) * e_ds (§8)
        sqrt_n = np.sqrt(counts)
        sums = counts * theta + sqrt_n * centered_e
        # Ensure zero count gives zero sum
        sums = np.where(counts == 0, 0.0, sums)
        return sums


class DGP2VectorVAR(BaseScoreDGP):
    """
    DGP2: Vector Autoregressive VAR(1) with calendar-gap decay and season reset (§8.2).
    Stable transition A, discrete Lyapunov stationary covariance Sigma_inf, exact E[e_d] = 0.
    """

    def __init__(
        self,
        A: np.ndarray,
        Q: np.ndarray,
    ):
        self.A = np.asarray(A, dtype=np.float64)
        self.Q = np.asarray(Q, dtype=np.float64)
        # Solve discrete Lyapunov equation: Sigma_inf = A * Sigma_inf * A^T + Q
        self.sigma_inf = linalg.solve_discrete_lyapunov(self.A, self.Q)

    @classmethod
    def fit_from_residuals(cls, residuals: np.ndarray, ridge_lambda: float = 0.1) -> "DGP2VectorVAR":
        """Fits ridge VAR(1) model from pilot residuals (§8.2)."""
        res = np.asarray(residuals, dtype=np.float64)
        T, n_stats = res.shape
        r_curr = res[1:]
        r_prev = res[:-1]

        cov_cross = r_curr.T @ r_prev
        cov_prev = r_prev.T @ r_prev

        # Ridge regularization
        ridge_diag = ridge_lambda * np.trace(cov_prev) / float(n_stats) * np.eye(n_stats)
        A0 = cov_cross @ np.linalg.pinv(cov_prev + ridge_diag)

        # Enforce stability: spectral norm <= 0.95
        spectral_norm = np.linalg.norm(A0, ord=2)
        scale = min(1.0, 0.95 / max(spectral_norm, 1e-12))
        A = A0 * scale

        # Residual innovations
        innovations = r_curr - (r_prev @ A.T)
        Q_sample = np.cov(innovations, rowvar=False)
        if Q_sample.ndim == 0:
            Q_sample = np.eye(n_stats) * float(Q_sample)
        Q = 0.9 * Q_sample + 0.1 * np.diag(np.diag(Q_sample)) + 1e-6 * np.eye(n_stats)

        return cls(A=A, Q=Q)

    def generate_scores(
        self,
        template_counts: np.ndarray,
        theta: float,
        rng: np.random.Generator,
        seasons: Optional[List[Any]] = None,
        gap_days: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        counts = np.asarray(template_counts, dtype=np.float64)
        T, n_stats = counts.shape
        gaps = gap_days if gap_days is not None else np.ones(T, dtype=int)
        season_list = seasons if seasons is not None else [1] * T

        e = np.empty((T, n_stats), dtype=np.float64)
        e_curr = rng.multivariate_normal(np.zeros(n_stats), self.sigma_inf)

        for d in range(T):
            if d == 0 or season_list[d] != season_list[d - 1]:
                # Season reset: draw from stationary distribution
                e_curr = rng.multivariate_normal(np.zeros(n_stats), self.sigma_inf)
            else:
                h = max(1, int(gaps[d]))
                A_h = np.linalg.matrix_power(self.A, h)
                Q_h = self.sigma_inf - A_h @ self.sigma_inf @ A_h.T
                # Numerical PSD repair
                Q_h = (Q_h + Q_h.T) / 2.0
                eigvals = np.linalg.eigvalsh(Q_h)
                if np.min(eigvals) < 1e-9:
                    Q_h += (max(0.0, -np.min(eigvals)) + 1e-7) * np.eye(n_stats)
                eta = rng.multivariate_normal(np.zeros(n_stats), Q_h)
                e_curr = A_h @ e_curr + eta
            e[d] = e_curr

        sqrt_n = np.sqrt(counts)
        sums = counts * theta + sqrt_n * e
        return np.where(counts == 0, 0.0, sums)


class DGP3VarianceStress(BaseScoreDGP):
    """
    DGP3: Variance & Persistence Stress Generator (§8.3).
    Scales residual vectors by c = sqrt(Omega_target / Omega_base) to match target scalar Omega.
    """

    def __init__(
        self,
        base_dgp2: DGP2VectorVAR,
        persistence_mult: float = 1.05,
        omega_target_scale: float = 1.5,
    ):
        self.base_dgp = base_dgp2
        self.persistence_mult = persistence_mult
        self.omega_target_scale = omega_target_scale

        # Stressed A matrix
        stressed_A = base_dgp2.A * persistence_mult
        norm_A = np.linalg.norm(stressed_A, ord=2)
        if norm_A >= 0.98:
            stressed_A *= 0.98 / norm_A
        self.stressed_dgp = DGP2VectorVAR(A=stressed_A, Q=base_dgp2.Q)

    def generate_scores(
        self,
        template_counts: np.ndarray,
        theta: float,
        rng: np.random.Generator,
        seasons: Optional[List[Any]] = None,
        gap_days: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        counts = np.asarray(template_counts, dtype=np.float64)
        raw_sums = self.stressed_dgp.generate_scores(
            template_counts=counts,
            theta=0.0,  # zero mean residuals
            rng=rng,
            seasons=seasons,
            gap_days=gap_days,
        )
        # Extract implied residuals: e = raw_sums / sqrt(counts)
        with np.errstate(divide="ignore", invalid="ignore"):
            sqrt_n = np.sqrt(counts)
            raw_e = np.where(counts > 0, raw_sums / sqrt_n, 0.0)

        # Scale residuals by stress factor
        scale_c = np.sqrt(self.omega_target_scale)
        stressed_e = raw_e * scale_c

        sums = counts * theta + sqrt_n * stressed_e
        return np.where(counts == 0, 0.0, sums)
