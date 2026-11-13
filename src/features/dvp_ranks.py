"""Empirical Bayes smoothing, log-relatives, and cutoff percentile ranks for Defense vs Position (DvP)."""
from typing import Dict, List, Optional, Tuple
import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

TAU_POSSESSIONS = 500.0
BETA_MINUTES = 500.0

DEFAULT_DVP_PRIORS = {
    "guard": {
        "v0": {"pts": 47.2, "reb": 12.6, "ast": 13.7},
        "r0": {"pts": 0.481, "reb": 0.129, "ast": 0.139},
    },
    "wing": {
        "v0": {"pts": 43.2, "reb": 16.8, "ast": 8.4},
        "r0": {"pts": 0.462, "reb": 0.179, "ast": 0.090},
    },
    "big": {
        "v0": {"pts": 22.3, "reb": 14.0, "ast": 4.2},
        "r0": {"pts": 0.477, "reb": 0.300, "ast": 0.089},
    },
}

POSITION_GROUPS = ["guard", "wing", "big"]
STATS = ["pts", "reb", "ast"]


def smooth_dvp_volume(
    sum_y: float,
    sum_e: float,
    v0: float,
    tau: float = TAU_POSSESSIONS,
) -> Tuple[float, float]:
    """
    Compute Empirical Bayes smoothed group volume per 100 possessions (§8):
    V_shrunk = 100 * [sum_y + tau * v0 / 100] / [sum_e + tau]
    """
    if sum_e + tau <= 0:
        return float(v0), 1.0
    v_shrunk = 100.0 * (float(sum_y) + tau * (float(v0) / 100.0)) / (float(sum_e) + tau)
    prior_weight = tau / (float(sum_e) + tau)
    return float(v_shrunk), float(prior_weight)


def smooth_dvp_minute_rate(
    sum_y: float,
    sum_m: float,
    r0: float,
    beta: float = BETA_MINUTES,
) -> Tuple[float, float]:
    """
    Compute Empirical Bayes smoothed group minute-rate (§8):
    R_shrunk = [sum_y + beta * r0] / [sum_m + beta]
    """
    if sum_m + beta <= 0:
        return float(r0), 1.0
    r_shrunk = (float(sum_y) + beta * float(r0)) / (float(sum_m) + beta)
    prior_weight = beta / (float(sum_m) + beta)
    return float(r_shrunk), float(prior_weight)


def compute_log_relative(shrunk_val: float, prior_val: float) -> float:
    """Compute log relative context: ln(shrunk_val / prior_val)."""
    if shrunk_val <= 0 or prior_val <= 0:
        return 0.0
    return float(np.log(shrunk_val / prior_val))


def compute_dvp_team_profiles_asof(
    obs_df: pd.DataFrame,
    as_of_date: str,
    window_k: int = 10,
    priors: Optional[Dict] = None,
) -> pd.DataFrame:
    """
    Build complete per-team DvP profiles across all position groups as-of a specific cutoff date.
    Strictly filters games with game_date < as_of_date (anti-leakage lag-1, §9).
    """
    if obs_df.empty:
        return pd.DataFrame()

    if priors is None:
        priors = DEFAULT_DVP_PRIORS

    cutoff_str = str(as_of_date)[:10]
    # Filter strictly before cutoff date and quality valid
    hist = obs_df[
        (obs_df["game_date"].astype(str).str[:10] < cutoff_str) & 
        (obs_df.get("is_quality_valid", True) == True)
    ].copy()

    if hist.empty:
        return pd.DataFrame()

    hist = hist.sort_values(by=["team_abbreviation", "game_date"])

    profiles = []
    # For each team, identify last K distinct games
    for team, group in hist.groupby("team_abbreviation"):
        distinct_games = group["game_id"].drop_duplicates().tail(window_k)
        n_games = len(distinct_games)
        tail = group[group["game_id"].isin(distinct_games)]

        is_supported = (n_games >= 5)

        row = {
            "team_abbreviation": team,
            "sample_games": n_games,
            "cutoff_date": as_of_date,
            "dvp_supported": is_supported,
        }

        for grp in POSITION_GROUPS:
            grp_priors = priors.get(grp, DEFAULT_DVP_PRIORS.get(grp, {}))
            v0_map = grp_priors.get("v0", {})
            r0_map = grp_priors.get("r0", {})

            sub = tail[tail["position_group"] == grp]
            tot_m = float(sub["group_minutes"].sum()) if not sub.empty else 0.0

            for s in STATS:
                stat_col = f"group_{s}"
                exp_col = "possessions_game_common" if s == "reb" else "possessions_foe"

                # Denominators are game-level exposures (once per game)
                if not sub.empty:
                    game_exp = sub.drop_duplicates(subset=["game_id"])[exp_col].sum()
                    sum_y = float(sub[stat_col].sum())
                    sum_e = float(game_exp)
                else:
                    sum_y = 0.0
                    sum_e = 0.0

                v0 = v0_map.get(s, 10.0)
                r0 = r0_map.get(s, 0.20)

                v_shrunk, v_pw = smooth_dvp_volume(sum_y, sum_e, v0)
                r_shrunk, r_pw = smooth_dvp_minute_rate(sum_y, tot_m, r0)

                v_rel = compute_log_relative(v_shrunk, v0)
                r_rel = compute_log_relative(r_shrunk, r0)

                prefix = f"dvp_{s}_{grp}"
                row[f"{prefix}_volume_per100"] = round(v_shrunk, 2)
                row[f"{prefix}_volume_rel"] = round(v_rel, 4)
                row[f"{prefix}_volume_prior_weight"] = round(v_pw, 4)

                row[f"{prefix}_minrate"] = round(r_shrunk, 4)
                row[f"{prefix}_minrate_rel"] = round(r_rel, 4)
                row[f"{prefix}_minrate_prior_weight"] = round(r_pw, 4)

        profiles.append(row)

    if not profiles:
        return pd.DataFrame()

    res = pd.DataFrame(profiles)
    n_teams = len(res)

    # Compute ranks and percentiles across teams for each (stat, group, metric)
    for grp in POSITION_GROUPS:
        for s in STATS:
            prefix = f"dvp_{s}_{grp}"
            # 1. Volume rank (Rank 1 = allows least volume = best defense; 30 = worst)
            vol_col = f"{prefix}_volume_per100"
            if vol_col in res.columns:
                res[f"{prefix}_volume_rank_asc"] = res[vol_col].rank(method="average", ascending=True)
                res[f"{prefix}_volume_pct_asc"] = (res[f"{prefix}_volume_rank_asc"] - 1.0) / max(float(n_teams - 1), 1.0)

            # 2. Minute-rate rank
            rate_col = f"{prefix}_minrate"
            if rate_col in res.columns:
                res[f"{prefix}_minrate_rank_asc"] = res[rate_col].rank(method="average", ascending=True)
                res[f"{prefix}_minrate_pct_asc"] = (res[f"{prefix}_minrate_rank_asc"] - 1.0) / max(float(n_teams - 1), 1.0)

    return res
