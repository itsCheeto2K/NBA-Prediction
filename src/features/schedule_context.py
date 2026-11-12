from datetime import timedelta
from typing import Optional
import numpy as np
import pandas as pd

def compute_team_schedule_table(team_logs_df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute team schedule metrics: rest days, b2b, 3-in-4, 4-in-6 congestion.
    """
    if team_logs_df.empty:
        return pd.DataFrame()

    df = team_logs_df[["team_abbreviation", "game_id", "game_date"]].drop_duplicates().copy()
    df["game_date_dt"] = pd.to_datetime(df["game_date"])
    df = df.sort_values(by=["team_abbreviation", "game_date_dt", "game_id"]).reset_index(drop=True)

    grouped = df.groupby("team_abbreviation")
    prev_date = grouped["game_date_dt"].shift(1)
    days_diff = (df["game_date_dt"] - prev_date).dt.days

    df["b2b"] = (days_diff == 1).astype(int)
    # Default rest days is 3.0 if no prior game
    df["rest_days"] = np.where(days_diff.isna(), 3, np.maximum(0, days_diff - 1)).astype(int)

    # Congestion: 3 in 4 days and 4 in 6 days
    is_3in4 = []
    is_4in6 = []

    for team, group in grouped:
        dates = group["game_date_dt"].to_numpy()
        n = len(dates)
        for i in range(n):
            curr_d = dates[i]
            # Games in [curr_d - 3 days, curr_d]
            start_3d = curr_d - np.timedelta64(3, "D")
            count_3d = np.sum((dates[:i+1] >= start_3d) & (dates[:i+1] <= curr_d))
            is_3in4.append(int(count_3d >= 3))

            # Games in [curr_d - 5 days, curr_d]
            start_5d = curr_d - np.timedelta64(5, "D")
            count_5d = np.sum((dates[:i+1] >= start_5d) & (dates[:i+1] <= curr_d))
            is_4in6.append(int(count_5d >= 4))

    df["3in4"] = is_3in4
    df["4in6"] = is_4in6

    return df

def compute_team_and_opponent_schedule_context(
    player_df: pd.DataFrame,
    team_logs_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Merge team and opponent schedule context (b2b, rest advantage, congestion) onto player rows.
    """
    if team_logs_df.empty or "opponent_abbr" not in player_df.columns:
        return player_df

    res = player_df.copy()
    team_sched = compute_team_schedule_table(team_logs_df)

    # Team lookup map: (team_abbreviation, game_id) -> metrics
    team_map = team_sched.set_index(["team_abbreviation", "game_id"]).to_dict(orient="index")

    team_b2b_list = []
    team_rest_list = []
    team_3in4_list = []
    team_4in6_list = []

    opp_b2b_list = []
    opp_rest_list = []
    opp_3in4_list = []
    opp_4in6_list = []
    rest_adv_list = []

    for _, row in res.iterrows():
        t = row.get("team_abbreviation")
        o = row.get("opponent_abbr")
        gid = row.get("game_id")

        # Team metrics
        t_data = team_map.get((t, gid), {})
        t_b2b = t_data.get("b2b", 0)
        t_rest = t_data.get("rest_days", 2)
        t_3in4 = t_data.get("3in4", 0)
        t_4in6 = t_data.get("4in6", 0)

        team_b2b_list.append(t_b2b)
        team_rest_list.append(t_rest)
        team_3in4_list.append(t_3in4)
        team_4in6_list.append(t_4in6)

        # Opponent metrics
        o_data = team_map.get((o, gid), {})
        o_b2b = o_data.get("b2b", 0)
        o_rest = o_data.get("rest_days", 2)
        o_3in4 = o_data.get("3in4", 0)
        o_4in6 = o_data.get("4in6", 0)

        opp_b2b_list.append(o_b2b)
        opp_rest_list.append(o_rest)
        opp_3in4_list.append(o_3in4)
        opp_4in6_list.append(o_4in6)

        rest_adv_list.append(t_rest - o_rest)

    res["team_b2b"] = team_b2b_list
    res["team_rest_days"] = team_rest_list
    res["team_3in4"] = team_3in4_list
    res["team_4in6"] = team_4in6_list

    res["opp_b2b"] = opp_b2b_list
    res["opp_rest_days"] = opp_rest_list
    res["opp_3in4"] = opp_3in4_list
    res["opp_4in6"] = opp_4in6_list
    res["rest_advantage_days"] = rest_adv_list

    return res

def compute_player_workload_context(player_df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute player-specific workload and rested B2B status following §6.2.
    """
    res = player_df.copy()
    if "game_date" not in res.columns:
        return res

    res["game_date_dt"] = pd.to_datetime(res["game_date"])
    res = res.sort_values(by=["player_id", "game_date_dt", "game_id"]).reset_index(drop=True)

    # 1. Did player play in the team's immediately preceding game?
    res["_is_played"] = (res["min"].fillna(0.0) > 0).astype(int)
    res["player_played_previous_team_game"] = (
        res.groupby("player_id")["_is_played"].shift(1).fillna(1).astype(int)
    )
    res = res.drop(columns=["_is_played"])

    # 2. Team B2B but player rested
    team_b2b_col = res.get("team_b2b", pd.Series([0] * len(res)))
    res["team_b2b_but_player_rested"] = (
        (team_b2b_col == 1) & (res["player_played_previous_team_game"] == 0)
    ).astype(int)

    # 3. Workload from actual played games (min > 0)
    last_game_days = []
    prev_minutes = []
    sum_prev3 = []
    minutes_last7d = []

    grouped = res.groupby("player_id")
    for pid, group in grouped:
        dates = group["game_date_dt"].to_numpy()
        mins = group["min"].fillna(0.0).to_numpy()
        n = len(group)

        for i in range(n):
            if i == 0:
                last_game_days.append(3)
                prev_minutes.append(25.0)
                sum_prev3.append(75.0)
                minutes_last7d.append(0.0)
                continue

            curr_d = dates[i]
            past_dates = dates[:i]
            past_mins = mins[:i]

            # Filter to played games
            played_mask = past_mins > 0
            if not np.any(played_mask):
                last_game_days.append(3)
                prev_minutes.append(25.0)
                sum_prev3.append(75.0)
                minutes_last7d.append(0.0)
                continue

            valid_dates = past_dates[played_mask]
            valid_mins = past_mins[played_mask]

            # Days since last game
            days_since = (curr_d - valid_dates[-1]) / np.timedelta64(1, "D")
            last_game_days.append(int(days_since))
            prev_minutes.append(float(valid_mins[-1]))

            # Sum of minutes in last 3 games
            s3 = float(np.sum(valid_mins[-3:]))
            sum_prev3.append(round(s3, 1))

            # Minutes in the last 7 calendar days [curr_d - 7D, curr_d - 1D]
            start_7d = curr_d - np.timedelta64(7, "D")
            mask_7d = (past_dates >= start_7d) & (past_dates < curr_d)
            m7 = float(np.sum(past_mins[mask_7d]))
            minutes_last7d.append(round(m7, 1))

    res["player_last_game_days"] = last_game_days
    res["player_minutes_prev_game"] = prev_minutes
    res["player_minutes_sum_prev3"] = sum_prev3
    res["player_minutes_last7days"] = minutes_last7d

    res = res.drop(columns=["game_date_dt"])
    return res
