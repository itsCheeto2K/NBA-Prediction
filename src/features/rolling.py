import math
import numpy as np
import pandas as pd
from typing import List, Optional

def compute_player_rolling_features(
    df: pd.DataFrame,
    windows: Optional[List[int]] = None,
    decay_halflife: float = 10.0,
) -> pd.DataFrame:
    """
    Compute anti-leakage rolling features per player.
    All rolling features strictly apply shift(1) so that game t NEVER includes game t's stats.
    """
    windows = windows or [5, 10, 20]
    stats_to_roll = ["pts", "reb", "ast", "min", "fga", "fta", "fg3a"]
    
    # Ensure dataframe is sorted by player and game date/id
    df_sorted = df.copy()
    if "game_date" in df_sorted.columns:
        df_sorted["game_date_dt"] = pd.to_datetime(df_sorted["game_date"])
        df_sorted = df_sorted.sort_values(by=["player_id", "game_date_dt", "game_id"]).reset_index(drop=True)
    else:
        df_sorted = df_sorted.sort_values(by=["player_id", "game_id"]).reset_index(drop=True)

    grouped = df_sorted.groupby("player_id", group_keys=False)
    
    # Expanding count of prior games
    df_sorted["n_games_history"] = grouped["pts"].shift(1).expanding().count().astype(int)
    # Correct group-level expanding count:
    df_sorted["n_games_history"] = grouped.cumcount()

    # Calculate rolling features for available stats
    available_stats = [s for s in stats_to_roll if s in df_sorted.columns]
    
    for stat in available_stats:
        shifted_stat = grouped[stat].shift(1)
        
        for w in windows:
            # Rolling mean (min_periods=1: requires at least 1 prior game)
            mean_col = f"{stat}_roll_mean_{w}"
            df_sorted[mean_col] = shifted_stat.groupby(df_sorted["player_id"]).rolling(w, min_periods=1).mean().reset_index(drop=True)
            
            # Rolling std (min_periods=2: requires at least 2 prior games, else 0.0)
            std_col = f"{stat}_roll_std_{w}"
            df_sorted[std_col] = (
                shifted_stat.groupby(df_sorted["player_id"])
                .rolling(w, min_periods=2)
                .std()
                .reset_index(drop=True)
                .fillna(0.0)
            )

        # Form trend: short term (5) minus long term (20) if available
        if 5 in windows and 20 in windows:
            df_sorted[f"{stat}_trend_5_20"] = (
                df_sorted[f"{stat}_roll_mean_5"] - df_sorted[f"{stat}_roll_mean_20"]
            )
            
        # Exponential decay weighted mean (halflife)
        decay_factor = math.log(2.0) / decay_halflife
        
        def calc_decay_mean(series: pd.Series) -> pd.Series:
            arr = series.to_numpy()
            n = len(arr)
            out = np.full(n, np.nan, dtype=np.float64)
            for i in range(1, n):
                past_vals = arr[:i]
                # Filter out NaNs if any
                valid_mask = ~np.isnan(past_vals)
                if not np.any(valid_mask):
                    continue
                valid_vals = past_vals[valid_mask]
                idx = np.arange(len(valid_vals))
                # Most recent past game has lag 1
                lags = len(valid_vals) - 1 - idx
                weights = np.exp(-decay_factor * lags)
                out[i] = np.sum(weights * valid_vals) / np.sum(weights)
            return pd.Series(out, index=series.index)
            
        df_sorted[f"{stat}_decay_mean"] = grouped[stat].apply(calc_decay_mean).reset_index(drop=True)

    if "game_date_dt" in df_sorted.columns:
        df_sorted = df_sorted.drop(columns=["game_date_dt"])

    return df_sorted
