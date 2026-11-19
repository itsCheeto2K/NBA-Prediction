"""Display a conditional minutes forecast."""
import numpy as np
import pandas as pd

from src.collectors.injuries import normalize_text
from src.features.participation import normalize_injury_status
from src.models.playing_time import PROJECTION_FEATURES


def project_playing_time(model, row, target_date, team_injuries=(), stale_injuries=False):
    missing = {c: np.nan for c in PROJECTION_FEATURES}
    if model is None or row is None:
        return None, missing
    cutoff = pd.Timestamp(str(target_date)[:10]).normalize()
    last_fit = max(model.metadata.get("training_end", "1900-01-01"), model.metadata.get("calibration_end", "1900-01-01"))
    if cutoff <= pd.Timestamp(last_fit):
        return {"status": "unavailable", "reason": "Forecast requires a model fitted before the target game"}, missing
    history_date = pd.to_datetime(str(row.get("last_game_date", row.get("game_date", "")))[:10], errors="coerce")
    if pd.notna(history_date) and history_date >= cutoff:
        return {"status": "unavailable", "reason": "Historical forecast requires pregame history"}, missing
    own = pd.DataFrame([row])
    if float(row.get("n_games_history", 0)) < 1:
        return {"status": "unavailable", "reason": "No prior played games"}, missing
    mu, lo, hi = [float(x[0]) for x in model.predict(own)]
    features = model.features(own).iloc[0].to_dict()
    flags = []
    if float(row.get("n_games_history", 0)) < 5:
        flags.append("Limited History")
    if float(row.get("days_since_last_appearance", 0)) >= 14:
        flags.append("Return From Absence")
    if float(row.get("min_roll_std_5", 0)) >= 6:
        flags.append("Variable Rotation")
    if stale_injuries:
        flags.append("Stale Injury Report")
    result = {"status": "estimated", "expected_minutes": round(mu, 1),
              "interval_80": {"lower": round(lo, 1), "upper": round(hi, 1), "coverage": .8},
              "conditional_on_playing": True, "includes_overtime": True, "risk_flags": flags,
              "projected_for": str(cutoff.date()), "history_as_of": str(row.get("last_game_date", row.get("game_date", "")))[:10],
              "minutes_restriction_confirmed": None, "model_version": model.metadata.get("recipe_version")}
    # A current injury report can flag uncertainty; minutes remain conditional on playing.
    injury_status = {normalize_text(x.get("player_name", "")): normalize_injury_status(x.get("status", ""))
                     for x in team_injuries} if not stale_injuries else {}
    own_status = injury_status.get(normalize_text(row.get("player_name", "")))
    if own_status == "out":
        flags.append("Reported Out")
        return result, features
    if own_status in ("questionable", "doubtful"):
        flags.append("Availability Uncertain")
    return result, features
