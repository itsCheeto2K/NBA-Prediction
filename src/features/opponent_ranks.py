"""Empirical Bayes smoothing, log-relative calculations, and cutoff percentile ranks for opponent profiling."""
from typing import Dict, Any, List, Optional, Tuple
import numpy as np
import pandas as pd

TAU_POSSESSIONS = 500.0

DEFAULT_LEAGUE_PRIORS = {
    "pts_allowed": 114.0,
    "ast_allowed": 26.0,
    "oreb_allowed": 10.5,
    "dreb_allowed": 33.0,
    "reb_allowed": 43.5,
    "fg3m_allowed": 13.0,
    "fg3a_allowed": 36.0,
    "fta_allowed": 22.0,
    "blocks_made": 5.0,
    "blocks_allowed": 5.0,
    "missed_fga": 48.0,
}

METRIC_EXPOSURE_MAP = {
    "pts_allowed": "possessions_foe",
    "ast_allowed": "possessions_foe",
    "oreb_allowed": "possessions_game_common",
    "dreb_allowed": "possessions_game_common",
    "reb_allowed": "possessions_game_common",
    "fg3m_allowed": "possessions_foe",
    "fg3a_allowed": "possessions_foe",
    "fta_allowed": "possessions_foe",
    "blocks_made": "possessions_foe",
    "blocks_allowed": "possessions_own",
    "missed_fga": "possessions_own",
}


def compute_smoothed_rate(
    sum_y: float, 
    sum_e: float, 
    r0: float, 
    tau: float = TAU_POSSESSIONS
) -> Tuple[float, float]:
    """
    Compute empirical shrinkage rate per 100 possessions (§6):
    R_shrunk = 100 * [sum_y + tau * r0 / 100] / [sum_e + tau]
    prior_weight = tau / (sum_e + tau)
    """
    if sum_e + tau <= 0:
        return r0, 1.0
    r_shrunk = 100.0 * (float(sum_y) + tau * (float(r0) / 100.0)) / (float(sum_e) + tau)
    prior_weight = tau / (float(sum_e) + tau)
    return r_shrunk, prior_weight


def compute_log_relative(r_shrunk: float, r0: float) -> float:
    """Compute log relative context: ln(r_shrunk / r0)."""
    if r_shrunk <= 0 or r0 <= 0:
        return 0.0
    return float(np.log(r_shrunk / r0))


def compute_percentile_ranks(series: pd.Series) -> Tuple[pd.Series, pd.Series]:
    """
    Compute average tie ranks and ascending percentiles (§8):
    pct_asc = (rank_asc - 1) / (N - 1)
    If all values equal or N == 1, pct is 0.5.
    """
    n = len(series)
    if n <= 1:
        return pd.Series(1.0, index=series.index), pd.Series(0.5, index=series.index)

    ranks = series.rank(method="average", ascending=True)
    if series.nunique() <= 1:
        pcts = pd.Series(0.5, index=series.index)
    else:
        pcts = (ranks - 1.0) / float(n - 1)
    return ranks, pcts


def compute_opponent_team_profiles_asof(
    pairs_df: pd.DataFrame,
    as_of_date: str,
    window_k: int = 10,
    priors: Optional[Dict[str, float]] = None
) -> pd.DataFrame:
    """
    Build complete per-team smoothed rates, log-relatives, and ranks as-of a specific cutoff date.
    Strictly filters games with game_date < as_of_date (anti-leakage lag-1).
    """
    if priors is None:
        priors = DEFAULT_LEAGUE_PRIORS

    # Filter historical games strictly before cutoff date
    hist = pairs_df[pairs_df["game_date"] < as_of_date].copy()
    if hist.empty:
        return pd.DataFrame()

    hist = hist.sort_values(by=["team_abbreviation", "game_date"])

    profiles = []
    # For each team, take last K games
    for team, group in hist.groupby("team_abbreviation"):
        tail = group.tail(window_k)
        n_games = len(tail)
        row = {
            "team_abbreviation": team,
            "sample_games": n_games,
            "cutoff_date": as_of_date
        }

        for metric, exp_col in METRIC_EXPOSURE_MAP.items():
            r0 = priors.get(metric, 100.0)
            if metric in tail.columns and exp_col in tail.columns:
                sum_y = float(tail[metric].sum())
                sum_e = float(tail[exp_col].sum())
            else:
                sum_y = 0.0
                sum_e = 0.0

            r_shrunk, p_weight = compute_smoothed_rate(sum_y, sum_e, r0)
            log_rel = compute_log_relative(r_shrunk, r0)

            row[f"opp_{metric}_per100_shrunk_prev{window_k}"] = r_shrunk
            row[f"opp_{metric}_log_relative_prev{window_k}"] = log_rel
            row[f"opp_{metric}_prior_weight_prev{window_k}"] = p_weight

        profiles.append(row)

    if not profiles:
        return pd.DataFrame()

    prof_df = pd.DataFrame(profiles)

    # Compute ranks and percentiles across all active teams for each metric
    for metric in METRIC_EXPOSURE_MAP.keys():
        col_shrunk = f"opp_{metric}_per100_shrunk_prev{window_k}"
        if col_shrunk in prof_df.columns:
            ranks, pcts = compute_percentile_ranks(prof_df[col_shrunk])
            prof_df[f"opp_{metric}_rank_asc_prev{window_k}"] = ranks
            prof_df[f"opp_{metric}_pct_asc_prev{window_k}"] = pcts

    return prof_df
