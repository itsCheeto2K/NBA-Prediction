import pandas as pd

from src.models.game_context import historical_games, upcoming_game, baseline_projection


def _logs():
    rows = []
    for day in range(1, 13):
        for team, matchup, pts in (("AAA", "AAA vs. BBB", 100 + day), ("BBB", "BBB @ AAA", 95 + day)):
            rows.append({"game_id": str(day), "game_date": f"2026-01-{day:02d}",
                         "team_abbreviation": team, "matchup": matchup,
                         "pts": pts, "fga": 80, "fta": 20, "oreb": 10, "tov": 12})
    return pd.DataFrame(rows)


def test_upcoming_context_ignores_current_and_future_results():
    logs = _logs()
    before = baseline_projection(upcoming_game(logs, "AAA", "BBB", "2026-01-10"))
    assert "home_points" not in before and "away_points" not in before
    changed = logs.copy()
    changed.loc[changed.game_date.ge("2026-01-10"), "pts"] = 999
    after = baseline_projection(upcoming_game(changed, "AAA", "BBB", "2026-01-10"))
    assert before == after


def test_bad_home_away_pair_is_excluded():
    logs = _logs()
    logs.loc[logs.game_id.eq("4") & logs.team_abbreviation.eq("AAA"), "matchup"] = "AAA @ BBB"
    games = historical_games(logs)
    assert "4" not in set(games.game_id)
    assert len(games) == 11
