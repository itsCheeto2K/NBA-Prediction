"""Build and screen canonical Defense vs Position (DvP) game observations (§5, §6 of Spec)."""
from typing import Dict, List, Optional, Tuple
import logging
import numpy as np
import pandas as pd

from src.features.opponent_pairs import build_team_game_pairs
from src.features.dvp_position import get_player_positions_df

logger = logging.getLogger(__name__)


def build_dvp_game_observations(
    player_logs_df: pd.DataFrame,
    team_logs_df: pd.DataFrame,
    pos_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Construct game-level DvP observations for defending team t facing offensive team u:
    - Group Y_tgs: total PTS, REB, AST conceded to group g of team u in game h.
    - Group M_tg: total player-minutes played by group g of team u.
    - Exposures:
      - E_th (PTS, AST) = possessions_foe (offensive possessions of u).
      - E_th (REB) = possessions_game_common (common game possessions).
    - Applies quality screen (§6):
      - Mapped known-group minutes >= 95% of total player minutes.
      - Unknown-group stat <= 5% of total stat.
    """
    if player_logs_df.empty or team_logs_df.empty:
        return pd.DataFrame()

    if pos_df is None:
        pos_df = get_player_positions_df()

    # 1. Merge player positions
    p_df = player_logs_df.copy()
    p_df = p_df.merge(pos_df[["player_id", "position_group"]], on="player_id", how="left")
    p_df["position_group"] = p_df["position_group"].fillna("unknown")

    # Fill default numeric columns
    for col in ["pts", "reb", "ast", "min"]:
        if col not in p_df.columns:
            p_df[col] = 0.0

    # Ensure min is positive
    p_df["min"] = np.maximum(p_df["min"], 0.0)

    # 2. Check game-level quality screens per offensive team
    # Total minutes and stats per game and team
    totals = p_df.groupby(["game_id", "team_abbreviation"]).agg(
        tot_min=("min", "sum"),
        tot_pts=("pts", "sum"),
        tot_reb=("reb", "sum"),
        tot_ast=("ast", "sum"),
    ).reset_index()

    # Known groups only
    known = p_df[p_df["position_group"] != "unknown"].groupby(["game_id", "team_abbreviation"]).agg(
        known_min=("min", "sum"),
        known_pts=("pts", "sum"),
    ).reset_index()

    check = totals.merge(known, on=["game_id", "team_abbreviation"], how="left").fillna(0.0)
    check["min_coverage"] = np.where(check["tot_min"] > 0, check["known_min"] / check["tot_min"], 1.0)
    check["unknown_pts_ratio"] = np.where(check["tot_pts"] > 0, (check["tot_pts"] - check["known_pts"]) / check["tot_pts"], 0.0)

    valid_offensive_mask = (check["min_coverage"] >= 0.95) & (check["unknown_pts_ratio"] <= 0.05)
    valid_game_teams = set(zip(check.loc[valid_offensive_mask, "game_id"], check.loc[valid_offensive_mask, "team_abbreviation"]))

    # 3. Aggregate group totals
    grp = p_df.groupby(["game_id", "team_abbreviation", "position_group"]).agg(
        group_pts=("pts", "sum"),
        group_reb=("reb", "sum"),
        group_ast=("ast", "sum"),
        group_minutes=("min", "sum"),
        group_players_count=("player_id", "count"),
    ).reset_index().rename(columns={"team_abbreviation": "foe_team"})

    # Filter out unknown groups from final metric rows (unknown was validated in quality screen)
    grp = grp[grp["position_group"] != "unknown"]

    # 4. Build team game pairs to get true defending vs offensive team mapping
    pairs = build_team_game_pairs(team_logs_df)
    if pairs.empty:
        return pd.DataFrame()

    # Defending team is team_abbreviation, offensive foe is opponent_abbr
    obs = pairs.merge(
        grp,
        left_on=["game_id", "opponent_abbr"],
        right_on=["game_id", "foe_team"],
        how="inner",
    )

    # 5. Mark validity flag
    obs["is_quality_valid"] = [
        (gid, foe) in valid_game_teams
        for gid, foe in zip(obs["game_id"], obs["opponent_abbr"])
    ]

    # Clean columns
    obs["game_date"] = obs["game_date"].astype(str).str[:10]
    keep_cols = [
        "game_id",
        "game_date",
        "team_abbreviation",  # Defending team t
        "opponent_abbr",      # Offensive team u
        "position_group",     # Group g
        "group_pts",
        "group_reb",
        "group_ast",
        "group_minutes",
        "group_players_count",
        "possessions_foe",          # E for PTS, AST
        "possessions_game_common",  # E for REB
        "is_quality_valid",
    ]
    return obs[keep_cols].sort_values(["game_date", "game_id", "team_abbreviation"])
