"""Pregame playing-time model; minutes are conditional on entering the game.

Raw quantiles are available as features; the separately calibrated interval
is for current forecast display.
"""
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from src.features.role_changes import eligible_role_features

FEATURES = ["min_roll_mean_5", "min_roll_mean_10", "min_roll_mean_20", "min_roll_std_5",
            "min_roll_std_10", "min_roll_std_20", "min_trend_5_20", "min_decay_mean",
            "player_minutes_prev_game", "player_minutes_sum_prev3", "player_minutes_last7days",
            "days_since_last_appearance", "n_games_history", "team_b2b", "team_rest_days",
            "team_3in4", "team_4in6", "is_home"]
PROJECTION_FEATURES = ["pt_expected_minutes", "pt_lower_minutes", "pt_upper_minutes", "pt_interval_width"]
RECIPE = "playing_time_v1"


def matrix(frame, columns=None):
    return frame.reindex(columns=columns or FEATURES).apply(pd.to_numeric, errors="coerce").fillna(0.)


def baseline(frame):
    return pd.to_numeric(frame.get("min_roll_mean_5", pd.Series(np.nan, index=frame.index)), errors="coerce").fillna(25.).clip(lower=0).to_numpy()


class PlayingTimeModel:
    def __init__(self, mean=None, lower=None, upper=None, metadata=None):
        self.mean, self.lower, self.upper = mean, lower, upper
        self.metadata = metadata or {}

    @classmethod
    def fit(cls, frame):
        columns = FEATURES + eligible_role_features(frame)
        x = matrix(frame, columns)
        y = frame["target_min"].to_numpy(float)
        params = dict(n_estimators=160, num_leaves=15, min_child_samples=60,
                      learning_rate=.04, random_state=20261117, n_jobs=4, verbosity=-1)
        mean = lgb.LGBMRegressor(objective="regression", **params).fit(x, y)
        lower = lgb.LGBMRegressor(objective="quantile", alpha=.1, **params).fit(x, y)
        upper = lgb.LGBMRegressor(objective="quantile", alpha=.9, **params).fit(x, y)
        return cls(mean, lower, upper, {"recipe_version": RECIPE,
                   "training_end": str(pd.to_datetime(frame.game_date).max().date()),
                   "mean_kind": "lgbm", "interval_offset": 0., "features": columns})

    def predict(self, frame, calibrated=True):
        x = matrix(frame, self.metadata.get("features", FEATURES))
        if self.metadata.get("mean_kind") == "rolling_baseline" or self.mean is None:
            mu = baseline(frame)
        else:
            mu = np.maximum(self.mean.predict(x), 0.)
        if self.lower is None:
            sd = pd.to_numeric(frame.get("min_roll_std_5", pd.Series(6., index=frame.index)), errors="coerce").fillna(6.).clip(lower=2).to_numpy()
            lo, hi = mu - 1.28155 * sd, mu + 1.28155 * sd
        else:
            a, b = self.lower.predict(x), self.upper.predict(x)
            lo, hi = np.minimum(np.minimum(a, b), mu), np.maximum(np.maximum(a, b), mu)
        offset = self.metadata.get("interval_offset", 0.) if calibrated else 0.
        return mu, np.maximum(0., lo - offset), np.maximum(mu, hi + offset)

    def features(self, frame):
        mu, lo, hi = self.predict(frame, calibrated=False)
        return pd.DataFrame(dict(zip(PROJECTION_FEATURES, (mu, lo, hi, hi - lo))), index=frame.index)

    def calibrate(self, frame):
        _, lo, hi = self.predict(frame, calibrated=False)
        y = frame.target_min.to_numpy(float)
        scores = np.maximum(lo - y, y - hi)
        level = min(1., np.ceil((len(y) + 1) * .8) / len(y))
        self.metadata.update(interval_offset=max(0., float(np.quantile(scores, level, method="higher"))),
                             calibration_end=str(pd.to_datetime(frame.game_date).max().date()),
                             interval_target_coverage=.8)

    def save(self, folder):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        for name in ("mean", "lower", "upper"):
            model = getattr(self, name)
            if model is not None:
                booster = model.booster_ if hasattr(model, "booster_") else model
                booster.save_model(str(folder / f"{name}.txt"))
        (folder / "manifest.json").write_text(json.dumps(self.metadata, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, folder):
        folder = Path(folder)
        metadata = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        models = [lgb.Booster(model_file=str(folder / f"{name}.txt")) if (folder / f"{name}.txt").exists() else None
                  for name in ("mean", "lower", "upper")]
        return cls(*models, metadata=metadata)


def historical_projection_features(frame, final_model, train_end, min_warmup_dates=40, block_dates=30):
    """Expanding chronological fits for training rows, frozen model thereafter.

    The first warmup dates use only lagged rolling baselines. A historical row
    never receives a projection from a model fitted on its own outcome or later.
    Calibration learned after train_end is never used as a historical feature.
    """
    dates = pd.to_datetime(frame.game_date).dt.normalize()
    end = pd.Timestamp(train_end)
    result = PlayingTimeModel().features(frame)
    training_dates = sorted(dates[dates <= end].unique())
    for start in range(min_warmup_dates, len(training_dates), block_dates):
        block = training_dates[start:start + block_dates]
        fit_rows = frame[(dates < block[0]) & (frame.target_min > 0)]
        model = PlayingTimeModel.fit(fit_rows)
        model.metadata["mean_kind"] = final_model.metadata.get("mean_kind", "lgbm")
        mask = dates.isin(block)
        result.loc[mask] = model.features(frame.loc[mask]).to_numpy()
    after = dates > end
    if after.any():
        result.loc[after] = final_model.features(frame.loc[after]).to_numpy()
    return result
