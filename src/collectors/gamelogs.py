import pandas as pd
from typing import Any, Optional
from nba_api.stats.endpoints import playergamelogs, leaguegamelog
from src.client import NBAClient
from src.config import SeasonType

def parse_minutes_to_float(val: Any) -> Optional[float]:
    """Convert minutes from MM:SS or raw number to float. Returns None for DNP/null."""
    if val is None or pd.isna(val):
        return None
    if isinstance(val, (int, float)):
        return float(val)
    val_str = str(val).strip()
    if not val_str or val_str.upper() in ("DNP", "N/A", "NONE"):
        return None
    if ":" in val_str:
        parts = val_str.split(":")
        try:
            minutes = float(parts[0])
            seconds = float(parts[1]) if len(parts) > 1 else 0.0
            return round(minutes + seconds / 60.0, 3)
        except ValueError:
            return None
    try:
        return float(val_str)
    except ValueError:
        return None

def normalize_player_gamelogs_df(df: pd.DataFrame) -> pd.DataFrame:
    """Standardize PlayerGameLogs into clean lowercase snake_case schema."""
    if df.empty:
        return pd.DataFrame()
        
    clean_df = df.copy()
    col_map = {
        "SEASON_YEAR": "season",
        "PLAYER_ID": "player_id",
        "PLAYER_NAME": "player_name",
        "NICKNAME": "nickname",
        "TEAM_ID": "team_id",
        "TEAM_ABBREVIATION": "team_abbreviation",
        "TEAM_NAME": "team_name",
        "GAME_ID": "game_id",
        "GAME_DATE": "game_date",
        "MATCHUP": "matchup",
        "WL": "wl",
        "MIN": "min",
        "FGM": "fgm",
        "FGA": "fga",
        "FG_PCT": "fg_pct",
        "FG3M": "fg3m",
        "FG3A": "fg3a",
        "FG3_PCT": "fg3_pct",
        "FTM": "ftm",
        "FTA": "fta",
        "FT_PCT": "ft_pct",
        "OREB": "oreb",
        "DREB": "dreb",
        "REB": "reb",
        "AST": "ast",
        "TOV": "tov",
        "STL": "stl",
        "BLK": "blk",
        "BLKA": "blka",
        "PF": "pf",
        "PFD": "pfd",
        "PTS": "pts",
        "PLUS_MINUS": "plus_minus",
    }
    
    clean_df = clean_df.rename(columns={k: v for k, v in col_map.items() if k in clean_df.columns})
    
    # Enforce 10-char string game_id
    if "game_id" in clean_df.columns:
        clean_df["game_id"] = clean_df["game_id"].astype(str).str.zfill(10)
        
    # Standardize minutes
    if "min" in clean_df.columns:
        clean_df["min"] = clean_df["min"].apply(parse_minutes_to_float)
        
    return clean_df

def normalize_team_gamelogs_df(df: pd.DataFrame) -> pd.DataFrame:
    """Standardize LeagueGameLog (team level) into clean schema."""
    if df.empty:
        return pd.DataFrame()
        
    clean_df = df.copy()
    col_map = {
        "SEASON_ID": "season_id",
        "TEAM_ID": "team_id",
        "TEAM_ABBREVIATION": "team_abbreviation",
        "TEAM_NAME": "team_name",
        "GAME_ID": "game_id",
        "GAME_DATE": "game_date",
        "MATCHUP": "matchup",
        "WL": "wl",
        "MIN": "min",
        "PTS": "pts",
        "FGM": "fgm",
        "FGA": "fga",
        "FG_PCT": "fg_pct",
        "FG3M": "fg3m",
        "FG3A": "fg3a",
        "FG3_PCT": "fg3_pct",
        "FTM": "ftm",
        "FTA": "fta",
        "FT_PCT": "ft_pct",
        "OREB": "oreb",
        "DREB": "dreb",
        "REB": "reb",
        "AST": "ast",
        "STL": "stl",
        "BLK": "blk",
        "TOV": "tov",
        "PF": "pf",
    }
    clean_df = clean_df.rename(columns={k: v for k, v in col_map.items() if k in clean_df.columns})
    
    if "game_id" in clean_df.columns:
        clean_df["game_id"] = clean_df["game_id"].astype(str).str.zfill(10)
        
    return clean_df

def fetch_player_gamelogs(
    season: str,
    season_type: str = SeasonType.REGULAR.value,
    client: Optional[NBAClient] = None,
    use_cache: bool = True,
) -> pd.DataFrame:
    """Fetch bulk player game logs for an entire season."""
    client = client or NBAClient()
    endpoint = client.execute(
        playergamelogs.PlayerGameLogs,
        params={
            "season_nullable": season,
            "season_type_nullable": season_type,
        },
        use_cache=use_cache,
    )
    raw_df = endpoint.player_game_logs.get_data_frame()
    return normalize_player_gamelogs_df(raw_df)

def fetch_team_gamelogs(
    season: str,
    season_type: str = SeasonType.REGULAR.value,
    client: Optional[NBAClient] = None,
    use_cache: bool = True,
) -> pd.DataFrame:
    """Fetch bulk team game logs for an entire season."""
    client = client or NBAClient()
    endpoint = client.execute(
        leaguegamelog.LeagueGameLog,
        params={
            "season": season,
            "season_type_all_star": season_type,
            "player_or_team_abbreviation": "T",
        },
        use_cache=use_cache,
    )
    raw_df = endpoint.league_game_log.get_data_frame()
    return normalize_team_gamelogs_df(raw_df)
