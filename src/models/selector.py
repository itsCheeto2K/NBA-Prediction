"""
Module: Stats-Only Model Selector & Release Bundle Architecture (§10–11 of NBA_PLAYER_PROPS_PLAN.md & Review Spec)
Provides:
- 12 mandatory mean candidate configurations per stat (WeightedAvg K=5,10,20, MinutesRate, LightGBM Poisson/RMSE, CatBoost Poisson/RMSE)
- 48 composite distribution recipes per stat (Mean x Raw[Poisson/NB2] x Calibrator[Identity/PiecewiseLinear])
- Temporal B0 internal split: 40% D_warm, 30% D_phi (for OOF dispersion fitting), 30% D_G (for OOF proxy calibrator fitting)
- Scalar phi fitting on out-of-fold predictions via NB2 negative log-likelihood
- Full-RPS evaluation on B1 with 0.5% R_ref indifference band shortlist and deterministic tie-breaking
- Distribution metric conflict safety diagnostic
- Atomic ModelBundle serialization and deserialization
"""

import hashlib
import json
import logging
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.special import gammaln

import lightgbm as lgb

from src.config import settings
from src.distribution.calibration import (
    PiecewiseLinearCDFCalibrator,
    calculate_full_rps,
    calculate_finite_grid_rps,
)
from src.distribution.engine import DiscreteDistribution
from src.models.baseline import (
    MinutesRateBaseline,
    WeightedAverageBaseline,
    calculate_poisson_deviance,
)

logger = logging.getLogger(__name__)


@dataclass
class MeanCandidateConfig:
    """Specification of a candidate mean learner (§4.1)."""
    candidate_id: str
    family: str  # "weighted_avg", "minutes_rate", "lgbm", "catboost"
    objective: str  # "poisson", "squared_error"
    params: Dict[str, Any] = field(default_factory=dict)
    family_rank: int = 2  # 0: weighted_avg, 1: minutes_rate, 2: boosting
    size_rank: int = 0    # 0: small (31 leaves / depth 6), 1: large (63 leaves / depth 8)


@dataclass
class CompositeRecipe:
    """Full composite distribution recipe (§4.2)."""
    recipe_id: str
    mean_candidate: MeanCandidateConfig
    raw_family: str       # "poisson" (phi=0) or "nb2" (phi fitted)
    calibrator_type: str  # "identity" or "piecewise_linear"
    raw_family_rank: int = 0  # 0: poisson, 1: nb2
    calibrator_rank: int = 0  # 0: identity, 1: piecewise_linear


def get_mandatory_mean_candidates(stat: str = "pts") -> List[MeanCandidateConfig]:
    """
    Returns the mandatory 12 mean configs per stat (§4.1):
    - 3 Weighted Average (K=5, 10, 20)
    - 1 Minutes x Shrunk Rate
    - 2 LightGBM Poisson (num_leaves=31, 63)
    - 2 LightGBM Squared-Error (num_leaves=31, 63)
    - 2 CatBoost Poisson (depth=6, 8)
    - 2 CatBoost RMSE (depth=6, 8)
    """
    candidates = [
        # Weighted Average Baselines
        MeanCandidateConfig(
            candidate_id=f"WeightedAvg_K5_{stat}",
            family="weighted_avg",
            objective="squared_error",
            params={"k": 5},
            family_rank=0,
            size_rank=0,
        ),
        MeanCandidateConfig(
            candidate_id=f"WeightedAvg_K10_{stat}",
            family="weighted_avg",
            objective="squared_error",
            params={"k": 10},
            family_rank=0,
            size_rank=0,
        ),
        MeanCandidateConfig(
            candidate_id=f"WeightedAvg_K20_{stat}",
            family="weighted_avg",
            objective="squared_error",
            params={"k": 20},
            family_rank=0,
            size_rank=0,
        ),
        # Minutes x Rate Baseline
        MeanCandidateConfig(
            candidate_id=f"MinutesRate_{stat}",
            family="minutes_rate",
            objective="poisson",
            params={},
            family_rank=1,
            size_rank=0,
        ),
        # LightGBM Poisson
        MeanCandidateConfig(
            candidate_id=f"LGBM_Poisson_leaves31_{stat}",
            family="lgbm",
            objective="poisson",
            params={"num_leaves": 31, "learning_rate": 0.05, "n_estimators": 300},
            family_rank=2,
            size_rank=0,
        ),
        MeanCandidateConfig(
            candidate_id=f"LGBM_Poisson_leaves63_{stat}",
            family="lgbm",
            objective="poisson",
            params={"num_leaves": 63, "learning_rate": 0.05, "n_estimators": 300},
            family_rank=2,
            size_rank=1,
        ),
        # LightGBM Squared-Error
        MeanCandidateConfig(
            candidate_id=f"LGBM_RMSE_leaves31_{stat}",
            family="lgbm",
            objective="squared_error",
            params={"num_leaves": 31, "learning_rate": 0.05, "n_estimators": 300},
            family_rank=2,
            size_rank=0,
        ),
        MeanCandidateConfig(
            candidate_id=f"LGBM_RMSE_leaves63_{stat}",
            family="lgbm",
            objective="squared_error",
            params={"num_leaves": 63, "learning_rate": 0.05, "n_estimators": 300},
            family_rank=2,
            size_rank=1,
        ),
        # CatBoost Poisson
        MeanCandidateConfig(
            candidate_id=f"CatBoost_Poisson_depth6_{stat}",
            family="catboost",
            objective="poisson",
            params={"depth": 6, "learning_rate": 0.05, "iterations": 300},
            family_rank=2,
            size_rank=0,
        ),
        MeanCandidateConfig(
            candidate_id=f"CatBoost_Poisson_depth8_{stat}",
            family="catboost",
            objective="poisson",
            params={"depth": 8, "learning_rate": 0.05, "iterations": 300},
            family_rank=2,
            size_rank=1,
        ),
        # CatBoost RMSE
        MeanCandidateConfig(
            candidate_id=f"CatBoost_RMSE_depth6_{stat}",
            family="catboost",
            objective="squared_error",
            params={"depth": 6, "learning_rate": 0.05, "iterations": 300},
            family_rank=2,
            size_rank=0,
        ),
        MeanCandidateConfig(
            candidate_id=f"CatBoost_RMSE_depth8_{stat}",
            family="catboost",
            objective="squared_error",
            params={"depth": 8, "learning_rate": 0.05, "iterations": 300},
            family_rank=2,
            size_rank=1,
        ),
    ]
    return candidates


def build_composite_recipes(mean_candidates: List[MeanCandidateConfig]) -> List[CompositeRecipe]:
    """
    Expands 12 mean candidates x 2 raw distributions (Poisson, NB2) x 2 calibrators (Identity, PiecewiseLinear)
    yielding 48 composite recipes (§4.2).
    """
    recipes = []
    for mc in mean_candidates:
        for raw in ["poisson", "nb2"]:
            for cal in ["identity", "piecewise_linear"]:
                recipe_id = f"{mc.candidate_id}__{raw}__{cal}"
                recipes.append(
                    CompositeRecipe(
                        recipe_id=recipe_id,
                        mean_candidate=mc,
                        raw_family=raw,
                        calibrator_type=cal,
                        raw_family_rank=0 if raw == "poisson" else 1,
                        calibrator_rank=0 if cal == "identity" else 1,
                    )
                )
    return recipes


def fit_dispersion_phi(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """
    Fits empirical scalar dispersion phi >= 0 minimizing NB2 negative log-likelihood (§4, §6):
    NB2 parameterization: r = 1/phi, p = r / (r + mu).
    log PMF(y) = lgamma(y + r) - lgamma(r) - lgamma(y + 1) + r*log(p) + y*log(1 - p).
    """
    y = np.maximum(np.asarray(y_true, dtype=np.float64), 0.0)
    mu = np.maximum(np.asarray(y_pred, dtype=np.float64), 1e-4)

    # Filter non-finite or empty
    mask = np.isfinite(y) & np.isfinite(mu)
    y_filt = y[mask]
    mu_filt = mu[mask]
    if len(y_filt) < 10:
        return 0.05  # safe default

    def neg_log_likelihood(phi: float) -> float:
        if phi <= 1e-6:
            # Poisson limit
            return float(np.sum(mu_filt - y_filt * np.log(mu_filt) + gammaln(y_filt + 1.0)))
        r = 1.0 / phi
        p = r / (r + mu_filt)
        term1 = gammaln(y_filt + r) - gammaln(r) - gammaln(y_filt + 1.0)
        term2 = r * np.log(p) + y_filt * np.log(np.maximum(1.0 - p, 1e-12))
        return -float(np.sum(term1 + term2))

    res = minimize_scalar(neg_log_likelihood, bounds=(1e-5, 2.0), method="bounded")
    best_phi = float(res.x)
    return round(best_phi, 5) if best_phi > 1e-4 else 0.0


@dataclass
class ModelBundle:
    """
    Complete production release bundle (§11).
    Contains full execution specifications for atomic loading in API/inference.
    """
    bundle_id: str
    stat: str
    mean_family: str
    mean_config: Dict[str, Any]
    feature_schema: List[str]
    numerical_projection_policy: str
    raw_distribution_family: str
    fitted_phi: float
    calibrator_type: str
    calibrator_knots: Optional[List[float]] = None
    mean_model_path: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    selection_report: Dict[str, Any] = field(default_factory=dict)

    _mean_predictor: Optional[Any] = field(default=None, repr=False)
    _calibrator_obj: Optional[Any] = field(default=None, repr=False)

    def save(self, target_dir: Union[str, Path]) -> Path:
        out_path = Path(target_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        manifest_path = out_path / "bundle_manifest.json"

        bundle_dict = asdict(self)
        bundle_dict.pop("_mean_predictor", None)
        bundle_dict.pop("_calibrator_obj", None)

        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(bundle_dict, f, indent=2)
        logger.info(f"Saved atomic ModelBundle for {self.stat} to {out_path}")
        return manifest_path

    @classmethod
    def load(cls, bundle_dir: Union[str, Path]) -> "ModelBundle":
        b_path = Path(bundle_dir)
        manifest_path = b_path / "bundle_manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"ModelBundle manifest not found at {manifest_path}")

        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        bundle = cls(**data)

        # Restore calibrator
        if bundle.calibrator_type == "piecewise_linear" and bundle.calibrator_knots is not None:
            calibrator = PiecewiseLinearCDFCalibrator(eps_mix=0.001)
            calibrator.c_knots = np.asarray(bundle.calibrator_knots, dtype=np.float64)
            bundle._calibrator_obj = calibrator
        else:
            bundle._calibrator_obj = None

        # Restore mean predictor
        if bundle.mean_family == "lgbm":
            model_file = b_path / bundle.mean_model_path if bundle.mean_model_path else (b_path / f"lgbm_{bundle.stat.lower()}.txt")
            if model_file.exists():
                booster = lgb.Booster(model_file=str(model_file))
                bundle._mean_predictor = booster
        elif bundle.mean_family == "catboost":
            from catboost import CatBoostRegressor
            model_file = b_path / bundle.mean_model_path if bundle.mean_model_path else (b_path / f"catboost_{bundle.stat.lower()}.cbm")
            if model_file.exists():
                cb = CatBoostRegressor()
                cb.load_model(str(model_file))
                bundle._mean_predictor = cb
        elif bundle.mean_family == "weighted_avg":
            k_val = bundle.mean_config.get("k", 5)
            bundle._mean_predictor = WeightedAverageBaseline(stat=bundle.stat.lower(), k=k_val)
        elif bundle.mean_family == "minutes_rate":
            bundle._mean_predictor = MinutesRateBaseline(stat=bundle.stat.lower())

        return bundle

    def predict_mean(self, df_row: pd.DataFrame) -> float:
        """Computes point mean according to the bundle's numerical projection policy."""
        if self.mean_family == "lgbm":
            feat_names = [f for f in self.feature_schema if f in df_row.columns]
            X = df_row[feat_names].fillna(0.0).to_numpy(dtype=np.float64)
            raw = float(self._mean_predictor.predict(X)[0])
        elif self.mean_family == "catboost":
            feat_names = [f for f in self.feature_schema if f in df_row.columns]
            X = df_row[feat_names].fillna(0.0).to_numpy(dtype=np.float64)
            raw = float(self._mean_predictor.predict(X)[0])
        elif self.mean_family in ("weighted_avg", "minutes_rate"):
            raw = float(self._mean_predictor.predict(df_row)[0])
        else:
            raw = 10.0

        # Apply projection policy (§5.3)
        return max(1e-6, raw)

    def predict_distribution(self, df_row: pd.DataFrame) -> DiscreteDistribution:
        """Returns the full calibrated DiscreteDistribution object (§6)."""
        mu = self.predict_mean(df_row)
        dist = DiscreteDistribution(
            mu=mu,
            phi=self.fitted_phi,
            dist_type=self.raw_distribution_family,
            calibrator=self._calibrator_obj,
            k_ui_prefix=70,
        )
        return dist


class ModelSelector:
    """
    Executes Section 10-11 Model Selection & Verification Protocol:
    1. Splits B0 into chronological contiguous D_warm (40%), D_phi (30%), D_G (30%) (§6).
    2. Fits dispersion phi on D_phi OOF predictions.
    3. Fits proxy calibrator G on D_G OOF predictions.
    4. Evaluates all 48 composite recipes on B1 using discrete Full RPS.
    5. Formulates shortlist within 0.5% R_ref indifference band and applies deterministic tie-breaking (§7.2).
    6. Performs safety diagnostics: distribution metric conflict check and interval coverage (§7.3).
    7. Exports winner as a standalone production ModelBundle (§11).
    """

    def __init__(
        self,
        stat: str = "pts",
        models_dir: Optional[Path] = None,
        reports_dir: Optional[Path] = None,
    ):
        self.stat = stat.lower()
        self.models_dir = models_dir or (settings.BASE_DIR / "models")
        self.reports_dir = reports_dir or (settings.BASE_DIR / "reports")
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def split_b0_chronological(
        self, df_b0: pd.DataFrame
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """Contiguous chronological 40% D_warm, 30% D_phi, 30% D_G split (§6)."""
        df_sorted = df_b0.sort_values("game_date").copy()
        unique_dates = df_sorted["game_date"].unique()
        n_dates = len(unique_dates)

        idx_warm = math.floor(0.40 * n_dates)
        idx_phi = idx_warm + math.floor(0.30 * n_dates)

        dates_warm = set(unique_dates[:idx_warm])
        dates_phi = set(unique_dates[idx_warm:idx_phi])
        dates_g = set(unique_dates[idx_phi:])

        df_warm = df_sorted[df_sorted["game_date"].isin(dates_warm)].copy()
        df_phi = df_sorted[df_sorted["game_date"].isin(dates_phi)].copy()
        df_g = df_sorted[df_sorted["game_date"].isin(dates_g)].copy()

        logger.info(
            f"B0 Temporal Split for {self.stat.upper()}: "
            f"D_warm={len(df_warm)} rows ({len(dates_warm)} dates), "
            f"D_phi={len(df_phi)} rows ({len(dates_phi)} dates), "
            f"D_G={len(df_g)} rows ({len(dates_g)} dates)"
        )
        return df_warm, df_phi, df_g

    def select_best_recipe(
        self,
        recipes_results: List[Dict[str, Any]],
        ref_recipe_id: str,
    ) -> Dict[str, Any]:
        """
        Executes Section 7.2 Selection & Tie-Break Protocol:
        - R_best = min_m R_m
        - R_ref = recipe_id == ref_recipe_id
        - tol_s = max(1e-8, 0.005 * R_ref)
        - Shortlist: recipes with R_m <= R_best + tol_s
        - Tie-break tuple:
          (mean_family_rank, raw_family_rank, G_rank, size_rank, latency, candidate_id)
        """
        ref_res = next((r for r in recipes_results if r["recipe_id"] == ref_recipe_id), None)
        if ref_res is None:
            # Fallback to mean of all recipes if reference missing
            r_ref = recipes_results[0]["mean_full_rps"]
        else:
            r_ref = ref_res["mean_full_rps"]

        r_best = min(r["mean_full_rps"] for r in recipes_results)
        best_recipe = min(recipes_results, key=lambda x: x["mean_full_rps"])

        tol_s = max(1e-8, 0.005 * r_ref)
        shortlist = [r for r in recipes_results if r["mean_full_rps"] <= (r_best + tol_s)]

        # RPS and log score are both proper scores but emphasize different
        # failure modes. Do not select a calibration recipe that is materially
        # worse on log score when an RPS-near-equivalent option avoids that
        # regression. If no option satisfies the guard, retain the original
        # RPS shortlist decision and expose the conflict below.
        best_log_score = min(r["mean_neg_log_score"] for r in recipes_results)
        log_safe = [r for r in shortlist if r["mean_neg_log_score"] <= best_log_score * 1.01 + 1e-4]
        if log_safe:
            shortlist = log_safe

        # Sort shortlist by deterministic tie-break tuple (§7.2)
        def tie_break_key(r: Dict[str, Any]) -> Tuple:
            return (
                r["mean_family_rank"],
                r["raw_family_rank"],
                r["calibrator_rank"],
                r["size_rank"],
                r.get("latency", 0.0),
                r["recipe_id"],
            )

        sorted_shortlist = sorted(shortlist, key=tie_break_key)
        finalist = sorted_shortlist[0]

        # Safety diagnostic check (§7.3)
        conflict_flag = False
        log_score_finalist = finalist.get("mean_neg_log_score", 0.0)
        log_score_best = best_log_score
        if log_score_best > 0:
            diff_rel = (log_score_finalist - log_score_best) / log_score_best
            diff_abs = log_score_finalist - log_score_best
            if diff_rel > 0.01 and diff_abs > 1e-4:
                conflict_flag = True

        return {
            "selected_winner": finalist,
            "best_rps_recipe": best_recipe,
            "r_best": round(r_best, 5),
            "r_ref": round(r_ref, 5),
            "indifference_tolerance": round(tol_s, 6),
            "shortlist_count": len(shortlist),
            "shortlist_recipe_ids": [r["recipe_id"] for r in sorted_shortlist],
            "distribution_metric_conflict": conflict_flag,
        }

    def evaluate_recipe_on_b1(
        self,
        mu_b1: np.ndarray,
        y_b1: np.ndarray,
        raw_family: str,
        phi: float,
        calibrator_obj: Optional[PiecewiseLinearCDFCalibrator],
        k_eval: int = 70,
    ) -> Dict[str, float]:
        """
        Fast vectorized Full RPS and probabilistic scoring on B1 on full support (§8, §11).
        Uses adaptive grid spanning outcomes and full distribution support without clipping.
        RPS_i = sum_{k=0}^K [F(k) - 1{y_i <= k}]^2
        """
        N = len(y_b1)
        mu_arr = np.maximum(mu_b1, 1e-4)
        y_arr = np.maximum(y_b1, 0.0)

        # Adaptive evaluation grid spanning tail of distribution and all outcomes (§8, §11, Issue 27)
        max_y = float(np.max(y_arr)) if len(y_arr) > 0 else 0.0
        max_mu = float(np.max(mu_arr)) if len(mu_arr) > 0 else 0.0
        from scipy import stats
        if raw_family in ("nb2", "nbinom") and phi > 1e-5:
            r = 1.0 / phi
            p_val = r / (r + max_mu)
            tail_bound = int(stats.nbinom.ppf(1.0 - 1e-6, r, p_val))
        else:
            tail_bound = int(stats.poisson.ppf(1.0 - 1e-6, max(max_mu, 1e-3)))

        k_upper = max(
            int(np.ceil(max_y)) + 25,
            tail_bound + 25,
            k_eval,
            80,
        )
        grid_k = np.arange(k_upper + 1)
        indicator = (grid_k[None, :] >= y_arr[:, None]).astype(np.float64)

        # 1. Compute raw CDFs
        if raw_family in ("nb2", "nbinom") and phi > 1e-5:
            r = 1.0 / phi
            p = r / (r + mu_arr)
            raw_cdfs = stats.nbinom.cdf(grid_k[None, :], r, p[:, None])
        else:
            raw_cdfs = stats.poisson.cdf(grid_k[None, :], mu_arr[:, None])

        # 2. Apply calibrator if present (monotonic accumulate, preserving boundary)
        if calibrator_obj is not None:
            cal_cdfs = calibrator_obj(raw_cdfs)
            cal_cdfs = np.maximum.accumulate(cal_cdfs, axis=1)
        else:
            cal_cdfs = raw_cdfs

        # 3. Full RPS calculation on full support
        squared_diffs = np.sum((cal_cdfs - indicator) ** 2, axis=1)
        full_rps_per_row = squared_diffs
        mean_full_rps = float(np.mean(full_rps_per_row))

        # 4. Discrete negative log-score diagnostic without artificial clipping or floor distortion (§7.3, Issue 27)
        y_ints = np.round(y_arr).astype(int)
        if raw_family in ("nb2", "nbinom") and phi > 1e-5:
            r = 1.0 / phi
            p_arr = r / (r + mu_arr)
            raw_logpmf = stats.nbinom.logpmf(y_ints, r, p_arr)
        else:
            raw_logpmf = stats.poisson.logpmf(y_ints, mu_arr)

        if calibrator_obj is None:
            log_scores = raw_logpmf
        else:
            f_y = np.take_along_axis(raw_cdfs, y_ints[:, None], axis=1).reshape(-1)
            f_prev = np.where(
                y_ints > 0,
                np.take_along_axis(raw_cdfs, np.maximum(0, y_ints - 1)[:, None], axis=1).reshape(-1),
                0.0,
            )
            log_scores = calibrator_obj.log_mass(f_prev, f_y, raw_logpmf)

        mean_neg_log_score = float(-np.mean(log_scores))

        # 5. 90% prediction interval coverage (§7.3)
        q05 = np.argmax(cal_cdfs >= 0.05, axis=1)
        q95 = np.argmax(cal_cdfs >= 0.95, axis=1)
        q95 = np.where(np.max(cal_cdfs, axis=1) < 0.95, k_upper, q95)
        in_interval = (y_arr >= q05) & (y_arr <= q95)
        coverage_90 = float(np.mean(in_interval))

        return {
            "mean_full_rps": round(mean_full_rps, 5),
            "mean_neg_log_score": round(mean_neg_log_score, 4),
            "coverage_90": round(coverage_90, 4),
        }

    def execute_selection_pipeline(
        self,
        df_b0: pd.DataFrame,
        df_b1: pd.DataFrame,
        features: List[str],
        fast_mode: bool = False,
    ) -> Dict[str, Any]:
        """
        Runs the complete Selection & Verification Pipeline (§6, §7, §11).
        Evaluates 12 mean configs x 4 distribution wrappers = 48 composite recipes.
        """
        import time
        target_col = f"target_{self.stat}"
        y_b1 = df_b1[target_col].to_numpy(dtype=np.float64)

        df_warm, df_phi, df_g = self.split_b0_chronological(df_b0)
        mean_candidates = get_mandatory_mean_candidates(self.stat)

        recipes_results = []
        fitted_models: Dict[str, Any] = {}
        fitted_phis: Dict[str, float] = {}
        fitted_calibrators: Dict[str, Optional[PiecewiseLinearCDFCalibrator]] = {}

        for mc in mean_candidates:
            t0 = time.time()
            cid = mc.candidate_id
            logger.info(f"Training mean candidate: {cid} ({mc.family}, {mc.objective})...")

            # 1. Fit on D_warm -> predict on D_phi to get OOF predictions for phi
            if mc.family == "weighted_avg":
                k_val = mc.params.get("k", 5)
                base = WeightedAverageBaseline(stat=self.stat, k=k_val)
                pred_phi = base.predict(df_phi)
                pred_g = base.predict(df_g)
                pred_b1 = base.predict(df_b1)
                full_model = base

            elif mc.family == "minutes_rate":
                base = MinutesRateBaseline(stat=self.stat)
                pred_phi = base.predict(df_phi)
                pred_g = base.predict(df_g)
                pred_b1 = base.predict(df_b1)
                full_model = base

            elif mc.family == "lgbm":
                n_est = 50 if fast_mode else mc.params.get("n_estimators", 250)
                obj = "poisson" if mc.objective == "poisson" else "regression"
                leaves = mc.params.get("num_leaves", 31)

                # Train on D_warm
                m_warm = lgb.LGBMRegressor(
                    objective=obj,
                    num_leaves=leaves,
                    learning_rate=0.05,
                    n_estimators=n_est,
                    random_state=20261110,
                    verbosity=-1,
                )
                m_warm.fit(df_warm[features].fillna(0.0), df_warm[target_col])
                pred_phi = np.maximum(m_warm.predict(df_phi[features].fillna(0.0)), 1e-4)

                # Train on D_warm + D_phi
                df_warm_phi = pd.concat([df_warm, df_phi], ignore_index=True)
                m_warm_phi = lgb.LGBMRegressor(
                    objective=obj,
                    num_leaves=leaves,
                    learning_rate=0.05,
                    n_estimators=n_est,
                    random_state=20261110,
                    verbosity=-1,
                )
                m_warm_phi.fit(df_warm_phi[features].fillna(0.0), df_warm_phi[target_col])
                pred_g = np.maximum(m_warm_phi.predict(df_g[features].fillna(0.0)), 1e-4)

                # Full fit on all B0
                full_model = lgb.LGBMRegressor(
                    objective=obj,
                    num_leaves=leaves,
                    learning_rate=0.05,
                    n_estimators=n_est,
                    random_state=20261110,
                    verbosity=-1,
                )
                full_model.fit(df_b0[features].fillna(0.0), df_b0[target_col])
                pred_b1 = np.maximum(full_model.predict(df_b1[features].fillna(0.0)), 1e-4)

            elif mc.family == "catboost":
                from catboost import CatBoostRegressor
                iters = 50 if fast_mode else mc.params.get("iterations", 250)
                loss_fn = "Poisson" if mc.objective == "poisson" else "RMSE"
                depth = mc.params.get("depth", 6)

                m_warm = CatBoostRegressor(
                    loss_function=loss_fn,
                    depth=depth,
                    learning_rate=0.05,
                    iterations=iters,
                    random_seed=20261110,
                    verbose=0,
                )
                m_warm.fit(df_warm[features].fillna(0.0), df_warm[target_col])
                pred_phi = np.maximum(m_warm.predict(df_phi[features].fillna(0.0)), 1e-4)

                df_warm_phi = pd.concat([df_warm, df_phi], ignore_index=True)
                m_warm_phi = CatBoostRegressor(
                    loss_function=loss_fn,
                    depth=depth,
                    learning_rate=0.05,
                    iterations=iters,
                    random_seed=20261110,
                    verbose=0,
                )
                m_warm_phi.fit(df_warm_phi[features].fillna(0.0), df_warm_phi[target_col])
                pred_g = np.maximum(m_warm_phi.predict(df_g[features].fillna(0.0)), 1e-4)

                full_model = CatBoostRegressor(
                    loss_function=loss_fn,
                    depth=depth,
                    learning_rate=0.05,
                    iterations=iters,
                    random_seed=20261110,
                    verbose=0,
                )
                full_model.fit(df_b0[features].fillna(0.0), df_b0[target_col])
                pred_b1 = np.maximum(full_model.predict(df_b1[features].fillna(0.0)), 1e-4)

            elapsed_latency = time.time() - t0
            fitted_models[cid] = full_model

            # 2. Fit scalar phi on D_phi
            phi_fitted = fit_dispersion_phi(df_phi[target_col].to_numpy(), pred_phi)
            fitted_phis[cid] = phi_fitted

            # 3. Fit proxy G on D_G using OOF predictions with phi_fitted
            K_grid = 50
            from scipy import stats
            if phi_fitted > 1e-5:
                r_val = 1.0 / phi_fitted
                p_arr = r_val / (r_val + pred_g)
                k_mat = np.arange(K_grid + 1)
                raw_cdfs_g = stats.nbinom.cdf(k_mat[None, :], r_val, p_arr[:, None])
            else:
                k_mat = np.arange(K_grid + 1)
                raw_cdfs_g = stats.poisson.cdf(k_mat[None, :], pred_g[:, None])

            y_g = df_g[target_col].to_numpy()
            calibrator_proxy = PiecewiseLinearCDFCalibrator(eps_mix=0.001, lambda_reg=1e-4)
            # Fit on a deterministic, representative sample across the full
            # chronological calibration block. Passing only its first 300
            # rows made calibration depend on the early part of that block.
            calibrator_proxy.fit(raw_cdfs_g, y_g, max_samples=1000, random_state=20261119)
            fitted_calibrators[cid] = calibrator_proxy

            # 4. Evaluate the 4 composite recipes for this candidate on B1
            for raw in ["poisson", "nb2"]:
                phi_eval = 0.0 if raw == "poisson" else phi_fitted
                for cal in ["identity", "piecewise_linear"]:
                    cal_obj = None if cal == "identity" else calibrator_proxy
                    recipe_id = f"{cid}__{raw}__{cal}"

                    scores = self.evaluate_recipe_on_b1(
                        mu_b1=pred_b1,
                        y_b1=y_b1,
                        raw_family=raw,
                        phi=phi_eval,
                        calibrator_obj=cal_obj,
                    )

                    dev = calculate_poisson_deviance(y_b1, pred_b1)
                    rmse = float(np.sqrt(np.mean((y_b1 - pred_b1) ** 2)))

                    recipe_summary = {
                        "recipe_id": recipe_id,
                        "candidate_id": cid,
                        "mean_family": mc.family,
                        "mean_family_rank": mc.family_rank,
                        "objective": mc.objective,
                        "raw_family": raw,
                        "raw_family_rank": 0 if raw == "poisson" else 1,
                        "calibrator_type": cal,
                        "calibrator_rank": 0 if cal == "identity" else 1,
                        "size_rank": mc.size_rank,
                        "fitted_phi": phi_eval,
                        "latency": elapsed_latency,
                        "poisson_deviance": round(dev, 4),
                        "rmse": round(rmse, 4),
                        "mean_full_rps": scores["mean_full_rps"],
                        "mean_neg_log_score": scores["mean_neg_log_score"],
                        "coverage_90": scores["coverage_90"],
                    }
                    recipes_results.append(recipe_summary)

        # 5. Apply Section 7.2 selection protocol
        ref_id = f"MinutesRate_{self.stat}__poisson__identity"
        selection_meta = self.select_best_recipe(recipes_results, ref_recipe_id=ref_id)
        winner = selection_meta["selected_winner"]

        # 6. Save winning model artifact and atomic ModelBundle (§11)
        bundle_id = f"bundle_{self.stat}_{winner['recipe_id']}"
        bundle_dir = self.models_dir / f"bundle_{self.stat}"
        bundle_dir.mkdir(parents=True, exist_ok=True)

        # Save model file if LightGBM or CatBoost
        win_cid = winner["candidate_id"]
        win_model = fitted_models[win_cid]
        model_filename = None

        if winner["mean_family"] == "lgbm":
            model_filename = f"lgbm_{self.stat}.txt"
            win_model.booster_.save_model(str(bundle_dir / model_filename))
        elif winner["mean_family"] == "catboost":
            model_filename = f"catboost_{self.stat}.cbm"
            win_model.save_model(str(bundle_dir / model_filename))

        win_knots = None
        if winner["calibrator_type"] == "piecewise_linear":
            win_knots = [float(k) for k in fitted_calibrators[win_cid].c_knots]

        # Preserve candidate parameters (e.g. k for WeightedAverage) in mean_config
        cand_map = {mc.candidate_id: mc for mc in mean_candidates}
        win_mc = cand_map.get(win_cid)
        mean_cfg = {"objective": winner["objective"], "candidate_id": win_cid}
        if win_mc and win_mc.params:
            mean_cfg.update(win_mc.params)
        if winner["mean_family"] == "weighted_avg":
            mean_cfg["k"] = getattr(win_model, "k", mean_cfg.get("k", 5))

        bundle = ModelBundle(
            bundle_id=bundle_id,
            stat=self.stat.upper(),
            mean_family=winner["mean_family"],
            mean_config=mean_cfg,
            feature_schema=features,
            numerical_projection_policy="max(1e-6, raw_pred)",
            raw_distribution_family=winner["raw_family"],
            fitted_phi=winner["fitted_phi"],
            calibrator_type=winner["calibrator_type"],
            calibrator_knots=win_knots,
            mean_model_path=model_filename,
            metadata={
                "train_samples": len(df_b0),
                "val_samples": len(df_b1),
                "fast_mode": fast_mode,
            },
            selection_report=selection_meta,
        )
        bundle.save(bundle_dir)

        # 7. Write full benchmark ledger to reports
        ledger_path = self.reports_dir / f"model_selection_ledger_{self.stat}.json"
        with open(ledger_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "stat": self.stat.upper(),
                    "total_recipes_evaluated": len(recipes_results),
                    "selection_summary": selection_meta,
                    "recipes": recipes_results,
                },
                f,
                indent=2,
            )
        logger.info(f"Model Selection Ledger for {self.stat.upper()} saved to {ledger_path}")

        return {
            "stat": self.stat.upper(),
            "selection_summary": selection_meta,
            "bundle_dir": str(bundle_dir),
            "total_recipes": len(recipes_results),
        }
