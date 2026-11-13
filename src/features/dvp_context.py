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
_GLOBAL_DVP_OBS_CACHE_KEY: Optional[Tuple] = None
_GLOBAL_DVP_PROFILES_CACHE: Dict[Tuple, pd.DataFrame] = {}


def get_cached_dvp_observations(
    player_logs_df: pd.DataFrame,
    team_logs_df: pd.DataFrame,
) -> pd.DataFrame:
    """Cache and return game observations across sessions."""
    global _GLOBAL_DVP_OBS_CACHE, _GLOBAL_DVP_OBS_CACHE_KEY
    cache_key = (
        len(player_logs_df),
        len(team_logs_df),
        str(player_logs_df.index[-1]) if not player_logs_df.empty else 0,
    )
    if _GLOBAL_DVP_OBS_CACHE is not None and _GLOBAL_DVP_OBS_CACHE_KEY == cache_key:
        return _GLOBAL_DVP_OBS_CACHE

    _GLOBAL_DVP_OBS_CACHE = build_dvp_game_observations(player_logs_df, team_logs_df)
    _GLOBAL_DVP_OBS_CACHE_KEY = cache_key
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


def compute_dvp_features(
    player_df: pd.DataFrame,
    team_logs_df: Optional[pd.DataFrame] = None,
    window_k: int = 10,
    pos_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Compute position-matched Defense vs Position (DvP) features for every player game record.
    Follows strict anti-leakage protocol: only opponent games with game_date < player's game_date are used.
    
    Generates 19 position-matched DvP columns:
      - dvp_{pts,reb,ast}_volume_per100
      - dvp_{pts,reb,ast}_volume_rank_asc
      - dvp_{pts,reb,ast}_volume_rel
      - dvp_{pts,reb,ast}_minrate
      - dvp_{pts,reb,ast}_minrate_rank_asc
      - dvp_{pts,reb,ast}_minrate_rel
      - dvp_supported
    """
    if player_df.empty:
        return player_df

    res = player_df.copy()

    if pos_df is None:
        pos_df = get_player_positions_df()

    if "position_group" not in res.columns:
        if not pos_df.empty and "player_id" in res.columns:
            res = res.merge(pos_df[["player_id", "position_group"]], on="player_id", how="left")
        else:
            res["position_group"] = "wing"

    res["position_group"] = res["position_group"].fillna("wing")
    res.loc[res["position_group"] == "unknown", "position_group"] = "wing"

    dvp_metric_cols = [
        "dvp_pts_volume_per100", "dvp_pts_volume_rank_asc", "dvp_pts_volume_rel",
        "dvp_pts_minrate", "dvp_pts_minrate_rank_asc", "dvp_pts_minrate_rel",
        "dvp_reb_volume_per100", "dvp_reb_volume_rank_asc", "dvp_reb_volume_rel",
        "dvp_reb_minrate", "dvp_reb_minrate_rank_asc", "dvp_reb_minrate_rel",
        "dvp_ast_volume_per100", "dvp_ast_volume_rank_asc", "dvp_ast_volume_rel",
        "dvp_ast_minrate", "dvp_ast_minrate_rank_asc", "dvp_ast_minrate_rel",
        "dvp_supported",
    ]

    def _fill_fallbacks(df: pd.DataFrame) -> pd.DataFrame:
        df["dvp_supported"] = df["dvp_supported"].fillna(False).astype(bool)
        for grp in ["guard", "wing", "big"]:
            mask = df["position_group"] == grp
            if not mask.any():
                continue
            v0_map = DEFAULT_DVP_PRIORS.get(grp, {}).get("v0", {})
            r0_map = DEFAULT_DVP_PRIORS.get(grp, {}).get("r0", {})
            for s in ["pts", "reb", "ast"]:
                v0 = v0_map.get(s, 45.0 if s == "pts" else (15.0 if s == "reb" else 8.0))
                r0 = r0_map.get(s, 0.48 if s == "pts" else (0.18 if s == "reb" else 0.10))
                df.loc[mask, f"dvp_{s}_volume_per100"] = df.loc[mask, f"dvp_{s}_volume_per100"].fillna(v0)
                df.loc[mask, f"dvp_{s}_volume_rank_asc"] = df.loc[mask, f"dvp_{s}_volume_rank_asc"].fillna(15.5)
                df.loc[mask, f"dvp_{s}_volume_rel"] = df.loc[mask, f"dvp_{s}_volume_rel"].fillna(0.0)
                df.loc[mask, f"dvp_{s}_minrate"] = df.loc[mask, f"dvp_{s}_minrate"].fillna(r0)
                df.loc[mask, f"dvp_{s}_minrate_rank_asc"] = df.loc[mask, f"dvp_{s}_minrate_rank_asc"].fillna(15.5)
                df.loc[mask, f"dvp_{s}_minrate_rel"] = df.loc[mask, f"dvp_{s}_minrate_rel"].fillna(0.0)
        return df

    if (
        team_logs_df is None 
        or team_logs_df.empty 
        or "opponent_abbr" not in res.columns 
        or "game_date" not in res.columns
    ):
        for col in dvp_metric_cols:
            res[col] = np.nan
        return _fill_fallbacks(res)

    obs = build_dvp_game_observations(player_df, team_logs_df, pos_df=pos_df)
    if obs.empty:
        for col in dvp_metric_cols:
            res[col] = np.nan
        return _fill_fallbacks(res)

    obs["game_date"] = obs["game_date"].astype(str).str[:10]

    unique_dates = sorted(res["game_date"].dropna().astype(str).unique())
    lookup_records = []

    for raw_d in unique_dates:
        d_cutoff = raw_d[:10]
        prof = compute_dvp_team_profiles_asof(obs, d_cutoff, window_k=window_k)
        if prof.empty:
            continue

        for _, row in prof.iterrows():
            team = row["team_abbreviation"]
            supp = bool(row.get("dvp_supported", True))
            for grp in ["guard", "wing", "big"]:
                rec = {
                    "game_date": raw_d,
                    "opponent_abbr": team,
                    "position_group": grp,
                    "dvp_supported": supp,
                }
                for s in ["pts", "reb", "ast"]:
                    prefix = f"dvp_{s}_{grp}"
                    rec[f"dvp_{s}_volume_per100"] = row.get(f"{prefix}_volume_per100", np.nan)
                    rec[f"dvp_{s}_volume_rank_asc"] = row.get(f"{prefix}_volume_rank_asc", np.nan)
                    rec[f"dvp_{s}_volume_rel"] = row.get(f"{prefix}_volume_rel", np.nan)
                    rec[f"dvp_{s}_minrate"] = row.get(f"{prefix}_minrate", np.nan)
                    rec[f"dvp_{s}_minrate_rank_asc"] = row.get(f"{prefix}_minrate_rank_asc", np.nan)
                    rec[f"dvp_{s}_minrate_rel"] = row.get(f"{prefix}_minrate_rel", np.nan)
                lookup_records.append(rec)

    if lookup_records:
        lookup_df = pd.DataFrame(lookup_records)
        lookup_df = lookup_df.drop_duplicates(subset=["game_date", "opponent_abbr", "position_group"])
        res = res.merge(lookup_df, on=["game_date", "opponent_abbr", "position_group"], how="left")
    else:
        for col in dvp_metric_cols:
            res[col] = np.nan

    res = _fill_fallbacks(res)
    return res
