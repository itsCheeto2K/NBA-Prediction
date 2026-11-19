import numpy as np
import pandas as pd
import pandas.testing as pdt

from src.features.extended_stats import EXTENDED_FEATURE_COLS, RAW_STATS, compute_extended_stats
from src.features.target import latest_player_states


def games():
    df = pd.DataFrame({c: [1., 2., 3., 4.] for c in RAW_STATS})
    df["player_id"] = 10
    df["game_id"] = ["1", "2", "3", "4"]
    df["game_date"] = pd.date_range("2025-01-01", periods=4)
    df["season"] = "2024-25"
    df["min"] = 30.
    df["fga"] = [2., 10., 8., 12.]
    df["fgm"] = [1., 8., 4., 6.]
    return df


def test_current_and_future_results_cannot_change_pregame_features():
    df = games()
    before = compute_extended_stats(df)
    df.loc[2:, list(RAW_STATS)] = 999.
    after = compute_extended_stats(df)
    pdt.assert_frame_equal(before.loc[:2, EXTENDED_FEATURE_COLS], after.loc[:2, EXTENDED_FEATURE_COLS])
    assert before.loc[0, EXTENDED_FEATURE_COLS].isna().all()


def test_weighted_percentages_and_zero_exposure():
    df = games()
    df["fg3a"] = 0.
    out = compute_extended_stats(df)
    assert np.isclose(out.loc[2, "ext_fg_pct_5"], 9 / 12)
    assert np.isnan(out.loc[2, "ext_fg3_pct_5"])
    df.loc[0, "fgm"] = np.nan
    out = compute_extended_stats(df)
    assert np.isclose(out.loc[2, "ext_fg_pct_5"], 8 / 10)


def test_season_reset_and_player_isolation():
    df = games()
    df.loc[2:, "season"] = "2025-26"
    other = df.copy()
    other["player_id"] = 11
    other["pts"] = 1000.
    out = compute_extended_stats(pd.concat([df, other], ignore_index=True))
    own = out[out.player_id == 10]
    assert np.isnan(own.iloc[2].ext_pts_season)
    assert own.iloc[3].ext_pts_season == 3.
    assert own.iloc[2].ext_pts_5 == 1.5


def test_inference_recomputes_exact_same_recipe_as_next_training_row():
    df = games()
    historical = compute_extended_stats(df.iloc[:3])
    state = latest_player_states(historical).iloc[0]
    next_game = compute_extended_stats(df).iloc[3]
    np.testing.assert_allclose(state[EXTENDED_FEATURE_COLS].astype(float),
                               next_game[EXTENDED_FEATURE_COLS].astype(float), equal_nan=True)


def test_dd_td_frequency_and_dnp_not_zero_game():
    df = games()
    df.loc[0, ["pts", "reb", "ast"]] = [20., 10., 10.]
    df.loc[1, "min"] = 0.
    out = compute_extended_stats(df)
    assert out.loc[2, "ext_double_double_5"] == 1.
    assert out.loc[2, "ext_triple_double_5"] == 1.
    assert out.loc[2, "ext_pts_5"] == 20.


def test_returning_player_starts_new_season_profile_without_old_totals():
    df = games()
    df.loc[3, "player_id"] = 11
    df.loc[3, "season"] = "2025-26"
    states = latest_player_states(compute_extended_stats(df)).set_index("player_id")
    assert np.isnan(states.loc[10, "ext_pts_season"])
    assert states.loc[10, "ext_pts_5"] == 2.


def test_training_inference_parity_preserves_explicit_nonplayed_rows():
    df = pd.concat([games(), games().assign(game_id=["5", "6", "7", "8"],
                       game_date=pd.date_range("2025-01-05", periods=4))], ignore_index=True)
    df.loc[4, "min"] = 0.
    state = latest_player_states(compute_extended_stats(df.iloc[:7])).iloc[0]
    training = compute_extended_stats(df).iloc[7]
    np.testing.assert_allclose(state[EXTENDED_FEATURE_COLS].astype(float),
                               training[EXTENDED_FEATURE_COLS].astype(float), equal_nan=True)
