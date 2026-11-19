"""Evaluate lagged game-context estimates as additional PTS distribution inputs."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from scripts.train_extended_release import promotion_gate, score
from src.config import settings
from src.models.game_context import historical_games
from src.models.injury_ablation import enrich_dataset_with_injury_features
from src.models.selector import ModelBundle, ModelSelector
from src.storage.datasets import atomic_json, dataset_view


def main():
    view = dataset_view()
    logs = pd.concat([pd.read_parquet(p) for p in view.glob("team_gamelogs_*.parquet")], ignore_index=True)
    games = historical_games(logs.drop_duplicates(["game_id", "team_abbreviation"]))
    games["context_total"] = (games.home_pts_10 + games.away_allowed_10 + games.away_pts_10 + games.home_allowed_10) / 2
    games["context_pace"] = (games.home_poss_10 + games.away_poss_10) / 2
    games["context_home_points"] = (games.home_pts_10 + games.away_allowed_10) / 2
    games["context_away_points"] = (games.away_pts_10 + games.home_allowed_10) / 2
    data = enrich_dataset_with_injury_features(pd.read_parquet(view.path("features_all_seasons.parquet")))
    data = data.merge(games[["game_id", "team_abbreviation_home", "context_total", "context_pace",
                             "context_home_points", "context_away_points"]], on="game_id", how="left", validate="many_to_one")
    data["context_team_points"] = np.where(data.team_abbreviation.eq(data.team_abbreviation_home),
                                           data.context_home_points, data.context_away_points)
    played = data[data.target_min.gt(0)].copy()
    b0 = played[played.season.eq("2023-24")]
    b1all = played[played.season.eq("2024-25")]
    cutoff = sorted(pd.to_datetime(b1all.game_date).unique())[len(pd.to_datetime(b1all.game_date).unique()) // 3]
    b1 = b1all[pd.to_datetime(b1all.game_date).le(cutoff)]
    later = played[pd.to_datetime(played.game_date).gt(cutoff)]
    baseline = ModelBundle.load(Path(view.metadata["models_dir"]) / "bundle_pts")
    features = list(baseline.feature_schema) + ["context_total", "context_pace", "context_team_points"]
    reports = settings.REPORTS_DIR / "game_context_pts"
    candidates = settings.DATA_DIR / "aux_models" / "game_context" / view.version / "pts_candidates"
    if not (candidates / "bundle_pts" / "bundle_manifest.json").exists():
        ModelSelector("pts", candidates, reports).execute_selection_pipeline(b0, b1, features)
    candidate = ModelBundle.load(candidates / "bundle_pts")
    periods = {season: {"rows": len(part), "baseline": score(baseline, part, reports),
                        "candidate": score(candidate, part, reports)} for season, part in later.groupby("season")}
    gate = promotion_gate(periods)
    report = {"snapshot": view.version, "selection_end": str(pd.Timestamp(cutoff).date()),
              "features": features[-3:], "periods": periods, "gate": gate,
              "decision": "REVIEW_FOR_RELEASE" if gate["passed"] else "KEEP_ACTIVE_PTS"}
    atomic_json(reports / "comparison.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
