import logging
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Default league rate priors per minute (§6.1)
ROLE_RATE_PRIORS = {
    "fga": 0.40,
    "fta": 0.10,
    "fg3a": 0.15,
    "ast": 0.10,
    "oreb": 0.04,
    "dreb": 0.14,
    "pts": 0.55,
}

BETA_0_MINUTES = 200.0  # Smoothing pseudo-exposure minutes from §6.1
DECAY_HALF_LIFE_DAYS = 20.0  # Exponential decay parameter w_n = 2^(-delta_d / 20)

def compute_exponential_decay_weights(dates_series: pd.Series, cutoff_date: pd.Timestamp) -> np.ndarray:
    """
    Computes time-decay weights w_n = 2^(-Delta d_n / 20) as defined in §6.1.
    """
    days_diff = np.maximum(0.0, (cutoff_date - pd.to_datetime(dates_series)).dt.total_seconds() / 86400.0)
    weights = np.power(2.0, -days_diff / DECAY_HALF_LIFE_DAYS)
    return weights.to_numpy()

def compute_player_rate_and_volume(
    player_history_df: pd.DataFrame,
    cutoff_date: pd.Timestamp,
    quantities: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Calculates smoothed rates rho_iq and volume proxies u_iq = b_i * rho_iq (§6.1).
    Uses at most 20 past games within 365 days.
    """
    if quantities is None:
        quantities = ["fga", "fta", "fg3a", "ast", "oreb", "dreb", "pts"]

    if player_history_df.empty:
        baseline_min = 20.0
        rates = dict(ROLE_RATE_PRIORS)
        volumes = {q: baseline_min * rates[q] for q in quantities}
        return {
            "baseline_minutes": baseline_min,
            "rates": rates,
            "volumes": volumes,
            "games_count": 0,
        }

    df = player_history_df.copy()
    df["game_date_dt"] = pd.to_datetime(df["game_date"])

    # Strict anti-leakage filter: strictly prior to cutoff and within 365 days
    valid_mask = (df["game_date_dt"] < cutoff_date) & (df["game_date_dt"] >= cutoff_date - pd.Timedelta(days=365))
    df = df[valid_mask].sort_values("game_date_dt").tail(20)

    if df.empty or "min" not in df.columns:
        baseline_min = 20.0
        rates = dict(ROLE_RATE_PRIORS)
        volumes = {q: baseline_min * rates[q] for q in quantities}
        return {
            "baseline_minutes": baseline_min,
            "rates": rates,
            "volumes": volumes,
            "games_count": 0,
        }

    # Exponential weights
    weights = compute_exponential_decay_weights(df["game_date_dt"], cutoff_date)
    minutes = df["min"].fillna(0.0).to_numpy()
    sum_w_min = float(np.sum(weights * minutes))

    # Baseline minutes: weighted mean of up to 10 most recent games smoothed with 5 pseudo-games of 20 min
    recent_10 = df.tail(10)
    w_10 = weights[-len(recent_10):]
    m_10 = minutes[-len(recent_10):]
    baseline_min = float((np.sum(w_10 * m_10) + 5.0 * 20.0) / (np.sum(w_10) + 5.0))

    rates = {}
    volumes = {}

    for q in quantities:
        prior_rate = ROLE_RATE_PRIORS.get(q, 0.10)
        q_vals = df[q].fillna(0.0).to_numpy() if q in df.columns else np.zeros_like(minutes)
        sum_w_q = float(np.sum(weights * q_vals))

        # rho_iq = (beta0 * rho_prior + sum(w * X)) / (beta0 + sum(w * M))
        smoothed_rate = (BETA_0_MINUTES * prior_rate + sum_w_q) / (BETA_0_MINUTES + sum_w_min)
        rates[q] = round(float(smoothed_rate), 4)
        volumes[q] = round(float(baseline_min * smoothed_rate), 3)

    return {
        "baseline_minutes": round(baseline_min, 2),
        "rates": rates,
        "volumes": volumes,
        "games_count": len(df),
    }

def compute_missing_role_features(
    target_player_id: int,
    team_roster_profiles: List[Dict[str, Any]],
    participation_probs: Dict[str, float],
    team_totals_prev10: Optional[Dict[str, float]] = None,
) -> Dict[str, float]:
    """
    Computes expected missing role proxies for teammates j != target_player_id (§7.1):
    L_minutes = sum_{j != i} (1 - pi_j) * b_j
    L_q       = sum_{j != i} (1 - pi_j) * u_jq
    Lnorm_q   = L_q / max(1.0, Q_team_q)
    """
    if team_totals_prev10 is None:
        team_totals_prev10 = {
            "fga": 88.0,
            "fta": 22.0,
            "fg3a": 35.0,
            "ast": 26.0,
            "oreb": 10.0,
            "dreb": 34.0,
            "pts": 115.0,
        }

    l_minutes = 0.0
    l_quantities = {q: 0.0 for q in ["fga", "fta", "fg3a", "ast", "oreb", "dreb", "pts"]}
    missing_count = 0.0

    # Top 2 missing role tracking (§4.2 of NBA_MISSING_ROLE_ALLOCATOR_FIX_SPEC.md)
    # Store tuples of (ell_j, pid_str) for deterministic descending sorting
    teammate_lost_items: List[Tuple[float, str]] = []

    for player in team_roster_profiles:
        pid = player["player_id"]
        if pid == target_player_id:
            continue

        p_name = str(player.get("player_name", pid))
        pi = participation_probs.get(str(pid), participation_probs.get(p_name, 0.90))
        prob_absent = max(0.0, 1.0 - pi)
        b_j = player["baseline_minutes"]
        ell_j = prob_absent * b_j

        l_minutes += ell_j
        teammate_lost_items.append((ell_j, str(pid)))

        if prob_absent >= 0.5:
            missing_count += 1.0

        for q in l_quantities.keys():
            u_jq = player["volumes"].get(q, b_j * ROLE_RATE_PRIORS.get(q, 0.10))
            l_quantities[q] += prob_absent * u_jq

    # Sort descending by ell_j, tie-break by player_id string
    teammate_lost_items.sort(key=lambda item: (item[0], item[1]), reverse=True)
    if len(teammate_lost_items) >= 2:
        top2_lost_minutes = float(teammate_lost_items[0][0] + teammate_lost_items[1][0])
    elif len(teammate_lost_items) == 1:
        top2_lost_minutes = float(teammate_lost_items[0][0])
    else:
        top2_lost_minutes = 0.0

    features = {
        "teammate_missing_minutes": round(l_minutes, 2),
        "teammate_missing_min_norm": round(l_minutes / 240.0, 4),
        "teammate_top2_lost_minutes": round(top2_lost_minutes, 2),
        "teammate_expected_absences": round(missing_count, 2),
    }

    for q, val in l_quantities.items():
        q_scale = max(1.0, team_totals_prev10.get(q, 50.0))
        features[f"teammate_missing_{q}"] = round(val, 2)
        features[f"teammate_missing_{q}_norm"] = round(val / q_scale, 4)

    return features


def compute_delta_missing_role_features(
    current_features: Dict[str, float],
    past_team_snapshots: List[Dict[str, float]],
    min_snapshots_required: int = 5,
) -> Dict[str, Any]:
    """
    Computes Delta L_iq = L_iq_now - Lbar_iq following §4.3.
    Requires at least 5 historical snapshots to compute valid delta;
    otherwise returns NaN and sets delta_history_count.
    """
    n_past = len(past_team_snapshots)
    delta_out: Dict[str, Any] = {
        "delta_history_count": n_past,
        "delta_context_ready": n_past >= min_snapshots_required,
    }

    tracked_keys = ["teammate_missing_minutes", "teammate_missing_pts", "teammate_missing_reb", "teammate_missing_ast"]

    if n_past < min_snapshots_required:
        for k in tracked_keys:
            delta_out[f"{k}_delta"] = np.nan
            delta_out[f"{k}_historical_mean"] = np.nan
        return delta_out

    # Compute mean across up to 10 past snapshots
    for k in tracked_keys:
        past_vals = [s.get(k, 0.0) for s in past_team_snapshots if k in s and not pd.isna(s[k])]
        if len(past_vals) >= min_snapshots_required:
            mean_val = float(np.mean(past_vals))
            curr_val = float(current_features.get(k, 0.0))
            delta_out[f"{k}_historical_mean"] = round(mean_val, 2)
            delta_out[f"{k}_delta"] = round(curr_val - mean_val, 2)
        else:
            delta_out[f"{k}_historical_mean"] = np.nan
            delta_out[f"{k}_delta"] = np.nan

    return delta_out


def evaluate_injury_context_support(
    l_minutes: float,
    max_support_ratio: float = 0.45,  # 0.45 * 240 = 108 min missing
) -> Dict[str, Any]:
    """
    Evaluates whether the team injury context is within supported training range (§10).
    Extreme missing minutes (> 45% of team budget) triggers TEAM_CONTEXT_SUPPORT_UNVALIDATED.
    """
    l_norm = l_minutes / 240.0
    is_supported = l_norm <= max_support_ratio
    return {
        "l_minutes_norm": round(l_norm, 4),
        "is_supported": is_supported,
        "reason_code": None if is_supported else "TEAM_CONTEXT_SUPPORT_UNVALIDATED",
    }

def compute_opponent_missing_role_features(
    opponent_roster_profiles: List[Dict[str, Any]],
    participation_probs: Dict[str, float],
    opp_totals_prev10: Optional[Dict[str, float]] = None,
) -> Dict[str, float]:
    """
    Computes expected missing role proxies for the opponent's roster (§7.1).
    """
    if opp_totals_prev10 is None:
        opp_totals_prev10 = {
            "fga": 88.0,
            "fta": 22.0,
            "fg3a": 35.0,
            "ast": 26.0,
            "oreb": 10.0,
            "dreb": 34.0,
            "pts": 115.0,
        }

    l_minutes = 0.0
    l_quantities = {q: 0.0 for q in ["fga", "fta", "fg3a", "ast", "oreb", "dreb", "pts"]}

    for player in opponent_roster_profiles:
        pid = player["player_id"]
        p_name = str(player.get("player_name", pid))
        pi = participation_probs.get(str(pid), participation_probs.get(p_name, 0.90))
        prob_absent = max(0.0, 1.0 - pi)
        b_k = player["baseline_minutes"]

        l_minutes += prob_absent * b_k
        for q in l_quantities.keys():
            u_kq = player["volumes"].get(q, b_k * ROLE_RATE_PRIORS.get(q, 0.10))
            l_quantities[q] += prob_absent * u_kq

    features = {
        "opp_missing_minutes": round(l_minutes, 2),
        "opp_missing_min_norm": round(l_minutes / 240.0, 4),
    }

    for q, val in l_quantities.items():
        q_scale = max(1.0, opp_totals_prev10.get(q, 50.0))
        features[f"opp_missing_{q}"] = round(val, 2)
        features[f"opp_missing_{q}_norm"] = round(val / q_scale, 4)

    return features

def compute_own_injury_return_features(
    player_history_df: pd.DataFrame,
    cutoff_date: pd.Timestamp,
    current_status: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Computes own injury and return trajectory features (§8.1):
    - days_since_last_appearance
    - is_long_absence_return (>= 14 days)
    - games_since_return
    """
    status_clean = str(current_status or "available").lower().strip()
    status_code_map = {
        "available": 0,
        "not_listed": 0,
        "probable": 1,
        "day-to-day": 2,
        "questionable": 3,
        "doubtful": 4,
        "out": 5,
        "unknown": 2,
    }
    status_code = status_code_map.get(status_clean, 0)

    if player_history_df.empty or "game_date" not in player_history_df.columns:
        return {
            "own_status_code": status_code,
            "own_is_questionable": int(status_clean in ("questionable", "day-to-day")),
            "own_is_doubtful": int(status_clean == "doubtful"),
            "own_is_out": int(status_clean == "out"),
            "days_since_last_appearance": 3,
            "is_long_absence_return": 0,
            "games_since_return": 10,
        }

    df = player_history_df.copy()
    df["game_date_dt"] = pd.to_datetime(df["game_date"])
    past_games = df[df["game_date_dt"] < cutoff_date].sort_values("game_date_dt")

    if past_games.empty:
        return {
            "own_status_code": status_code,
            "own_is_questionable": int(status_clean in ("questionable", "day-to-day")),
            "own_is_doubtful": int(status_clean == "doubtful"),
            "own_is_out": int(status_clean == "out"),
            "days_since_last_appearance": 3,
            "is_long_absence_return": 0,
            "games_since_return": 10,
        }

    last_game_date = past_games.iloc[-1]["game_date_dt"]
    days_since_last = max(0, int((cutoff_date - last_game_date).days))

    # Detect 14+ day gap in history
    dates = past_games["game_date_dt"].tolist()
    gaps = [(dates[i] - dates[i - 1]).days for i in range(1, len(dates))]
    
    # Check if returning from a recent long absence (>= 14 days)
    is_long_absence_return = 1 if days_since_last >= 14 else 0
    games_since_return = 10

    for idx, gap in enumerate(reversed(gaps)):
        if gap >= 14:
            games_since_return = idx + 1
            break

    return {
        "own_status_code": status_code,
        "own_is_questionable": int(status_clean in ("questionable", "day-to-day")),
        "own_is_doubtful": int(status_clean == "doubtful"),
        "own_is_out": int(status_clean == "out"),
        "days_since_last_appearance": days_since_last,
        "is_long_absence_return": is_long_absence_return,
        "games_since_return": min(10, games_since_return),
    }
