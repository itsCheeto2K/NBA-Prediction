"""Rebuild all local features and select models, then publish one tested release.

No network collection. Existing parquet/model artifacts are retained for rollback.
"""
import json
import logging
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from src.config import settings
from src.collectors.sync import _SYNC_LOCK
from src.features.builder import build_feature_dataset
from src.models.injury_ablation import enrich_dataset_with_injury_features
from src.models.trainer import FEATURE_COLS
from src.models.selector import ModelSelector, ModelBundle
from src.storage.datasets import dataset_view, prepare_snapshot, atomic_json


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    run_id = "release_" + uuid.uuid4().hex[:12]
    if not _SYNC_LOCK.acquire(run_id):
        raise RuntimeError("Another sync/release owns the dataset lease")
    token = _SYNC_LOCK.get_fencing_token(run_id)
    release = settings.DATA_DIR / "releases" / run_id
    stage = release / "parquet"
    stage.mkdir(parents=True)
    try:
        view = dataset_view()
        players = pd.concat([pd.read_parquet(p) for p in view.glob("player_gamelogs_*.parquet")], ignore_index=True)
        teams = pd.concat([pd.read_parquet(p) for p in view.glob("team_gamelogs_*.parquet")], ignore_index=True)
        features = build_feature_dataset(players, teams)
        features.to_parquet(stage / "features_all_seasons.parquet", index=False)
        for season, frame in features.groupby("season"):
            frame.to_parquet(stage / f"features_{season}.parquet", index=False)

        # Compute deterministic return history once across seasons. No archived
        # injury snapshots exist: unknown injury columns are excluded below.
        enriched = enrich_dataset_with_injury_features(features)
        # Train on all completed seasons through 2023-24. 2024-25 remains the
        # chronological selection window and later seasons remain untouched.
        training_seasons = ["2021-22", "2022-23", "2023-24"]
        b0 = enriched[enriched.season.isin(training_seasons) & (enriched.target_min > 0)].copy()
        b1 = enriched[(enriched.season == "2024-25") & (enriched.target_min > 0)].copy()
        if b0.empty or b1.empty:
            raise RuntimeError(
                "Cannot rebuild release: historical training seasons through 2023-24 "
                "and 2024-25 selection data are required. Backfill missing seasons first."
            )
        dates = sorted(b1.game_date_dt.unique())
        b1 = b1[b1.game_date_dt <= dates[len(dates) // 3]].copy()
        columns = [c for c in FEATURE_COLS if c in enriched and b0[c].notna().any() and b1[c].notna().any()]
        models = release / "models"
        reports = release / "reports"
        summaries = {}
        for stat in ["pts", "reb", "ast"]:
            logging.info("Selecting all 48 distribution recipes for %s", stat)
            summaries[stat] = ModelSelector(stat, models, reports).execute_selection_pipeline(b0, b1, columns)
            bundle = ModelBundle.load(models / f"bundle_{stat}")
            dist = bundle.predict_distribution(b1.head(1))
            probs = dist.calculate_line_probabilities(20.5 if stat == "pts" else 4.5)
            if abs(sum(probs[k] for k in ["q_over", "q_under", "q_push"]) - 1) > 2e-6:
                raise RuntimeError("Release distribution failed mass validation")
        atomic_json(models / "features_meta.json", {"features": columns, "recipe_version": "audit_v2", "injury_snapshot_features": False})
        atomic_json(reports / "release_validation.json", {"run_id": run_id, "features": len(columns), "rows": len(features), "training_seasons": training_seasons, "train_rows": len(b0), "validation_season": "2024-25_first_third", "validation_rows": len(b1), "injury_evidence": "unavailable_excluded", "selection": summaries})

        payload = prepare_snapshot(stage, run_id, view, settings.DATA_DIR)
        payload.update(models_dir=str(models.resolve()), reports_dir=str(reports.resolve()), feature_recipe_version="audit_v2")
        with _SYNC_LOCK.commit_guard(run_id, token):
            atomic_json(settings.DATA_DIR / "snapshots" / "manifest.json", payload)
        print(json.dumps({"published": run_id, "models": str(models), "reports": str(reports)}))
    finally:
        _SYNC_LOCK.release(run_id)


if __name__ == "__main__":
    main()
