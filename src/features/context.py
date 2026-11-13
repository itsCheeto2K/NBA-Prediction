import re
import pandas as pd
from typing import Optional, Dict, Any

def compute_matchup_context(df: pd.DataFrame) -> pd.DataFrame:
    """Extract is_home and opponent_abbr from the MATCHUP column."""
    res = df.copy()
    if "matchup" not in res.columns:
        return res
        
    def parse_matchup(val: str):
        if not isinstance(val, str):
            return 1, ""
        val = val.strip()
        if "@" in val:
            parts = val.split("@")
            return 0, parts[1].strip()
        elif "vs." in val:
            parts = val.split("vs.")
            return 1, parts[1].strip()
        elif "vs" in val:
            parts = val.split("vs")
            return 1, parts[1].strip()
        return 1, ""
        
    parsed = res["matchup"].apply(parse_matchup)
    res["is_home"] = [p[0] for p in parsed]
    res["opponent_abbr"] = [p[1] for p in parsed]
    return res

def compute_rest_and_b2b(df: pd.DataFrame) -> pd.DataFrame:
    """Compute rest days between consecutive games and mark back-to-back (is_b2b)."""
    res = df.copy()
    if "game_date" not in res.columns:
        return res
        
    res["game_date_dt"] = pd.to_datetime(res["game_date"])
    res = res.sort_values(by=["player_id", "game_date_dt", "game_id"]).reset_index(drop=True)
    
    grouped = res.groupby("player_id")
    prev_date = grouped["game_date_dt"].shift(1)
    
    res["rest_days"] = (res["game_date_dt"] - prev_date).dt.days
    res["is_b2b"] = (res["rest_days"] == 1).astype(int)
    
    # Days since last game flag: if rest > 14 days, mark returning from extended rest
    res["is_extended_rest"] = (res["rest_days"] > 14).astype(int)
    
    res = res.drop(columns=["game_date_dt"])
    return res

def compute_opponent_defense_context(
    player_df: pd.DataFrame,
    team_logs_df: pd.DataFrame,
    window: int = 10,
) -> pd.DataFrame:
    """
    Compute historical rolling defensive stats for opponent teams (strictly prior to game date).
    """
    if team_logs_df.empty or "opponent_abbr" not in player_df.columns:
        return player_df
        
    t_df = team_logs_df.copy()
    t_df["game_date_dt"] = pd.to_datetime(t_df["game_date"])
    t_df = t_df.sort_values(by=["team_abbreviation", "game_date_dt"]).reset_index(drop=True)
    
    # For each team game, points allowed is opponent's points in that game.
    # Build fast O(1) lookup: game_id -> {team: pts}
    game_to_team_pts: Dict[Any, Dict[str, float]] = {}
    for (gid, team), pts in game_pts.items():
        if gid not in game_to_team_pts:
            game_to_team_pts[gid] = {}
        game_to_team_pts[gid][team] = pts
    
    def get_opp_pts(row):
        gid = row["game_id"]
        teams = game_to_team_pts.get(gid, {})
        for t, p in teams.items():
            if t != row["team_abbreviation"]:
                return p
        return None
        
    t_df["pts_allowed"] = t_df.apply(get_opp_pts, axis=1)
    
    # Rolling points allowed per team (strictly shifted by 1)
    t_grouped = t_df.groupby("team_abbreviation")
    t_df["opp_pts_allowed_roll"] = (
        t_grouped["pts_allowed"]
        .shift(1)
        .rolling(window, min_periods=1)
        .mean()
    )
    
    # Merge onto player_df via (opponent_abbr, game_id)
    opp_stats_map = t_df.set_index(["team_abbreviation", "game_id"])["opp_pts_allowed_roll"].to_dict()
    
    res = player_df.copy()
    res["opp_pts_allowed_roll"] = res.apply(
        lambda r: opp_stats_map.get((r.get("opponent_abbr"), r.get("game_id"))),
        axis=1,
    )
    return res
