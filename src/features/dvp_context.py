"""Join and resolve DvP features for player prop prediction targets (§11 of Spec)."""
from typing import Dict, List, Optional, Tuple, Any
import logging
import pandas as pd
import numpy as np

from src.features.dvp_position import resolve_player_position, get_player_positions_df
from src.features.dvp_observations import build_dvp_game_observations
from src.features.dvp_ranks import compute_dvp_team_profiles_asof, DEFAULT_DVP_PRIORS

logger = logging.getLogger(__name__)

_GLOBAL_DVP_OBS_CACHE: Optional[pd.DataFrame] = None
_GLOBAL_DVP_PROFILES_CACHE: Dict[Tuple, pd.DataFrame] = {}


def get_cached_dvp_observations(
    player_logs_df: pd.DataFrame,
    team_logs_df: pd.DataFrame,
) -> pd.DataFrame:
    """Cache and return game observations across sessions."""
    global _GLOBAL_DVP_OBS_CACHE
    if _GLOBAL_DVP_OBS_CACHE is not None and len(_GLOBAL_DVP_OBS_CACHE) > 0:
        return _GLOBAL_DVP_OBS_CACHE

    _GLOBAL_DVP_OBS_CACHE = build_dvp_game_observations(player_logs_df, team_logs_df)
    return _GLOBAL_DVP_OBS_CACHE


def get_cached_dvp_profiles_asof(
    player_logs_df: pd.DataFrame,
    team_logs_df: pd.DataFrame,
    as_of_date: str = "2099-01-01",
    window_k: int = 10,
) -> pd.DataFrame:
    """Compute and cache all 30 teams' DvP profiles as-of a specific date."""
    global _GLOBAL_DVP_PROFILES_CACHE
    cache_key = (len(player_logs_df), len(team_logs_df), as_of_date, window_k)
    if cache_key in _GLOBAL_DVP_PROFILES_CACHE:
        return _GLOBAL_DVP_PROFILES_CACHE[cache_key]

    obs = get_cached_dvp_observations(player_logs_df, team_logs_df)
    if obs.empty:
        return pd.DataFrame()

    profs = compute_dvp_team_profiles_asof(obs, as_of_date, window_k=window_k)
    _GLOBAL_DVP_PROFILES_CACHE[cache_key] = profs
    return profs


def resolve_player_target_dvp(
    player_id: int,
    opponent_abbr: str,
    player_logs_df: pd.DataFrame,
    team_logs_df: pd.DataFrame,
    as_of_date: str = "2099-01-01",
) -> Dict[str, Any]:
    """
    Resolve and extract specific position-matched DvP context for an individual player target (§11).
    """
    raw_pos, grp = resolve_player_position(player_id)
    if grp == "unknown":
        grp = "wing"  # Fallback median group

    profs = get_cached_dvp_profiles_asof(player_logs_df, team_logs_df, as_of_date=as_of_date)
    opp = str(opponent_abbr).strip().upper()

    res = {
        "player_id": player_id,
        "position_raw": raw_pos,
        "position_group": grp,
        "opponent_abbr": opp,
        "dvp_supported": False,
        "dvp_pts_volume_per100": DEFAULT_DVP_PRIORS.get(grp, {}).get("v0", {}).get("pts", 45.0),
        "dvp_pts_volume_rank_asc": 15.5,
        "dvp_pts_volume_rel": 0.0,
        "dvp_pts_minrate": DEFAULT_DVP_PRIORS.get(grp, {}).get("r0", {}).get("pts", 0.48),
        "dvp_pts_minrate_rank_asc": 15.5,
        "dvp_pts_minrate_rel": 0.0,
        "dvp_reb_volume_per100": DEFAULT_DVP_PRIORS.get(grp, {}).get("v0", {}).get("reb", 14.0),
        "dvp_reb_volume_rank_asc": 15.5,
        "dvp_reb_volume_rel": 0.0,
        "dvp_reb_minrate": DEFAULT_DVP_PRIORS.get(grp, {}).get("r0", {}).get("reb", 0.18),
        "dvp_reb_minrate_rank_asc": 15.5,
        "dvp_reb_minrate_rel": 0.0,
        "dvp_ast_volume_per100": DEFAULT_DVP_PRIORS.get(grp, {}).get("v0", {}).get("ast", 8.0),
        "dvp_ast_volume_rank_asc": 15.5,
        "dvp_ast_volume_rel": 0.0,
        "dvp_ast_minrate": DEFAULT_DVP_PRIORS.get(grp, {}).get("r0", {}).get("ast", 0.10),
        "dvp_ast_minrate_rank_asc": 15.5,
        "dvp_ast_minrate_rel": 0.0,
    }

    if not profs.empty:
        t_sub = profs[profs["team_abbreviation"] == opp]
        if not t_sub.empty:
            row = t_sub.iloc[0]
            res["dvp_supported"] = bool(row.get("dvp_supported", True))
            for s in ["pts", "reb", "ast"]:
                prefix = f"dvp_{s}_{grp}"
                res[f"dvp_{s}_volume_per100"] = float(row.get(f"{prefix}_volume_per100", res[f"dvp_{s}_volume_per100"]))
                res[f"dvp_{s}_volume_rank_asc"] = float(row.get(f"{prefix}_volume_rank_asc", 15.5))
                res[f"dvp_{s}_volume_rel"] = float(row.get(f"{prefix}_volume_rel", 0.0))
                res[f"dvp_{s}_minrate"] = float(row.get(f"{prefix}_minrate", res[f"dvp_{s}_minrate"]))
                res[f"dvp_{s}_minrate_rank_asc"] = float(row.get(f"{prefix}_minrate_rank_asc", 15.5))
                res[f"dvp_{s}_minrate_rel"] = float(row.get(f"{prefix}_minrate_rel", 0.0))

    return res


def get_team_all_dvp_profiles(
    team_abbr: str,
    player_logs_df: pd.DataFrame,
    team_logs_df: pd.DataFrame,
) -> Dict[str, Any]:
    """Retrieve full 3-position DvP profile breakdown for an opponent team (§12)."""
    team_abbr = str(team_abbr).strip().upper()
    profs = get_cached_dvp_profiles_asof(player_logs_df, team_logs_df)

    res = {
        "team_abbr": team_abbr,
        "has_dvp": False,
        "groups": {},
    }

    if profs.empty:
        return res

    t_sub = profs[profs["team_abbreviation"] == team_abbr]
    if t_sub.empty:
        return res

    row = t_sub.iloc[0]
    res["has_dvp"] = True
    res["dvp_supported"] = bool(row.get("dvp_supported", True))
    res["sample_games"] = int(row.get("sample_games", 0))

    for grp in ["guard", "wing", "big"]:
        res["groups"][grp] = {
            "pts": {
                "volume_per100": float(row.get(f"dvp_pts_{grp}_volume_per100", 45.0)),
                "rank_asc": float(row.get(f"dvp_pts_{grp}_volume_rank_asc", 15.5)),
                "minrate": float(row.get(f"dvp_pts_{grp}_minrate", 0.48)),
                "minrate_rank_asc": float(row.get(f"dvp_pts_{grp}_minrate_rank_asc", 15.5)),
            },
            "reb": {
                "volume_per100": float(row.get(f"dvp_reb_{grp}_volume_per100", 14.0)),
                "rank_asc": float(row.get(f"dvp_reb_{grp}_volume_rank_asc", 15.5)),
                "minrate": float(row.get(f"dvp_reb_{grp}_minrate", 0.18)),
                "minrate_rank_asc": float(row.get(f"dvp_reb_{grp}_minrate_rank_asc", 15.5)),
            },
            "ast": {
                "volume_per100": float(row.get(f"dvp_ast_{grp}_volume_per100", 8.0)),
                "rank_asc": float(row.get(f"dvp_ast_{grp}_volume_rank_asc", 15.5)),
                "minrate": float(row.get(f"dvp_ast_{grp}_minrate", 0.10)),
                "minrate_rank_asc": float(row.get(f"dvp_ast_{grp}_minrate_rank_asc", 15.5)),
            },
        }

    return res
