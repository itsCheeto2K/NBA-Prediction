"""Fit a chronological FGA forecast; publish an auxiliary model only if held-out MAE improves."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from src.config import settings
from src.models.shot_volume import ShotVolumeModel, baseline, matrix
from src.storage.datasets import atomic_json, dataset_view


def score(model, frame):
    y = frame.fga.to_numpy(float)
    return {"rows": len(frame), "baseline_mae": float(np.mean(np.abs(y - baseline(frame)))),
            "model_mae": float(np.mean(np.abs(y - model.predict(frame))))}


def main():
    view = dataset_view()
    data = pd.read_parquet(view.path("features_all_seasons.parquet"))
    data = data[data.target_min.gt(0) & data.fga.notna() & data.fga.ge(0)].copy()
    data["game_date_dt"] = pd.to_datetime(data.game_date)
    train = data[data.season.eq("2023-24")]
    selection_season = data[data.season.eq("2024-25")]
    cutoff = sorted(selection_season.game_date_dt.unique())[len(selection_season.game_date_dt.unique()) // 3]
    selection = selection_season[selection_season.game_date_dt.le(cutoff)]
    heldout = data[data.season.isin(("2025-26", "2026-27"))]
    model = ShotVolumeModel.fit(train)
    # Select shrinkage on the early 2024-25 window only; later seasons stay untouched.
    model.metadata["model_weight"] = min((.25, .5, .75, 1.),
        key=lambda w: float(np.mean(np.abs(selection.fga.to_numpy(float) -
            (w * model.booster.predict(matrix(selection))
             + (1 - w) * baseline(selection))))))
    selection_score = score(model, selection)
    heldout_scores = {season: score(model, part) for season, part in heldout.groupby("season")}
    # A small in-sample selection gain alone does not justify publishing.
    passed = (selection_score["model_mae"] < .995 * selection_score["baseline_mae"] and
              all(item["model_mae"] < .995 * item["baseline_mae"] for item in heldout_scores.values()))
    report = {"dataset_version": view.version, "training_end": model.metadata["training_end"],
              "model_weight": model.metadata["model_weight"],
              "selection_end": str(pd.Timestamp(cutoff).date()), "selection": selection_score,
              "heldout": heldout_scores, "published": bool(passed),
              "semantics": "FGA conditional on entering the game; no estimated betting ROI"}
    folder = settings.DATA_DIR / "aux_models" / "shot_volume" / view.version
    atomic_json(folder / "evaluation.json", report)
    if passed:
        model.save(folder)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
