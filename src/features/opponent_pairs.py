"""Canonical team-game pair construction and possession calculation for opponent profiling."""
from typing import Dict, Any, Optional
import numpy as np
import pandas as pd

def calculate_possessions(
    fga: float, 
    fta: float, 
    oreb: float, 
    tov: float, 
    min_poss: float = 40.0
) -> float:
    """
    Calculate approximate offensive possessions:
    P = FGA + 0.44 * FTA - OREB + TOV
    Enforces a floor of min_poss (default 40.0).
    """
    p = float(fga) + 0.44 * float(fta) - float(oreb) + float(tov)
    return max(p, min_poss)


def build_team_game_pairs(team_logs_df: pd.DataFrame) -> pd.DataFrame:
    """
    Self-join team gamelogs by game_id to build canonical own/foe paired records.
    Extracts defensive allowances, blocks made/allowed, missed FG volume, and side-specific exposures.
    """
    if team_logs_df.empty:
        return pd.DataFrame()

    df = team_logs_df.copy()
    
    # Ensure numeric columns exist and fill NAs
    numeric_cols = [
        "fga", "fgm", "fta", "ftm", "oreb", "dreb", "reb", 
        "ast", "stl", "blk", "tov", "pf", "pts", "fg3a", "fg3m"
    ]
    for c in numeric_cols:
        if c not in df.columns:
            df[c] = 0.0
        else:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

    # Calculate own offensive possessions for each team row
    df["possessions_own"] = [
        calculate_possessions(fga=r.fga, fta=r.fta, oreb=r.oreb, tov=r.tov)
        for r in df.itertuples()
    ]

    # Self-join on game_id to link with opponent in the same game
    # Columns to bring from foe (opponent):
    foe_cols = [
        "game_id", "team_id", "team_abbreviation", "pts", "ast", "reb", 
        "oreb", "dreb", "fg3m", "fg3a", "fta", "fga", "fgm", "blk", 
        "possessions_own"
    ]
    # Filter to available columns
    avail_foe_cols = [c for c in foe_cols if c in df.columns]
    
    foe_df = df[avail_foe_cols].copy()
    # Rename foe columns
    rename_map = {
        "team_id": "opponent_team_id",
        "team_abbreviation": "opponent_abbr",
        "pts": "pts_allowed",
        "ast": "ast_allowed",
        "reb": "reb_allowed",
        "oreb": "oreb_allowed",
        "dreb": "dreb_allowed",
        "fg3m": "fg3m_allowed",
        "fg3a": "fg3a_allowed",
        "fta": "fta_allowed",
        "fga": "opp_fga",
        "fgm": "opp_fgm",
        "blk": "blocks_allowed",  # shots of t blocked by foe
        "possessions_own": "possessions_foe"  # offensive possessions of foe
    }
    foe_df = foe_df.rename(columns=rename_map)

    # Merge on game_id
    merged = pd.merge(df, foe_df, on="game_id", how="inner")
    
    # Exclude self-matches (t.team_id == u.opponent_team_id)
    if "opponent_team_id" in merged.columns and "team_id" in merged.columns:
        merged = merged[merged["team_id"] != merged["opponent_team_id"]].copy()
    elif "opponent_abbr" in merged.columns and "team_abbreviation" in merged.columns:
        merged = merged[merged["team_abbreviation"] != merged["opponent_abbr"]].copy()

    # Calculate derived stats per spec §5:
    # blocks_made by team t (occurred while foe was on offense)
    merged["blocks_made"] = merged["blk"]
    # missed_fga by team t (proxy rebound context)
    merged["missed_fga"] = np.maximum(0.0, merged["fga"] - merged["fgm"])
    # common game possessions: (P_own + P_foe) / 2
    merged["possessions_game_common"] = (merged["possessions_own"] + merged["possessions_foe"]) / 2.0

    return merged
