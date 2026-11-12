from typing import Dict, Optional, Tuple
import numpy as np
import pandas as pd

# League prior defaults for early season / missing data
PRIOR_PACE = 100.0
PRIOR_DEF_RATING = 115.0
PRIOR_AST_PER100 = 25.0
PRIOR_DREB_SHARE = 0.75
PRIOR_FG3A_SHARE = 0.38

def compute_team_game_stats_extended(team_logs_df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute game-level possession and opponent stats conceded (points, assists, rebounds).
    """
    df = team_logs_df.copy()
    
    # Fill standard columns if missing
    for col in ["fga", "fta", "oreb", "dreb", "tov", "ast", "fg3a", "pts"]:
        if col not in df.columns:
            df[col] = 0.0
            
    # Estimate possessions: 0.96 * (FGA + 0.44 * FTA - OREB + TOV)
    df["possessions"] = np.maximum(
        0.96 * (df["fga"] + 0.44 * df["fta"] - df["oreb"] + df["tov"]),
        40.0,
    )

    # Map game opponents
    lookup = df.set_index(["game_id", "team_abbreviation"]).to_dict(orient="index")
    
    pts_allowed_list = []
    ast_allowed_list = []
    opp_fga_list = []
    opp_fta_list = []
    opp_fg3a_list = []
    opp_oreb_list = []
    opp_tov_list = []
    def_poss_list = []

    for _, row in df.iterrows():
        gid = row["game_id"]
        team = row["team_abbreviation"]

        # Find opponent in same game_id
        other_teams = [t for (g, t) in lookup.keys() if g == gid and t != team]
        if other_teams:
            opp_team = other_teams[0]
            opp_row = lookup[(gid, opp_team)]
            pts_allowed = opp_row.get("pts", 100.0)
            ast_allowed = opp_row.get("ast", 25.0)
            opp_fga = opp_row.get("fga", 85.0)
            opp_fta = opp_row.get("fta", 20.0)
            opp_fg3a = opp_row.get("fg3a", 30.0)
            opp_oreb = opp_row.get("oreb", 10.0)
            opp_tov = opp_row.get("tov", 13.0)
            def_poss = opp_row.get("possessions", 100.0)
        else:
            pts_allowed = 100.0
            ast_allowed = 25.0
            opp_fga = 85.0
            opp_fta = 20.0
            opp_fg3a = 30.0
            opp_oreb = 10.0
            opp_tov = 13.0
            def_poss = 100.0

        pts_allowed_list.append(pts_allowed)
        ast_allowed_list.append(ast_allowed)
        opp_fga_list.append(opp_fga)
        opp_fta_list.append(opp_fta)
        opp_fg3a_list.append(opp_fg3a)
        opp_oreb_list.append(opp_oreb)
        opp_tov_list.append(opp_tov)
        def_poss_list.append(def_poss)

    df["pts_allowed"] = pts_allowed_list
    df["ast_allowed"] = ast_allowed_list
    df["opp_fga"] = opp_fga_list
    df["opp_fta"] = opp_fta_list
    df["opp_fg3a"] = opp_fg3a_list
    df["opp_oreb"] = opp_oreb_list
    df["opp_tov"] = opp_tov_list
    df["def_possessions"] = def_poss_list

    return df

def compute_opponent_p0_features(
    player_df: pd.DataFrame,
    team_logs_df: pd.DataFrame,
    window: int = 10,
) -> pd.DataFrame:
    """
    Compute historical rolling opponent defensive metrics per 100 possessions strictly before game date.
    """
    if team_logs_df.empty or "opponent_abbr" not in player_df.columns:
        return player_df

    ext_team = compute_team_game_stats_extended(team_logs_df)
    ext_team["game_date_dt"] = pd.to_datetime(ext_team["game_date"])
    ext_team = ext_team.sort_values(by=["team_abbreviation", "game_date_dt", "game_id"]).reset_index(drop=True)

    # Compute rolling metrics per team
    grouped = ext_team.groupby("team_abbreviation")
    
    team_opp_metrics: Dict[Tuple[str, str], Dict[str, float]] = {}

    for team, group in grouped:
        dates = group["game_date_dt"].to_numpy()
        gids = group["game_id"].to_numpy()
        pts_alw = group["pts_allowed"].to_numpy()
        ast_alw = group["ast_allowed"].to_numpy()
        def_poss = group["def_possessions"].to_numpy()
        poss = group["possessions"].to_numpy()
        dreb = group["dreb"].to_numpy()
        opp_oreb = group["opp_oreb"].to_numpy()
        opp_fg3a = group["opp_fg3a"].to_numpy()
        opp_fga = group["opp_fga"].to_numpy()
        
        n = len(group)
        for i in range(n):
            gid = str(gids[i])
            if i == 0:
                team_opp_metrics[(team, gid)] = {
                    "opp_def_rating_prev10": PRIOR_DEF_RATING,
                    "opp_pace_prev10": PRIOR_PACE,
                    "opp_allowed_ast_per100_prev10": PRIOR_AST_PER100,
                    "opp_dreb_share_prev10": PRIOR_DREB_SHARE,
                    "opp_fg3a_share_prev10": PRIOR_FG3A_SHARE,
                    "opp_sample_games": 0,
                    "opp_feature_missing": 1,
                }
                continue

            # Prior window games [max(0, i-window) .. i-1]
            w_start = max(0, i - window)
            w_pts = np.sum(pts_alw[w_start:i])
            w_def_poss = np.sum(def_poss[w_start:i])
            w_ast = np.sum(ast_alw[w_start:i])
            w_poss = np.mean(poss[w_start:i])
            w_dreb = np.sum(dreb[w_start:i])
            w_opp_oreb = np.sum(opp_oreb[w_start:i])
            w_opp_fg3a = np.sum(opp_fg3a[w_start:i])
            w_opp_fga = np.sum(opp_fga[w_start:i])

            def_rtg = (100.0 * w_pts / w_def_poss) if w_def_poss > 0 else PRIOR_DEF_RATING
            ast_per100 = (100.0 * w_ast / w_def_poss) if w_def_poss > 0 else PRIOR_AST_PER100
            dreb_share = (w_dreb / (w_dreb + w_opp_oreb)) if (w_dreb + w_opp_oreb) > 0 else PRIOR_DREB_SHARE
            fg3a_share = (w_opp_fg3a / w_opp_fga) if w_opp_fga > 0 else PRIOR_FG3A_SHARE

            team_opp_metrics[(team, gid)] = {
                "opp_def_rating_prev10": round(float(def_rtg), 2),
                "opp_pace_prev10": round(float(w_poss), 2),
                "opp_allowed_ast_per100_prev10": round(float(ast_per100), 2),
                "opp_dreb_share_prev10": round(float(dreb_share), 3),
                "opp_fg3a_share_prev10": round(float(fg3a_share), 3),
                "opp_sample_games": i - w_start,
                "opp_feature_missing": 0,
            }

    # Merge onto player_df via (opponent_abbr, game_id)
    res = player_df.copy()
    
    def_rtg_col = []
    pace_col = []
    ast_col = []
    dreb_col = []
    fg3a_col = []
    samples_col = []
    missing_col = []

    for _, row in res.iterrows():
        opp = row.get("opponent_abbr")
        gid = str(row.get("game_id"))
        
        m = team_opp_metrics.get((opp, gid), {
            "opp_def_rating_prev10": PRIOR_DEF_RATING,
            "opp_pace_prev10": PRIOR_PACE,
            "opp_allowed_ast_per100_prev10": PRIOR_AST_PER100,
            "opp_dreb_share_prev10": PRIOR_DREB_SHARE,
            "opp_fg3a_share_prev10": PRIOR_FG3A_SHARE,
            "opp_sample_games": 0,
            "opp_feature_missing": 1,
        })
        def_rtg_col.append(m["opp_def_rating_prev10"])
        pace_col.append(m["opp_pace_prev10"])
        ast_col.append(m["opp_allowed_ast_per100_prev10"])
        dreb_col.append(m["opp_dreb_share_prev10"])
        fg3a_col.append(m["opp_fg3a_share_prev10"])
        samples_col.append(m["opp_sample_games"])
        missing_col.append(m["opp_feature_missing"])

    res["opp_def_rating_prev10"] = def_rtg_col
    res["opp_pace_prev10"] = pace_col
    res["opp_allowed_ast_per100_prev10"] = ast_col
    res["opp_dreb_share_prev10"] = dreb_col
    res["opp_fg3a_share_prev10"] = fg3a_col
    res["opp_sample_games"] = samples_col
    res["opp_feature_missing"] = missing_col

    return res
