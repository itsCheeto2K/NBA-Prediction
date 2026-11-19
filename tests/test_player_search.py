import pandas as pd
import pytest
from fastapi.testclient import TestClient


def test_partial_name_search_is_case_insensitive_and_can_filter_active_players(monkeypatch):
    import src.api.main as api
    monkeypatch.setattr(api, "PLAYERS_DF", pd.DataFrame([
        {"player_id":201939,"full_name":"Stephen Curry","is_active":True},
        {"player_id":203552,"full_name":"Seth Curry","is_active":True},
        {"player_id":1,"full_name":"Dell Curry","is_active":False},
        {"player_id":2,"full_name":"Other Player","is_active":True},
    ]))
    monkeypatch.setattr(api, "CURRENT_ROSTER_DF", pd.DataFrame([
        {"player_id":pid,"team_abbreviation":"GSW","season":"2026-27",
         "fetched_at":pd.Timestamp.now(tz="UTC").isoformat()} for pid in [201939,203552]]))
    client=TestClient(api.app)
    result=client.get("/api/players?query=Cur&active_only=true")
    assert result.status_code == 200
    assert [p["full_name"] for p in result.json()] == ["Stephen Curry","Seth Curry"]
    assert len(client.get("/api/players?query=cUR").json()) == 3
    assert client.get("/api/players?query=Cur.*&active_only=true").json() == []


@pytest.mark.parametrize("stale", [False, True])
def test_active_search_requires_fresh_roster_and_ignores_stale_active_flags(monkeypatch, stale):
    import src.api.main as api
    monkeypatch.setattr(api,"PLAYERS_DF",pd.DataFrame([
        {"player_id":2544,"full_name":"LeBron James","is_active":True},
        {"player_id":1,"full_name":"Former player still flagged active","is_active":True},
    ]))
    monkeypatch.setattr(api,"CURRENT_ROSTER_DF",pd.DataFrame([{
        "player_id":2544,"team_abbreviation":"LAL","season":"2026-27",
        "fetched_at":(pd.Timestamp.now(tz="UTC")-pd.Timedelta(hours=25 if stale else 0)).isoformat()}]))
    client=TestClient(api.app)
    result=client.get("/api/players?active_only=true")
    if stale:
        assert result.status_code == 503
        assert client.get("/api/teams/LAL/roster?verified_only=true").status_code == 503
    else:
        assert result.status_code == 200
        assert [p["player_id"] for p in result.json()] == [2544]
        assert result.json()[0]["membership_verified"] is True
        assert client.get("/api/players?active_only=true&player_id=1").json() == []
        assert client.get("/api/players?query=Former&active_only=true").json() == []


def test_suggestions_refill_to_ten_after_filtering_old_favorites(monkeypatch):
    import src.api.main as api
    ids=[2544]+list(range(100,112))
    monkeypatch.setattr(api,"PLAYERS_DF",pd.DataFrame([
        {"player_id":pid,"full_name":f"Player {pid}","is_active":True} for pid in ids]))
    monkeypatch.setattr(api,"CURRENT_ROSTER_DF",pd.DataFrame([
        {"player_id":pid,"team_abbreviation":"BOS","season":"2026-27",
         "fetched_at":pd.Timestamp.now(tz="UTC").isoformat()} for pid in ids[1:]]))
    result=TestClient(api.app).get("/api/players?active_only=true")
    assert result.status_code == 200
    assert len(result.json()) == 10
    assert 2544 not in [p["player_id"] for p in result.json()]
