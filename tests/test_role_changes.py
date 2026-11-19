import copy

import numpy as np
import pandas as pd

from src.features.role_changes import ROLE_FEATURES, STATS, archived_role_features, features_from_context, observed_comparison
from src.services.role_changes import build_role_context


def data():
    history = []
    participation = []
    for i in range(10):
        day = f"2026-11-{i+1:02d}"
        gid = str(i+1).zfill(10)
        history.append(dict(player_id=1, player_name="Alpha Guard", team_abbreviation="BOS", game_id=gid, game_date=day,
                            min=30.+(4 if i>=5 else 0), fga=10.+(2 if i>=5 else 0), fta=4., fg3a=4., pts=20.+(3 if i>=5 else 0), ast=5.))
        if i < 5:
            history.append(dict(player_id=2, player_name="Beta Guard", team_abbreviation="BOS", game_id=gid, game_date=day,
                                min=36., fga=19., fta=6., fg3a=8., pts=25., ast=7.))
        participation.append(dict(player_id=2, team_abbreviation="BOS", game_id=gid, game_date=day,
                                  state="played" if i<5 else "did_not_play", known_at="2026-11-11T00:00:00Z"))
    roster = pd.DataFrame([dict(player_id=1, player_name="Alpha Guard", team_abbreviation="BOS"),
                           dict(player_id=2, player_name="Beta Guard", team_abbreviation="BOS")])
    teams = pd.DataFrame([dict(team_abbreviation="BOS", game_id=str(i+1).zfill(10), game_date=f"2026-11-{i+1:02d}", fga=100.) for i in range(10)])
    injury = {"fetched_at": "2026-11-17T10:00:00Z", "is_stale_report": False,
              "teams": {"BOS": [{"player_name": "Beta Guard", "status": "Out"}]}}
    return pd.DataFrame(history), roster, teams, injury, pd.DataFrame(participation)


def context(values=None, **kwargs):
    h, r, t, inj, p = values or data()
    return build_role_context(1, "BOS", h, r, t, inj, p, "2026-11-18", game_id="0022600300",
                             tipoff_at="2026-11-18T00:30:00Z", as_of="2026-11-17T11:00:00Z", **kwargs)


def test_absent_volume_comes_from_player_history_not_fixed_minutes_multipliers():
    result, features, snapshot = context()
    assert result["missing"]["min"] == 36.
    assert result["missing"]["fga"] == 19.
    assert features["role_missing_fga"] == 19. and 19. != 36.*.4
    assert result["missing_fga_share"] == .19
    assert result["joint_comparison"]["supported"]
    assert result["joint_comparison"]["delta"]["min"] == 4.
    assert result["joint_comparison"]["delta"]["fga"] == 2.
    assert features["role_joint_pts_delta"] == 3.
    assert snapshot and len(snapshot["players"]) == 2
    assert not result["model_applied"]


def test_questionable_is_a_separate_scenario_not_a_confirmed_absence():
    values = list(data())
    values[3]["teams"]["BOS"][0]["status"] = "Questionable"
    result, features, _ = context(values)
    assert result["out_count"] == 0 and result["uncertain_count"] == 1
    assert result["missing"]["fga"] == 0.
    assert result["teammates"][0]["comparison"]["without_games"] == 5
    assert features["role_missing_fga"] == 0.


def test_absence_is_never_inferred_from_missing_boxscore_row():
    h, _, _, _, _ = data()
    result = observed_comparison(h, pd.DataFrame(), 1, [2], "BOS", "2026-11-18", "2026-11-17T11:00:00Z")
    assert result["without_games"] == 0 and result["unknown_games"] == 10
    assert result["delta"] is None


def test_stale_report_or_unverified_roster_cannot_become_zero_missing_features():
    values = list(data()); values[3]["is_stale_report"] = True
    result, features, snapshot = context(values)
    assert result["status"] == "unavailable" and snapshot is None
    assert all(pd.isna(value) for value in features.values())
    result, features, snapshot = context(roster_fresh=False)
    assert all(pd.isna(value) for value in features.values())


def test_unmapped_out_player_has_unknown_missing_volume_not_zero():
    values = list(data()); values[3]["teams"]["BOS"][0]["player_name"] = "Different Player"
    result, features, snapshot = context(values)
    assert result["unmapped_count"] == 1 and result["missing"]["fga"] is None
    assert features["role_missing_fga"] is None and snapshot is None


def test_future_game_results_do_not_change_current_profiles_or_deltas():
    values = list(data())
    result, features, _ = context(values)
    future = values[0].iloc[[0,1]].copy(); future["game_id"]="0022600300";future["game_date"]="2026-11-18"
    future[list(STATS)] = 999.
    values[0] = pd.concat([values[0], future], ignore_index=True)
    other, other_features, _ = context(values)
    assert features == other_features
    assert result["teammates"] == other["teammates"]


def test_future_evidence_and_other_team_participation_are_excluded():
    h, _, _, _, p = data()
    p.loc[p.state.eq("did_not_play"), "known_at"] = "2026-11-19T00:00:00Z"
    result = observed_comparison(h, p, 1, [2], "BOS", "2026-11-18", "2026-11-17T11:00:00Z")
    assert result["without_games"] == 0
    p.loc[:, "team_abbreviation"] = "NYK"
    result = observed_comparison(h, p, 1, [2], "BOS", "2026-11-18", "2026-11-17T11:00:00Z")
    assert result["with_games"] == 0


def test_archived_training_inputs_require_a_real_pregame_snapshot():
    _, _, _, _, p = data()
    result, live, snapshot = context()
    own = dict(player_id=1, team_abbreviation="BOS", game_id="0022600300", game_date="2026-11-18", min=35., fga=12., pts=25., fta=3., fg3a=6., ast=4.)
    h = pd.concat([data()[0], pd.DataFrame([own])], ignore_index=True)
    archived = archived_role_features(h, [snapshot], p)
    for key in ROLE_FEATURES:
        if pd.notna(live[key]):
            assert archived.iloc[-1][key] == live[key]
    late = copy.deepcopy(snapshot);late["snapshot_at"]="2026-11-18T02:00:00Z"
    assert archived_role_features(h, [late], p).isna().all().all()
    leaked = copy.deepcopy(snapshot);leaked["players"][0]["profile"]["last_game_date"]="2026-11-18"
    assert archived_role_features(h, [leaked], p).isna().all().all()


def test_multiple_missing_players_do_not_add_overlapping_individual_deltas():
    h, _, _, _, p = data()
    second = p.copy();second["player_id"]=3
    second["state"] = np.where(second.state.eq("played"), "did_not_play", "played")
    comparison = observed_comparison(h, pd.concat([p,second]), 1, [2,3], "BOS", "2026-11-18", "2026-11-17T11:00:00Z")
    assert comparison["without_games"] == 0 and comparison["delta"] is None
