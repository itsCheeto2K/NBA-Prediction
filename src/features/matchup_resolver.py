import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
import numpy as np
import pandas as pd

from src.features.opponent_context import (
    compute_team_game_stats_extended,
    PRIOR_PACE,
    PRIOR_DEF_RATING,
    PRIOR_AST_PER100,
    PRIOR_DREB_SHARE,
    PRIOR_FG3A_SHARE,
)

logger = logging.getLogger(__name__)

def get_team_upcoming_game(
    team_abbr: str,
    sched_df: pd.DataFrame,
    current_vn_time: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """
    Find the next unplayed scheduled game for a team from ScheduleLeagueV2.
    Automatically advances to tomorrow's slate after 1:00 PM Vietnam Time (13:00 VN / 06:00 UTC)
    when all games from today's morning round have concluded.
    """
    if sched_df.empty or "game_status" not in sched_df.columns:
        return None

    from datetime import datetime, timezone, timedelta
    vn_tz = timezone(timedelta(hours=7))
    if current_vn_time is None:
        now_vn = datetime.now(vn_tz)
    else:
        now_vn = current_vn_time.astimezone(vn_tz) if current_vn_time.tzinfo else current_vn_time.replace(tzinfo=vn_tz)

    is_post_1pm = (now_vn.hour >= 13)

    home_col = None
    for cand in ["home_team_tricode", "homeTeam_teamTricode", "homeTeamTricode", "home_team_abbr"]:
        if cand in sched_df.columns:
            home_col = cand
            break

    away_col = None
    for cand in ["away_team_tricode", "awayTeam_teamTricode", "awayTeamTricode", "away_team_abbr"]:
        if cand in sched_df.columns:
            away_col = cand
            break

    if not home_col or not away_col:
        return None

    # Filter unplayed games (game_status == 1)
    unplayed = sched_df[sched_df["game_status"] == 1].copy()
    if unplayed.empty:
        return None

    team_matches = unplayed[(unplayed[home_col] == team_abbr) | (unplayed[away_col] == team_abbr)].copy()
    if team_matches.empty:
        return None

    # Parse tip-off times in Vietnam Time (UTC+7)
    time_col = "game_time_utc" if "game_time_utc" in team_matches.columns else "gameDateTimeEst"
    if time_col in team_matches.columns:
        team_matches["tipoff_dt"] = pd.to_datetime(team_matches[time_col], utc=True, errors="coerce").dt.tz_convert(vn_tz)
    else:
        team_matches["tipoff_dt"] = pd.NaT

    # If it's past 1:00 PM VN, any game that started before 1:00 PM VN today is already finished.
    # We advance to games scheduled after the 1:00 PM VN cutoff.
    valid_matches = team_matches
    if is_post_1pm:
        cutoff_today = now_vn.replace(hour=13, minute=0, second=0, microsecond=0)
        future_or_today_late = team_matches[team_matches["tipoff_dt"].isna() | (team_matches["tipoff_dt"] > cutoff_today)]
        if not future_or_today_late.empty:
            valid_matches = future_or_today_late

    next_match = valid_matches.iloc[0]
    is_home = (next_match[home_col] == team_abbr)
    opp_abbr = next_match[away_col] if is_home else next_match[home_col]
    game_date_us = str(next_match.get("game_date_est", next_match.get("game_time_utc", "")))[:10]
    game_status_text = str(next_match.get("game_status_text", "Scheduled"))

    # Slate classification & True Match Date (in Vietnam Time)
    tipoff_vn_str = ""
    slate_label = "Upcoming"
    tipoff_dt = next_match.get("tipoff_dt")
    if pd.notna(tipoff_dt):
        game_date_vn = tipoff_dt.strftime("%Y-%m-%d")
        tipoff_vn_str = tipoff_dt.strftime("%d/%m/%Y lúc %I:%M %p VN")
        if tipoff_dt.date() == now_vn.date():
            slate_label = "Today"
        elif tipoff_dt.date() == (now_vn + timedelta(days=1)).date():
            slate_label = "Tomorrow"
        else:
            slate_label = tipoff_dt.strftime("%d/%m")
    else:
        game_date_vn = game_date_us

    return {
        "game_id": str(next_match.get("game_id", "")),
        "game_date": game_date_vn,
        "game_date_vn": game_date_vn,
        "game_date_us": game_date_us,
        "is_home": 1 if is_home else 0,
        "opponent_abbr": opp_abbr,
        "game_status_text": game_status_text,
        "home_team": next_match[home_col],
        "away_team": next_match[away_col],
        "slate_label": slate_label,
        "tipoff_vn": tipoff_vn_str,
        "is_post_1pm_rolled": is_post_1pm,
    }

def get_team_current_defensive_profile(
    opp_abbr: str,
    team_logs_df: pd.DataFrame,
    window: int = 10,
) -> Dict[str, float]:
    """
    Compute an opponent's current rolling defensive rating, pace, and conceded stats
    as of today based on their most recent completed games.
    """
    if team_logs_df.empty:
        return {
            "opp_pace_prev10": PRIOR_PACE,
            "opp_def_rating_prev10": PRIOR_DEF_RATING,
            "opp_ast_allowed_per100_prev10": PRIOR_AST_PER100,
            "opp_dreb_share_prev10": PRIOR_DREB_SHARE,
            "opp_fg3a_share_prev10": PRIOR_FG3A_SHARE,
            "opp_pts_allowed_roll": 115.0,
        }

    ext = compute_team_game_stats_extended(team_logs_df)
    team_games = ext[ext["team_abbreviation"] == opp_abbr].sort_values("game_date")
    
    if team_games.empty:
        return {
            "opp_pace_prev10": PRIOR_PACE,
            "opp_def_rating_prev10": PRIOR_DEF_RATING,
            "opp_ast_allowed_per100_prev10": PRIOR_AST_PER100,
            "opp_dreb_share_prev10": PRIOR_DREB_SHARE,
            "opp_fg3a_share_prev10": PRIOR_FG3A_SHARE,
            "opp_pts_allowed_roll": 115.0,
        }

    recent = team_games.tail(window)
    tot_def_poss = recent["def_possessions"].sum()
    tot_pts_allowed = recent["pts_allowed"].sum()
    tot_ast_allowed = recent["ast_allowed"].sum()

    pace = float(recent["possessions"].mean()) if not recent.empty else PRIOR_PACE
    def_rtg = (float(tot_pts_allowed) / float(tot_def_poss) * 100.0) if tot_def_poss > 20 else PRIOR_DEF_RATING
    ast_per100 = (float(tot_ast_allowed) / float(tot_def_poss) * 100.0) if tot_def_poss > 20 else PRIOR_AST_PER100

    tot_dreb = recent["dreb"].sum()
    tot_opp_oreb = recent["opp_oreb"].sum()
    reb_denom = tot_dreb + tot_opp_oreb
    dreb_share = (float(tot_dreb) / float(reb_denom)) if reb_denom > 0 else PRIOR_DREB_SHARE

    tot_opp_fg3a = recent["opp_fg3a"].sum()
    tot_opp_fga = recent["opp_fga"].sum()
    fg3a_share = (float(tot_opp_fg3a) / float(tot_opp_fga)) if tot_opp_fga > 0 else PRIOR_FG3A_SHARE

    pts_allowed_roll = float(recent["pts_allowed"].mean()) if not recent.empty else 115.0

    return {
        "opp_pace_prev10": round(pace, 2),
        "opp_def_rating_prev10": round(def_rtg, 2),
        "opp_ast_allowed_per100_prev10": round(ast_per100, 2),
        "opp_dreb_share_prev10": round(dreb_share, 3),
        "opp_fg3a_share_prev10": round(fg3a_share, 3),
        "opp_pts_allowed_roll": round(pts_allowed_roll, 2),
    }

def resolve_live_matchup_context(
    player_history_row: pd.Series,
    team_abbr: str,
    sched_df: pd.DataFrame,
    team_logs_df: pd.DataFrame,
    opp_override: Optional[str] = None,
) -> Tuple[pd.Series, Dict[str, Any]]:
    """
    Overlays upcoming match context (or opponent override) onto the player's historical feature row.
    Guarantees the model evaluates the player against TODAY'S opponent, not yesterday's!
    """
    feature_row = player_history_row.copy()
    upcoming = get_team_upcoming_game(team_abbr, sched_df)

    active_opp = None
    is_home = int(feature_row.get("is_home", 1))
    game_info = {}

    if upcoming:
        active_opp = upcoming["opponent_abbr"]
        is_home = upcoming["is_home"]
        game_info = {
            "game_id": upcoming["game_id"],
            "game_date": upcoming["game_date"],
            "game_status_text": upcoming["game_status_text"],
            "home_team": upcoming["home_team"],
            "away_team": upcoming["away_team"],
            "scheduled_opponent": upcoming["opponent_abbr"],
            "is_home": bool(upcoming["is_home"] == 1),
            "is_override": False,
            "slate_label": upcoming.get("slate_label", "Upcoming"),
            "tipoff_vn": upcoming.get("tipoff_vn", ""),
            "is_post_1pm_rolled": upcoming.get("is_post_1pm_rolled", False),
        }

    # Handle manual opponent override if requested
    if opp_override and opp_override.strip():
        clean_opp = opp_override.strip().upper()
        active_opp = clean_opp
        game_info["is_override"] = True
        game_info["active_opponent"] = clean_opp
    elif active_opp:
        game_info["active_opponent"] = active_opp
    else:
        active_opp = str(feature_row.get("opponent_abbr", "OPP"))
        game_info["active_opponent"] = active_opp

    # Calculate opponent defensive profile for active_opp
    opp_profile = get_team_current_defensive_profile(active_opp, team_logs_df)

    # Overwrite opponent features in row
    feature_row["opponent_abbr"] = active_opp
    feature_row["is_home"] = is_home
    for k, v in opp_profile.items():
        feature_row[k] = v

    # Overwrite schedule context if upcoming game date is known
    if upcoming and not team_logs_df.empty:
        try:
            today_dt = pd.to_datetime(upcoming.get("game_date_us", upcoming["game_date"]))
            
            # Team last game
            team_games = team_logs_df[team_logs_df["team_abbreviation"] == team_abbr]
            if not team_games.empty:
                last_team_date = pd.to_datetime(team_games["game_date"].max())
                team_rest = max(0, int((today_dt - last_team_date).days) - 1)
                feature_row["team_rest_days"] = team_rest
                feature_row["team_b2b"] = 1 if team_rest == 0 else 0
                feature_row["is_b2b"] = feature_row["team_b2b"]
                feature_row["rest_days"] = team_rest

            # Opponent last game
            opp_games = team_logs_df[team_logs_df["team_abbreviation"] == active_opp]
            if not opp_games.empty:
                last_opp_date = pd.to_datetime(opp_games["game_date"].max())
                opp_rest = max(0, int((today_dt - last_opp_date).days) - 1)
                feature_row["opp_rest_days"] = opp_rest
                feature_row["opp_b2b"] = 1 if opp_rest == 0 else 0
                feature_row["rest_advantage_days"] = int(feature_row.get("team_rest_days", 1)) - opp_rest
        except Exception as e:
            logger.warning(f"Error computing live rest advantage: {e}")

    return feature_row, game_info
