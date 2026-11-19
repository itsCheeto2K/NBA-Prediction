"""Player state for the next game, using the training rolling/rate recipes."""
import numpy as np
import pandas as pd

from src.features.rolling import compute_player_rolling_features
from src.features.shrinkage import compute_gamma_poisson_rate
from src.features.extended_stats import RAW_STATS, compute_extended_stats


def latest_player_states(features: pd.DataFrame) -> pd.DataFrame:
    if features.empty:
        return features.copy()
    history = features.sort_values(["player_id", "game_date", "game_id"]).copy()
    cols = [c for c in ["player_id", "game_id", "game_date", "season", *RAW_STATS] if c in history]
    extended_past = history[cols].copy()
    history = history[history["min"] > 0].copy()
    if history.empty:
        return history
    latest = history.groupby("player_id", sort=False).tail(1).copy()
    past = history[cols].copy()
    target = latest[cols].copy()
    target["game_id"] = "9999999999"
    cutoff = pd.to_datetime(history["game_date"]).max() + pd.Timedelta(days=1)
    target["game_date"] = cutoff.isoformat()
    if "season" in history:
        # A returning player may not yet have an appearance in the active season.
        # Do not carry their previous season-to-date totals into the new season.
        latest_date = pd.to_datetime(history["game_date"]).max()
        target["season"] = history.loc[pd.to_datetime(history["game_date"]).eq(latest_date), "season"].iloc[-1]
    for col in RAW_STATS:
        if col in target:
            target[col] = np.nan
    past["_target"] = False
    target["_target"] = True
    frame = pd.concat([past, target], ignore_index=True)
    frame["game_date"] = pd.to_datetime(frame["game_date"], format="mixed")
    frame = compute_player_rolling_features(frame)
    for stat in ["pts", "reb", "ast"]:
        frame = compute_gamma_poisson_rate(frame, stat=stat)
    states = frame[frame["_target"]].set_index("player_id")
    # Preserve explicit nonplayed rows for the extended recipe's recorded-game
    # windows, exactly as in training; their box scores remain unknown, not zero.
    extended_past["_target"] = False
    extended_frame = pd.concat([extended_past, target], ignore_index=True)
    extended_frame["game_date"] = pd.to_datetime(extended_frame["game_date"], format="mixed")
    extended_frame = compute_extended_stats(extended_frame)
    extended_states = extended_frame[extended_frame["_target"]].set_index("player_id")
    extended_cols = [c for c in extended_states if c.startswith("ext_")]
    states = pd.concat([states.drop(columns=extended_cols, errors="ignore"), extended_states[extended_cols]], axis=1)
    latest = latest.set_index("player_id")
    updated = [col for col in states if col.startswith("ext_") or col == "n_games_history" or any(
        token in col for token in ("_roll_", "_decay_mean", "_trend_", "_rate_shrinkage", "_n_eff", "_exposure"))]
    latest = pd.concat([latest.drop(columns=updated, errors="ignore"), states[updated].reindex(latest.index)], axis=1)
    latest["last_game_date"] = latest["game_date"]
    return latest.reset_index()


def target_workload(row: dict, history: pd.DataFrame, team_logs: pd.DataFrame, cutoff) -> dict:
    """Update time-dependent inputs before prediction and response rendering."""
    row = dict(row)
    date = pd.Timestamp(cutoff).normalize()
    p = history[history["player_id"] == row["player_id"]].copy()
    p["_date"] = pd.to_datetime(p["game_date"], format="mixed")
    p = p[(p["_date"] < date) & (p["min"] > 0)].sort_values("_date")
    row["player_minutes_last7days"] = round(float(p.loc[p["_date"] >= date - pd.Timedelta(days=7), "min"].sum()), 1)
    row["player_minutes_prev_game"] = float(p.iloc[-1]["min"]) if not p.empty else 0.0
    row["player_minutes_sum_prev3"] = round(float(p["min"].tail(3).sum()), 1)
    if not team_logs.empty:
        dates = pd.to_datetime(team_logs["game_date"], format="mixed")
        past = team_logs.loc[dates < date].copy()
        past["_date"] = dates[dates < date]
        for team_key, prefix in [("team_abbreviation", "team"), ("opponent_abbr", "opp")]:
            games = past[past["team_abbreviation"] == row.get(team_key)].sort_values("_date")
            row[prefix + "_3in4"] = int((games["_date"] >= date - pd.Timedelta(days=3)).sum() >= 2)
            row[prefix + "_4in6"] = int((games["_date"] >= date - pd.Timedelta(days=5)).sum() >= 3)
            if prefix == "team":
                played = not games.empty and not p.empty and games.iloc[-1]["game_id"] == p.iloc[-1]["game_id"]
                row["player_played_previous_team_game"] = int(played)
                row["team_b2b_but_player_rested"] = int(bool(row.get("team_b2b")) and not played)
    return row
