import numpy as np
import pandas as pd

from src.models.playing_time import PlayingTimeModel, PROJECTION_FEATURES, historical_projection_features
from src.services.playing_time import project_playing_time


def test_minutes_are_conditional_and_not_capped_at_48():
    frame = pd.DataFrame({"min_roll_mean_5": [53., 30.], "min_roll_std_5": [4., 0.]})
    model = PlayingTimeModel()
    mu, lo, hi = model.predict(frame)
    assert mu[0] == 53.
    assert np.all(lo <= mu) and np.all(mu <= hi)
    assert np.all(lo >= 0)


def test_ui_calibration_never_leaks_into_historical_features():
    frame = pd.DataFrame({"min_roll_mean_5": [30.], "min_roll_std_5": [4.]})
    model = PlayingTimeModel(metadata={"interval_offset": 100.})
    features = model.features(frame)
    assert features.pt_lower_minutes.iloc[0] > 20
    assert model.predict(frame)[1][0] == 0.


def test_oof_models_are_fitted_strictly_before_each_prediction(monkeypatch):
    frame = pd.DataFrame({"game_date": pd.date_range("2023-01-01", periods=80),
                          "target_min": np.arange(80) % 30 + 1., "min_roll_mean_5": 25.})
    calls = []
    class Sentinel:
        def __init__(self, end):
            self.end = end
            self.metadata = {"mean_kind": "lgbm"}
        def features(self, rows):
            assert pd.to_datetime(rows.game_date).min() > self.end
            calls.append((self.end, pd.to_datetime(rows.game_date).min()))
            return pd.DataFrame({c: 20. for c in PROJECTION_FEATURES}, index=rows.index)
    def fit(rows):
        return Sentinel(pd.to_datetime(rows.game_date).max())
    monkeypatch.setattr(PlayingTimeModel, "fit", staticmethod(fit))
    end = frame.game_date.iloc[40]
    result = historical_projection_features(frame, Sentinel(end), end, min_warmup_dates=10, block_dates=10)
    assert calls and result.notna().all().all()
    assert result.pt_expected_minutes.iloc[0] == 25.


def inputs():
    row = dict(player_id=0, player_name="Player 0", team_abbreviation="BOS", n_games_history=20,
               min_roll_mean_5=40., min_roll_std_5=3., last_game_date="2026-11-15",
               game_date="2026-11-15", days_since_last_appearance=2.)
    model = PlayingTimeModel(metadata={"training_end": "2024-06-01", "calibration_end": "2025-06-01", "recipe_version": "test"})
    return model, row


def test_minutes_projection_has_no_starter_data():
    data, features = project_playing_time(*inputs(), "2026-11-17")
    assert not any(key.startswith("starter_") or key == "verified" for key in data)
    assert data["conditional_on_playing"] is True
    assert set(features) == set(PROJECTION_FEATURES)


def test_current_out_player_flagged_but_stale_report_not_treated_as_current():
    data, _ = project_playing_time(*inputs(), "2026-11-17", team_injuries=[{"player_name": "Player 0", "status": "Out"}])
    assert "Reported Out" in data["risk_flags"]
    stale, _ = project_playing_time(*inputs(), "2026-11-17", team_injuries=[{"player_name": "Player 0", "status": "Out"}], stale_injuries=True)
    assert "Reported Out" not in stale["risk_flags"]
    assert "Stale Injury Report" in stale["risk_flags"]


def test_historical_game_cannot_use_a_future_fitted_model():
    data, features = project_playing_time(*inputs(), "2024-01-01")
    assert data["status"] == "unavailable"
    assert all(np.isnan(v) for v in features.values())


def test_historical_game_cannot_use_current_player_state_from_after_the_game():
    data, _ = project_playing_time(*inputs(), "2026-11-14")
    assert data["status"] == "unavailable"
    assert "pregame history" in data["reason"]


def test_api_exposes_projection_independent_of_line_and_odds(monkeypatch):
    from fastapi.testclient import TestClient
    import src.api.main as api
    model = PlayingTimeModel(metadata={"training_end": "2024-06-01", "calibration_end": "2025-06-01", "recipe_version": "test"})
    monkeypatch.setattr(api, "PLAYING_TIME_MODEL", model)
    monkeypatch.setattr(api, "fetch_espn_injuries", lambda: {"players": {}, "teams": {}, "is_stale_report": False})
    client = TestClient(api.app)
    outputs = []
    for line, odds in [(10.5, 1.9), (35.5, 2.1)]:
        response = client.post("/api/predict", json={"player_id": 1628378, "stat": "pts", "line": line, "odds_over": odds})
        assert response.status_code == 200, response.text
        value = response.json()["playing_time_projection"]
        assert "starter_label" not in value and "starter_probability" not in value
        outputs.append(value)
    assert outputs[0] == outputs[1]
