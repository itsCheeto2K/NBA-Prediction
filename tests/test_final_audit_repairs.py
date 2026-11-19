"""Regressions for the remaining audited failures, independent of production data."""
import io
import json
import time

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from scipy import stats

from src.distribution.calibration import PiecewiseLinearCDFCalibrator
from src.features.target import latest_player_states, target_workload
from src.models.injury_ablation import enrich_dataset_with_injury_features
from src.models.selector import ModelSelector
from src.storage.datasets import dataset_view, prepare_snapshot, atomic_json


def test_identity_calibrated_tail_score_matches_raw_logpmf():
    model = ModelSelector()
    for mu, y in [(25.0, 80), (100.0, 0), (2.0, 3)]:
        score = model.evaluate_recipe_on_b1(np.array([mu]), np.array([y]), "poisson", 0,
                                           PiecewiseLinearCDFCalibrator())
        assert score["mean_neg_log_score"] == pytest.approx(-stats.poisson.logpmf(y, mu), abs=5e-5)


def test_log_mass_integrates_nonidentity_segments_and_tail_slope():
    cal = PiecewiseLinearCDFCalibrator()
    cal.c_knots = cal.knots_u ** 2
    low = np.array([0.13, 0.72, 1.0])
    high = np.array([0.39, 0.93, 1.0])
    raw = np.log(np.array([0.26, 0.21, 1e-40]))
    result = cal.log_mass(low, high, raw)
    assert result[:2] == pytest.approx(np.log(cal(high[:2]) - cal(low[:2])), abs=1e-12)
    slope = cal.eps_mix + (1-cal.eps_mix) * (cal.c_knots[-1]-cal.c_knots[-2]) / 0.05
    assert result[-1] == pytest.approx(raw[-1] + np.log(slope))


@pytest.mark.parametrize("number", ["NaN", "Infinity", "1e309"])
def test_nonfinite_request_returns_json_422(number):
    from src.api.main import app
    client = TestClient(app, raise_server_exceptions=False)
    result = client.post("/api/predict", content='{"player_id":123,"line":'+number+'}',
                         headers={"Content-Type": "application/json"})
    assert result.status_code == 422
    assert result.json()["detail"][0]["loc"] == ["body", "line"]


def test_ocr_explicit_line_in_name_wins_over_half_decimal_odds(monkeypatch):
    import src.services.odds_ocr_parser as parser
    tokens = ["Stephen Curry (22.5)", "1.5", "1.91"]
    boxes = [([[i*100,0],[i*100+80,0],[i*100+80,20],[i*100,20]], text, .99)
             for i, text in enumerate(tokens)]
    monkeypatch.setattr(parser, "_OCR_ENGINE", lambda arr: (boxes, None))
    buf = io.BytesIO()
    Image.new("RGB", (400, 50)).save(buf, format="PNG")
    result = parser.parse_odds_image(buf.getvalue(), [{"player_id":201939,"full_name":"Stephen Curry"}])[0]
    assert (result["line"], result["odds_over"], result["odds_under"]) == (22.5,1.5,1.91)


def player_history():
    return pd.DataFrame([{"player_id":1,"game_id":str(i),"game_date":d.isoformat(),
                          "team_abbreviation":"BOS","season":"2026-27", "pts":i+1,
                          "reb":3,"ast":2,"min":30.0,"fga":10,"fta":2,"fg3a":4}
                         for i,d in enumerate(pd.date_range("2026-10-01", periods=35))])


def test_next_game_state_uses_full_ewm_and_includes_last_rate_observation():
    from src.features.shrinkage import compute_gamma_poisson_rate
    history = player_history()
    row = latest_player_states(history).iloc[0]
    assert row.pts_roll_mean_5 == history.pts.tail(5).mean()
    assert row.pts_decay_mean == pytest.approx(history.pts.ewm(halflife=10).mean().iloc[-1])
    last = history.iloc[-1].copy()
    last["game_id"] = "9999999999"
    last["game_date"] = "2026-11-10T00:00:00"
    last["pts"] = last["min"] = np.nan
    expected = compute_gamma_poisson_rate(pd.concat([history,pd.DataFrame([last])]),stat="pts").iloc[-1]
    assert row.pts_rate_shrinkage == expected.pts_rate_shrinkage
    target = target_workload(row.to_dict(),history,pd.DataFrame(),"2026-11-06")
    mask = pd.to_datetime(history.game_date) >= pd.Timestamp("2026-10-30")
    assert target["player_minutes_last7days"] == history.loc[mask,"min"].sum()


def test_missing_role_uses_archived_roster_even_when_teammate_did_not_enter():
    target = pd.DataFrame([{"player_id":1,"game_id":"g","game_date":"2026-11-03",
                             "team_abbreviation":"BOS","opponent_abbr":"NYK"}])
    # Teammate 2 never appears in target gamelog; absence must still be counted.
    snapshot = pd.DataFrame([{"player_id":i,"game_id":"g","team_abbreviation":"BOS",
                              "snapshot_at":"2026-11-02T23:00:00Z","pi_participate":pi,
                              "baseline_minutes":30,"fga_volume":10,"ast_volume":4,"pts_volume":20,
                              "status":"available" if i==1 else "out"} for i,pi in [(1,.99),(2,0.)]])
    out = enrich_dataset_with_injury_features(target,snapshot)
    assert out.iloc[0].teammate_missing_minutes == 30
    assert out.iloc[0].teammate_missing_fga == 10
    assert enrich_dataset_with_injury_features(target).teammate_missing_minutes.isna().all()
    snapshot["snapshot_at"] = "2026-11-04T00:00:00Z"
    assert enrich_dataset_with_injury_features(target,snapshot).teammate_missing_minutes.isna().all()


def test_snapshot_publish_never_modifies_legacy_and_old_view_stays_readable(tmp_path):
    base = tmp_path/"parquet"
    base.mkdir()
    pd.DataFrame({"marker":["old"]}).to_parquet(base/"x.parquet")
    before = dataset_view(base,tmp_path)
    stage = tmp_path/"stage"
    stage.mkdir()
    pd.DataFrame({"marker":["new"]}).to_parquet(stage/"x.parquet")
    payload = prepare_snapshot(stage,"new",before,tmp_path)
    atomic_json(tmp_path/"snapshots"/"manifest.json",payload)
    after = dataset_view(base,tmp_path)
    assert pd.read_parquet(before.path("x.parquet")).marker.tolist() == ["old"]
    assert pd.read_parquet(after.path("x.parquet")).marker.tolist() == ["new"]


def test_lost_fence_after_copy_cannot_publish(tmp_path):
    from src.collectors.sync import SyncLeaseLock, SyncLockError
    path = tmp_path/"lease.json"
    path.write_text(json.dumps({"run_id":"new","fencing_token":7,"status":"LOCKED","heartbeat":time.time()}))
    lock = SyncLeaseLock(path)
    # Simulate takeover while worker was copying expensive artifacts.
    path.write_text(json.dumps({"run_id":"other","fencing_token":8,"status":"LOCKED","heartbeat":time.time()}))
    with pytest.raises(SyncLockError):
        with lock.commit_guard("new",7):
            pytest.fail("stale worker entered the commit section")


def test_completed_game_is_rejected_before_inference(monkeypatch):
    import src.api.main as api
    monkeypatch.setattr(api,"PLAYERS_DF",pd.DataFrame([{"player_id":1,"full_name":"Test"}]))
    monkeypatch.setattr(api,"LATEST_FEATURES_DF",pd.DataFrame([{"player_id":1,"n_games_history":10,"team_abbreviation":"BOS"}]))
    monkeypatch.setattr(api,"SCHEDULE_DF",pd.DataFrame([{"game_id":"g","game_status":3,"game_status_text":"Final"}]))
    result = TestClient(api.app).post("/api/predict",json={"player_id":1,"game_id":"g"})
    assert result.status_code == 422


def test_captured_resource_view_survives_next_publication(monkeypatch):
    import src.api.main as api
    before = api.get_resources()
    old_models = before["MODELS"]
    monkeypatch.setattr(api,"MODELS",{"new_generation":object()})
    after = api.get_resources()
    assert after["MODELS"] is not old_models
    assert before["MODELS"] is old_models


@pytest.mark.parametrize("fresh_roster", [False, True])
def test_predict_uses_the_same_workload_it_reports(monkeypatch, fresh_roster):
    import src.api.main as api
    history = player_history()
    row = latest_player_states(history)
    seen = {}
    class Model:
        def predict(self, values):
            seen["workload"] = values[0][0]
            return np.array([20.0])
    monkeypatch.setattr(api,"PLAYERS_DF",pd.DataFrame([{"player_id":1,"full_name":"Test"}]))
    monkeypatch.setattr(api,"LATEST_FEATURES_DF",row)
    monkeypatch.setattr(api,"PLAYER_HISTORY_DF",history)
    monkeypatch.setattr(api,"TEAM_LOGS_DF",pd.DataFrame())
    monkeypatch.setattr(api,"PLAYER_LOGS_DF",pd.DataFrame())
    monkeypatch.setattr(api,"SCHEDULE_DF",pd.DataFrame([{
        "game_id":"future","game_status":1,"home_team_tricode":"BOS","away_team_tricode":"NYK",
        "game_date_est":"2026-11-06","game_time_utc":"2026-11-07T00:00:00Z"}]))
    monkeypatch.setattr(api,"FEATURES_META",["player_minutes_last7days"])
    monkeypatch.setattr(api,"MODELS",{"lgbm_pts":Model()})
    monkeypatch.setattr(api,"BUNDLES",{})
    roster = pd.DataFrame([{"player_id":1,"team_abbreviation":"BOS","season":"2026-27",
                            "fetched_at":pd.Timestamp.now(tz="UTC").isoformat()}]) if fresh_roster else pd.DataFrame()
    monkeypatch.setattr(api,"CURRENT_ROSTER_DF",roster)
    monkeypatch.setattr(api,"fetch_espn_injuries",lambda: {"players":{},"teams":{}})
    result = TestClient(api.app).post("/api/predict",json={"player_id":1,"game_id":"future","line":20.5})
    assert result.status_code == 200, result.text
    assert seen["workload"] == result.json()["schedule_context"]["player_minutes_last7days"]
    assert result.json()["condition"]["metadata"]["membership_verified"] is fresh_roster


@pytest.mark.parametrize("age_hours,season,expected", [(0,"2026-27",True), (25,"2026-27",False),
                                                       (0,"2025-26",False)])
def test_roster_freshness_returns_json_serializable_boolean(age_hours, season, expected):
    from src.collectors.roster import membership_is_fresh
    roster = pd.DataFrame([{"season":season,
                            "fetched_at":(pd.Timestamp.now(tz="UTC")-pd.Timedelta(hours=age_hours)).isoformat()}])
    result = membership_is_fresh(roster,"2026-27")
    assert result is expected
    assert json.loads(json.dumps({"membership_verified":result}))["membership_verified"] is expected


def test_unexpected_api_failure_returns_json_without_exception_details(monkeypatch):
    import src.api.main as api
    def broken_resources():
        raise RuntimeError("private diagnostic information")
    monkeypatch.setattr(api,"get_resources",broken_resources)
    result = TestClient(api.app,raise_server_exceptions=False).post("/api/predict",json={"player_id":1})
    assert result.status_code == 500
    assert result.headers["content-type"].startswith("application/json")
    assert result.json()["detail"].startswith("Internal server error")
    assert "private diagnostic information" not in result.text


def test_batch_preserves_player_rejection_and_continues_other_rows(monkeypatch):
    import src.api.main as api
    from types import SimpleNamespace
    def prediction(req):
        if req.player_id == 1:
            return api.JSONResponse(status_code=422,content={"detail":"Player has insufficient history"})
        if req.player_id == 2:
            raise api.HTTPException(status_code=422,detail="Player is not on the current roster")
        return SimpleNamespace(expected_value=20.0,median=20,line_probabilities=SimpleNamespace(
            q_over=.55,q_under=.45,q_push=0),pricing=None,dvp_context=None)
    monkeypatch.setattr(api,"predict_props",prediction)
    result=TestClient(api.app).post("/api/fastcheck/predict-batch",json=[
        {"player_id":i,"line":20.5} for i in [1,2,3]])
    assert result.status_code == 200
    rows=result.json()
    assert rows[0]["error"] == "Player has insufficient history"
    assert rows[1]["error"] == "Player is not on the current roster"
    assert rows[2]["error"] is None
    assert rows[2]["q_over"] == 55


def test_roster_without_membership_evidence_excludes_previous_seasons(monkeypatch):
    import src.api.main as api
    monkeypatch.setattr(api,"LATEST_FEATURES_DF",pd.DataFrame([
        {"player_id":1,"player_name":"Current appearance","team_abbreviation":"BOS","season":"2026-27","min_roll_mean_5":30,"pts_roll_mean_5":20},
        {"player_id":2,"player_name":"Old appearance","team_abbreviation":"BOS","season":"2024-25","min_roll_mean_5":30,"pts_roll_mean_5":20},
    ]))
    monkeypatch.setattr(api,"CURRENT_ROSTER_DF",pd.DataFrame())
    rows = api.get_team_roster("BOS")
    assert [r["player_id"] for r in rows] == [1]
    assert rows[0]["membership_verified"] is False
    assert rows[0]["roster_source"] == "season_appearances_reference"


def sync_fixture(tmp_path, monkeypatch, audit_status="COMPLETE"):
    from types import SimpleNamespace
    import src.collectors.sync as sync
    base = tmp_path/"parquet"
    base.mkdir()
    raw = pd.DataFrame({"game_id":["0022600001"],"game_date":["2026-11-15"],"season":["2026-27"],"marker":["old"]})
    for name in ["schedule", "team_gamelogs", "player_gamelogs"]:
        raw.to_parquet(base/f"{name}_2026-27.parquet",index=False)
    original = dataset_view(base,tmp_path)
    atomic_json(tmp_path/"snapshots"/"manifest.json",{"active_snapshot":"old","files":{n:str(p) for n,p in original.files.items()}})
    status_file = tmp_path/"manifests"/"sync.json"
    atomic_json(status_file,{"status":"SUCCESS","last_successful_sync_time":"previous-success","latest_game_date":"2026-11-14"})
    monkeypatch.setattr(sync,"settings",SimpleNamespace(DATA_DIR=tmp_path,PARQUET_DIR=base,SEASONS=["2026-27"],create_dirs=lambda:None))
    monkeypatch.setattr(sync,"SYNC_STATUS_FILE",status_file)
    monkeypatch.setattr(sync,"_SYNC_LOCK",sync.SyncLeaseLock(tmp_path/"lease.json"))
    new = raw.assign(marker="new")
    for name in ["fetch_schedule","fetch_team_gamelogs","fetch_player_gamelogs"]:
        monkeypatch.setattr(sync,name,lambda **kw:new)
    monkeypatch.setattr(sync,"audit_backfill_completeness",lambda *a,**kw:{"status":audit_status})
    monkeypatch.setattr(sync,"build_feature_dataset",lambda **kw:new)
    import src.collectors.roster as roster
    def unavailable(*a,**kw):
        raise RuntimeError("No live roster in this test")
    monkeypatch.setattr(roster,"fetch_current_roster",unavailable)
    return sync,base


def test_sync_publish_has_one_pointer_and_preserves_original_files(tmp_path,monkeypatch):
    sync,base = sync_fixture(tmp_path,monkeypatch)
    result = sync.sync_season_data(client=object(),job_id="new")
    assert result["status"] == "SUCCESS"
    view = dataset_view(base,tmp_path)
    assert view.version == "new"
    assert pd.read_parquet(view.path("team_gamelogs_2026-27.parquet")).marker.tolist() == ["new"]
    assert pd.read_parquet(base/"team_gamelogs_2026-27.parquet").marker.tolist() == ["old"]


def test_sync_ownership_lost_during_copy_does_not_publish(tmp_path,monkeypatch):
    sync,base = sync_fixture(tmp_path,monkeypatch)
    import src.storage.datasets as datasets
    original = datasets.prepare_snapshot
    def takeover(*args,**kwargs):
        result = original(*args,**kwargs)
        path = sync._SYNC_LOCK.lock_file
        lease = json.loads(path.read_text())
        lease.update(run_id="other",fencing_token=lease["fencing_token"]+1,heartbeat=time.time())
        path.write_text(json.dumps(lease))
        return result
    monkeypatch.setattr(datasets,"prepare_snapshot",takeover)
    from src.collectors.sync import SyncLockError
    with pytest.raises(SyncLockError):
        sync.sync_season_data(client=object(),job_id="lost")
    assert dataset_view(base,tmp_path).version == "old"


def test_partial_sync_keeps_watermark_and_successful_timestamp(tmp_path,monkeypatch):
    sync,base = sync_fixture(tmp_path,monkeypatch,audit_status="PARTIAL")
    result = sync.sync_season_data(client=object(),job_id="partial")
    assert result["latest_game_date"] == "2026-11-14"
    assert result["latest_game_date_us"] == "2026-11-14 (US ET)"
    assert result["last_successful_sync_time"] == "previous-success"
    assert dataset_view(base,tmp_path).version == "old"
