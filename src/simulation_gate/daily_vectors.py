"""
Module: Daily Vector Aggregation & Ledger Validation (§3 of Review Spec)
Provides:
- Ingestion and auditing of row-level prediction ledgers
- Canonical aggregation into daily 6-vectors: (S_PTS, S_REB, S_AST, N_PTS, N_REB, N_AST)
- Gap days and season boundary alignment
"""

from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd


def aggregate_prediction_ledger_to_daily_vectors(
    df_ledger: pd.DataFrame,
) -> Tuple[np.ndarray, np.ndarray, List[Any], np.ndarray]:
    """
    Aggregates row-level prediction ledger into daily vectors (§3.2):
    For each date d and stat s in {PTS, REB, AST}:
    - d_i = (p_H - y)^2 - (p_SH - y)^2
    - S_ds = sum d_i
    - N_ds = count(eligible rows)
    Returns:
    - sums: (T, 3) matrix
    - counts: (T, 3) matrix
    - seasons: List of length T
    - gap_days: (T,) array of calendar day gaps
    """
    df = df_ledger.copy()
    required_cols = ["game_date", "stat", "p_H", "p_SH", "y"]
    for c in required_cols:
        if c not in df.columns:
            raise ValueError(f"Missing required ledger column: {c}")

    df["stat_norm"] = df["stat"].str.upper().str.strip()
    df = df[df["stat_norm"].isin(["PTS", "REB", "AST"])].copy()

    # Calculate row-level Brier difference: d_i = (q - y)^2 - (p - y)^2 (§3.2)
    p_h = df["p_H"].to_numpy(dtype=np.float64)
    p_sh = df["p_SH"].to_numpy(dtype=np.float64)
    y = df["y"].to_numpy(dtype=np.float64)
    df["d_brier"] = (p_h - y) ** 2 - (p_sh - y) ** 2

    # Group by game_date, season
    if "season" not in df.columns:
        df["season"] = 1

    df["game_date_dt"] = pd.to_datetime(df["game_date"])
    unique_dates = df.sort_values("game_date_dt")[["game_date", "season", "game_date_dt"]].drop_duplicates("game_date")

    T = len(unique_dates)
    sums = np.zeros((T, 3), dtype=np.float64)
    counts = np.zeros((T, 3), dtype=np.float64)
    seasons_list = []
    dates_list = []

    stat_map = {"PTS": 0, "REB": 1, "AST": 2}

    date_to_idx = {d: i for i, d in enumerate(unique_dates["game_date"])}

    for _, r in unique_dates.iterrows():
        seasons_list.append(r["season"])
        dates_list.append(r["game_date"])

    # Group aggregations
    grouped = df.groupby(["game_date", "stat_norm"])
    for (d_val, s_val), group in grouped:
        d_idx = date_to_idx[d_val]
        s_idx = stat_map[s_val]
        sums[d_idx, s_idx] = float(group["d_brier"].sum())
        counts[d_idx, s_idx] = float(len(group))

    # Calculate gap days
    d_series = unique_dates["game_date_dt"].reset_index(drop=True)
    gaps = np.ones(T, dtype=int)
    if T > 1:
        diffs = d_series.diff().dt.days.fillna(1).to_numpy(dtype=int)
        gaps = np.maximum(1, diffs)

    return sums, counts, seasons_list, gaps
