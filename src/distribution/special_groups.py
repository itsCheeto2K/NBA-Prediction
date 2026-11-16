"""
Module: Special Groups Management (§9 & §10)
Handles:
- Rookies and low-history players (§9.1)
- Long absence and return episodes (§9.2, §6)
- Team changes and stint tracking (§9.3, §7)
- Role shifts and rotation context (§8)
- Operational state precedence and diagnostics (§10)
- Dispersion handling without ad-hoc post-hoc inflation (§4, §5)
"""

from typing import Any, Dict, List, Optional, Union
import numpy as np
import pandas as pd


def calculate_return_episode_state(
    appearance_dates: Union[List[pd.Timestamp], np.ndarray, pd.Series],
    cutoff_dt: pd.Timestamp,
    threshold_days: float = 14.0,
    max_active_appearances: int = 3,
) -> Dict[str, Any]:
    """
    Computes deterministic return episode state machine following §6.
    
    Rules:
    - Appearances are strictly before cutoff_dt and completed (min > 0, verified).
    - An episode is triggered if elapsed inactivity between appearances >= threshold_days (14.0 days).
    - If days since last appearance >= 14.0, target is a return_candidate (episode count 0).
    - If target is within the first 3 appearances (counts 0, 1, 2) since a gap >= 14 days,
      return_episode_active is True.
    - At count 3 (after 3 appearances have been observed), the episode is concluded (active=False).
    - DNP does not increment return count.
    """
    if len(appearance_dates) == 0:
        return {
            "days_since_last_appearance": np.nan,
            "long_absence_flag": False,
            "return_candidate": False,
            "return_games_observed": 0,
            "return_episode_active": False,
            "unknown_history": True,
        }

    # Ensure timestamps are sorted
    dates = pd.to_datetime(appearance_dates)
    past_mask = dates < cutoff_dt
    if not np.any(past_mask):
        return {
            "days_since_last_appearance": np.nan,
            "long_absence_flag": False,
            "return_candidate": False,
            "return_games_observed": 0,
            "return_episode_active": False,
            "unknown_history": True,
        }

    valid_past = pd.Series(dates[past_mask]).sort_values().reset_index(drop=True)
    last_app_dt = valid_past.iloc[-1]
    days_since = max(0.0, float((cutoff_dt - last_app_dt).total_seconds() / 86400.0))
    long_absence = days_since >= threshold_days

    # Target immediately follows an elapsed gap >= 14 days
    if long_absence:
        return {
            "days_since_last_appearance": round(days_since, 2),
            "long_absence_flag": True,
            "return_candidate": True,
            "return_games_observed": 0,
            "return_episode_active": True,
            "unknown_history": False,
        }

    # If days_since < 14, check if an earlier return episode is still active
    # Find all consecutive appearance gaps >= threshold_days
    if len(valid_past) >= 2:
        gaps_sec = (valid_past.iloc[1:].to_numpy() - valid_past.iloc[:-1].to_numpy()).astype("timedelta64[s]").astype(float)
        gap_days = gaps_sec / 86400.0
        gap_indices = np.where(gap_days >= threshold_days)[0]
        if len(gap_indices) > 0:
            last_gap_idx = gap_indices[-1]  # index in valid_past[:-1]
            # The appearance that returned was at last_gap_idx + 1
            # Number of appearances observed since that return appearance (including the return game itself):
            apps_since_return = len(valid_past) - (last_gap_idx + 1)
            is_active = (apps_since_return < max_active_appearances)
            return {
                "days_since_last_appearance": round(days_since, 2),
                "long_absence_flag": False,
                "return_candidate": False,
                "return_games_observed": int(apps_since_return),
                "return_episode_active": bool(is_active),
                "unknown_history": False,
            }

    return {
        "days_since_last_appearance": round(days_since, 2),
        "long_absence_flag": False,
        "return_candidate": False,
        "return_games_observed": 0,
        "return_episode_active": False,
        "unknown_history": False,
    }


def calculate_team_stint_state(
    team_history: Union[List[str], np.ndarray, pd.Series],
    current_team: Optional[str] = None,
    max_recent_transfer_games: int = 10,
) -> Dict[str, Any]:
    """
    Computes continuous team stint tracking and transfer flag following §7.
    
    Replaces naive `games_current_team < nba_games_observed` with:
    - `games_current_stint_observed`: appearances in the current continuous block with current_team.
    - `team_change_observed`: whether the player previously played for a different NBA team.
    - `recent_transfer_flag`: True if team_change_observed and games_current_stint_observed < 10.
    """
    if len(team_history) == 0 or current_team is None:
        return {
            "games_current_stint_observed": 0,
            "team_change_observed": False,
            "recent_transfer_flag": False,
            "membership_known": False,
        }

    t_list = list(team_history)
    n_total = len(t_list)

    # Count backwards consecutive appearances matching current_team
    stint_count = 0
    for t in reversed(t_list):
        if t == current_team:
            stint_count += 1
        else:
            break

    # Check if any appearance prior to this stint belonged to another team
    prior_teams = t_list[: n_total - stint_count]
    team_change_observed = any(t != current_team and t is not None for t in prior_teams)
    recent_transfer = bool(team_change_observed and (stint_count < max_recent_transfer_games))

    return {
        "games_current_stint_observed": stint_count,
        "team_change_observed": team_change_observed,
        "recent_transfer_flag": recent_transfer,
        "membership_known": True,
    }


def assess_player_condition(
    row: Union[pd.Series, Dict[str, Any]],
    has_valid_model: bool = True,
    has_valid_prior: bool = True,
) -> Dict[str, Any]:
    """
    Assess operational data quality status and scenario conditions following §9, §10, and §13.
    
    Strict Precedence Order (§10.2):
    1. INSUFFICIENT_DATA (Highest priority):
       - Critical schema fail, player unresolved, missing prior or model.
       - Forecast and EV are NOT issued.
    2. SCENARIO_ONLY:
       - Player ruled OUT or SUSPENDED -> forecast not issued.
       - Questionable / Doubtful injury status -> conditional scenario only.
       - Active return episode (within 3 games of gap >= 14 days) -> minutes limit scenario.
       - Role shift candidate (|trend_5v20| >= 5 min).
       - Low history cohort (< 5 games) -> wide prior-backed scenario.
    3. READY:
       - Integrity passed, support floor met.
       - Forecast issued with explicit conditioning: 'given_player_enters_game'.
       - Never labeled as 'absolute certainty' or 'full confidence'.
    """
    def get_val(key: str, default: Any = None) -> Any:
        if isinstance(row, dict):
            val = row.get(key, default)
        else:
            val = row.get(key, default) if hasattr(row, "get") else default
        return default if pd.isna(val) else val

    # 1. Integrity check
    player_id = get_val("player_id")
    n_games = int(get_val("n_games_history", get_val("nba_games_observed", 0)))
    min_roll = float(get_val("min_roll_mean_5", 0.0))
    rest_days = get_val("rest_days", get_val("days_since_last_appearance"))
    rest_days_val = float(rest_days) if rest_days is not None else None

    # Flags
    own_status = str(get_val("injury_status", get_val("own_status", "ACTIVE"))).upper()
    is_true_rookie = bool(get_val("is_true_rookie_verified", False))
    low_history = n_games < 5

    # Return episode
    return_candidate = bool(get_val("return_candidate", False))
    return_games_obs = int(get_val("return_games_observed", 0))
    return_ep_active = bool(get_val("return_episode_active", False))
    long_absence = bool(get_val("long_absence_flag", (rest_days_val is not None and rest_days_val >= 14.0)))

    if not return_ep_active and long_absence:
        return_candidate = True
        return_ep_active = True

    # Transfer & Role shift
    recent_transfer = bool(get_val("recent_transfer_flag", False))
    role_shift = bool(get_val("role_shift_candidate", False))
    low_minutes = bool(min_roll < 10.0 and n_games >= 5)

    reason_codes: List[str] = []

    # --- Precedence 1: INSUFFICIENT_DATA ---
    if player_id is None or not has_valid_prior or not has_valid_model:
        reason_codes.append("SCHEMA_OR_MODEL_UNAVAILABLE")
        operational_state = "INSUFFICIENT_DATA"
        forecast_status = "not_issued"
        action = "Do not issue probabilities or EV; missing model or prior lineage."
    elif n_games == 0 and not has_valid_prior:
        reason_codes.append("ZERO_HISTORY_NO_PRIOR")
        operational_state = "INSUFFICIENT_DATA"
        forecast_status = "not_issued"
        action = "Do not issue probabilities or EV; player has zero history and no usable prior."

    # --- Precedence 2: SCENARIO_ONLY ---
    elif own_status in ("OUT", "SUSPENDED"):
        reason_codes.append("PLAYER_RULED_OUT")
        operational_state = "SCENARIO_ONLY"
        forecast_status = "not_issued"
        action = f"Player officially ruled {own_status}. No in-game prop forecast issued."
    elif own_status in ("QUESTIONABLE", "DOUBTFUL", "DAY-TO-DAY"):
        reason_codes.append("QUESTIONABLE_INJURY_STATUS")
        operational_state = "SCENARIO_ONLY"
        forecast_status = "conditional_scenario"
        action = "Player listed as questionable/doubtful; output conditional participation scenario."
    elif return_ep_active:
        reason_codes.append("RETURN_EPISODE_ACTIVE")
        operational_state = "SCENARIO_ONLY"
        forecast_status = "conditional_scenario"
        action = (
            f"Player returning after long absence ({rest_days_val:.1f} days, appearance {return_games_obs+1}/3). "
            "Monitor potential minutes restriction."
        )
    elif low_history:
        reason_codes.append("LOW_HISTORY_COHORT")
        operational_state = "SCENARIO_ONLY"
        forecast_status = "conditional_scenario"
        action = f"Player has observed history of {n_games} games (<5). Heavy shrinkage to position/league prior."
    elif role_shift:
        reason_codes.append("ROLE_SHIFT_UNVALIDATED")
        operational_state = "SCENARIO_ONLY"
        forecast_status = "conditional_scenario"
        action = "Recent minutes trend indicates rotation shift (|trend_5v20| >= 5.0m)."
    elif low_minutes:
        # Note per §10.2: low minutes alone is not a failure if player has long history, but flagged
        reason_codes.append("BENCH_LIMITED_ROTATION")
        operational_state = "READY"
        forecast_status = "issued"
        action = "Limited rotation player (<10 min avg). Standard forecast issued with bench conditioning."

    # --- Precedence 3: READY ---
    else:
        reason_codes.append("STANDARD_PRODUCTION_SUPPORT")
        operational_state = "READY"
        forecast_status = "issued"
        action = "Standard model forecast issued given player enters game."

    return {
        "operational_state": operational_state,
        "status": operational_state,  # Backward compatibility alias
        "reason_codes": reason_codes,
        "conditioning": "given_player_enters_game" if forecast_status != "not_issued" else "unconditional_not_issued",
        "forecast_status": forecast_status,
        "flags": {
            "insufficient_data": operational_state == "INSUFFICIENT_DATA",
            "low_history_flag": low_history,
            "long_absence_flag": long_absence,
            "return_candidate": return_candidate,
            "return_games_observed": return_games_obs,
            "return_episode_active": return_ep_active,
            "returning_from_rest": return_ep_active,  # Backward compatibility alias
            "recent_transfer_flag": recent_transfer,
            "role_shift_candidate": role_shift,
            "low_minutes_role": low_minutes,
            "own_status": own_status,
            "is_true_rookie_verified": is_true_rookie,
        },
        "metadata": {
            "n_games_history": n_games,
            "rest_days": round(rest_days_val, 1) if rest_days_val is not None else None,
            "days_since_last_appearance": round(rest_days_val, 1) if rest_days_val is not None else None,
            "min_roll_mean_5": round(min_roll, 1),
            "return_games_observed": return_games_obs,
        },
        "action": action,
        "recipe_version": "special_groups_v2",
    }


def adjust_dispersion_for_uncertainty(
    base_phi: float,
    n_eff: float = 20.0,
    is_returning: bool = False,
    mode: str = "pooled",
) -> float:
    """
    Evaluates count dispersion parameter phi for Negative Binomial distribution (§4, §5).
    
    CRITICAL STATISTICAL NOTICE (§4, §4.1):
    In NB2 with mean mu and dispersion phi, Var = mu + phi * mu^2.
    Artificially inflating phi with ad-hoc terms (e.g. +0.02*(5-ESS) or +0.04)
    does NOT preserve the median, heavily inflates upper tail probabilities (Over),
    and violates calibration guarantees without empirical validation.
    
    Default Production Mode:
    - 'pooled': Uses the empirically fitted/validated baseline phi (e.g. 0.04 for PTS, 0.08 for REB, 0.09 for AST).
    
    Experimental Comparison Mode:
    - 'legacy_manual_inflation': Preserved strictly as an unvalidated legacy experiment.
    """
    if mode == "pooled":
        return round(float(base_phi), 4)

    if mode == "legacy_manual_inflation":
        adjusted = float(base_phi)
        if n_eff < 5.0:
            uncertainty_boost = (5.0 - max(n_eff, 0.0)) * 0.02
            adjusted += uncertainty_boost
        if is_returning:
            adjusted += 0.04
        return round(float(adjusted), 4)

    raise ValueError(f"Unknown dispersion adjustment mode: '{mode}'. Choose 'pooled' or 'legacy_manual_inflation'.")
