import re
import pandas as pd
from typing import Any, Optional, Tuple
from nba_api.stats.endpoints import boxscoretraditionalv3, boxscoreadvancedv3
from src.client import NBAClient

def parse_iso_duration_to_seconds(val: Any) -> Optional[float]:
    """
    Parse ISO 8601 duration (e.g. 'PT34M25.00S') or 'MM:SS' into exact unrounded float seconds (§2.1).
    Example: 'PT36M22.00S' -> 36 * 60 + 22.0 = 2182.0 seconds.
    """
    if val is None or pd.isna(val):
        return None
    val_str = str(val).strip()
    if not val_str or val_str.upper() in ("DNP", "N/A", "NONE", "NULL"):
        return None
        
    # Check for ISO 8601 duration: PT36M22.00S or PT36M22S
    iso_match = re.match(r"PT(?:(\d+)M)?(?:([\d.]+)S)?", val_str)
    if iso_match:
        m_str, s_str = iso_match.groups()
        minutes = float(m_str) if m_str else 0.0
        seconds = float(s_str) if s_str else 0.0
        return float(minutes * 60.0 + seconds)
        
    # Check for MM:SS
    if ":" in val_str:
        parts = val_str.split(":")
        try:
            minutes = float(parts[0])
            seconds = float(parts[1]) if len(parts) > 1 else 0.0
            return float(minutes * 60.0 + seconds)
        except ValueError:
            return None
            
    try:
        # If float already (assumed in minutes if small, or seconds if large?)
        # Standard convention: raw float in minutes
        num = float(val_str)
        return float(num * 60.0)
    except ValueError:
        return None

def parse_iso_duration_to_minutes(val: Any) -> Optional[float]:
    """
    Parse ISO 8601 duration or 'MM:SS' into exact unrounded float minutes (§2.1).
    Never round to 2 or 3 decimals before model features or training.
    Example: 'PT36M22.00S' -> 36 + 22.0 / 60.0 = 36.36666666666667
    """
    secs = parse_iso_duration_to_seconds(val)
    if secs is None:
        return None
    return float(secs / 60.0)

def format_minutes_display(val: Optional[float]) -> str:
    """Format minutes for UI/CLI presentation only, e.g. '36.37m' (§2.1)."""
    if val is None or pd.isna(val):
        return "N/A"
    return f"{val:.2f}m"

def normalize_boxscore_traditional_v3(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize BoxScoreTraditionalV3 player_stats into standardized schema (§2.1, §3).
    Preserves exact unrounded minutes and seconds, and rigorously distinguishes
    DNP vs played=1 with 0 points vs played=1 with rounded 0 minutes.
    """
    if df.empty:
        return pd.DataFrame()
        
    clean_df = df.copy()
    col_map = {
        "gameId": "game_id",
        "teamId": "team_id",
        "teamCity": "team_city",
        "teamName": "team_name",
        "teamTricode": "team_abbreviation",
        "personId": "player_id",
        "firstName": "first_name",
        "familyName": "last_name",
        "position": "position",
        "comment": "comment",
        "minutes": "min",
        "points": "pts",
        "reboundsTotal": "reb",
        "reboundsOffensive": "oreb",
        "reboundsDefensive": "dreb",
        "assists": "ast",
        "steals": "stl",
        "blocks": "blk",
        "turnovers": "tov",
        "foulsPersonal": "pf",
        "fieldGoalsMade": "fgm",
        "fieldGoalsAttempted": "fga",
        "fieldGoalsPercentage": "fg_pct",
        "threePointersMade": "fg3m",
        "threePointersAttempted": "fg3a",
        "threePointersPercentage": "fg3_pct",
        "freeThrowsMade": "ftm",
        "freeThrowsAttempted": "fta",
        "freeThrowsPercentage": "ft_pct",
        "plusMinusPoints": "plus_minus",
    }
    clean_df = clean_df.rename(columns={k: v for k, v in col_map.items() if k in clean_df.columns})
    
    # Enforce 10-char string game_id
    if "game_id" in clean_df.columns:
        clean_df["game_id"] = clean_df["game_id"].astype(str).str.zfill(10)
        
    # Identify DNP vs Inactive status from comment
    comment_col = clean_df.get("comment", pd.Series([""] * len(clean_df))).fillna("")
    is_dnp = comment_col.astype(str).str.upper().str.contains(
        "DNP|DID NOT|INACTIVE|NOT DRESS|NOT WITH TEAM|SUSPENDED", regex=True
    )
    clean_df["is_dnp"] = is_dnp
    
    # Standardize minutes and seconds (unrounded)
    if "min" in clean_df.columns:
        clean_df["min_seconds"] = clean_df["min"].apply(parse_iso_duration_to_seconds)
        clean_df["min"] = clean_df["min"].apply(parse_iso_duration_to_minutes)
        
        # If DNP, set minutes and seconds to None
        clean_df.loc[clean_df["is_dnp"], "min"] = None
        clean_df.loc[clean_df["is_dnp"], "min_seconds"] = None
    else:
        clean_df["min_seconds"] = None
        clean_df["min"] = None

    # Determine participation status and played flag
    # Played: Not DNP, and has minutes/seconds > 0 or has non-DNP box score entry
    pts_col = clean_df.get("pts", pd.Series([0] * len(clean_df))).fillna(0)
    
    def classify_status(row):
        if row["is_dnp"]:
            return "DNP"
        m_sec = row.get("min_seconds")
        pts = row.get("pts", 0)
        if m_sec is not None and m_sec > 0:
            if pts == 0:
                return "PLAYED_ZERO_PTS"
            if m_sec < 60.0:
                return "PLAYED_SUB_MINUTE"
            return "PLAYED"
        elif m_sec == 0.0:
            # Entered game but logged 0 seconds (e.g. late defensive sub for 1 play)
            if pts == 0:
                return "PLAYED_ZERO_PTS"
            return "PLAYED"
        else:
            # No minutes recorded and not explicitly DNP
            return "UNKNOWN"

    clean_df["participation_status"] = clean_df.apply(classify_status, axis=1)
    clean_df["played"] = clean_df["participation_status"].isin(["PLAYED", "PLAYED_ZERO_PTS", "PLAYED_SUB_MINUTE"]).astype(int)
        
    return clean_df

def normalize_boxscore_advanced_v3(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize BoxScoreAdvancedV3 player_stats into standardized schema."""
    if df.empty:
        return pd.DataFrame()
        
    clean_df = df.copy()
    col_map = {
        "gameId": "game_id",
        "teamId": "team_id",
        "personId": "player_id",
        "minutes": "min",
        "offensiveRating": "offensive_rating",
        "defensiveRating": "defensive_rating",
        "netRating": "net_rating",
        "usagePercentage": "usage_pct",
        "estimatedPace": "pace",
        "pace": "pace",
        "possessions": "possessions",
    }
    clean_df = clean_df.rename(columns={k: v for k, v in col_map.items() if k in clean_df.columns})
    
    if "game_id" in clean_df.columns:
        clean_df["game_id"] = clean_df["game_id"].astype(str).str.zfill(10)
        
    if "min" in clean_df.columns:
        clean_df["min_seconds"] = clean_df["min"].apply(parse_iso_duration_to_seconds)
        clean_df["min"] = clean_df["min"].apply(parse_iso_duration_to_minutes)
        
    return clean_df

def fetch_boxscores(
    game_id: str,
    client: Optional[NBAClient] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch both traditional and advanced V3 box scores for a given game."""
    client = client or NBAClient()
    game_id_str = str(game_id).zfill(10)
    
    # 1. Traditional V3
    trad_endpoint = client.execute(
        boxscoretraditionalv3.BoxScoreTraditionalV3,
        params={"game_id": game_id_str},
    )
    trad_df = normalize_boxscore_traditional_v3(trad_endpoint.player_stats.get_data_frame())
    
    # 2. Advanced V3
    adv_endpoint = client.execute(
        boxscoreadvancedv3.BoxScoreAdvancedV3,
        params={"game_id": game_id_str},
    )
    adv_df = normalize_boxscore_advanced_v3(adv_endpoint.player_stats.get_data_frame())
    
    return trad_df, adv_df
