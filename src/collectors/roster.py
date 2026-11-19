"""Current membership evidence, separate from historical boxscore teams."""
from datetime import datetime, timezone

import pandas as pd
from nba_api.stats.endpoints import commonallplayers

from src.client import NBAClient


def fetch_current_roster(season: str, client: NBAClient, use_cache: bool = False):
    endpoint = client.execute(commonallplayers.CommonAllPlayers,
                              params={"season": season, "is_only_current_season": 1}, use_cache=use_cache)
    frame = endpoint.common_all_players.get_data_frame().rename(columns={
        "PERSON_ID": "player_id", "TEAM_ABBREVIATION": "team_abbreviation", "TEAM_ID": "team_id",
        "DISPLAY_FIRST_LAST": "player_name",
    })
    required = {"player_id", "team_abbreviation", "team_id"}
    if not required.issubset(frame):
        raise ValueError("Current roster response has no membership columns")
    frame = frame[(frame["team_id"] > 0) & frame["team_abbreviation"].ne("")].copy()
    if frame.empty or frame.player_id.duplicated().any():
        raise ValueError("Invalid current roster snapshot")
    frame["fetched_at"] = datetime.now(timezone.utc).isoformat()
    frame["season"] = season
    return frame


def membership_is_fresh(frame: pd.DataFrame, season: str) -> bool:
    if frame is None or frame.empty or not {"fetched_at", "season"}.issubset(frame):
        return False
    oldest = pd.to_datetime(frame["fetched_at"], utc=True, errors="coerce").min()
    age = (pd.Timestamp.now(tz="UTC") - oldest).total_seconds()
    # Series.all() returns a NumPy scalar, which cannot be serialized in
    # untyped API metadata by Pydantic. Keep the public result a Python bool.
    return bool(pd.notna(oldest) and 0 <= age <= 24 * 3600 and frame["season"].eq(season).all())
