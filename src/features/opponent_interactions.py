"""Cross-feature interactions between player profiles and opponent defensive allowances."""
import numpy as np
import pandas as pd

def compute_opponent_feature_interactions(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute specific interactions (§11):
    - PTS: 3PA share * opp_fg3m_allowed_log_rel, FTA rate * opp_fta_allowed_log_rel, 2PA share * opp_blocks_made_log_rel
    - AST: AST rate * opp_ast_allowed_log_rel
    - REB: DREB rate * opp_missed_fga_log_rel
    """
    res = df.copy()

    fga = res.get("fga_roll_mean_10", res.get("fga_roll_mean_5", 10.0))
    fg3a = res.get("fg3a_roll_mean_10", res.get("fg3a_roll_mean_5", 3.0))
    fta = res.get("fta_roll_mean_10", res.get("fta_roll_mean_5", 3.0))
    ast = res.get("ast_roll_mean_10", res.get("ast_roll_mean_5", 3.0))
    reb = res.get("reb_roll_mean_10", res.get("reb_roll_mean_5", 5.0))
    mins = np.maximum(res.get("min_roll_mean_10", res.get("min_roll_mean_5", 25.0)), 5.0)

    # Safe shares and rates
    fga_safe = np.maximum(fga, 1.0)
    p_3pa_share = np.clip(fg3a / fga_safe, 0.0, 1.0)
    p_2pa_share = np.clip((fga - fg3a) / fga_safe, 0.0, 1.0)
    p_fta_rate = fta / mins
    p_ast_rate = ast / mins
    p_reb_rate = reb / mins

    # Opponent log-relatives (default 0.0 if not present)
    opp_3pm_rel = res.get("opp_fg3m_allowed_log_relative_prev10", 0.0)
    opp_fta_rel = res.get("opp_fta_allowed_log_relative_prev10", 0.0)
    opp_blk_rel = res.get("opp_blocks_made_log_relative_prev10", 0.0)
    opp_ast_rel = res.get("opp_ast_allowed_log_relative_prev10", 0.0)
    opp_missed_rel = res.get("opp_missed_fga_log_relative_prev10", 0.0)

    # Compute explicit interactions
    res["interact_pts_3pa_x_opp_3pm_allowed"] = p_3pa_share * opp_3pm_rel
    res["interact_pts_fta_x_opp_fta_allowed"] = p_fta_rate * opp_fta_rel
    res["interact_pts_2pt_x_opp_blocks_made"] = p_2pa_share * opp_blk_rel
    res["interact_ast_rate_x_opp_ast_allowed"] = p_ast_rate * opp_ast_rel
    res["interact_reb_dreb_x_opp_missed_fga"] = p_reb_rate * opp_missed_rel

    return res
