import pandas as pd
from nba_api.stats.static import players, teams

def get_all_players_df() -> pd.DataFrame:
    """Retrieve offline reference table of all NBA players."""
    all_players = players.get_players()
    df = pd.DataFrame(all_players)
    if not df.empty:
        df = df.rename(columns={
            "id": "player_id",
            "full_name": "full_name",
            "first_name": "first_name",
            "last_name": "last_name",
            "is_active": "is_active",
        })
    return df

def get_all_teams_df() -> pd.DataFrame:
    """Retrieve offline reference table of all 30 NBA teams."""
    all_teams = teams.get_teams()
    df = pd.DataFrame(all_teams)
    if not df.empty:
        df = df.rename(columns={
            "id": "team_id",
            "full_name": "full_name",
            "abbreviation": "abbreviation",
            "nickname": "nickname",
            "city": "city",
            "state": "state",
            "year_founded": "year_founded",
        })
    return df
