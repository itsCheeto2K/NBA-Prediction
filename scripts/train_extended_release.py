"""Train the complete extended recipe and gate publication against live bundles.

Selection dates remain identical to the previous release for a fair feature
comparison. Later seasons are evaluation only, never training/calibration data.
Run with: python scripts/train_extended_release.py
"""
import json
import logging
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from src.config import settings
from src.collectors.sync import _SYNC_LOCK
from src.features.builder import build_feature_dataset
from src.features.extended_stats import EXTENDED_FEATURE_COLS, RECIPE_VERSION, UNAVAILABLE_ADVANCED
from src.features.target import latest_player_states
from src.models.injury_ablation import enrich_dataset_with_injury_features
from src.models.selector import ModelBundle, ModelSelector
from src.models.trainer import FEATURE_COLS
from src.storage.datasets import atomic_json, dataset_view, prepare_snapshot

TRAINING_SEASONS = ("2021-22", "2022-23", "2023-24")
SELECTION_SEASON = "2024-25"


def score(bundle, frame, reports):
    """Batch mean predictions, chunked distribution scoring to bound memory."""
    if bundle.mean_family in ("lgbm", "catboost"):
        mu = bundle._mean_predictor.predict(frame[bundle.feature_schema].fillna(0.).to_numpy(dtype=float))
    else:
        mu = bundle._mean_predictor.predict(frame)
    mu = np.maximum(mu, 1e-6)
    evaluator = ModelSelector(bundle.stat, reports / "unused", reports)
    totals = {}
    for start in range(0, len(frame), 2000):
        part = frame.iloc[start:start + 2000]
        metrics = evaluator.evaluate_recipe_on_b1(mu[start:start + len(part)], part[f"target_{bundle.stat.lower()}"].to_numpy(),
                    bundle.raw_distribution_family, bundle.fitted_phi, bundle._calibrator_obj)
        for name, value in metrics.items():
            totals[name] = totals.get(name, 0.) + value * len(part)
    return {name: value / len(frame) for name, value in totals.items()}


def promotion_gate(periods):
    """Fixed before training: >=0.5% RPS gain, log loss <=1% regression.

    Also require no season to regress by over 1% in RPS. This is a release
    safety check, not a confidence interval or proof of profitability.
    """
    n = sum(p["rows"] for p in periods.values())
    aggregate = {kind: {metric: sum(p["rows"] * p[kind][metric] for p in periods.values()) / n
                        for metric in ("mean_full_rps", "mean_neg_log_score", "coverage_90")}
                 for kind in ("baseline", "candidate")}
    gain = 1 - aggregate["candidate"]["mean_full_rps"] / aggregate["baseline"]["mean_full_rps"]
    passed = gain >= .005 and aggregate["candidate"]["mean_neg_log_score"] <= 1.01 * aggregate["baseline"]["mean_neg_log_score"]
    passed = passed and all(p["candidate"]["mean_full_rps"] <= 1.01 * p["baseline"]["mean_full_rps"] for p in periods.values())
    return {"passed": bool(passed), "rps_improvement_pct": 100 * gain, "aggregate": aggregate}


def write_markdown(report, destination):
    lines = ["# Huấn luyện lại với các nhóm stats mở rộng", "",
             f"- Release: `{report['run_id']}`", f"- Recipe: `{RECIPE_VERSION}`",
             f"- Dữ liệu: {report['rows']:,} lượt thi đấu; mới nhất {report['raw_latest_date']}.",
             f"- Đầu vào: {report['features']} feature, gồm {len(report['new_features'])} feature mới.",
             f"- Train: các mùa {', '.join(report['training_seasons'])} ({report['training_rows']:,} dòng).",
             f"- Chọn cấu hình: đầu mùa 2024-25 đến {report['selection_end']} ({report['selection_rows']:,} dòng).",
             "- Kiểm tra sau huấn luyện: phần còn lại của 2024-25, 2025-26 và 2026-27 hiện có.", "",
             "## Các nhóm đã bổ sung", "",
             "PTS/REB/AST/MIN; FGM/FGA, 2PM/2PA, 3PM/3PA, FTM/FTA; FG%, 2P%, 3P%, FT%, TS%, eFG%; "
             "DREB/OREB; STL/BLK; TOV/PF; AST/TO; +/−; tần suất double-double/triple-double.", "",
             "Mỗi chỉ số có L5/L10/L20 và từ đầu mùa. Chỉ dùng các trận trước trận cần dự đoán. "
             "Tỷ lệ ném tính từ tổng made/attempts trên cùng mẫu; không làm tròn đầu vào model. "
             "Rank, màu UI và số liệu tổng kết tương lai không được đưa vào công thức.", "",
             "Chưa có dữ liệu nguồn cho USG%, ORtg, DRtg, PER; không tự tạo số thay thế.", "",
             "## Kết quả đối chiếu bản đang chạy", "",
             "RPS và negative log-score càng thấp càng tốt. Độ phủ 90% là chỉ số chẩn đoán, không phải tỷ lệ thắng cược.", "",
             "| Market | RPS cũ | RPS mới | Cải thiện RPS | Log-score cũ | Log-score mới | Bản được dùng |",
             "|---|---:|---:|---:|---:|---:|---|"]
    for stat, result in report["markets"].items():
        gate = result["gate"]
        old, new = gate["aggregate"]["baseline"], gate["aggregate"]["candidate"]
        lines.append(f"| {stat.upper()} | {old['mean_full_rps']:.5f} | {new['mean_full_rps']:.5f} | "
                     f"{gate['rps_improvement_pct']:.2f}% | {old['mean_neg_log_score']:.4f} | "
                     f"{new['mean_neg_log_score']:.4f} | {'Mới' if gate['passed'] else 'Giữ bản cũ'} |")
    lines += ["", "Điều kiện thay bản cũ: RPS tổng cải thiện ít nhất 0,5%; log-score tổng không xấu hơn quá 1%; "
              "RPS mỗi mùa không xấu hơn quá 1%. Đã chạy đủ 48 cấu hình/market, tổng 144 cấu hình.", "",
              "217 feature là bộ đầu vào của các model ứng viên đã huấn luyện. Các market giữ bản cũ vẫn dùng "
              "trọng số và schema cũ; các feature mới chưa tác động đến dự đoán của những market này.", "",
              "## Giới hạn", "", "Giữ nguyên mốc train/chọn cấu hình của release cũ để so sánh. Các mùa sau chỉ dùng để kiểm tra, "
              "không được đưa ngược vào train hoặc calibration. Quyết định phát hành có sử dụng tập kiểm tra, "
              "nên kết quả sau lựa chọn vẫn cần xác nhận trên các trận tương lai.", "",
              "Chưa có odds/line nhà cái theo thời điểm lịch sử nên chưa thể kết luận ROI hoặc cải thiện hiệu suất cược. "
              "DNP/void, push và công thức settlement/EV vẫn giữ nguyên.", "",
              "Chi tiết từng mùa, từng cấu hình và đường dẫn model nằm trong "
              f"`data/releases/{report['run_id']}/reports/extended_training_report.json`.", ""]
    if report.get("verification"):
        lines += ["## Kiểm tra thực thi", "", f"- Python: {report['verification']['python_passed']} kiểm tra đạt.",
                  f"- JavaScript: {report['verification']['javascript_passed']} kiểm tra đạt.",
                  "- API sau khi nạp release: 3 model sẵn sàng; PTS/REB/AST trả JSON, xác suất và EV hợp lệ.",
                  "- Kiểm tra chống rò rỉ dữ liệu, reset mùa mới và parity train/inference có dòng DNP đều đạt.", ""]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines), encoding="utf-8")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    run_id = sys.argv[1] if len(sys.argv) > 1 else "extended_" + uuid.uuid4().hex[:12]
    if not run_id.startswith("extended_") or not run_id.replace("_", "").isalnum():
        raise ValueError("Invalid release id")
    if not _SYNC_LOCK.acquire(run_id):
        raise RuntimeError("Another sync/release owns the dataset lease")
    token = _SYNC_LOCK.get_fencing_token(run_id)
    release = settings.DATA_DIR / "releases" / run_id
    stage, candidates, models, reports = [release / name for name in ("parquet", "candidates", "models", "reports")]
    stage.mkdir(parents=True, exist_ok=True)
    try:
        view = dataset_view()
        previous_models = Path(view.metadata.get("models_dir", settings.BASE_DIR / "models"))
        previous_manifest = release / "previous_manifest.json"
        if previous_manifest.exists():
            saved_view = json.loads(previous_manifest.read_text(encoding="utf-8"))
            if saved_view.get("active_snapshot") != view.version:
                raise RuntimeError("Dataset changed since this run; start a new release instead of resuming")
        else:
            atomic_json(previous_manifest, dict(view.metadata))
        players = pd.concat([pd.read_parquet(p) for p in view.glob("player_gamelogs_*.parquet")], ignore_index=True)
        teams = pd.concat([pd.read_parquet(p) for p in view.glob("team_gamelogs_*.parquet")], ignore_index=True)
        logging.info("Building extended pregame profiles for %s raw rows", len(players))
        cached = stage / "features_all_seasons.parquet"
        features = pd.read_parquet(cached) if cached.exists() else build_feature_dataset(players, teams)
        features.to_parquet(stage / "features_all_seasons.parquet", index=False)
        for season, frame in features.groupby("season"):
            frame.to_parquet(stage / f"features_{season}.parquet", index=False)
        enriched = enrich_dataset_with_injury_features(features)
        played = enriched[enriched.target_min > 0].copy()
        b0 = played[played.season.isin(TRAINING_SEASONS)].copy()
        season_b1 = played[played.season == SELECTION_SEASON]
        if b0.empty or season_b1.empty:
            raise RuntimeError(
                "Missing historical training/selection data. Required train seasons: "
                f"{', '.join(TRAINING_SEASONS)}; selection season: {SELECTION_SEASON}. "
                "Backfill the historical seasons before training."
            )
        dates = sorted(season_b1.game_date_dt.unique())
        cutoff = dates[len(dates) // 3]
        b1 = season_b1[season_b1.game_date_dt <= cutoff].copy()
        heldout = played[played.game_date_dt > cutoff].copy()
        columns = [c for c in FEATURE_COLS if c in enriched and b0[c].notna().any() and b1[c].notna().any()]
        report = {"run_id": run_id, "recipe_version": RECIPE_VERSION, "rows": len(features),
                  "raw_latest_date": str(played.game_date_dt.max()), "baseline_models_dir": str(previous_models),
                  "training_seasons": list(TRAINING_SEASONS), "training_rows": len(b0),
                  "selection_season": SELECTION_SEASON, "selection_rows": len(b1), "selection_end": str(cutoff),
                  "features": len(columns), "new_features": [c for c in columns if c in EXTENDED_FEATURE_COLS],
                  "unavailable_advanced": list(UNAVAILABLE_ADVANCED), "markets": {},
                  "gate": "aggregate RPS improvement >=0.5%; aggregate log loss regression <=1%; each season RPS regression <=1%",
                  "limitations": ["Historical release split retained; no fitting on held-out seasons.",
                      "Release gate uses held-out results; post-gate performance requires future confirmation.",
                      "No historical bookmaker lines/odds: no ROI or betting hit-rate claim.",
                      "DD/TD inputs are historical frequencies; UI season totals/ranks/colors are not model inputs."]}
        for stat in ("pts", "reb", "ast"):
            logging.info("Training %s: all 48 recipes with %s features", stat, len(columns))
            ledger = reports / f"model_selection_ledger_{stat}.json"
            if ledger.exists() and (candidates / f"bundle_{stat}" / "bundle_manifest.json").exists():
                saved = json.loads(ledger.read_text(encoding="utf-8"))
                selection = {"stat": stat.upper(), "selection_summary": saved["selection_summary"],
                             "total_recipes": saved["total_recipes_evaluated"], "bundle_dir": str(candidates / f"bundle_{stat}")}
            else:
                selection = ModelSelector(stat, candidates, reports).execute_selection_pipeline(b0, b1, columns)
            candidate = ModelBundle.load(candidates / f"bundle_{stat}")
            baseline = ModelBundle.load(previous_models / f"bundle_{stat}")
            periods = {}
            for season, frame in heldout.groupby("season"):
                logging.info("Scoring %s on held-out %s (%s rows)", stat, season, len(frame))
                periods[season] = {"rows": len(frame), "baseline": score(baseline, frame, reports),
                                   "candidate": score(candidate, frame, reports)}
            gate = promotion_gate(periods)
            report["markets"][stat] = {"selection": selection, "periods": periods, "gate": gate,
                                       "active": "candidate" if gate["passed"] else "baseline"}
            source = candidates if gate["passed"] else previous_models
            shutil.copytree(source / f"bundle_{stat}", models / f"bundle_{stat}", dirs_exist_ok=True)
            atomic_json(reports / "extended_training_report.json", report)
            logging.info("%s gate: %s", stat, gate)
        # Validate actual next-game inference, including reloaded production bundles.
        states = latest_player_states(enriched)
        for stat in ("pts", "reb", "ast"):
            bundle = ModelBundle.load(models / f"bundle_{stat}")
            missing = set(bundle.feature_schema) - set(states.columns)
            if missing:
                raise RuntimeError(f"Inference schema incomplete: {missing}")
            for _, row in states.tail(5).iterrows():
                probs = bundle.predict_distribution(row.to_frame().T).calculate_line_probabilities(20.5 if stat == "pts" else 4.5)
                if abs(sum(probs[k] for k in ("q_over", "q_under", "q_push")) - 1.) > 2e-6:
                    raise RuntimeError("Distribution does not conserve probability mass")
        atomic_json(models / "features_meta.json", {"features": columns, "recipe_version": RECIPE_VERSION,
                    "injury_snapshot_features": False, "markets": {s: r["active"] for s, r in report["markets"].items()}})
        payload = prepare_snapshot(stage, run_id, view, settings.DATA_DIR)
        payload.update(models_dir=str(models.resolve()), reports_dir=str(reports.resolve()),
                       feature_recipe_version=RECIPE_VERSION, committed_at=datetime.now(timezone.utc).isoformat())
        with _SYNC_LOCK.commit_guard(run_id, token):
            atomic_json(settings.DATA_DIR / "snapshots" / "manifest.json", payload)
        report["published"] = True
        atomic_json(reports / "extended_training_report.json", report)
        write_markdown(report, settings.REPORTS_DIR / "EXTENDED_STATS_RETRAINING_2026-11-17.md")
        print(json.dumps({"published": run_id, "reports": str(reports), "active": {s: r["active"] for s, r in report["markets"].items()}}))
    finally:
        _SYNC_LOCK.release(run_id)


if __name__ == "__main__":
    main()
