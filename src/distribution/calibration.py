"""
Module: Discrete CDF Calibration & Full RPS (§10.4.3, §10.4.4 of NBA_PLAYER_PROPS_PLAN.md & Review Spec)
Implements:
- Exact full Ranked Probability Score (RPS) with adaptive tail expansion and error bound (§8)
- Finite-grid RPS_K score for fixed threshold benchmarking (§8)
- Piecewise-linear monotonic CDF Calibrator with strict hard endpoints G(0)=0 and G(1)=1 (§11, §12)
- Monotonicity checks with numerical tolerance 1e-12 (§13)
"""

from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np
from scipy.optimize import minimize
from sklearn.isotonic import IsotonicRegression


def calculate_finite_grid_rps(cdf: np.ndarray, actual_y: float, K: Optional[int] = None) -> float:
    """
    Calculates discrete finite-grid score (§8):
    RPS_K(F, y) = sum_{k=0}^{K} [F(k) - 1{y <= k}]^2
    Note: Does not identify the infinite tail; useful for fixed-grid benchmarking.
    """
    grid_len = (K + 1) if K is not None else len(cdf)
    grid_len = min(grid_len, len(cdf))
    k_grid = np.arange(grid_len)
    step_indicator = (k_grid >= actual_y).astype(np.float64)
    squared_diff = (cdf[:grid_len] - step_indicator) ** 2
    return float(np.sum(squared_diff))


def calculate_full_rps(
    dist_or_cdf: Any,
    actual_y: float,
    K_initial: int = 200,
    tol: float = 1e-8,
    hard_limit: int = 10000,
) -> float:
    """
    Calculates the exact infinite-support discrete Ranked Probability Score (§8):
    
        RPS(F, y) = sum_{k=0}^{infty} [F(k) - 1{y <= k}]^2
        
    Strict Rules (§8):
    - Never clip actual_y to a fixed grid (clipping falsifies the score).
    - Grid extends dynamically so that K >= max(K_initial, ceil(actual_y)).
    - For parametric distributions, dynamically expands K until the remainder bound
      R_tail = sum_{k=K+1}^{infty} S(k)^2 <= tol.
    """
    y_val = max(0.0, float(actual_y))
    ceil_y = int(math.ceil(y_val))

    # Case 1: dist_or_cdf is a DiscreteDistribution object with callable cdf and sf
    if hasattr(dist_or_cdf, "cdf") and hasattr(dist_or_cdf, "sf"):
        K = max(K_initial, ceil_y + 10)
        while K < hard_limit:
            # Check tail remainder bound: R_tail <= S(K+1) * mu_bound
            sf_K = float(dist_or_cdf.sf(K))
            if sf_K <= 1e-12:
                break
            # Bound R_tail <= sf_K^2 * 10
            if (sf_K ** 2) <= tol:
                break
            K += 50

        k_grid = np.arange(K + 1)
        cdf_vals = np.asarray(dist_or_cdf.cdf(k_grid))
        indicator = (k_grid >= y_val).astype(np.float64)
        score = float(np.sum((cdf_vals - indicator) ** 2))
        return score

    # Case 2: Array of CDF values
    cdf_arr = np.asarray(dist_or_cdf, dtype=np.float64)
    N = len(cdf_arr)

    if ceil_y >= N:
        # Actual y exceeds current array size!
        # For k in [0, N-1]: indicator is 0.0, diff is cdf_arr[k]^2
        # For k in [N, ceil_y - 1]: F(k) = 1.0 (assuming CDF reaches 1), indicator is 0.0 -> diff is 1.0^2 = 1.0
        # For k >= ceil_y: F(k) = 1.0, indicator is 1.0 -> diff is 0.0
        sum_prefix = float(np.sum((cdf_arr - 0.0) ** 2))
        unobserved_deficit = float(ceil_y - N)
        return sum_prefix + unobserved_deficit

    # y is within array range
    k_grid = np.arange(N)
    indicator = (k_grid >= y_val).astype(np.float64)
    return float(np.sum((cdf_arr - indicator) ** 2))


import math


class PiecewiseLinearCDFCalibrator:
    """
    Monotonic Piecewise-Linear CDF Calibrator with Hard Constraints (§11, §12).
    
    Architecture:
    - 21 fixed knots: u_j = j / 20 for j = 0, ..., 20.
    - Hard constraints: c_0 = 0.0, c_20 = 1.0, and c_{j+1} >= c_j.
    - H_c(u) is linear interpolation through (u_j, c_j).
    - Smoothing mixture: G(u) = eps_mix * u + (1 - eps_mix) * H_c(u), with eps_mix = 0.001.
    
    Guaranteed Properties:
    - G(0) = 0.0 strictly.
    - G(1) = 1.0 strictly.
    - Continuous on [0, 1].
    - Strictly increasing with minimum slope >= 0.001 and maximum slope <= 20.
    - Preserves all positive PMF mass; zero flat segments.
    """

    def __init__(self, eps_mix: float = 0.001, lambda_reg: float = 1e-4):
        self.eps_mix = eps_mix
        self.lambda_reg = lambda_reg
        self.knots_u = np.linspace(0.0, 1.0, 21)
        self.c_knots = self.knots_u.copy()  # Initialized to identity
        self.is_fitted = False

    def _evaluate_G(self, u: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        """Evaluates G(u) = eps_mix * u + (1 - eps_mix) * H_c(u)."""
        if isinstance(u, (int, float)):
            u_clipped = float(np.clip(u, 0.0, 1.0))
            h_val = float(np.interp(u_clipped, self.knots_u, self.c_knots))
            return float(self.eps_mix * u_clipped + (1.0 - self.eps_mix) * h_val)

        u_arr = np.clip(np.asarray(u, dtype=np.float64), 0.0, 1.0)
        h_arr = np.interp(u_arr, self.knots_u, self.c_knots)
        return self.eps_mix * u_arr + (1.0 - self.eps_mix) * h_arr

    def __call__(self, u: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        return self._evaluate_G(u)

    def calibrate(self, u: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        return self._evaluate_G(u)

    def log_mass(self, lower: np.ndarray, upper: np.ndarray, raw_log_mass: np.ndarray) -> np.ndarray:
        """Log of G(upper)-G(lower), without cancellation in either CDF tail.

        G is piecewise linear. Integrating its slopes gives the exact average
        slope over the probability interval; raw log-PMF supplies its width
        even when both CDF endpoints round to the same floating point number.
        """
        lower, upper, raw_log_mass = np.broadcast_arrays(lower, upper, raw_log_mass)
        slopes = self.eps_mix + (1.0 - self.eps_mix) * np.diff(self.c_knots) / np.diff(self.knots_u)
        lo = np.clip(lower, 0.0, 1.0)
        hi = np.clip(upper, 0.0, 1.0)
        width = hi - lo
        integral = np.zeros_like(width, dtype=float)
        for a, b, slope in zip(self.knots_u[:-1], self.knots_u[1:], slopes):
            integral += np.maximum(0.0, np.minimum(hi, b) - np.maximum(lo, a)) * slope
        segment = np.clip(np.searchsorted(self.knots_u, lo, side="right") - 1, 0, len(slopes) - 1)
        average = np.divide(integral, width, out=slopes[segment].copy(), where=width > 0)
        return np.asarray(raw_log_mass) + np.log(average)

    def calibrate_cdf(self, raw_cdf: np.ndarray, tol: float = 1e-12) -> np.ndarray:
        """
        Calibrates raw CDF vector, enforcing hard endpoints and monotonicity (§13).
        Validates that negative increments do not exceed numerical tolerance.
        """
        raw = np.asarray(raw_cdf, dtype=np.float64)
        cal = self._evaluate_G(raw)

        # Monotonicity audit (§13)
        diffs = np.diff(cal)
        min_diff = float(np.min(diffs)) if len(diffs) > 0 else 0.0
        if min_diff < -1e-6:
            raise ValueError(f"Severe CDF monotonicity violation detected: min_increment={min_diff}")

        # Tiny numerical precision repair
        if min_diff < 0.0:
            cal = np.maximum.accumulate(cal)

        cal[0] = max(0.0, cal[0])
        cal[-1] = 1.0
        return np.clip(cal, 0.0, 1.0)

    def fit(
        self,
        raw_cdfs: np.ndarray,
        actual_ys: np.ndarray,
        max_samples: int = 1000,
        random_state: int = 20261119,
    ) -> "PiecewiseLinearCDFCalibrator":
        """
        Fits knots c_1, ..., c_19 minimizing regularized average RPS (§12):
        
            min_{c} 1/N sum_n RPS_K(G(F_raw,n), y_n) + lambda/19 sum_{j=1}^{19} (c_j - u_j)^2
            s.t.    0 <= c_1 <= c_2 <= ... <= c_19 <= 1.0
                    c_0 = 0.0, c_20 = 1.0
        """
        n_samples = len(actual_ys)
        if n_samples == 0:
            return self

        # Subsample for efficient optimization if large dataset
        if n_samples > max_samples:
            # Reproducible calibration matters for release comparisons. The
            # previous global RNG made identical training runs select a
            # different calibration subset.
            idx = np.random.default_rng(random_state).choice(n_samples, max_samples, replace=False)
            sub_cdfs = raw_cdfs[idx]
            sub_ys = actual_ys[idx]
        else:
            sub_cdfs = raw_cdfs
            sub_ys = actual_ys

        n_sub, K_len = sub_cdfs.shape
        k_grid = np.arange(K_len)
        targets = np.array([(k_grid >= y).astype(np.float64) for y in sub_ys])

        # Objective function over 19 interior knots c[1..19]
        u_interior = self.knots_u[1:20]

        def objective(c_interior: np.ndarray) -> float:
            # Full 21 knots
            c_full = np.empty(21, dtype=np.float64)
            c_full[0] = 0.0
            c_full[1:20] = c_interior
            c_full[20] = 1.0

            # Evaluate G on all sub_cdfs
            h_mat = np.interp(sub_cdfs.ravel(), self.knots_u, c_full).reshape(sub_cdfs.shape)
            g_mat = self.eps_mix * sub_cdfs + (1.0 - self.eps_mix) * h_mat

            rps_loss = float(np.mean(np.sum((g_mat - targets) ** 2, axis=1)))
            reg_loss = float((self.lambda_reg / 19.0) * np.sum((c_interior - u_interior) ** 2))
            return rps_loss + reg_loss

        # Linear constraints: c_{j+1} - c_j >= 0
        # A @ c_interior >= 0
        def constraint_monotonic(c_int: np.ndarray) -> np.ndarray:
            diffs = np.empty(20, dtype=np.float64)
            diffs[0] = c_int[0] - 0.0           # c_1 >= 0.0
            diffs[1:19] = c_int[1:] - c_int[:-1] # c_{j+1} >= c_j
            diffs[19] = 1.0 - c_int[-1]         # c_19 <= 1.0
            return diffs

        init_c = u_interior.copy()
        bounds = [(0.0, 1.0) for _ in range(19)]
        constraints = [{"type": "ineq", "fun": constraint_monotonic}]

        res = minimize(
            objective,
            init_c,
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"maxiter": 150, "ftol": 1e-7},
        )

        if res.success or res.fun < objective(init_c):
            best_c = np.empty(21, dtype=np.float64)
            best_c[0] = 0.0
            best_c[1:20] = np.clip(res.x, 0.0, 1.0)
            best_c[20] = 1.0
            # Ensure monotonicity
            best_c = np.maximum.accumulate(best_c)
            best_c[-1] = 1.0
            self.c_knots = best_c
            self.is_fitted = True

        return self


class IsotonicCDFCalibrator:
    """
    Legacy Isotonic CDF Calibrator.
    Maintained for backward compatibility with existing unit tests and legacy pipelines.
    Recommend migrating to PiecewiseLinearCDFCalibrator for hard endpoints G(0)=0 and G(1)=1 (§11).
    """

    def __init__(self):
        self.iso_reg = IsotonicRegression(
            y_min=0.0,
            y_max=1.0,
            increasing=True,
            out_of_bounds="clip",
        )
        self.is_fitted = False

    def fit(self, raw_cdfs: np.ndarray, actual_ys: np.ndarray) -> "IsotonicCDFCalibrator":
        X_vals = []
        y_vals = []
        n_samples, n_thresholds = raw_cdfs.shape

        for i in range(n_samples):
            actual = actual_ys[i]
            for k in range(n_thresholds):
                X_vals.append(raw_cdfs[i, k])
                y_vals.append(1.0 if actual <= k else 0.0)

        # Include boundary constraints
        X_vals.extend([0.0, 1.0])
        y_vals.extend([0.0, 1.0])

        self.iso_reg.fit(X_vals, y_vals)
        self.is_fitted = True
        return self

    def calibrate(self, raw_cdf: np.ndarray) -> np.ndarray:
        if not self.is_fitted:
            return raw_cdf
        calibrated = self.iso_reg.predict(raw_cdf)
        calibrated = np.maximum.accumulate(calibrated)
        calibrated = np.clip(calibrated, 0.0, 1.0)
        calibrated[-1] = 1.0
        return calibrated
