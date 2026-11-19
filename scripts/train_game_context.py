"""Train and evaluate pregame game-total/pace model on chronological seasons."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from src.config import settings
from src.models.game_context import GameContextModel, historical_games
from src.storage.datasets import atomic_json, dataset_view


def score(model, frame):
    total, pace = model.predict(frame)
    total_base = (frame.home_pts_10 + frame.away_allowed_10 + frame.away_pts_10 + frame.home_allowed_10) / 2
    pace_base = (frame.home_poss_10 + frame.away_poss_10) / 2
    return {"games": len(frame), "total_mae_baseline": float(np.mean(abs(frame.target_total - total_base))),
            "total_mae_model": float(np.mean(abs(frame.target_total - total))),
            "pace_mae_baseline": float(np.mean(abs(frame.target_pace - pace_base))),
            "pace_mae_model": float(np.mean(abs(frame.target_pace - pace)))}


def main():
    view = dataset_view()
    logs = pd.concat([pd.read_parquet(path) for path in view.glob("team_gamelogs_*.parquet")], ignore_index=True)
    logs = logs.drop_duplicates(["game_id", "team_abbreviation"])
    games = historical_games(logs)
    dates = games.game_date_home
    train = games[dates.lt("2024-07-01")]
    select = games[dates.ge("2024-07-01") & dates.le("2024-12-19")]
    later = games[dates.gt("2024-12-19")]
    model = GameContextModel.fit(train)
    selection = score(model, select)
    heldout = {f"{year}-{str(year + 1)[-2:]}": score(model, part)
               for year, part in later.groupby(later.game_date_home.map(lambda value: value.year if value.month >= 7 else value.year - 1))}
    publish = selection["total_mae_model"] <= selection["total_mae_baseline"] and all(
        part["total_mae_model"] <= 1.01 * part["total_mae_baseline"] for part in heldout.values())
    folder = settings.DATA_DIR / "aux_models" / "game_context" / view.version
    report = {"snapshot": view.version, "train_games": len(train), "selection": selection,
              "heldout": heldout, "published": bool(publish),
              "targets": "Full-game total points and estimated possessions including OT"}
    atomic_json(folder / "evaluation.json", report)
    if publish:
        model.save(folder)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
