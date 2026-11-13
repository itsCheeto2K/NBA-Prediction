import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
from sklearn.metrics import mean_squared_error, mean_absolute_error
import lightgbm as lgb
from catboost import CatBoostRegressor

from src.config import settings
from src.models.baseline import (
    WeightedAverageBaseline,
    MinutesRateBaseline,
    calculate_poisson_deviance,
)

logger = logging.getLogger(__name__)

FEATURE_COLS = [
    # PTS features
    "pts_roll_mean_5", "pts_roll_std_5", "pts_roll_mean_10", "pts_roll_mean_20", "pts_trend_5_20", "pts_decay_mean",
    # REB features
    "reb_roll_mean_5", "reb_roll_std_5", "reb_roll_mean_10", "reb_roll_mean_20", "reb_decay_mean",
    # AST features
    "ast_roll_mean_5", "ast_roll_std_5", "ast_roll_mean_10", "ast_roll_mean_20", "ast_decay_mean",
    # Minutes features
    "min_roll_mean_5", "min_roll_std_5", "min_roll_mean_10", "min_roll_mean_20",
    # Shot opportunities
    "fga_roll_mean_5", "fga_roll_mean_10", "fta_roll_mean_5", "fg3a_roll_mean_5",
    # Rate shrinkage & exposures
    "pts_rate_shrinkage", "pts_n_eff", "pts_exposure",
    "reb_rate_shrinkage", "reb_n_eff", "reb_exposure",
    "ast_rate_shrinkage", "ast_n_eff", "ast_exposure",
    # Context & Schedule
    "is_home", "is_b2b", "rest_days", "n_games_history",
    # Opponent defense & pace (P0 context)
    "opp_pts_allowed_roll",
    "opp_pace_prev10",
    "opp_def_rating_prev10",
    "opp_ast_allowed_per100_prev10",
    "opp_dreb_share_prev10",
    "opp_fg3a_share_prev10",
    # Enhanced Opponent Rank & Relative Context (§5, §6, §8)
    "opp_pts_allowed_per100_shrunk_prev10",
    "opp_pts_allowed_log_relative_prev10",
    "opp_pts_allowed_pct_asc_prev10",
    "opp_ast_allowed_per100_shrunk_prev10",
    "opp_ast_allowed_log_relative_prev10",
    "opp_ast_allowed_pct_asc_prev10",
    "opp_reb_allowed_per100_shrunk_prev10",
    "opp_reb_allowed_log_relative_prev10",
    "opp_reb_allowed_pct_asc_prev10",
    "opp_fg3m_allowed_per100_shrunk_prev10",
    "opp_fg3m_allowed_log_relative_prev10",
    "opp_fg3m_allowed_pct_asc_prev10",
    "opp_fg3a_allowed_per100_shrunk_prev10",
    "opp_fg3a_allowed_log_relative_prev10",
    "opp_fg3a_allowed_pct_asc_prev10",
    "opp_fta_allowed_per100_shrunk_prev10",
    "opp_fta_allowed_log_relative_prev10",
    "opp_fta_allowed_pct_asc_prev10",
    "opp_blocks_made_per100_shrunk_prev10",
    "opp_blocks_made_log_relative_prev10",
    "opp_blocks_made_pct_asc_prev10",
    "opp_missed_fga_per100_shrunk_prev10",
    "opp_missed_fga_log_relative_prev10",
    "opp_missed_fga_pct_asc_prev10",
    # Cross-Feature Interactions (§11)
    "interact_pts_3pa_x_opp_3pm_allowed",
    "interact_pts_fta_x_opp_fta_allowed",
    "interact_pts_2pt_x_opp_blocks_made",
    "interact_ast_rate_x_opp_ast_allowed",
    "interact_reb_dreb_x_opp_missed_fga",
    # Rest, Workload & Congestion (P0 context)
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
    # Winning I3 Injury & Missing Role features (§6, §7, §8)
    "days_since_last_appearance",
    "is_long_absence_return",
    "games_since_return",
    "own_status_code",
    "own_is_questionable",
    "pi_participate",
    "teammate_missing_minutes",
    "teammate_missing_fga",
    "teammate_missing_ast",
    "teammate_missing_pts",
    "teammate_top2_lost_minutes",
    "opp_missing_minutes",
    "opp_missing_fga",
    "opp_missing_ast",
    "opp_missing_pts",
    # Defense vs Position (DvP) Context (§11, §14)
    "dvp_pts_volume_per100",
    "dvp_pts_volume_rank_asc",
    "dvp_pts_volume_rel",
    "dvp_pts_minrate",
    "dvp_pts_minrate_rank_asc",
    "dvp_pts_minrate_rel",
    "dvp_reb_volume_per100",
    "dvp_reb_volume_rank_asc",
    "dvp_reb_volume_rel",
    "dvp_reb_minrate",
    "dvp_reb_minrate_rank_asc",
    "dvp_reb_minrate_rel",
    "dvp_ast_volume_per100",
    "dvp_ast_volume_rank_asc",
    "dvp_ast_volume_rel",
    "dvp_ast_minrate",
    "dvp_ast_minrate_rank_asc",
    "dvp_ast_minrate_rel",
    "dvp_supported",
]

class ModelTrainer:
    """Trains and benchmarks Baselines, LightGBM, and CatBoost with Poisson loss."""

    def __init__(self, models_dir: Optional[Path] = None):
        self.models_dir = models_dir or (settings.BASE_DIR / "models")
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.features: List[str] = []

    def prepare_data(self) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Prepare temporal train and validation split following §11.1:
        - Train (B0): 2023-24 Regular Season
        - Validation (B1): 1st 1/3 of 2024-25 Regular Season sorted by date
        """
        b0_path = settings.PARQUET_DIR / "features_2023-24.parquet"
        b1_path = settings.PARQUET_DIR / "features_2024-25.parquet"

        if not b0_path.exists() or not b1_path.exists():
            raise FileNotFoundError(f"Missing parquet feature files: {b0_path} or {b1_path}")

        df_b0 = pd.read_parquet(b0_path)
        df_b1_full = pd.read_parquet(b1_path)

        # Filter active players who participated
        df_b0 = df_b0[df_b0["target_min"] > 0].copy()
        df_b1_full = df_b1_full[df_b1_full["target_min"] > 0].copy()

        # Split B1: first 1/3 of unique game dates
        df_b1_full["game_date_dt"] = pd.to_datetime(df_b1_full["game_date"])
        unique_dates = sorted(df_b1_full["game_date_dt"].unique())
        cutoff_date = unique_dates[len(unique_dates) // 3]

        df_b1 = df_b1_full[df_b1_full["game_date_dt"] <= cutoff_date].copy()
        logger.info(f"Prepared Train (B0 2023-24): {len(df_b0)} rows")
        logger.info(f"Prepared Validation (B1 early 2024-25): {len(df_b1)} rows (up to {cutoff_date.strftime('%Y-%m-%d')})")

        from src.models.injury_ablation import enrich_dataset_with_injury_features
        logger.info("Enriching B0 and B1 with winning I3 injury & missing role features...")
        df_b0 = enrich_dataset_with_injury_features(df_b0)
        df_b1 = enrich_dataset_with_injury_features(df_b1)

        return df_b0, df_b1

    def train_and_evaluate(self, stat: str = "pts") -> Dict[str, Any]:
        """Train and evaluate baseline, LightGBM, and CatBoost for a specific stat."""
        df_train, df_val = self.prepare_data()
        target_col = f"target_{stat}"

        # Clean features available in dataset
        self.features = [c for c in FEATURE_COLS if c in df_train.columns and c in df_val.columns]

        X_train = df_train[self.features].fillna(0.0).astype(float)
        y_train = df_train[target_col].to_numpy()

        X_val = df_val[self.features].fillna(0.0).astype(float)
        y_val = df_val[target_col].to_numpy()

        results = {
            "stat": stat.upper(),
            "train_samples": len(X_train),
            "val_samples": len(X_val),
            "models": {},
        }

        # 1. Baseline: Weighted Average
        base_avg = WeightedAverageBaseline(stat=stat)
        preds_base_avg = base_avg.predict(df_val)
        results["models"]["Baseline_WeightedAvg"] = {
            "rmse": round(float(np.sqrt(mean_squared_error(y_val, preds_base_avg))), 3),
            "mae": round(float(mean_absolute_error(y_val, preds_base_avg)), 3),
            "poisson_deviance": round(calculate_poisson_deviance(y_val, preds_base_avg), 3),
        }

        # 2. Baseline: Minutes x Rate
        base_min = MinutesRateBaseline(stat=stat)
        preds_base_min = base_min.predict(df_val)
        results["models"]["Baseline_MinutesRate"] = {
            "rmse": round(float(np.sqrt(mean_squared_error(y_val, preds_base_min))), 3),
            "mae": round(float(mean_absolute_error(y_val, preds_base_min)), 3),
            "poisson_deviance": round(calculate_poisson_deviance(y_val, preds_base_min), 3),
        }

        # 3. LightGBM Poisson
        logger.info(f"Training LightGBM Poisson for {stat.upper()}...")
        lgbm_model = lgb.LGBMRegressor(
            objective="poisson",
            n_estimators=300,
            learning_rate=0.03,
            num_leaves=31,
            random_state=20261109,
            verbosity=-1,
        )
        lgbm_model.fit(X_train, y_train)
        preds_lgbm = np.maximum(lgbm_model.predict(X_val), 0.1)

        results["models"]["LightGBM_Poisson"] = {
            "rmse": round(float(np.sqrt(mean_squared_error(y_val, preds_lgbm))), 3),
            "mae": round(float(mean_absolute_error(y_val, preds_lgbm)), 3),
            "poisson_deviance": round(calculate_poisson_deviance(y_val, preds_lgbm), 3),
        }
        # Save LightGBM model
        lgbm_path = self.models_dir / f"lgbm_{stat}.txt"
        lgbm_model.booster_.save_model(str(lgbm_path))

        # 4. CatBoost Poisson
        logger.info(f"Training CatBoost Poisson for {stat.upper()}...")
        cat_model = CatBoostRegressor(
            loss_function="Poisson",
            iterations=300,
            learning_rate=0.03,
            depth=6,
            random_seed=20261109,
            verbose=0,
        )
        cat_model.fit(X_train, y_train)
        preds_cat = np.maximum(cat_model.predict(X_val), 0.1)

        results["models"]["CatBoost_Poisson"] = {
            "rmse": round(float(np.sqrt(mean_squared_error(y_val, preds_cat))), 3),
            "mae": round(float(mean_absolute_error(y_val, preds_cat)), 3),
            "poisson_deviance": round(calculate_poisson_deviance(y_val, preds_cat), 3),
        }
        # Save CatBoost model
        cat_path = self.models_dir / f"catboost_{stat}.cbm"
        cat_model.save_model(str(cat_path))

        # Determine best model by Poisson Deviance
        best_model = min(results["models"].items(), key=lambda x: x[1]["poisson_deviance"])
        results["selected_best_model"] = best_model[0]

        return results

    def run_all_stats(self) -> Dict[str, Any]:
        """Train models for PTS, REB, AST and produce full benchmark report."""
        report = {}
        for s in ["pts", "reb", "ast"]:
            report[s] = self.train_and_evaluate(stat=s)

        # Save feature list for inference
        features_meta_path = self.models_dir / "features_meta.json"
        with open(features_meta_path, "w", encoding="utf-8") as f:
            json.dump({"features": self.features}, f, indent=2)

        # Save benchmark report
        report_path = settings.REPORTS_DIR / "phase3_models_benchmark.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        logger.info(f"Phase 3 Model Benchmark report saved to {report_path}")
        return report

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    trainer = ModelTrainer()
    benchmark_report = trainer.run_all_stats()
    print("Benchmark Results:")
    print(json.dumps(benchmark_report, indent=2))
