import pytest
import numpy as np
import pandas as pd
from src.features.opponent_interactions import compute_opponent_feature_interactions

def test_compute_opponent_feature_interactions():
    df = pd.DataFrame([{
        "fga_roll_mean_10": 15.0,
        "fg3a_roll_mean_10": 6.0,   # 3PA share = 6/15 = 0.4, 2PA share = 9/15 = 0.6
        "fta_roll_mean_10": 5.0,
        "ast_roll_mean_10": 7.0,
        "reb_roll_mean_10": 8.0,
        "min_roll_mean_10": 30.0,
        "opp_fg3m_allowed_log_relative_prev10": 0.15,
        "opp_fta_allowed_log_relative_prev10": 0.10,
        "opp_blocks_made_log_relative_prev10": -0.05,
        "opp_ast_allowed_log_relative_prev10": 0.20,
        "opp_missed_fga_log_relative_prev10": 0.08,
    }])

    res = compute_opponent_feature_interactions(df)
    
    # 3PA share * log_rel = 0.4 * 0.15 = 0.06
    assert abs(res["interact_pts_3pa_x_opp_3pm_allowed"].iloc[0] - 0.06) < 1e-5
    # FTA rate * log_rel = (5.0 / 30.0) * 0.10 = 0.0166667
    assert abs(res["interact_pts_fta_x_opp_fta_allowed"].iloc[0] - (5.0 / 30.0) * 0.10) < 1e-5
    # 2PA share * log_rel = 0.6 * (-0.05) = -0.03
    assert abs(res["interact_pts_2pt_x_opp_blocks_made"].iloc[0] - (-0.03)) < 1e-5
    # AST rate * log_rel = (7.0 / 30.0) * 0.20
    assert abs(res["interact_ast_rate_x_opp_ast_allowed"].iloc[0] - (7.0 / 30.0) * 0.20) < 1e-5
    # REB rate * log_rel = (8.0 / 30.0) * 0.08
    assert abs(res["interact_reb_dreb_x_opp_missed_fga"].iloc[0] - (8.0 / 30.0) * 0.08) < 1e-5
