"""Pregame field-goal attempts forecast, conditional on playing."""
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

FEATURES = ["fga_roll_mean_5", "fga_roll_mean_10", "fga_roll_mean_20", "fga_roll_std_5",
            "fga_roll_std_10", "fga_roll_std_20", "fga_trend_5_20", "fga_decay_mean",
            "min_roll_mean_5", "min_roll_mean_10", "min_roll_mean_20", "min_roll_std_5",
            "pts_roll_mean_5", "pts_roll_mean_10", "fta_roll_mean_5", "fg3a_roll_mean_5",
            "n_games_history", "days_since_last_appearance", "team_b2b", "team_rest_days", "is_home"]


def matrix(frame):
    return frame.reindex(columns=FEATURES).apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)


def baseline(frame):
    return pd.to_numeric(frame["fga_roll_mean_5"], errors="coerce").fillna(0).clip(lower=0).to_numpy()


class ShotVolumeModel:
    def __init__(self, booster, metadata):
        self.booster, self.metadata = booster, metadata

    @classmethod
    def fit(cls, frame):
        model = lgb.LGBMRegressor(objective="poisson", n_estimators=220, num_leaves=15,
                                  min_child_samples=80, learning_rate=.035, random_state=20261117,
                                  n_jobs=4, verbosity=-1)
        model.fit(matrix(frame), frame.fga.to_numpy(float))
        return cls(model, {"recipe": "shot_volume_v1", "features": FEATURES,
                           "training_end": str(pd.to_datetime(frame.game_date).max().date())})

    def predict(self, frame):
        weight = self.metadata.get("model_weight", 1.)
        return np.maximum(0, weight * self.booster.predict(matrix(frame)) + (1 - weight) * baseline(frame))

    def save(self, folder):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        booster = self.booster.booster_ if hasattr(self.booster, "booster_") else self.booster
        booster.save_model(str(folder / "mean.txt"))
        (folder / "manifest.json").write_text(json.dumps(self.metadata, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, folder):
        folder = Path(folder)
        return cls(lgb.Booster(model_file=str(folder / "mean.txt")),
                   json.loads((folder / "manifest.json").read_text(encoding="utf-8")))
