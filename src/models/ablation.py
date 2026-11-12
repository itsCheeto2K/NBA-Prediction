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

logger = logging.getLogger(__name__)

A0_BASE_COLS = [
    "pts_roll_mean_5", "pts_roll_std_5", "pts_roll_mean_10", "pts_roll_mean_20", "pts_trend_5_20", "pts_decay_mean",
    "reb_roll_mean_5", "reb_roll_std_5", "reb_roll_mean_10", "reb_roll_mean_20", "reb_decay_mean",
    "ast_roll_mean_5", "ast_roll_std_5", "ast_roll_mean_10", "ast_roll_mean_20", "ast_decay_mean",
    "min_roll_mean_5", "min_roll_std_5", "min_roll_mean_10", "min_roll_mean_20",
    "fga_roll_mean_5", "fga_roll_mean_10", "fta_roll_mean_5", "fg3a_roll_mean_5",
    "pts_rate_shrinkage", "pts_n_eff", "pts_exposure",
    "reb_rate_shrinkage", "reb_n_eff", "reb_exposure",
    "ast_rate_shrinkage", "ast_n_eff", "ast_exposure",
    "is_home", "n_games_history",
]

OPPONENT_P0_COLS = [
    "opp_pace_prev10",
    "opp_def_rating_prev10",
    "opp_ast_allowed_per100_prev10",
    "opp_dreb_share_prev10",
    "opp_fg3a_share_prev10",
    "opp_pts_allowed_roll",
]

SCHEDULE_P0_COLS = [
    "team_b2b",
    "opp_b2b",
    "team_rest_days",
    "opp_rest_days",
    "rest_advantage_days",
    "team_3in4",
    "team_4in6",
    "opp_3in4",
    "opp_4in6",
    "player_played_previous_team_game",
    "team_b2b_but_player_rested",
    "player_minutes_last7days",
    "is_b2b",
    "rest_days",
]

ABLATION_CONFIGS = {
    "A0": {"desc": "Player form, minutes, role, and home/away baseline", "cols": A0_BASE_COLS},
    "A1": {"desc": "A0 + Opponent context (pace, def rating, allowed ast, dreb share)", "cols": A0_BASE_COLS + OPPONENT_P0_COLS},
    "A2": {"desc": "A0 + Rest, workload, and congestion context (B2B, 3in4, rest advantage)", "cols": A0_BASE_COLS + SCHEDULE_P0_COLS},
    "A3": {"desc": "A0 + Both Opponent context and Rest/Schedule congestion context", "cols": A0_BASE_COLS + OPPONENT_P0_COLS + SCHEDULE_P0_COLS},
}


class AblationStudy:
    """
    Executes empirical ablation study A0-A3 as defined in
    NBA_OPPONENT_SCHEDULE_SUPPLEMENT_PLAN.md §11.
    """

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or settings.REPORTS_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def load_datasets(self) -> Tuple[pd.DataFrame, pd.DataFrame]:
        b0_path = settings.PARQUET_DIR / "features_2023-24.parquet"
        b1_path = settings.PARQUET_DIR / "features_2024-25.parquet"

        if not b0_path.exists() or not b1_path.exists():
            raise FileNotFoundError("Missing features parquet files. Please run build_features.py first.")

        df_b0 = pd.read_parquet(b0_path)
        df_b1_full = pd.read_parquet(b1_path)

        # Filter active minutes > 0
        df_b0 = df_b0[df_b0["target_min"] > 0].copy()
        df_b1_full = df_b1_full[df_b1_full["target_min"] > 0].copy()

        # Split B1 into the first 1/3 of unique game dates
        df_b1_full["game_date_dt"] = pd.to_datetime(df_b1_full["game_date"])
        unique_dates = sorted(df_b1_full["game_date_dt"].unique())
        cutoff_date = unique_dates[len(unique_dates) // 3]

        df_b1 = df_b1_full[df_b1_full["game_date_dt"] <= cutoff_date].copy().reset_index(drop=True)
        return df_b0, df_b1

    def run_ablation(self, stats_to_evaluate: List[str] = None) -> Dict[str, Any]:
        if stats_to_evaluate is None:
            stats_to_evaluate = ["pts", "reb", "ast"]

        df_train, df_val = self.load_datasets()
        logger.info(f"Loaded Train B0: {len(df_train)} rows | Val B1: {len(df_val)} rows")

        report: Dict[str, Any] = {
            "title": "Ablation Study A0-A3 Development Report",
            "protocol": "B0 (2023-24) Train, B1 (2024-25 early 1/3) Validation",
            "train_samples": len(df_train),
            "val_samples": len(df_val),
            "stats": {},
            "conclusion": {},
        }

        for stat in stats_to_evaluate:
            stat_upper = stat.upper()
            target_col = f"target_{stat}"
            logger.info(f"Running Ablation A0-A3 for target {stat_upper}...")

            stat_results: Dict[str, Any] = {
                "configs": {},
                "paired_comparison_vs_A0": {},
                "cohort_analysis": {},
            }

            predictions: Dict[str, np.ndarray] = {}
            y_val = df_val[target_col].to_numpy()
            y_train = df_train[target_col].to_numpy()

            for cfg_name, cfg_info in ABLATION_CONFIGS.items():
                cols = [c for c in cfg_info["cols"] if c in df_train.columns and c in df_val.columns]
                X_train = df_train[cols].fillna(0.0)
                X_val = df_val[cols].fillna(0.0)

                model = lgb.LGBMRegressor(
                    objective="poisson",
                    n_estimators=300,
                    learning_rate=0.03,
                    num_leaves=31,
                    random_state=20261109,
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

            # Paired comparison vs A0
            preds_a0 = predictions["A0"]
            point_deviance_a0 = 2.0 * (
                np.where(y_val > 0, y_val * np.log(np.maximum(y_val, 1e-9) / preds_a0), 0.0)
                - (y_val - preds_a0)
            )

            for cfg_name in ["A1", "A2", "A3"]:
                preds_ak = predictions[cfg_name]
                point_deviance_ak = 2.0 * (
                    np.where(y_val > 0, y_val * np.log(np.maximum(y_val, 1e-9) / preds_ak), 0.0)
                    - (y_val - preds_ak)
                )
                diff = point_deviance_ak - point_deviance_a0
                mean_diff = float(np.mean(diff))
                t_stat, p_val = stats.ttest_rel(point_deviance_ak, point_deviance_a0)

                stat_results["paired_comparison_vs_A0"][cfg_name] = {
                    "mean_deviance_diff": round(mean_diff, 5),
                    "improvement_percent": round((1.0 - np.mean(point_deviance_ak) / np.mean(point_deviance_a0)) * 100, 3),
                    "paired_t_stat": round(float(t_stat), 4),
                    "p_value": round(float(p_val), 6),
                    "is_statistically_significant": bool(p_val < 0.05 and mean_diff < 0),
                }

            # Cohort breakdowns comparing A0 vs A3
            cohorts = {
                "team_b2b": df_val["team_b2b"] == 1,
                "opp_b2b": df_val["opp_b2b"] == 1,
                "team_b2b_but_player_rested": df_val.get("team_b2b_but_player_rested", 0) == 1,
                "away_game": df_val["is_home"] == 0,
                "congestion_3in4": df_val.get("team_3in4", 0) == 1,
                "rest_advantage_positive": df_val.get("rest_advantage_days", 0) > 0,
                "rest_advantage_negative": df_val.get("rest_advantage_days", 0) < 0,
            }

            for cohort_name, mask in cohorts.items():
                n_cohort = int(mask.sum())
                if n_cohort >= 10:
                    y_sub = y_val[mask]
                    dev_a0 = float(calculate_poisson_deviance(y_sub, predictions["A0"][mask]))
                    dev_a3 = float(calculate_poisson_deviance(y_sub, predictions["A3"][mask]))
                    diff_pct = round((1.0 - dev_a3 / dev_a0) * 100, 2) if dev_a0 > 0 else 0.0

                    stat_results["cohort_analysis"][cohort_name] = {
                        "count": n_cohort,
                        "poisson_deviance_A0": round(dev_a0, 4),
                        "poisson_deviance_A3": round(dev_a3, 4),
                        "improvement_percent": diff_pct,
                    }

            report["stats"][stat_upper] = stat_results

        # Determine winner
        best_cfg_votes = []
        for s in stats_to_evaluate:
            stat_u = s.upper()
            best_c = min(
                report["stats"][stat_u]["configs"].items(),
                key=lambda x: x[1]["poisson_deviance"]
            )[0]
            best_cfg_votes.append(best_c)

        winning_config = max(set(best_cfg_votes), key=best_cfg_votes.count)
        report["conclusion"] = {
            "winning_config": winning_config,
            "decision": "KEEP" if winning_config in ["A1", "A2", "A3"] else "INCONCLUSIVE",
            "summary": f"Config {winning_config} selected based on lowest Poisson deviance across evaluated props.",
        }

        # Save to reports directory
        report_path = self.output_dir / "ablation_A0_A3_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        logger.info(f"Ablation report saved to {report_path}")
        return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    ablation = AblationStudy()
    res = ablation.run_ablation()
    print("Ablation Study Summary:")
    print(json.dumps(res["conclusion"], indent=2))
