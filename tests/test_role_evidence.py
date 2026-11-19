import copy
import json

import pandas as pd

from src.collectors.role_evidence import normalize_participation, save_pregame_snapshot


def test_only_explicit_dnp_can_mark_absent_and_unlisted_players_stay_unknown():
    history = pd.DataFrame([dict(game_id="0000000001", game_date="2026-11-01", team_abbreviation="BOS", player_id=99)])
    box = pd.DataFrame([dict(game_id="0000000001", player_id=1, team_abbreviation="BOS", min=30., is_dnp=False),
                        dict(game_id="0000000001", player_id=2, team_abbreviation="BOS", min=None, is_dnp=True),
                        dict(game_id="0000000001", player_id=3, team_abbreviation="BOS", min=0., is_dnp=False)])
    actual = normalize_participation(box, history, "2026-11-02T00:00:00Z").set_index("player_id")
    assert actual.loc[1, "state"] == "played"
    assert actual.loc[2, "state"] == "did_not_play"
    assert actual.loc[3, "state"] == "unknown"
    assert 99 not in actual.index


def test_snapshot_repeated_line_changes_do_not_replace_first_capture_time(tmp_path, monkeypatch):
    from src.config import settings
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    snapshot = {"game_id": "0000000001", "team_abbreviation": "BOS", "snapshot_at": "2026-11-01T10:00:00Z",
                "source_report_at": "2026-11-01T09:00:00Z", "players": []}
    path = save_pregame_snapshot(snapshot)
    repeated = copy.deepcopy(snapshot); repeated["snapshot_at"] = "2026-11-01T11:00:00Z"
    assert save_pregame_snapshot(repeated) == path
    assert json.loads(path.read_text())["snapshot_at"] == snapshot["snapshot_at"]
    assert len(list(path.parent.glob("*.json"))) == 1


def test_api_exposes_roles_without_manually_boosting_a_frozen_points_model(monkeypatch):
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    import src.api.main as api
    from src.distribution.engine import DiscreteDistribution
    mate = api.CURRENT_ROSTER_DF[api.CURRENT_ROSTER_DF.team_abbreviation.eq("CLE") & api.CURRENT_ROSTER_DF.player_id.ne(1628378)].iloc[0]
    injury = {"fetched_at": datetime.now(timezone.utc).isoformat(), "players": {}, "teams": {}, "is_stale_report": False}
    monkeypatch.setattr(api, "fetch_espn_injuries", lambda: injury)
    frozen = SimpleNamespace(bundle_id="frozen-test", raw_distribution_family="nb2", calibrator_type="identity",
                             feature_schema=["pts_roll_mean_5"],
                             predict_distribution=lambda row: DiscreteDistribution(mu=20., phi=.2, dist_type="nb2"))
    monkeypatch.setattr(api, "BUNDLES", dict(api.BUNDLES, pts=frozen))
    client = TestClient(api.app)
    payload = {"player_id": 1628378, "stat": "pts", "line": 24.5, "odds_over": 1.9, "odds_under": 1.9}
    first = client.post("/api/predict", json=payload)
    injury["teams"]["CLE"] = [{"player_name": str(mate.player_name), "status": "Out"}]
    second = client.post("/api/predict", json=payload)
    assert first.status_code == second.status_code == 200
    before, after = first.json(), second.json()
    assert before["role_context"]["out_count"] == 0
    assert after["role_context"]["out_count"] == 1
    assert after["role_context"]["model_applied"] is False
    assert before["expected_value"] == after["expected_value"]
    assert before["line_probabilities"] == after["line_probabilities"]
