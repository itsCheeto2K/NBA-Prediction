"""
Comprehensive Betting Simulation & Win Rate (Tỉ lệ thắng kèo) Evaluation.

Evaluates props prediction performance and simulated betting returns on:
1. Current Season (2026-27 holdout games)
2. Validation Season (2024-25 holdout games)

Compares:
- Old / Legacy uncalibrated model (phi=0.10, legacy Poisson/narrow NB2)
- New Release Model (release_f1146917918e: LightGBM Poisson + NB2 fitted phi=0.33039 + Piecewise-Linear Calibrator + post-rolling interactions)
"""
import json
import logging
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.storage.datasets import dataset_view
from src.models.selector import ModelBundle
from src.models.injury_ablation import enrich_dataset_with_injury_features

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

def evaluate_predictions(actuals, lines, q_overs, q_unders, decimal_odds=1.909):
    breakeven_prob = 1.0 / decimal_odds  # ~52.38%

    thresholds = [
        ("Tất cả kèo có edge (Edge >= 0%)", 0.00),
        ("Edge thấp (Edge >= 2%)", 0.02),
        ("Edge vừa (Edge >= 4%)", 0.04),
        ("Edge cao (Edge >= 6%)", 0.06),
        ("Kèo giá trị mạnh (Edge >= 8%)", 0.08),
    ]

    metrics = []
    for label, edge in thresholds:
        req_p = breakeven_prob + edge

        bet_over = (q_overs >= req_p) & (q_overs > q_unders)
        bet_under = (q_unders >= req_p) & (q_unders > q_overs)

        over_wins = (actuals[bet_over] > lines[bet_over]).sum()
        over_losses = (actuals[bet_over] < lines[bet_over]).sum()
        over_pushes = (actuals[bet_over] == lines[bet_over]).sum()

        under_wins = (actuals[bet_under] < lines[bet_under]).sum()
        under_losses = (actuals[bet_under] > lines[bet_under]).sum()
        under_pushes = (actuals[bet_under] == lines[bet_under]).sum()

        total_bets = int(bet_over.sum() + bet_under.sum())
        total_wins = int(over_wins + under_wins)
        total_losses = int(over_losses + under_losses)
        total_pushes = int(over_pushes + under_pushes)

        settled_bets = total_wins + total_losses
        win_rate = (total_wins / settled_bets * 100.0) if settled_bets > 0 else 0.0
        profit_units = total_wins * (decimal_odds - 1.0) - total_losses * 1.0
        roi = (profit_units / total_bets * 100.0) if total_bets > 0 else 0.0

        metrics.append({
            "threshold": label,
            "edge": f"+{edge*100:.1f}%",
            "min_prob": round(req_p * 100, 2),
            "bets": total_bets,
            "wins": total_wins,
            "losses": total_losses,
            "pushes": total_pushes,
            "win_rate": round(win_rate, 2),
            "profit_units": round(profit_units, 2),
            "roi": round(roi, 2),
        })

    return metrics

def run_simulation():
    view = dataset_view()
    manifest_path = Path("data/snapshots/manifest.json")
    with open(manifest_path) as f:
        manifest = json.load(f)
    models_dir = Path(manifest["models_dir"])

    bundles = {
        "PTS": ModelBundle.load(models_dir / "bundle_pts"),
        "REB": ModelBundle.load(models_dir / "bundle_reb"),
        "AST": ModelBundle.load(models_dir / "bundle_ast"),
    }

    datasets = [
        ("Mùa giải hiện tại (2026-27)", view.path("features_2026-27.parquet")),
        ("Tập kiểm thử Validation (2024-25)", view.path("features_2024-25.parquet")),
    ]

    all_results = {}

    for ds_name, parquet_path in datasets:
        logger.info(f"\n=======================================================")
        logger.info(f"Đang đánh giá trên: {ds_name}")
        logger.info(f"=======================================================")

        df = pd.read_parquet(parquet_path)
        df = enrich_dataset_with_injury_features(df)
        df = df[df["target_min"] > 0].copy()

        ds_stat_results = {}

        for stat, bundle in bundles.items():
            stat_lower = stat.lower()
            target_col = f"target_{stat_lower}"
            roll_col = f"{stat_lower}_roll_mean_5"

            valid_mask = df[target_col].notna() & df[roll_col].notna() & (df[roll_col] > 0)
            sub_df = df[valid_mask].copy()

            lines = np.floor(sub_df[roll_col].values) + 0.5
            actuals = sub_df[target_col].values
            floor_lines = np.floor(lines).astype(int)

            # Predict means
            feat_names = [f for f in bundle.feature_schema if f in sub_df.columns]
            X = sub_df[feat_names].fillna(0.0).to_numpy(dtype=np.float64)
            if bundle.mean_family in ("lgbm", "catboost"):
                mus = bundle._mean_predictor.predict(X)
            else:
                mus = bundle._mean_predictor.predict(sub_df)
            mus = np.maximum(1e-6, mus)

            # 1. New Model: Fitted distribution + Calibrator
            phi_new = bundle.fitted_phi
            dist_type = getattr(bundle, "raw_distribution_family", "nb2")
            if dist_type == "poisson" or phi_new < 1e-5:
                raw_cdf_new = stats.poisson.cdf(floor_lines, mus)
            else:
                r_new = 1.0 / phi_new
                p_new = r_new / (r_new + mus)
                raw_cdf_new = stats.nbinom.cdf(floor_lines, r_new, p_new)

            if bundle._calibrator_obj is not None:
                cal_cdf_new = bundle._calibrator_obj(raw_cdf_new)
                cal_cdf_new = np.clip(cal_cdf_new, 0.0, 1.0)
            else:
                cal_cdf_new = raw_cdf_new
            new_q_overs = 1.0 - cal_cdf_new
            new_q_unders = cal_cdf_new

            # 2. Old Model: Legacy narrow uncalibrated phi (PTS=0.10, REB=0.08, AST=0.08)
            phi_old = 0.10 if stat == "PTS" else 0.08
            r_old = 1.0 / phi_old
            p_old = r_old / (r_old + mus)
            raw_cdf_old = stats.nbinom.cdf(floor_lines, r_old, p_old)
            old_q_overs = 1.0 - raw_cdf_old
            old_q_unders = raw_cdf_old

            old_metrics = evaluate_predictions(actuals, lines, old_q_overs, old_q_unders)
            new_metrics = evaluate_predictions(actuals, lines, new_q_overs, new_q_unders)

            comparison = []
            for om, nm in zip(old_metrics, new_metrics):
                comparison.append({
                    "threshold": nm["threshold"],
                    "edge": nm["edge"],
                    "min_prob": nm["min_prob"],
                    "old_bets": om["bets"],
                    "old_win_rate": om["win_rate"],
                    "old_roi": om["roi"],
                    "old_profit": om["profit_units"],
                    "new_bets": nm["bets"],
                    "new_win_rate": nm["win_rate"],
                    "new_roi": nm["roi"],
                    "new_profit": nm["profit_units"],
                    "win_rate_diff": round(nm["win_rate"] - om["win_rate"], 2),
                    "roi_diff": round(nm["roi"] - om["roi"], 2),
                })

            ds_stat_results[stat] = {
                "sample_size": len(sub_df),
                "fitted_phi": bundle.fitted_phi,
                "legacy_phi": phi_old,
                "calibrator": bundle.calibrator_type,
                "comparison": comparison,
            }

            logger.info(f"\n--- Kết quả Kèo {stat} ({ds_name}, {len(sub_df)} trận) ---")
            logger.info(f"{'Ngưỡng cược':<32} | {'Cũ WR%':<8} {'Mới WR%':<8} {'Chênh lệch':<10} | {'Cũ ROI%':<9} {'Mới ROI%':<9}")
            logger.info("-" * 85)
            for c in comparison:
                diff_sign = "+" if c["win_rate_diff"] >= 0 else ""
                logger.info(f"{c['threshold']:<32} | {c['old_win_rate']:>6.2f}% {c['new_win_rate']:>6.2f}% {diff_sign + str(c['win_rate_diff']):>9}% | {c['old_roi']:>7.2f}% {c['new_roi']:>7.2f}%")

        all_results[ds_name] = ds_stat_results

    # Save to reports
    out_path = Path("reports/betting_simulation_report.json")
    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    logger.info(f"\nĐã lưu toàn bộ báo cáo chi tiết vào: {out_path}")
    return all_results

if __name__ == "__main__":
    run_simulation()
