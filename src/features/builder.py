import logging
import numpy as np
import pandas as pd
from typing import Optional

from src.features.context import compute_matchup_context
from src.features.schedule_context import (
    compute_team_and_opponent_schedule_context,
    compute_player_workload_context,
)
from src.features.opponent_context import compute_opponent_p0_features
from src.features.rolling import compute_player_rolling_features
from src.features.shrinkage import compute_gamma_poisson_rate

logger = logging.getLogger(__name__)

def build_feature_dataset(
    player_logs_df: pd.DataFrame,
    team_logs_df: Optional[pd.DataFrame] = None,
    players_ref_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    End-to-end feature pipeline builder.
    Strictly follows anti-leakage protocol: all predictors only use data prior to game time.
    Includes full Opponent & Schedule Supplement Plan features.
    """
    if player_logs_df.empty:
        return pd.DataFrame()
        
    df = player_logs_df.copy()
    
    # 1. Matchup Context
    logger.info("Computing matchup context (is_home, opponent_abbr)...")
    df = compute_matchup_context(df)
    
    # 2. Detailed Schedule Context (Team & Opponent B2B, Congestion, Rest Advantage)
    if team_logs_df is not None and not team_logs_df.empty:
        logger.info("Computing team & opponent schedule context (B2B, 3in4, 4in6, rest advantage)...")
        df = compute_team_and_opponent_schedule_context(df, team_logs_df)
    else:
        # Fallback to player's game date sequence
        dates_dt = pd.to_datetime(df["game_date"])
        prev_dates = pd.to_datetime(df.groupby("team_abbreviation")["game_date"].shift(1))
        days_diff = (dates_dt - prev_dates).dt.days
        df["team_b2b"] = (days_diff == 1).fillna(False).astype(int)
        df["team_rest_days"] = np.where(days_diff.isna(), 2, np.maximum(0, days_diff - 1)).astype(int)
        for c in ["team_3in4", "team_4in6", "opp_b2b", "opp_rest_days", "opp_3in4", "opp_4in6", "rest_advantage_days"]:
            df[c] = 0

    # Alias for backward compatibility
    df["is_b2b"] = df.get("team_b2b", 0)
    df["rest_days"] = df.get("team_rest_days", df.get("player_last_game_days", 2))

    # 3. Player-Specific Workload vs Team Schedule
    logger.info("Computing player-specific workload (played prev game, team b2b but rested, minutes last 7 days)...")
    df = compute_player_workload_context(df)

    # 4. Detailed Opponent P0 Defensive Context per 100 Possessions
    if team_logs_df is not None and not team_logs_df.empty:
        logger.info("Computing opponent defensive context per 100 possessions (pace, def rating, allowed ast, dreb share)...")
        df = compute_opponent_p0_features(df, team_logs_df, window=10)
    else:
        for c in ["opp_def_rating_prev10", "opp_pace_prev10", "opp_allowed_ast_per100_prev10", "opp_dreb_share_prev10", "opp_fg3a_share_prev10"]:
            df[c] = 0.0
        df["opp_sample_games"] = 0
        df["opp_feature_missing"] = 1

    # 5. Rolling Historical Player Features (Lag-1)
    logger.info("Computing rolling player features (windows 5, 10, 20)...")
    df = compute_player_rolling_features(df, windows=[5, 10, 20])
    
    # 6. Gamma-Poisson Rate Shrinkage
    logger.info("Computing Gamma-Poisson rate shrinkage for PTS, REB, AST...")
    for stat in ["pts", "reb", "ast"]:
        if stat in df.columns:
            df = compute_gamma_poisson_rate(df, stat=stat)
            
    # 7. Data Quality & Operational Flags (§9 & §13)
    logger.info("Generating data quality flags...")
    df["insufficient_data"] = df["n_games_history"] < 5
    df["is_returning_rest"] = (df["player_last_game_days"] > 14).astype(int)
    
    min_roll = df.get("min_roll_mean_5", df.get("min", pd.Series([0.0] * len(df))))
    df["is_ready"] = (df["n_games_history"] >= 5) & (min_roll >= 10.0)
    
    # 8. Target Isolation (explicit targets prefixed with target_)
    if "pts" in df.columns:
        df["target_pts"] = df["pts"]
    if "reb" in df.columns:
        df["target_reb"] = df["reb"]
    if "ast" in df.columns:
        df["target_ast"] = df["ast"]
    if "min" in df.columns:
        df["target_min"] = df["min"]
        
    return df
