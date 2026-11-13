"""Ablation study OPPR_R0 to OPPR_R3 as specified in NBA_OPPONENT_RANK_FEATURE_INTERACTIONS_SPEC.md §16."""
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple
import numpy as np
import pandas as pd
from sklearn.metrics import mean_squared_error, mean_absolute_error
import lightgbm as lgb
from scipy import stats

from src.config import settings
from src.models.baseline import calculate_poisson_deviance
from src.models.trainer import FEATURE_COLS

logger = logging.getLogger("ablation_opp_rank")

# 1. R0 Base Columns (Current Production Features)
R0_BASE_COLS = [c for c in FEATURE_COLS if not c.startswith("opp_") and not c.startswith("interact_")] + [
    "opp_pace_prev10",
    "opp_def_rating_prev10",
    "opp_ast_allowed_per100_prev10",
    "opp_dreb_share_prev10",
    "opp_fg3a_share_prev10",
    "opp_pts_allowed_roll",
]

# 2. R1 Granular Shrunk Values & Log-Relatives
R1_SHRUNK_COLS = [
    "opp_pts_allowed_per100_shrunk_prev10",
    "opp_pts_allowed_log_relative_prev10",
    "opp_ast_allowed_per100_shrunk_prev10",
    "opp_ast_allowed_log_relative_prev10",
    "opp_reb_allowed_per100_shrunk_prev10",
    "opp_reb_allowed_log_relative_prev10",
    "opp_fg3m_allowed_per100_shrunk_prev10",
    "opp_fg3m_allowed_log_relative_prev10",
    "opp_fg3a_allowed_per100_shrunk_prev10",
    "opp_fg3a_allowed_log_relative_prev10",
    "opp_fta_allowed_per100_shrunk_prev10",
    "opp_fta_allowed_log_relative_prev10",
    "opp_blocks_made_per100_shrunk_prev10",
    "opp_blocks_made_log_relative_prev10",
    "opp_missed_fga_per100_shrunk_prev10",
    "opp_missed_fga_log_relative_prev10",
]

# 3. R2 Ascending Percentile Ranks
R2_RANK_COLS = [
    "opp_pts_allowed_pct_asc_prev10",
    "opp_ast_allowed_pct_asc_prev10",
    "opp_reb_allowed_pct_asc_prev10",
    "opp_fg3m_allowed_pct_asc_prev10",
    "opp_fg3a_allowed_pct_asc_prev10",
    "opp_fta_allowed_pct_asc_prev10",
    "opp_blocks_made_pct_asc_prev10",
    "opp_missed_fga_pct_asc_prev10",
]

# 4. R3 Explicit Cross-Interactions
R3_INTERACTION_COLS = [
    "interact_pts_3pa_x_opp_3pm_allowed",
    "interact_pts_fta_x_opp_fta_allowed",
    "interact_pts_2pt_x_opp_blocks_made",
    "interact_ast_rate_x_opp_ast_allowed",
    "interact_reb_dreb_x_opp_missed_fga",
]

OPPR_CONFIGS = {
    "OPPR_R0": {"desc": "Baseline features (current valid pipeline)", "cols": R0_BASE_COLS},
    "OPPR_R1": {"desc": "R0 + Granular per-100 shrunk rates and log-relative context", "cols": R0_BASE_COLS + R1_SHRUNK_COLS},
    "OPPR_R2": {"desc": "R1 + Ascending percentile ranks across 30 teams", "cols": R0_BASE_COLS + R1_SHRUNK_COLS + R2_RANK_COLS},
    "OPPR_R3": {"desc": "R2 + Top cross-feature interactions per stat", "cols": R0_BASE_COLS + R1_SHRUNK_COLS + R2_RANK_COLS + R3_INTERACTION_COLS},
}


def calculate_pointwise_poisson_deviance(y_true: np.ndarray, y_pred: np.ndarray) -> np.ndarray:
    y = np.maximum(np.asarray(y_true, dtype=np.float64), 0.0)
    mu = np.maximum(np.asarray(y_pred, dtype=np.float64), 1e-6)
    pos_mask = y > 0
    dev = np.zeros_like(y, dtype=np.float64)
    dev[pos_mask] = 2.0 * (y[pos_mask] * np.log(y[pos_mask] / mu[pos_mask]) - (y[pos_mask] - mu[pos_mask]))
    dev[~pos_mask] = 2.0 * mu[~pos_mask]
    return dev


class OpponentRankAblationStudy:
    """Executes empirical ablation study OPPR_R0 to OPPR_R3."""

    def __init__(self, output_dir: Path = None):
        self.output_dir = output_dir or settings.REPORTS_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run_ablation(
        self, 
        df_train: pd.DataFrame, 
        df_val: pd.DataFrame, 
        stats_to_eval: List[str] = None
    ) -> Dict[str, Any]:
        if stats_to_eval is None:
            stats_to_eval = ["pts", "reb", "ast"]

        report = {
            "title": "Ablation Study OPPR_R0 to OPPR_R3 Report",
            "protocol": "B0 (2023-24) Train, B1 (2024-25 early 1/3) Validation",
            "train_samples": len(df_train),
            "val_samples": len(df_val),
            "stats": {}
        }

        for stat in stats_to_eval:
            stat_upper = stat.upper()
            target_col = f"target_{stat}"
            logger.info(f"--- Running Opponent Rank Ablation for {stat_upper} ---")

            stat_results = {"configs": {}, "paired_comparison_vs_R0": {}}
            r0_deviances = None

            for cfg_name, cfg in OPPR_CONFIGS.items():
                cols = [c for c in cfg["cols"] if c in df_train.columns and c in df_val.columns]

                X_train = df_train[cols].copy().fillna(0)
                y_train = df_train[target_col].to_numpy()
                X_val = df_val[cols].copy().fillna(0)
                y_val = df_val[target_col].to_numpy()

                # Train LightGBM model
                train_data = lgb.Dataset(X_train, label=y_train)
                params = {
                    "objective": "poisson",
                    "metric": "poisson",
                    "learning_rate": 0.05,
                    "num_leaves": 31,
                    "min_child_samples": 20,
                    "verbose": -1,
                    "seed": 42,
                }
                model = lgb.train(params, train_data, num_boost_round=120)

                preds = model.predict(X_val)
                rmse = float(np.sqrt(mean_squared_error(y_val, preds)))
                mae = float(mean_absolute_error(y_val, preds))
                dev_array = calculate_pointwise_poisson_deviance(y_val, preds)
                mean_dev = float(np.mean(dev_array))

                stat_results["configs"][cfg_name] = {
                    "description": cfg["desc"],
                    "n_features": len(cols),
                    "rmse": round(rmse, 4),
                    "mae": round(mae, 4),
                    "poisson_deviance": round(mean_dev, 4),
                }

                if cfg_name == "OPPR_R0":
                    r0_deviances = dev_array
                else:
                    diff = dev_array - r0_deviances
                    t_stat, p_val = stats.ttest_rel(dev_array, r0_deviances)
                    impr_pct = (stat_results["configs"]["OPPR_R0"]["poisson_deviance"] - mean_dev) / stat_results["configs"]["OPPR_R0"]["poisson_deviance"] * 100.0

                    stat_results["paired_comparison_vs_R0"][cfg_name] = {
                        "mean_deviance_diff": round(float(np.mean(diff)), 5),
                        "improvement_percent": round(float(impr_pct), 3),
                        "paired_t_stat": round(float(t_stat), 4),
                        "p_value": round(float(p_val), 6),
                        "is_statistically_significant": bool(p_val < 0.05 and impr_pct > 0),
                    }

            report["stats"][stat_upper] = stat_results

        # Save to reports directory
        out_path = self.output_dir / "ablation_opp_rank_report.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        logger.info(f"Saved Opponent Rank Ablation report to {out_path}")
        return report
