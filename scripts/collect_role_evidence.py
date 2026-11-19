"""Collect explicit DNP/played evidence from free NBA boxscores, no paid key.

Run outside the agent sandbox if network connections are restricted:
python scripts/collect_role_evidence.py --max-games 30 --lookback-days 90
Use --cache-only to inspect local evidence without network calls.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from src.collectors.role_evidence import collect_recent_participation, load_participation, load_pregame_snapshots, collection_progress
from src.features.role_changes import ROLE_FEATURES, archived_role_features, eligible_role_features
from src.storage.datasets import atomic_json, dataset_view
from src.config import settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-games", type=int, default=5)
    parser.add_argument("--lookback-days", type=int, default=60)
    parser.add_argument("--all-history", action="store_true", help="resume across every completed game in the feature catalog")
    parser.add_argument("--until-complete", action="store_true", help="keep requesting batches until all games are archived")
    parser.add_argument("--cache-only", action="store_true")
    args = parser.parse_args()
    if args.max_games < 1 or (args.lookback_days < 1 and not args.all_history):
        parser.error("limits must be positive")
    view = dataset_view()
    history = pd.read_parquet(view.path("features_all_seasons.parquet"))
    collected = {"status": "CACHE_ONLY", "collected_games": 0}
    if not args.cache_only:
        lookback = None if args.all_history else args.lookback_days
        while True:
            collected = collect_recent_participation(history, args.max_games, lookback)
            if not args.until_complete or collected.get("status") in ("COMPLETE", "UNAVAILABLE", "BUSY", "WAITING_RETRY", "STOPPED"):
                break
            if collected.get("collected_games", 0) == 0:
                break
        collected["progress"] = collection_progress(history, lookback)
    participation = load_participation(history)
    snapshots = load_pregame_snapshots()
    roles = archived_role_features(history, snapshots, participation)
    training = history.season.eq("2023-24")
    validation = history.season.eq("2024-25")
    report = {"collection": collected, "explicit_participation_records": len(participation),
              "explicit_dnp_records": int(participation.state.eq("did_not_play").sum()) if not participation.empty else 0,
              "pregame_snapshots": len(snapshots), "historical_rows_with_role_evidence": int(roles.role_out_count.notna().sum()),
              "eligible_training_features": eligible_role_features(roles[training]),
              "eligible_validation_features": eligible_role_features(roles[validation], min_rows=50, min_out_rows=10),
              "candidate_features": ROLE_FEATURES, "active_models_changed": False}
    report["training_status"] = "EVIDENCE_AVAILABLE_REQUIRES_TEMPORAL_EVALUATION" if report["eligible_training_features"] and report["eligible_validation_features"] else "NOT_TRAINED_INSUFFICIENT_ARCHIVED_PREGAME_EVIDENCE"
    path = settings.REPORTS_DIR / "role_evidence_2026-11-17.json"
    atomic_json(path, report)
    print(json.dumps(report, ensure_ascii=True))
    return 1 if collected["status"] in ("UNAVAILABLE", "INCOMPLETE") else 0


if __name__ == "__main__":
    raise SystemExit(main())
