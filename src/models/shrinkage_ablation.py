"""
Ablation Study F0-F3 for NBA Feature & Shrinkage Specification (§15)
Compares:
- F0: Baseline legacy constants / game-decay (alpha/beta constants, 10-game halflife)
- F1: League empirical prior + calendar day-decay (20 calendar days, beta_rate=200, no role split)
- F2: F1 + Position & Rotation Hierarchy pooling (tau=2000m, leaf/position/league priors) + exposure/quality features
- F3: F2 + Shooting Accuracy & Shot-Mix (2PT, 3PT, FT accuracy, 3PA share) + role-shift / transfer features
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
from sklearn.metrics import mean_squared_error, mean_absolute_error
import lightgbm as lgb
from scipy import stats

from src.config import settings
from src.models.baseline import calculate_poisson_deviance
from src.features.shrinkage import (
    ShrinkageConfig,
    PriorSnapshot,
    fit_prior_snapshot,
    compute_count_features,
    compute_shooting_features,
)

logger = logging.getLogger(__name__)

# Base context features common to all models
COMMON_CONTEXT_COLS = [
    "min_roll_mean_5", "min_roll_std_5", "min_roll_mean_10", "min_roll_mean_20",
    "is_home", "is_b2b", "rest_days", "n_games_history",
    "opp_pace_prev10", "opp_def_rating_prev10", "opp_ast_allowed_per100_prev10",
    "opp_dreb_share_prev10", "opp_fg3a_share_prev10",
    "team_b2b", "opp_b2b", "team_rest_days", "opp_rest_days", "rest_advantage_days",
    "team_3in4", "team_4in6", "player_played_previous_team_game", "player_minutes_last7days",
]

class ShrinkageAblationStudy:
    """Runs rigorous empirical ablation study F0-F3 as specified in §15."""

    def __init__(self, reports_dir: Optional[Path] = None):
        self.reports_dir = reports_dir or settings.REPORTS_DIR
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def load_data(self) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Loads B0 (2023-24) and B1 (2024-25 early 1/3)."""
        b0_path = settings.PARQUET_DIR / "features_2023-24.parquet"
        b1_path = settings.PARQUET_DIR / "features_2024-25.parquet"

        if not b0_path.exists() or not b1_path.exists():
            raise FileNotFoundError(f"Missing parquet feature files: {b0_path} or {b1_path}")

        df_b0 = pd.read_parquet(b0_path)
        df_b1_full = pd.read_parquet(b1_path)

        df_b0 = df_b0[df_b0["target_min"] > 0].copy()
        df_b1_full = df_b1_full[df_b1_full["target_min"] > 0].copy()

        df_b1_full["game_date_dt"] = pd.to_datetime(df_b1_full["game_date"])
        unique_dates = sorted(df_b1_full["game_date_dt"].unique())
        cutoff_date = unique_dates[len(unique_dates) // 3]
        df_b1 = df_b1_full[df_b1_full["game_date_dt"] <= cutoff_date].copy()

        logger.info(f"Loaded Train (B0 2023-24): {len(df_b0)} rows")
        logger.info(f"Loaded Validation (B1 early 2024-25): {len(df_b1)} rows (up to {cutoff_date.strftime('%Y-%m-%d')})")
        return df_b0, df_b1

    def enrich_features(self, df_b0: pd.DataFrame, df_b1: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Computes F1, F2, F3 shrinkage and shooting features on B0 and B1.
        Strictly fits prior snapshot on B0 before evaluating B1.
        """
        logger.info("Fitting empirical prior snapshot on B0...")
        cfg = ShrinkageConfig()
        origin_val = pd.to_datetime(df_b1["game_date"]).min()
        prior_snapshot = fit_prior_snapshot(df_b0, origin_utc=origin_val, config=cfg)

        logger.info("Computing count rate shrinkage & form features on B0...")
        counts_b0 = compute_count_features(df_b0, df_b0, prior_snapshot, cfg)
        shoot_b0 = compute_shooting_features(df_b0, df_b0, prior_snapshot, cfg)

        logger.info("Computing count rate shrinkage & form features on B1...")
        counts_b1 = compute_count_features(df_b0, df_b1, prior_snapshot, cfg)
        shoot_b1 = compute_shooting_features(df_b0, df_b1, prior_snapshot, cfg)

        # Merge new features
        drop_cols_counts = ["row_id", "player_id", "prediction_cutoff_utc"]
        drop_cols_shoot = ["row_id", "player_id"]

        b0_merged = pd.merge(df_b0.reset_index(drop=True), counts_b0.drop(columns=drop_cols_counts, errors="ignore"), left_index=True, right_index=True)
        b0_merged = pd.merge(b0_merged, shoot_b0.drop(columns=drop_cols_shoot, errors="ignore"), left_index=True, right_index=True)

        b1_merged = pd.merge(df_b1.reset_index(drop=True), counts_b1.drop(columns=drop_cols_counts, errors="ignore"), left_index=True, right_index=True)
        b1_merged = pd.merge(b1_merged, shoot_b1.drop(columns=drop_cols_shoot, errors="ignore"), left_index=True, right_index=True)

        return b0_merged, b1_merged

    def run_ablation(self, stats_to_evaluate: Optional[List[str]] = None) -> Dict[str, Any]:
        """Executes ablation protocol F0-F3 across PTS, REB, AST."""
        if stats_to_evaluate is None:
            stats_to_evaluate = ["pts", "reb", "ast"]

        df_train_raw, df_val_raw = self.load_data()
        df_train, df_val = self.enrich_features(df_train_raw, df_val_raw)

        report: Dict[str, Any] = {
            "title": "NBA Feature & Shrinkage Specification (§15) Ablation Study F0-F3",
            "protocol": "B0 (2023-24) Train, B1 (2024-25 early 1/3) Validation, Poisson Objective",
            "train_samples": len(df_train),
            "val_samples": len(df_val),
            "stats": {},
            "conclusion": {},
        }

        for stat in stats_to_evaluate:
            stat_upper = stat.upper()
            target_col = f"target_{stat}"
            logger.info(f"Running Shrinkage Ablation F0-F3 for target {stat_upper}...")

            # Define feature sets for this stat
            f0_cols = COMMON_CONTEXT_COLS + [
                f"{stat}_roll_mean_5", f"{stat}_roll_std_5", f"{stat}_roll_mean_10", f"{stat}_roll_mean_20",
                f"{stat}_rate_shrinkage", f"{stat}_n_eff", f"{stat}_exposure",
            ]
            f1_cols = COMMON_CONTEXT_COLS + [
                f"{stat}_roll_mean_5", f"{stat}_roll_std_5", f"{stat}_roll_mean_10", f"{stat}_roll_mean_20",
                f"{stat}_rate_shrunk", f"{stat}_n_eff_games", f"{stat}_exposure_minutes", f"{stat}_prior_weight",
            ]
            f2_cols = f1_cols + [
                f"{stat}_prior_mean", f"{stat}_history_games", f"{stat}_history_minutes",
                "days_since_last_appearance", "long_absence_flag",
            ]
            f3_cols = f2_cols + [
                "2pt_accuracy_shrunk", "3pt_accuracy_shrunk", "ft_accuracy_shrunk",
                "three_pa_share_shrunk", "minutes_trend_5v20", "role_shift_candidate",
                "transfer_flag", "start_share_prev10_current_team",
            ]

            configs = {
                "F0": {"desc": "Baseline legacy constants / game-decay (alpha/beta constants, 10-game decay)", "cols": f0_cols},
                "F1": {"desc": "F0 + League empirical prior + calendar day-decay (20-day half-life, beta=200)", "cols": f1_cols},
                "F2": {"desc": "F1 + Position/Rotation hierarchical pooling (tau=2000m) + exposure/quality features", "cols": f2_cols},
                "F3": {"desc": "F2 + Shooting accuracy (2PT/3PT/FT) + 3PA share + role-shift / transfer features", "cols": f3_cols},
            }

            predictions: Dict[str, np.ndarray] = {}
            y_val = df_val[target_col].to_numpy()
            y_train = df_train[target_col].to_numpy()

            stat_results: Dict[str, Any] = {
                "configs": {},
                "paired_comparison_vs_F0": {},
            }

            for cfg_name, cfg_info in configs.items():
                cols = [c for c in cfg_info["cols"] if c in df_train.columns and c in df_val.columns]
                X_train = df_train[cols].astype(float).fillna(0.0)
                X_val = df_val[cols].astype(float).fillna(0.0)

                model = lgb.LGBMRegressor(
                    objective="poisson",
                    n_estimators=300,
                    learning_rate=0.03,
                    num_leaves=31,
                    random_state=20261110,
                    verbosity=-1,
                )
                model.fit(X_train, y_train)
                preds = np.maximum(model.predict(X_val), 0.1)
                predictions[cfg_name] = preds

                rmse = float(np.sqrt(mean_squared_error(y_val, preds)))
                mae = float(mean_absolute_error(y_val, preds))
                dev = float(calculate_poisson_deviance(y_val, preds))

                stat_results["configs"][cfg_name] = {
                    "description": cfg_info["desc"],
                    "n_features": len(cols),
                    "rmse": round(rmse, 4),
                    "mae": round(mae, 4),
                    "poisson_deviance": round(dev, 4),
                }

            # Paired comparison vs F0
            preds_f0 = predictions["F0"]
            point_deviance_f0 = 2.0 * (
                np.where(y_val > 0, y_val * np.log(np.maximum(y_val, 1e-9) / preds_f0), 0.0)
                - (y_val - preds_f0)
            )

            for cfg_name in ["F1", "F2", "F3"]:
                preds_fk = predictions[cfg_name]
                point_deviance_fk = 2.0 * (
                    np.where(y_val > 0, y_val * np.log(np.maximum(y_val, 1e-9) / preds_fk), 0.0)
                    - (y_val - preds_fk)
                )
                diff = point_deviance_fk - point_deviance_f0
                mean_diff = float(np.mean(diff))
                t_stat, p_val = stats.ttest_rel(point_deviance_fk, point_deviance_f0)

                stat_results["paired_comparison_vs_F0"][cfg_name] = {
                    "mean_deviance_diff": round(mean_diff, 5),
                    "improvement_percent": round((1.0 - np.mean(point_deviance_fk) / np.mean(point_deviance_f0)) * 100, 3),
                    "paired_t_stat": round(float(t_stat), 4),
                    "p_value": round(float(p_val), 6),
                    "is_statistically_significant": bool(p_val < 0.05 and mean_diff < 0),
                }

            report["stats"][stat] = stat_results

        # Summary conclusion
        pts_f0 = report["stats"]["pts"]["configs"]["F0"]["poisson_deviance"]
        pts_f3 = report["stats"]["pts"]["configs"]["F3"]["poisson_deviance"]
        pts_diff = pts_f3 - pts_f0
        pts_pct = round((1.0 - pts_f3 / pts_f0) * 100, 3)

        report["conclusion"] = {
            "decision": "ADOPT" if pts_diff < 0 else "KEEP_BASELINE",
            "winning_config": "F3",
            "pts_poisson_deviance_F0": pts_f0,
            "pts_poisson_deviance_F3": pts_f3,
            "pts_improvement_percent": pts_pct,
            "paired_t_stat": report["stats"]["pts"]["paired_comparison_vs_F0"]["F3"]["paired_t_stat"],
            "p_value": report["stats"]["pts"]["paired_comparison_vs_F0"]["F3"]["p_value"],
        }

        report_path = self.reports_dir / "ablation_F0_F3_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        logger.info(f"Ablation F0-F3 report saved to {report_path}")
        return report

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    study = ShrinkageAblationStudy()
    res = study.run_ablation()
    print("Ablation Results:")
    print(json.dumps(res, indent=2))
