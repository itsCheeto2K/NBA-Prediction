"""Pregame team matchup forecast from strictly preceding team box scores."""
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

METRICS = ("pts", "allowed", "poss")
FEATURES = [f"{side}_{metric}_{window}" for side in ("home", "away")
            for metric in METRICS for window in (5, 10)] + ["home_rest", "away_rest"]


def prepare_team_logs(logs):
    df = logs.copy()
    df["game_date"] = pd.to_datetime(df.game_date).dt.normalize()
    df["is_home"] = df.matchup.astype(str).str.contains("vs.", regex=False)
    df["poss"] = (df.fga + .44 * df.fta - df.oreb + df.tov).clip(lower=40)
    other = df[["game_id", "team_abbreviation", "pts"]].rename(columns={"team_abbreviation": "opponent", "pts": "allowed"})
    df = df.merge(other, on="game_id")
    df = df[df.team_abbreviation.ne(df.opponent)].copy()
    df = df.sort_values(["team_abbreviation", "game_date", "game_id"])
    grouped = df.groupby("team_abbreviation", sort=False)
    df["rest"] = grouped.game_date.diff().dt.days.sub(1).clip(lower=0).fillna(2)
    for metric in METRICS:
        for window in (5, 10):
            df[f"{metric}_{window}"] = grouped[metric].transform(
                lambda series: series.shift(1).rolling(window, min_periods=1).mean())
    return df


def historical_games(logs):
    frame = prepare_team_logs(logs)
    # Some source rows inconsistently label both sides as away; exclude those
    # games instead of guessing who hosted.
    unique_sides = frame.groupby("game_id").is_home.agg(["sum", "count"])
    valid_ids = unique_sides.index[(unique_sides["sum"] == 1) & (unique_sides["count"] == 2)]
    frame = frame[frame.game_id.isin(valid_ids)]
    home = frame[frame.is_home].copy()
    away = frame[~frame.is_home].copy()
    columns = [f"{metric}_{window}" for metric in METRICS for window in (5, 10)] + ["rest"]
    base = ["game_id", "game_date", "team_abbreviation", "opponent", "pts", "poss"]
    home = home[base + columns].rename(columns={c: "home_" + c for c in columns})
    away = away[base + columns].rename(columns={c: "away_" + c for c in columns})
    games = home.merge(away, on="game_id", suffixes=("_home", "_away"), validate="one_to_one")
    games = games[games.team_abbreviation_home.eq(games.opponent_away) & games.team_abbreviation_away.eq(games.opponent_home)]
    games["target_total"] = games.pts_home + games.pts_away
    games["target_pace"] = (games.poss_home + games.poss_away) / 2
    return games


def upcoming_game(logs, home_team, away_team, target_date):
    cutoff = pd.Timestamp(str(target_date)[:10]).normalize()
    prior = logs[pd.to_datetime(logs.game_date).dt.normalize().lt(cutoff)]
    if prior.empty:
        return None
    profile = prepare_team_logs(prior)
    values = {}
    for side, team in (("home", home_team), ("away", away_team)):
        rows = profile[profile.team_abbreviation.eq(team)]
        if len(rows) < 5:
            return None
        last = rows.iloc[-1]
        values[f"{side}_rest"] = max(0, (cutoff - last.game_date).days - 1)
        for metric in METRICS:
            for window in (5, 10):
                values[f"{side}_{metric}_{window}"] = float(rows[metric].tail(window).mean())
    return pd.DataFrame([values])


def baseline_projection(frame):
    row = frame.iloc[0]
    home = (row.home_pts_10 + row.away_allowed_10) / 2
    away = (row.away_pts_10 + row.home_allowed_10) / 2
    return {"status": "estimated", "game_total": round(float(home + away), 1),
            "pace": round(float((row.home_poss_10 + row.away_poss_10) / 2), 1),
            "method": "Pregame L10 Team Baseline", "includes_overtime": True}


class GameContextModel:
    def __init__(self, total, pace, metadata):
        self.total, self.pace, self.metadata = total, pace, metadata

    @classmethod
    def fit(cls, frame):
        x = frame[FEATURES].fillna(frame[FEATURES].median()).fillna(0)
        params = dict(n_estimators=130, num_leaves=8, min_child_samples=60,
                      learning_rate=.035, random_state=20261117, n_jobs=4, verbosity=-1)
        total = lgb.LGBMRegressor(**params).fit(x, frame.target_total)
        pace = lgb.LGBMRegressor(**params).fit(x, frame.target_pace)
        return cls(total, pace, {"recipe": "game_context_v1", "features": FEATURES,
                                 "training_end": str(frame.game_date_home.max().date())})

    def predict(self, frame):
        x = frame.reindex(columns=FEATURES).fillna(0)
        return self.total.predict(x), self.pace.predict(x)

    def save(self, folder):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        for name in ("total", "pace"):
            model = getattr(self, name)
            (model.booster_ if hasattr(model, "booster_") else model).save_model(str(folder / f"{name}.txt"))
        (folder / "manifest.json").write_text(json.dumps(self.metadata, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, folder):
        folder = Path(folder)
        return cls(*(lgb.Booster(model_file=str(folder / f"{name}.txt")) for name in ("total", "pace")),
                   json.loads((folder / "manifest.json").read_text(encoding="utf-8")))
