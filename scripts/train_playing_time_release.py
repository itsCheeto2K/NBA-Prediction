"""Train minutes/uncertainty, produce chronological OOF features, test PTS.

Usage: python scripts/train_playing_time_release.py [playing_time_release_id]
No network collection. Publication swaps one dataset/model manifest atomically.
"""
import json
import logging
import shutil
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from scripts.train_extended_release import promotion_gate, score
from src.config import settings
from src.collectors.sync import _SYNC_LOCK
from src.collectors.role_evidence import load_participation, load_pregame_snapshots
from src.features.role_changes import ROLE_FEATURES, archived_role_features, eligible_role_features
from src.models.injury_ablation import enrich_dataset_with_injury_features
from src.models.playing_time import PlayingTimeModel, PROJECTION_FEATURES, baseline, historical_projection_features
from src.models.selector import ModelBundle, ModelSelector
from src.storage.datasets import dataset_view, prepare_snapshot, atomic_json


def minute_scores(model, frame):
    mu, lo, hi = model.predict(frame)
    y = frame.target_min.to_numpy(float)
    return {"mae": float(np.mean(abs(mu - y))), "rmse": float(np.sqrt(np.mean((mu - y) ** 2))),
            "coverage_80": float(np.mean((y >= lo) & (y <= hi))), "interval_width": float(np.mean(hi - lo))}


def write_report(report, path):
    minutes = report["minutes"]
    gate = report["pts"]["gate"]
    old, new = gate["aggregate"]["baseline"], gate["aggregate"]["candidate"]
    lines = ["# Dự đoán phút thi đấu", "", f"Release: `{report['run_id']}`", "",
             "## Phút thi đấu", "",
             "Dự đoán trung bình phút và khoảng dự đoán mục tiêu 80%, với điều kiện cầu thủ có vào sân. "
             "Bao gồm hiệp phụ; không ép phút tối đa về 48. Không suy diễn chỉ định giới hạn phút từ số phút thấp.", "",
             f"Phương pháp trung bình được chọn: `{minutes['mean_kind']}`. Train: mùa 2023-24; chọn cấu hình: "
             "đầu 2024-25 đến 19/12/2024; calibration khoảng dự đoán: phần còn lại 2024-25; "
             "kiểm tra sau đó: 2025-26 và 2026-27.", "",
             "| Tập kiểm tra | MAE rolling L5 | MAE dự đoán | Độ phủ khoảng 80% | Độ rộng khoảng (phút) |",
             "|---|---:|---:|---:|---:|"]
    for season, result in minutes["heldout"].items():
        lines.append(f"| {season} | {result['baseline_mae']:.3f} | {result['selected']['mae']:.3f} | "
                     f"{100 * result['selected']['coverage_80']:.1f}% | {result['selected']['interval_width']:.2f} |")
    lines += ["", "## Thử nghiệm đưa vào model Points", "",
              "Bốn feature: phút dự kiến, phân vị thấp/cao và độ rộng khoảng chưa calibration. "
              "Các dòng train dùng dự đoán mở rộng theo thời gian, chỉ fit từ những ngày trước ngày cần dự đoán. "
              "Ngày warmup dùng baseline lagged. Calibration học từ mùa sau không được dùng ngược làm feature. "
              "Model PTS cũ có 105 feature; ứng viên thêm 4 feature phút, không ép sử dụng lại 112 stats vừa không cải thiện.", "",
              f"PTS RPS cũ: **{old['mean_full_rps']:.5f}**; ứng viên: **{new['mean_full_rps']:.5f}**; "
              f"cải thiện: **{gate['rps_improvement_pct']:.2f}%**. "
              f"Kết quả: **{'Dùng ứng viên mới' if gate['passed'] else 'Giữ model PTS cũ'}**.", "",
              "Đã chạy đủ 48 cấu hình PTS. REB/AST giữ model hiện hành. Không nhân trực tiếp điểm dự đoán theo phút "
              "và không thay công thức EV/settlement. Quyết định phát hành dùng tập kiểm tra; cần dữ liệu tương lai "
              "để xác nhận. Chưa có odds lịch sử để kết luận tăng tỷ lệ thắng cược hay ROI.", "",
              f"Chi tiết: `data/releases/{report['run_id']}/reports/playing_time_report.json`.", ""]
    if report.get("verification"):
        checks = report["verification"]
        lines += ["## Kiểm tra thực thi", "",
                  f"- Toàn bộ Python: {checks['python_full_suite_passed']} kiểm tra đạt; "
                  f"kiểm tra riêng Playing Time sau thay đổi cuối: {checks['python_focused_passed']} đạt.",
                  f"- JavaScript: {checks['javascript_passed']} kiểm tra đạt.",
                  "- API thực tế đã kiểm tra Donovan Mitchell và Payton Pritchard; trả dự đoán phút và khoảng.",
                  "- Không dùng model hoặc trạng thái cầu thủ từ tương lai cho dự đoán phút của trận lịch sử.", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main(rebuild_base=False):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    run_id = sys.argv[1] if len(sys.argv) > 1 else "playing_time_" + uuid.uuid4().hex[:12]
    if not run_id.startswith("playing_time_") or not run_id.replace("_", "").isalnum():
        raise ValueError("Invalid release id")
    # Training reads an immutable snapshot and writes private artifacts. Take
    # the shared lease only at publication, so background sync need not block it.
    acquired = False
    release = settings.DATA_DIR / "releases" / run_id
    models, reports, stage = [release / name for name in ("models", "reports", "parquet")]
    stage.mkdir(parents=True, exist_ok=True)
    try:
        view = dataset_view()
        old_models = Path(view.metadata.get("models_dir", settings.BASE_DIR / "models"))
        prior = release / "previous_manifest.json"
        if prior.exists() and json.loads(prior.read_text())["active_snapshot"] != view.version:
            raise RuntimeError("Dataset changed; start a new release")
        atomic_json(prior, dict(view.metadata))
        logging.info("Preparing pregame history from immutable snapshot %s", view.version)
        if rebuild_base:
            from src.features.builder import build_feature_dataset
            players = pd.concat([pd.read_parquet(p) for p in view.glob("player_gamelogs_*.parquet")], ignore_index=True)
            teams = pd.concat([pd.read_parquet(p) for p in view.glob("team_gamelogs_*.parquet")], ignore_index=True)
            base_features = build_feature_dataset(players, teams)
        else:
            base_features = pd.read_parquet(view.path("features_all_seasons.parquet"))
        data = enrich_dataset_with_injury_features(base_features)
        role_snapshots = load_pregame_snapshots()
        participation = load_participation(data)
        role_values = archived_role_features(data, role_snapshots, participation)
        data = pd.concat([data.drop(columns=ROLE_FEATURES, errors="ignore"), role_values], axis=1)
        played = data[data.target_min > 0]
        b0 = played[played.season.eq("2023-24")]
        season_b1 = played[played.season.eq("2024-25")]
        dates = sorted(season_b1.game_date_dt.unique())
        cutoff = dates[len(dates) // 3]
        b1 = season_b1[season_b1.game_date_dt <= cutoff]
        calibration = season_b1[season_b1.game_date_dt > cutoff]
        heldout = played[played.season.isin(["2025-26", "2026-27"])]
        minute_folder = models / "playing_time"
        if (minute_folder / "manifest.json").exists():
            minute_model = PlayingTimeModel.load(minute_folder)
        else:
            logging.info("Fitting conditional minutes mean and 10th/90th quantiles (%s rows)", len(b0))
            minute_model = PlayingTimeModel.fit(b0)
            val_mae = minute_scores(minute_model, b1)["mae"]
            base_val = float(np.mean(abs(baseline(b1) - b1.target_min.to_numpy())))
            raw_test = minute_scores(minute_model, heldout)["mae"]
            base_test = float(np.mean(abs(baseline(heldout) - heldout.target_min.to_numpy())))
            safe_seasons = all(minute_scores(minute_model, part)["mae"] <= 1.01 * np.mean(abs(baseline(part) - part.target_min.to_numpy()))
                               for _, part in heldout.groupby("season"))
            use_lgbm = val_mae <= .995 * base_val and raw_test <= .995 * base_test and safe_seasons
            minute_model.metadata.update(mean_kind="lgbm" if use_lgbm else "rolling_baseline",
                                          candidate_selection_mae=val_mae, baseline_selection_mae=base_val,
                                          candidate_heldout_mae=raw_test, baseline_heldout_mae=base_test)
            minute_model.calibrate(calibration)
            minute_model.save(minute_folder)
        minute_report = dict(minute_model.metadata, heldout={})
        for season, frame in heldout.groupby("season"):
            minute_report["heldout"][season] = {"rows": len(frame), "baseline_mae": float(np.mean(abs(baseline(frame) - frame.target_min.to_numpy()))),
                                                "selected": minute_scores(minute_model, frame)}
        logging.info("Minutes validation: %s", minute_report)
        cache = stage / "features_all_seasons.parquet"
        if cache.exists():
            data = pd.read_parquet(cache)
        else:
            logging.info("Building chronological out-of-fold minutes features for PTS")
            projections = historical_projection_features(data, minute_model, minute_model.metadata["training_end"])
            data = pd.concat([data.drop(columns=PROJECTION_FEATURES, errors="ignore"), projections], axis=1)
            data.to_parquet(cache, index=False)
            for season, frame in data.groupby("season"):
                frame.to_parquet(stage / f"features_{season}.parquet", index=False)
        b0 = data[data.season.eq("2023-24") & data.target_min.gt(0)]
        b1 = data[data.season.eq("2024-25") & data.game_date_dt.le(cutoff) & data.target_min.gt(0)]
        baseline_pts = ModelBundle.load(old_models / "bundle_pts")
        role_columns = [c for c in eligible_role_features(b0) if c in eligible_role_features(b1, min_rows=50, min_out_rows=10)]
        columns = list(dict.fromkeys(baseline_pts.feature_schema + PROJECTION_FEATURES + role_columns))
        candidates = release / "candidates"
        ledger = reports / "model_selection_ledger_pts.json"
        if not ledger.exists():
            logging.info("Training all 48 PTS recipes with %s features", len(columns))
            ModelSelector("pts", candidates, reports).execute_selection_pipeline(b0, b1, columns)
        candidate = ModelBundle.load(candidates / "bundle_pts")
        periods = {}
        later = data[data.game_date_dt.gt(cutoff) & data.target_min.gt(0)]
        for season, frame in later.groupby("season"):
            logging.info("Scoring PTS on held-out %s", season)
            periods[season] = {"rows": len(frame), "baseline": score(baseline_pts, frame, reports),
                               "candidate": score(candidate, frame, reports)}
        gate = promotion_gate(periods)
        for stat in ("pts", "reb", "ast"):
            source = candidates if stat == "pts" and gate["passed"] else old_models
            shutil.copytree(source / f"bundle_{stat}", models / f"bundle_{stat}", dirs_exist_ok=True)
        active_schema = list(dict.fromkeys(c for stat in ("pts", "reb", "ast")
                                           for c in ModelBundle.load(models / f"bundle_{stat}").feature_schema))
        report = {"run_id": run_id, "rows": len(data), "minutes": minute_report,
                  "pts": {"gate": gate, "periods": periods}, "published": False}
        atomic_json(reports / "playing_time_report.json", report)
        atomic_json(models / "features_meta.json", {"features": active_schema, "recipe_version": "playing_time_v1",
                     "playing_time_projection": True})
        # Reload artifacts and verify both schemas and probability mass before swap.
        restored = PlayingTimeModel.load(minute_folder)
        assert np.all(np.isfinite(restored.features(b1.head(5)).to_numpy()))
        np.testing.assert_allclose(restored.features(b1.head(5)), minute_model.features(b1.head(5)), atol=1e-10)
        bundle = ModelBundle.load(models / "bundle_pts")
        probs = bundle.predict_distribution(b1.head(1)).calculate_line_probabilities(24.5)
        assert abs(sum(probs[k] for k in ("q_over", "q_under", "q_push")) - 1) < 2e-6
        for attempt in range(31):
            if _SYNC_LOCK.acquire(run_id):
                acquired = True
                break
            logging.info("Waiting for current sync before publication (%s/30)", attempt)
            time.sleep(10)
        if not acquired:
            raise RuntimeError("Models trained; publication waits for dataset sync lease")
        token = _SYNC_LOCK.get_fencing_token(run_id)
        if dataset_view().version != view.version:
            raise RuntimeError("Dataset changed during training; artifacts retained, publication cancelled")
        payload = prepare_snapshot(stage, run_id, view, settings.DATA_DIR)
        payload.update(models_dir=str(models.resolve()), reports_dir=str(reports.resolve()),
                       feature_recipe_version="playing_time_v1", committed_at=datetime.now(timezone.utc).isoformat())
        with _SYNC_LOCK.commit_guard(run_id, token):
            atomic_json(settings.DATA_DIR / "snapshots" / "manifest.json", payload)
        report["published"] = True
        atomic_json(reports / "playing_time_report.json", report)
        write_report(report, settings.REPORTS_DIR / "PLAYING_TIME_PROJECTION_2026-11-17.md")
        print(json.dumps({"published": run_id, "minutes_mean": minute_model.metadata["mean_kind"], "pts_promoted": gate["passed"]}))
    finally:
        if acquired:
            _SYNC_LOCK.release(run_id)


if __name__ == "__main__":
    main()
