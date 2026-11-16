"""
Module: Discrete Distribution Engine (§10.3, §10.4 of NBA_PLAYER_PROPS_PLAN.md & Review Spec)
Provides full mathematical discrete distribution objects (Poisson & NB2):
- Infinite-support queries (pmf, logpmf, cdf, sf, ppf) without UI prefix lumping (§5, §6)
- Over/Under/Push calculation honoring discrete integer lines and tail mass (§7)
- Equal-tail prediction intervals and exact integer medians
- Prefix mass + tail accounting: sum(prefix_pmf(K)) + tail_mass(K) == 1.0 (§5, §6)
"""

import math
from typing import Any, Callable, Dict, List, Optional, Union
import numpy as np
from scipy import stats


class DiscreteDistribution:
    """
    Parametric discrete count distribution object (Poisson or NB2) (§6).
    Optionally calibrated by a monotonic mapping G: [0, 1] -> [0, 1].
    
    Infinite support queries are computed analytically or via scipy,
    ensuring that evaluation at lines L > 70 or in the upper tail is exact
    and never artificially capped or truncated.
    """

    def __init__(
        self,
        mu: float,
        phi: float = 0.0,
        dist_type: str = "poisson",
        calibrator: Optional[Callable[[Union[float, np.ndarray]], Union[float, np.ndarray]]] = None,
        k_ui_prefix: int = 70,
    ):
        if np.isnan(mu) or np.isinf(mu) or mu < 0:
            raise ValueError(f"Invalid mean parameter mu={mu}. Must be finite non-negative.")
        if np.isnan(phi) or np.isinf(phi) or phi < 0:
            raise ValueError(f"Invalid dispersion parameter phi={phi}. Must be finite non-negative.")

        self.mu = max(float(mu), 0.001)
        self.phi = float(phi)
        self.dist_type = dist_type.lower()
        self.calibrator = calibrator
        self.k_ui_prefix = k_ui_prefix

        # Scipy parametric distribution setup
        if self.dist_type in ("nbinom", "nb2") and self.phi > 1e-6:
            self.r = 1.0 / self.phi
            self.p = self.r / (self.r + self.mu)
            self._scipy_dist = stats.nbinom(self.r, self.p)
        else:
            self.r = None
            self.p = None
            self._scipy_dist = stats.poisson(self.mu)

    def pmf(self, k: Union[int, float, np.ndarray]) -> Union[float, np.ndarray]:
        """Exact probability mass function P(X = k) for non-negative integers."""
        if isinstance(k, (int, float)):
            k_int = int(round(k))
            if k_int < 0 or abs(k - k_int) > 1e-6:
                return 0.0
            if self.calibrator is not None:
                # Calibrated PMF: p_cal(k) = F_cal(k) - F_cal(k-1)
                f_k = self.cdf(k_int)
                f_prev = self.cdf(k_int - 1) if k_int > 0 else 0.0
                return max(0.0, float(f_k - f_prev))
            return float(self._scipy_dist.pmf(k_int))

        # Array input
        k_arr = np.asarray(k)
        is_int = (np.abs(k_arr - np.round(k_arr)) < 1e-6) & (k_arr >= 0)
        valid_k = np.where(is_int, np.round(k_arr).astype(int), 0)
        
        if self.calibrator is not None:
            f_k = self.cdf(valid_k)
            f_prev = np.where(valid_k > 0, self.cdf(valid_k - 1), 0.0)
            res = np.where(is_int, np.maximum(0.0, f_k - f_prev), 0.0)
            return res

        res = np.where(is_int, self._scipy_dist.pmf(valid_k), 0.0)
        return res

    def logpmf(self, k: Union[int, float, np.ndarray]) -> Union[float, np.ndarray]:
        """Log probability mass function log P(X = k)."""
        p = self.pmf(k)
        if isinstance(p, (float, int, np.floating)):
            return float(np.log(max(p, 1e-300)))
        return np.log(np.maximum(p, 1e-300))

    def cdf(self, k: Union[int, float, np.ndarray]) -> Union[float, np.ndarray]:
        """Cumulative distribution function F(k) = P(X <= floor(k))."""
        if isinstance(k, (int, float)):
            if k < 0:
                return 0.0
            floor_k = int(math.floor(k))
            raw_f = float(self._scipy_dist.cdf(floor_k))
            if self.calibrator is not None:
                cal_f = float(self.calibrator(raw_f))
                return np.clip(cal_f, 0.0, 1.0)
            return np.clip(raw_f, 0.0, 1.0)

        k_arr = np.asarray(k)
        floor_k = np.floor(k_arr).astype(int)
        raw_f = np.where(k_arr >= 0, self._scipy_dist.cdf(floor_k), 0.0)
        if self.calibrator is not None:
            cal_f = np.asarray(self.calibrator(raw_f))
            return np.clip(cal_f, 0.0, 1.0)
        return np.clip(raw_f, 0.0, 1.0)

    def sf(self, k: Union[int, float, np.ndarray]) -> Union[float, np.ndarray]:
        """Survival function S(k) = P(X > floor(k)) = 1 - F(floor(k))."""
        if isinstance(k, (int, float)):
            if k < 0:
                return 1.0
            floor_k = int(math.floor(k))
            if self.calibrator is not None:
                # Calibrated survival function
                return max(0.0, 1.0 - self.cdf(floor_k))
            return max(0.0, float(self._scipy_dist.sf(floor_k)))

        k_arr = np.asarray(k)
        floor_k = np.floor(k_arr).astype(int)
        if self.calibrator is not None:
            return np.where(k_arr < 0, 1.0, np.maximum(0.0, 1.0 - self.cdf(floor_k)))
        return np.where(k_arr < 0, 1.0, np.maximum(0.0, self._scipy_dist.sf(floor_k)))

    def ppf(self, q: float) -> int:
        """
        Quantile function (smallest integer k >= 0 where F(k) >= q) (§6, §9).
        Computes over the true infinite support using exponential bracketing and bisection.
        """
        if q <= 0.0:
            return 0
        if q >= 1.0:
            return int(self.mu * 10 + 100)

        # Exponential bracketing
        high = max(10, int(self.mu * 2))
        while self.cdf(high) < q:
            high *= 2
            if high > 100000:
                break

        low = 0
        while low < high:
            mid = (low + high) // 2
            if self.cdf(mid) >= q:
                high = mid
            else:
                low = mid + 1
        return int(low)

    def quantile(self, alpha: float) -> int:
        """Alias for ppf(alpha)."""
        return self.ppf(alpha)

    def median(self) -> int:
        """Smallest integer k where F(k) >= 0.5 (§9)."""
        return self.ppf(0.5)

    def mean(self, tol: float = 1e-6, max_k: int = 5000) -> float:
        """
        Expectation of the distribution (§9).
        For uncalibrated distributions, returns exact analytical mean self.mu.
        For calibrated distributions, evaluates E[X] = sum_{k=0}^infty S(k).
        """
        if self.calibrator is None:
            return float(self.mu)
        
        total_mean = 0.0
        k = 0
        while k < max_k:
            sf_val = float(self.sf(k))
            total_mean += sf_val
            if sf_val < tol:
                break
            k += 1
        return float(total_mean)

    def mean_with_error_bound(self, tol: float = 1e-6, max_k: int = 5000) -> Dict[str, float]:
        """
        Computes calibrated expectation with remaining tail error bound (§6, §9).
        """
        if self.calibrator is None:
            return {
                "mean": float(self.mu),
                "tail_error_bound": 0.0,
                "converged": True,
                "k_evaluated": 0,
            }
        
        total_mean = 0.0
        k = 0
        converged = False
        while k < max_k:
            sf_val = float(self.sf(k))
            total_mean += sf_val
            if sf_val < tol:
                converged = True
                break
            k += 1
        
        tail_bound = float(self.sf(k)) * float(self.mu) * 20.0
        return {
            "mean": float(total_mean),
            "tail_error_bound": float(tail_bound),
            "converged": converged,
            "k_evaluated": k,
        }

    def prefix_pmf(self, K: Optional[int] = None) -> np.ndarray:
        """
        Returns PMF array for integer grid [0, 1, ..., K] (§5, §6).
        Does NOT lump or truncate the remaining tail mass into K!
        """
        k_val = K if K is not None else self.k_ui_prefix
        grid = np.arange(k_val + 1)
        return self.pmf(grid)

    def tail_mass(self, K: Optional[int] = None) -> float:
        """Remaining tail mass P(X > K) = sf(K) (§5, §6)."""
        k_val = K if K is not None else self.k_ui_prefix
        return float(self.sf(k_val))

    def prediction_interval(self, coverage: float = 0.90, policy: str = "equal_tail") -> Dict[str, Any]:
        """
        Equal-tail prediction interval [Q((1-c)/2), Q(1 - (1-c)/2)] (§9).
        For 90% coverage: [Q(0.05), Q(0.95)].
        """
        if policy != "equal_tail":
            raise ValueError(f"Unsupported interval policy: {policy}. Use 'equal_tail'.")
        alpha = (1.0 - coverage) / 2.0
        q_low = self.ppf(alpha)
        q_high = self.ppf(1.0 - alpha)
        # Exact model mass covered by discrete interval
        mass = float(self.cdf(q_high) - (self.cdf(q_low - 1) if q_low > 0 else 0.0))
        return {
            "lower": int(q_low),
            "upper": int(q_high),
            "coverage": round(coverage, 2),
            "nominal_model_mass": round(mass, 4),
            "policy": policy,
        }

    def calculate_line_probabilities(self, line: float) -> Dict[str, float]:
        """
        Exact conditional probabilities for Over, Under, Push at any given line L (§7):
        - q_over = 1 - F(floor(L)) = sf(floor(L))
        - q_under = F(ceil(L) - 1)
        - q_push = pmf(L) if L is integer else 0.0
        
        Guaranteed: q_over + q_under + q_push == 1.0 within floating point precision,
        and valid for any line L, including lines > 70.
        """
        floor_l = int(math.floor(line))
        ceil_l = int(math.ceil(line))

        q_over = float(self.sf(floor_l))
        q_under = float(self.cdf(ceil_l - 1)) if ceil_l > 0 else 0.0

        is_integer_line = abs(line - round(line)) < 1e-6
        if is_integer_line:
            q_push = float(self.pmf(int(round(line))))
        else:
            q_push = 0.0

        total = q_over + q_under + q_push
        if total > 0 and abs(total - 1.0) > 1e-9:
            q_over /= total
            q_under /= total
            q_push /= total

        return {
            "line": line,
            "q_over": round(float(q_over), 6),
            "q_under": round(float(q_under), 6),
            "q_push": round(float(q_push), 6),
        }


class DiscreteDistributionEngine:
    """
    Factory and high-level coordinator for discrete count probability distributions (§6).
    Preserves backwards compatibility with legacy API signatures while utilizing
    the full DiscreteDistribution object underneath.
    """

    def __init__(self, dist_type: str = "poisson", k_max: int = 70):
        self.dist_type = dist_type.lower()
        self.k_max = k_max

    def get_distribution(
        self,
        mu: float,
        phi: float = 0.0,
        calibrator: Optional[Callable] = None,
    ) -> DiscreteDistribution:
        """Instantiates a full mathematical DiscreteDistribution object (§6)."""
        return DiscreteDistribution(
            mu=mu,
            phi=phi,
            dist_type=self.dist_type,
            calibrator=calibrator,
            k_ui_prefix=self.k_max,
        )

    def compute_pmf(self, mu: float, phi: float = 0.0, k_max: Optional[int] = None) -> np.ndarray:
        """
        Legacy interface: returns prefix PMF array for grid [0, ..., k_max].
        Ensures clean sum without arbitrarily clipping the distribution tail when mu is high.
        """
        dist = self.get_distribution(mu=mu, phi=phi)
        effective_k = k_max if k_max is not None else max(self.k_max, dist.ppf(0.9999) + 5)
        pmf_arr = dist.prefix_pmf(effective_k)
        # Normalize prefix cleanly for callers expecting a finite vector
        total = np.sum(pmf_arr)
        if total > 0:
            pmf_arr = pmf_arr / total
        return pmf_arr

    def compute_cdf(self, pmf: np.ndarray) -> np.ndarray:
        """Compute cumulative distribution function F(k) = P(X <= k)."""
        cdf = np.cumsum(pmf)
        cdf = np.clip(cdf, 0.0, 1.0)
        cdf[-1] = 1.0
        return cdf

    def calculate_line_probabilities(
        self,
        cdf: Optional[np.ndarray] = None,
        pmf: Optional[np.ndarray] = None,
        line: float = 0.0,
        mu: Optional[float] = None,
        phi: float = 0.0,
    ) -> Dict[str, float]:
        """Calculates line probabilities using exact infinite support if mu provided or exact distribution formulas."""
        if mu is not None:
            dist = self.get_distribution(mu=mu, phi=phi)
            return dist.calculate_line_probabilities(line)

        if cdf is None or pmf is None:
            raise ValueError("Either (mu, phi) or (cdf, pmf) must be provided to calculate line probabilities.")

        floor_l = int(math.floor(line))
        ceil_l = int(math.ceil(line))
        k_max = len(cdf) - 1

        if floor_l < 0:
            q_over = 1.0
        elif floor_l >= k_max:
            q_over = 0.0
        else:
            q_over = 1.0 - cdf[floor_l]

        idx_under = ceil_l - 1
        if idx_under < 0:
            q_under = 0.0
        elif idx_under >= k_max:
            q_under = 1.0
        else:
            q_under = cdf[idx_under]

        is_integer_line = abs(line - round(line)) < 1e-6
        if is_integer_line and 0 <= int(round(line)) <= k_max:
            q_push = float(pmf[int(round(line))])
        else:
            q_push = 0.0

        total = q_over + q_under + q_push
        if total > 0:
            q_over /= total
            q_under /= total
            q_push /= total

        return {
            "line": line,
            "q_over": round(float(q_over), 4),
            "q_under": round(float(q_under), 4),
            "q_push": round(float(q_push), 4),
        }

    def compute_median(self, cdf: np.ndarray) -> int:
        """Find the smallest integer k where F(k) >= 0.5."""
        indices = np.where(cdf >= 0.5)[0]
        return int(indices[0]) if len(indices) > 0 else 0

    def compute_prediction_interval(self, pmf: np.ndarray, coverage: float = 0.90) -> Dict[str, Any]:
        """Compute equal-tail prediction interval [Q(alpha), Q(1-alpha)] from PMF."""
        cdf = self.compute_cdf(pmf)
        alpha = (1.0 - coverage) / 2.0
        idx_low = int(np.where(cdf >= alpha)[0][0])
        idx_high = int(np.where(cdf >= (1.0 - alpha))[0][0])
        return {
            "lower": idx_low,
            "upper": idx_high,
            "coverage": coverage,
        }
