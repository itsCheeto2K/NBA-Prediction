"""Fetch the two newly enabled historical NBA seasons into local parquet.

Run from the project root with network access available:
    python scripts/backfill_history.py

This writes season-scoped parquet files and, after a complete audit, publishes
a rebuilt feature snapshot. It does not change the active model. Run
train_extended_release.py after a complete backfill to select a model.
"""
import json
import logging
import sys
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.pipeline.backfill import BackfillPipeline
from src.config import settings
from src.collectors.sync import _SYNC_LOCK
from src.features.builder import build_feature_dataset
from src.storage.datasets import atomic_json, dataset_view, prepare_snapshot


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    pipeline = BackfillPipeline()
    summary = {}
    failed = False
    for season in ("2021-22", "2022-23"):
        result = pipeline.run_season_p0(season)
        summary[season] = result
        audit = result.get("completeness_audit", {})
        failed |= audit.get("status") != "COMPLETE"
    print(json.dumps(summary, indent=2, default=str))
    if failed:
        logging.error("Historical backfill is incomplete; do not retrain/publish yet.")
        return 1

    # Publish immutable raw and feature data together so dataset_view() and
    # later release training can actually see the newly fetched seasons.
    run_id = "history_" + uuid.uuid4().hex[:10]
    if not _SYNC_LOCK.acquire(run_id):
        raise RuntimeError("Another sync/release owns the dataset lease")
    token = _SYNC_LOCK.get_fencing_token(run_id)
    try:
        view = dataset_view()
        player_paths = list(view.glob("player_gamelogs_*.parquet"))
        team_paths = list(view.glob("team_gamelogs_*.parquet"))
        schedule_paths = list(view.glob("schedule_*.parquet"))
        for season in ("2021-22", "2022-23"):
            player_paths.append(settings.PARQUET_DIR / f"player_gamelogs_{season}.parquet")
            team_paths.append(settings.PARQUET_DIR / f"team_gamelogs_{season}.parquet")
            schedule_paths.append(settings.PARQUET_DIR / f"schedule_{season}.parquet")
        import pandas as pd

        players = pd.concat([pd.read_parquet(path) for path in player_paths], ignore_index=True)
        teams = pd.concat([pd.read_parquet(path) for path in team_paths], ignore_index=True)
        features = build_feature_dataset(players, teams)
        with TemporaryDirectory(prefix="nba_history_stage_", dir=settings.DATA_DIR) as temp_dir:
            stage = Path(temp_dir)
            for path in set(schedule_paths + player_paths + team_paths):
                if path.exists():
                    (stage / path.name).write_bytes(path.read_bytes())
            features.to_parquet(stage / "features_all_seasons.parquet", index=False)
            for season, frame in features.groupby("season"):
                frame.to_parquet(stage / f"features_{season}.parquet", index=False)
            payload = prepare_snapshot(stage, run_id, view, settings.DATA_DIR)
            payload["historical_backfill"] = ["2021-22", "2022-23"]
            with _SYNC_LOCK.commit_guard(run_id, token):
                atomic_json(settings.DATA_DIR / "snapshots" / "manifest.json", payload)
    finally:
        _SYNC_LOCK.release(run_id)
    logging.info("Both historical seasons passed the completeness audit.")
    logging.info("Published history and rebuilt features as snapshot %s; run model training next.", run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
