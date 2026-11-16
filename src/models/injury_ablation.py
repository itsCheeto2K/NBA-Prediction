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

# Base features I0 (A3 winner from Opponent & Schedule supplement plan)
I0_BASE_COLS = [
    # Player form / rolling stats
    "pts_roll_mean_5", "pts_roll_std_5", "pts_roll_mean_10", "pts_roll_mean_20", "pts_trend_5_20", "pts_decay_mean",
    "reb_roll_mean_5", "reb_roll_std_5", "reb_roll_mean_10", "reb_roll_mean_20", "reb_decay_mean",
    "ast_roll_mean_5", "ast_roll_std_5", "ast_roll_mean_10", "ast_roll_mean_20", "ast_decay_mean",
    "min_roll_mean_5", "min_roll_std_5", "min_roll_mean_10", "min_roll_mean_20",
    "fga_roll_mean_5", "fga_roll_mean_10", "fta_roll_mean_5", "fg3a_roll_mean_5",
    "pts_rate_shrinkage", "pts_n_eff", "pts_exposure",
    "reb_rate_shrinkage", "reb_n_eff", "reb_exposure",
    "ast_rate_shrinkage", "ast_n_eff", "ast_exposure",
    "is_home", "n_games_history",
    # Opponent context
    "opp_pace_prev10", "opp_def_rating_prev10", "opp_ast_allowed_per100_prev10",
    "opp_dreb_share_prev10", "opp_fg3a_share_prev10", "opp_pts_allowed_roll",
    # Schedule context
    "team_b2b", "opp_b2b", "team_rest_days", "opp_rest_days", "rest_advantage_days",
    "team_3in4", "team_4in6", "opp_3in4", "opp_4in6",
    "player_played_previous_team_game", "team_b2b_but_player_rested", "player_minutes_last7days",
]

OWN_INJURY_COLS = [
    "days_since_last_appearance",
    "is_long_absence_return",
    "games_since_return",
    "own_status_code",
    "own_is_questionable",
    "pi_participate",
]

TEAMMATE_MISSING_COLS = [
    "teammate_missing_minutes",
    "teammate_missing_fga",
    "teammate_missing_ast",
    "teammate_missing_pts",
    "teammate_top2_lost_minutes",
]

OPPONENT_MISSING_COLS = [
    "opp_missing_minutes",
    "opp_missing_fga",
    "opp_missing_ast",
    "opp_missing_pts",
]

INJURY_ABLATION_CONFIGS = {
    "I0": {"desc": "Baseline stats + opponent context + schedule congestion (No injury data)", "cols": I0_BASE_COLS},
    "I1": {"desc": "I0 + Own injury, return trajectory, and participation probability pi", "cols": I0_BASE_COLS + OWN_INJURY_COLS},
    "I2": {"desc": "I1 + Teammate missing roles (minutes, FGA, AST, PTS vacancies)", "cols": I0_BASE_COLS + OWN_INJURY_COLS + TEAMMATE_MISSING_COLS},
    "I3": {"desc": "I2 + Opponent missing roles (conceded defensive absences)", "cols": I0_BASE_COLS + OWN_INJURY_COLS + TEAMMATE_MISSING_COLS + OPPONENT_MISSING_COLS},
}

def enrich_dataset_with_injury_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Enriches dataset with historical own injury, return trajectory,
    and expected missing role features following §6, §7, and §8.
    """
    out = df.copy()
    out["game_date_dt"] = pd.to_datetime(out["game_date"])
    out = out.sort_values(by=["player_id", "game_date_dt"]).reset_index(drop=True)

    # 1. Own return features (§8.1)
    prev_dates = out.groupby("player_id")["game_date_dt"].shift(1)
    days_diff = (out["game_date_dt"] - prev_dates).dt.total_seconds() / 86400.0
    out["days_since_last_appearance"] = np.where(days_diff.isna(), 3.0, days_diff)
    out["is_long_absence_return"] = (out["days_since_last_appearance"] >= 14.0).astype(int)

    # Count games since a 14+ day gap
    gap_cumsum = out.groupby("player_id")["is_long_absence_return"].cumsum()
    out["games_since_return"] = np.clip(
        out.groupby(["player_id", gap_cumsum]).cumcount(),
        0, 10
    )

    # Baseline status proxies for historical games where player entered
    out["own_status_code"] = np.where(out["days_since_last_appearance"] >= 14, 2, np.where(out.get("team_b2b", 0) == 1, 1, 0))
    out["own_is_questionable"] = (out["own_status_code"] >= 2).astype(int)
    out["pi_participate"] = np.clip(1.0 - 0.08 * out["own_is_questionable"] - 0.05 * out.get("team_b2b", 0), 0.70, 0.99)

    # 2. Teammate missing role proxies (§7.1, Issue 06)
    # Estimate pre-game baseline player volume from rolling history
    out["player_b_min"] = out["min_roll_mean_5"].fillna(out.get("min_decay_mean", np.nan)).fillna(20.0)
    out["player_b_fga"] = out["fga_roll_mean_5"].fillna(8.0)
    out["player_b_ast"] = out["ast_roll_mean_5"].fillna(2.5)
    out["player_b_pts"] = out["pts_roll_mean_5"].fillna(10.0)

    # Pre-game absence probability from pre-game injury status / rest signals
    prob_absent = np.maximum(0.0, 1.0 - out["pi_participate"])
    out["ell_min"] = prob_absent * out["player_b_min"]
    out["ell_fga"] = prob_absent * out["player_b_fga"]
    out["ell_ast"] = prob_absent * out["player_b_ast"]
    out["ell_pts"] = prob_absent * out["player_b_pts"]

    # Pre-game expected lost volume per team-game
    team_game_tot = out.groupby(["game_id", "team_abbreviation"])[["ell_min", "ell_fga", "ell_ast", "ell_pts"]].transform("sum")

    # Teammate missing volume strictly excludes player i's own missing volume
    out["teammate_missing_minutes"] = np.maximum(0.0, team_game_tot["ell_min"] - out["ell_min"])
    out["teammate_missing_fga"] = np.maximum(0.0, team_game_tot["ell_fga"] - out["ell_fga"])
    out["teammate_missing_ast"] = np.maximum(0.0, team_game_tot["ell_ast"] - out["ell_ast"])
    out["teammate_missing_pts"] = np.maximum(0.0, team_game_tot["ell_pts"] - out["ell_pts"])

    # Teammate top 2 lost minutes among teammates (Issue 06, §7.1)
    out["rank_desc"] = out.groupby(["game_id", "team_abbreviation"])["ell_min"].rank(method="first", ascending=False).astype(int)
    top1 = out[out["rank_desc"] == 1].set_index(["game_id", "team_abbreviation"])["ell_min"]
    top2 = out[out["rank_desc"] == 2].set_index(["game_id", "team_abbreviation"])["ell_min"]
    top3 = out[out["rank_desc"] == 3].set_index(["game_id", "team_abbreviation"])["ell_min"]

    idx = pd.MultiIndex.from_arrays([out["game_id"], out["team_abbreviation"]])
    m1 = top1.reindex(idx).fillna(0.0).values
    m2 = top2.reindex(idx).fillna(0.0).values
    m3 = top3.reindex(idx).fillna(0.0).values
    rank = out["rank_desc"].values

    out["teammate_top2_lost_minutes"] = np.where(rank == 1, m2 + m3, np.where(rank == 2, m1 + m3, m1 + m2))

    # 3. Opponent missing role proxies (§7.1)
    team_tot_summary = out.groupby(["game_id", "team_abbreviation"])[["ell_min", "ell_fga", "ell_ast", "ell_pts"]].sum().reset_index()
    opp_game_tot = team_tot_summary.rename(columns={
        "team_abbreviation": "opponent_abbr",
        "ell_min": "opp_missing_minutes",
        "ell_fga": "opp_missing_fga",
        "ell_ast": "opp_missing_ast",
        "ell_pts": "opp_missing_pts",
    })

    out = out.merge(opp_game_tot, on=["game_id", "opponent_abbr"], how="left")
    out["opp_missing_minutes"] = out["opp_missing_minutes"].fillna(0.0)
    out["opp_missing_fga"] = out["opp_missing_fga"].fillna(0.0)
    out["opp_missing_ast"] = out["opp_missing_ast"].fillna(0.0)
    out["opp_missing_pts"] = out["opp_missing_pts"].fillna(0.0)

    out = out.drop(
        columns=["ell_min", "ell_fga", "ell_ast", "ell_pts", "rank_desc", "player_b_min", "player_b_fga", "player_b_ast", "player_b_pts"],
        errors="ignore",
    )

    return out


class InjuryAblationStudy:
    """
    Executes empirical ablation study I0-I3 as defined in
    NBA_INJURY_MODEL_SUPPLEMENT_PLAN.md §15.2.
    """

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or settings.REPORTS_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def load_and_enrich_data(self) -> Tuple[pd.DataFrame, pd.DataFrame]:
        b0_path = settings.PARQUET_DIR / "features_2023-24.parquet"
        b1_path = settings.PARQUET_DIR / "features_2024-25.parquet"

        if not b0_path.exists() or not b1_path.exists():
            raise FileNotFoundError("Missing features parquet files. Please build features first.")

        df_b0 = pd.read_parquet(b0_path)
        df_b1_full = pd.read_parquet(b1_path)

        df_b0 = df_b0[df_b0["target_min"] > 0].copy()
        df_b1_full = df_b1_full[df_b1_full["target_min"] > 0].copy()

        # Split B1: first 1/3 of unique game dates
        df_b1_full["game_date_dt"] = pd.to_datetime(df_b1_full["game_date"])
        unique_dates = sorted(df_b1_full["game_date_dt"].unique())
        cutoff_date = unique_dates[len(unique_dates) // 3]

        df_b1 = df_b1_full[df_b1_full["game_date_dt"] <= cutoff_date].copy().reset_index(drop=True)

        logger.info(f"Enriching Train (B0 2023-24: {len(df_b0)} rows) with Injury features...")
        df_b0_enriched = enrich_dataset_with_injury_features(df_b0)

        logger.info(f"Enriching Validation (B1 early 2024-25: {len(df_b1)} rows) with Injury features...")
        df_b1_enriched = enrich_dataset_with_injury_features(df_b1)

        return df_b0_enriched, df_b1_enriched

    def run_ablation(self, stats_to_evaluate: List[str] = None) -> Dict[str, Any]:
        if stats_to_evaluate is None:
            stats_to_evaluate = ["pts", "reb", "ast"]

        df_train, df_val = self.load_and_enrich_data()

        report: Dict[str, Any] = {
            "title": "Injury Model Ablation Study I0-I3 Development Report",
            "protocol": "B0 (2023-24) Train, B1 (2024-25 early 1/3) Validation, Conditional A_i = 1",
            "train_samples": len(df_train),
            "val_samples": len(df_val),
            "stats": {},
            "conclusion": {},
        }

        for stat in stats_to_evaluate:
            stat_upper = stat.upper()
            target_col = f"target_{stat}"
            logger.info(f"Running Injury Ablation I0-I3 for target {stat_upper}...")

            stat_results: Dict[str, Any] = {
                "configs": {},
                "paired_comparison_vs_I0": {},
                "cohort_analysis": {},
            }

            predictions: Dict[str, np.ndarray] = {}
            y_val = df_val[target_col].to_numpy()
            y_train = df_train[target_col].to_numpy()

            for cfg_name, cfg_info in INJURY_ABLATION_CONFIGS.items():
                cols = [c for c in cfg_info["cols"] if c in df_train.columns and c in df_val.columns]
                X_train = df_train[cols].fillna(0.0)
                X_val = df_val[cols].fillna(0.0)

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

            # Paired comparison vs I0
            preds_i0 = predictions["I0"]
            point_deviance_i0 = 2.0 * (
                np.where(y_val > 0, y_val * np.log(np.maximum(y_val, 1e-9) / preds_i0), 0.0)
                - (y_val - preds_i0)
            )

            for cfg_name in ["I1", "I2", "I3"]:
                preds_ik = predictions[cfg_name]
                point_deviance_ik = 2.0 * (
                    np.where(y_val > 0, y_val * np.log(np.maximum(y_val, 1e-9) / preds_ik), 0.0)
                    - (y_val - preds_ik)
                )
                diff = point_deviance_ik - point_deviance_i0
                mean_diff = float(np.mean(diff))
                t_stat, p_val = stats.ttest_rel(point_deviance_ik, point_deviance_i0)

                stat_results["paired_comparison_vs_I0"][cfg_name] = {
                    "mean_deviance_diff": round(mean_diff, 5),
                    "improvement_percent": round((1.0 - np.mean(point_deviance_ik) / np.mean(point_deviance_i0)) * 100, 3),
                    "paired_t_stat": round(float(t_stat), 4),
                    "p_value": round(float(p_val), 6),
                    "is_statistically_significant": bool(p_val < 0.05 and mean_diff < 0),
                }

            # Cohort analysis (§15.3): Questionable status, Long absence return, High teammate vacancy
            cohorts = {
                "own_status_risk": df_val["own_is_questionable"] == 1,
                "long_absence_return": df_val["is_long_absence_return"] == 1,
                "high_teammate_missing": df_val["teammate_missing_minutes"] >= 30.0,
            }

            winning_cfg = min(
                stat_results["configs"].items(),
                key=lambda x: x[1]["poisson_deviance"]
            )[0]

            for cohort_name, mask in cohorts.items():
                n_cohort = int(mask.sum())
                if n_cohort >= 10:
                    y_sub = y_val[mask]
                    dev_i0 = float(calculate_poisson_deviance(y_sub, predictions["I0"][mask]))
                    dev_win = float(calculate_poisson_deviance(y_sub, predictions[winning_cfg][mask]))
                    diff_pct = round((1.0 - dev_win / dev_i0) * 100, 2) if dev_i0 > 0 else 0.0

                    stat_results["cohort_analysis"][cohort_name] = {
                        "count": n_cohort,
                        "poisson_deviance_I0": round(dev_i0, 4),
                        f"poisson_deviance_{winning_cfg}": round(dev_win, 4),
                        "improvement_percent": diff_pct,
                    }

            report["stats"][stat_upper] = stat_results

        # Select overall winner
        best_votes = []
        for s in stats_to_evaluate:
            stat_u = s.upper()
            best_c = min(
                report["stats"][stat_u]["configs"].items(),
                key=lambda x: x[1]["poisson_deviance"]
            )[0]
            best_votes.append(best_c)

        winning_config = max(set(best_votes), key=best_votes.count)
        report["conclusion"] = {
            "winning_config": winning_config,
            "decision": "KEEP" if winning_config in ["I1", "I2", "I3"] else "INCONCLUSIVE",
            "summary": f"Configuration {winning_config} demonstrated the lowest Poisson deviance across evaluated props.",
        }

        # Save to reports
        report_path = self.output_dir / "ablation_I0_I3_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        logger.info(f"Injury Ablation report saved to {report_path}")
        return report

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    study = InjuryAblationStudy()
    res = study.run_ablation()
    print("Injury Ablation Conclusion:")
    print(json.dumps(res["conclusion"], indent=2))
