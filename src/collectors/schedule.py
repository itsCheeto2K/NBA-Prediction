import pandas as pd
from typing import Optional, Dict, Any
from nba_api.stats.endpoints import scheduleleaguev2
from src.client import NBAClient

def normalize_schedule_df(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize raw ScheduleLeagueV2 dataset into clean standard format."""
    if df.empty:
        return pd.DataFrame()
    
    clean_df = df.copy()
    
    # Standardize column mapping (handling both camelCase, nested, and UPPERCASE variants)
    col_map = {
        "gameId": "game_id",
        "GAME_ID": "game_id",
        "seasonYear": "season",
        "SEASON_YEAR": "season",
        "gameDateEst": "game_date_est",
        "GAME_DATE_EST": "game_date_est",
        "gameDateTimeUTC": "game_time_utc",
        "GAME_DATE_TIME_UTC": "game_time_utc",
        "homeTeamId": "home_team_id",
        "HOME_TEAM_ID": "home_team_id",
        "awayTeamId": "away_team_id",
        "AWAY_TEAM_ID": "away_team_id",
        "homeTeam_teamId": "home_team_id",
        "awayTeam_teamId": "away_team_id",
        "homeTeamTricode": "home_team_tricode",
        "HOME_TEAM_TRICODE": "home_team_tricode",
        "awayTeamTricode": "away_team_tricode",
        "AWAY_TEAM_TRICODE": "away_team_tricode",
        "homeTeam_teamTricode": "home_team_tricode",
        "awayTeam_teamTricode": "away_team_tricode",
        "gameStatus": "game_status",
        "GAME_STATUS": "game_status",
        "gameStatusText": "game_status_text",
        "GAME_STATUS_TEXT": "game_status_text",
    }
    
    clean_df = clean_df.rename(columns={k: v for k, v in col_map.items() if k in clean_df.columns})
    
    # Enforce 10-char string game_id with leading zeros (e.g. 0022400061)
    if "game_id" in clean_df.columns:
        clean_df["game_id"] = clean_df["game_id"].astype(str).str.zfill(10)
        
    return clean_df

def fetch_schedule(season: str, client: Optional[NBAClient] = None, use_cache: bool = True) -> pd.DataFrame:
    """Fetch league schedule for a given season (e.g. '2026-27')."""
    client = client or NBAClient()
    endpoint = client.execute(
        scheduleleaguev2.ScheduleLeagueV2,
        params={"season": season},
        use_cache=use_cache,
    )
    raw_df = endpoint.season_games.get_data_frame()
    return normalize_schedule_df(raw_df)

def get_next_game_for_team(schedule_df: pd.DataFrame, team_abbr: str) -> Optional[Dict[str, Any]]:
    """Find the next upcoming game for a given team abbreviation."""
    if schedule_df is None or schedule_df.empty or not team_abbr:
        return None

    abbr = team_abbr.upper().strip()
    home_col = None
    for cand in ["home_team_tricode", "homeTeam_teamTricode", "homeTeamTricode"]:
        if cand in schedule_df.columns:
            home_col = cand
            break

    away_col = None
    for cand in ["away_team_tricode", "awayTeam_teamTricode", "awayTeamTricode"]:
        if cand in schedule_df.columns:
            away_col = cand
            break

    if not home_col or not away_col:
        return None

    matches = schedule_df[(schedule_df[home_col] == abbr) | (schedule_df[away_col] == abbr)]
    if matches.empty:
        return None

    # Filter for non-final games if possible
    status_col = "game_status_text" if "game_status_text" in matches.columns else "gameStatusText"
    if status_col in matches.columns:
        upcoming = matches[~matches[status_col].astype(str).str.upper().str.contains("FINAL", regex=True)]
        if not upcoming.empty:
            row = upcoming.iloc[0]
            return {
                "game_id": str(row.get("game_id", "")),
                "game_date": str(row.get("game_date_est", "")),
                "home_team_tricode": str(row.get(home_col, "")),
                "away_team_tricode": str(row.get(away_col, "")),
                "game_time_et": str(row.get("game_time_utc", "")),
            }

    row = matches.iloc[-1]
    return {
        "game_id": str(row.get("game_id", "")),
        "game_date": str(row.get("game_date_est", "")),
        "home_team_tricode": str(row.get(home_col, "")),
        "away_team_tricode": str(row.get(away_col, "")),
        "game_time_et": str(row.get("game_time_utc", "")),
    }
