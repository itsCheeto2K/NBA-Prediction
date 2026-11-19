"""Compare current PTS bundle with 48 FGA-augmented PTS recipes on later seasons."""
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from scripts.train_extended_release import promotion_gate, score
from src.config import settings
from src.models.selector import ModelBundle, ModelSelector
from src.models.injury_ablation import enrich_dataset_with_injury_features
from src.models.shot_volume import ShotVolumeModel, baseline, matrix
from src.storage.datasets import atomic_json, dataset_view


def shot_oof(frame, model, block_dates=30, warmup_dates=40):
    """Expanding shot fits on training dates; no row uses its own FGA as input."""
    dates = pd.to_datetime(frame.game_date).dt.normalize()
    output = pd.Series(baseline(frame), index=frame.index, dtype=float)
    training_dates = sorted(dates[dates.le(pd.Timestamp(model.metadata["training_end"]))].unique())
    for start in range(warmup_dates, len(training_dates), block_dates):
        block = training_dates[start:start + block_dates]
        fit = frame[dates.lt(block[0]) & frame.target_min.gt(0)]
        fold = ShotVolumeModel.fit(fit)
        fold.metadata["model_weight"] = model.metadata["model_weight"]
        mask = dates.isin(block)
        output.loc[mask] = fold.predict(frame.loc[mask])
    later = dates.gt(pd.Timestamp(model.metadata["training_end"]))
    output.loc[later] = model.predict(frame.loc[later])
    return output


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    view = dataset_view()
    folder = settings.DATA_DIR / "aux_models" / "shot_volume" / view.version
    shot = ShotVolumeModel.load(folder)
    previous = ModelBundle.load(Path(view.metadata["models_dir"]) / "bundle_pts")
    data = enrich_dataset_with_injury_features(pd.read_parquet(view.path("features_all_seasons.parquet")))
    played = data[data.target_min.gt(0)].copy()
    played["shot_expected_fga"] = shot_oof(played, shot)
    b0 = played[played.season.eq("2023-24")]
    b1all = played[played.season.eq("2024-25")]
    cutoff = sorted(pd.to_datetime(b1all.game_date).unique())[len(pd.to_datetime(b1all.game_date).unique()) // 3]
    b1 = b1all[pd.to_datetime(b1all.game_date).le(cutoff)]
    later = played[pd.to_datetime(played.game_date).gt(cutoff)]
    reports = settings.REPORTS_DIR / "shot_volume_pts"
    candidates = folder / "pts_candidates"
    features = list(previous.feature_schema) + ["shot_expected_fga"]
    if not (candidates / "bundle_pts" / "bundle_manifest.json").exists():
        ModelSelector("pts", candidates, reports).execute_selection_pipeline(b0, b1, features)
    candidate = ModelBundle.load(candidates / "bundle_pts")
    periods = {}
    for season, part in later.groupby("season"):
        periods[season] = {"rows": len(part), "baseline": score(previous, part, reports),
                           "candidate": score(candidate, part, reports)}
    gate = promotion_gate(periods)
    report = {"snapshot": view.version, "shot_model": shot.metadata, "feature": "shot_expected_fga",
              "recipes": 48, "selection_end": str(pd.Timestamp(cutoff).date()), "periods": periods,
              "gate": gate, "decision": "PROMOTE_REQUIRES_RELEASE" if gate["passed"] else "KEEP_ACTIVE_PTS"}
    atomic_json(reports / "comparison.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
