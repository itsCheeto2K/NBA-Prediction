"""Descriptive season averages and league-wide comparisons; no inference changes."""
import numpy as np
import pandas as pd

METRICS = [
    ("pts", "PTS"), ("reb", "REB"), ("ast", "AST"), ("stl", "STL"),
    ("blk", "BLK"), ("min", "MIN"), ("fg_pct", "FG%"),
    ("fg3_pct", "3P%"), ("tov", "TOV"), ("plus_minus", "+/-"),
]
MIN_GAMES = 5
MIN_PEERS = 5
BAND_STD = 0.25


def position_bucket(raw):
    # Preserve the specificity of the source: do not invent PG/SG from G,
    # and never put a pure C in the same comparison bucket as PF or F-C.
    aliases = {"GUARD":"G", "FORWARD":"F", "CENTER":"C", "POINT GUARD":"PG",
               "SHOOTING GUARD":"SG", "SMALL FORWARD":"SF", "POWER FORWARD":"PF",
               "F-G":"G-F", "C-F":"F-C"}
    value = str(raw).strip().upper()
    value = aliases.get(value,value)
    return value if value in {"PG","SG","SF","PF","C","G","F","G-F","F-C"} else "unknown"


def build_season_stats(player_id: int, logs: pd.DataFrame, positions: pd.DataFrame, season: str):
    frame = logs.copy() if logs is not None else pd.DataFrame()
    if not frame.empty:
        frame = frame[frame["season"].eq(season)].copy()
        frame["min"] = pd.to_numeric(frame["min"], errors="coerce")
        frame = frame[frame["min"] > 0].drop_duplicates(["player_id", "game_id"])
    position_rows = positions.drop_duplicates("player_id", keep="last").set_index("player_id") if positions is not None and not positions.empty else pd.DataFrame()
    raw = str(position_rows.loc[player_id, "position_raw"]) if player_id in position_rows.index else "Unknown"
    group = position_bucket(raw)
    result = {"player_id": player_id, "season": season, "position_raw": raw,
              "position_group": group, "position_label": {"G":"Guards", "F":"Forwards", "C":"Centers",
                  "PG":"Point Guards", "SG":"Shooting Guards", "SF":"Small Forwards", "PF":"Power Forwards",
                  "G-F":"Guard / Forward", "F-C":"Forward / Center"}.get(group,"Unknown"),
              "games_played": 0, "stats": [], "comparison": {
                  "min_games": MIN_GAMES, "min_peers": MIN_PEERS, "average_band_std": BAND_STD,
                  "scope": "league",
                  "method": "All qualified league players, including the selected player; mean +/- 0.25 population SD. TOV is lower-is-better.",
              }}
    if frame.empty:
        averages, counts, totals, games = pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.Series(dtype=int)
    else:
        for column in ["pts","reb","ast","stl","blk","min","tov","plus_minus","fgm","fga","fg3m","fg3a"]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce") if column in frame else np.nan
            frame[column] = frame[column].replace([np.inf, -np.inf], np.nan)
        grouped = frame.groupby("player_id")
        games = grouped.size()
        averages = grouped[[key for key, _ in METRICS if key not in ("fg_pct", "fg3_pct")]].mean()
        counts = grouped.count()
        totals = grouped[["fgm","fga","fg3m","fg3a"]].sum(min_count=1)
        for key, made, attempted in [("fg_pct","fgm","fga"), ("fg3_pct","fg3m","fg3a")]:
            # Season shooting percentages are ratios of totals, not means of game percentages.
            averages[key] = (100 * totals[made] / totals[attempted].where(totals[attempted] > 0))
            averages[key] = averages[key].where(averages[key].between(0,100))
    result["games_played"] = int(games.get(player_id, 0))
    peer_ids = [int(pid) for pid in averages.index if games.get(pid,0) >= MIN_GAMES]
    for key, label in METRICS:
        value = averages.loc[player_id,key] if player_id in averages.index else np.nan
        peers = averages.loc[peer_ids,key].dropna() if peer_ids else pd.Series(dtype=float)
        own_eligible = result["games_played"] >= MIN_GAMES
        min_attempts = None
        if key in ("fg_pct", "fg3_pct"):
            attempted, min_attempts = ("fga",50) if key == "fg_pct" else ("fg3a",20)
            peers = peers[totals.loc[peers.index,attempted] >= min_attempts]
            own_eligible = own_eligible and player_id in totals.index and totals.loc[player_id,attempted] >= min_attempts
        elif player_id in counts.index:
            own_eligible = own_eligible and counts.loc[player_id,key] >= MIN_GAMES
            peers = peers[counts.loc[peers.index,key] >= MIN_GAMES]
        mean = float(peers.mean()) if len(peers) >= MIN_PEERS else None
        spread = float(peers.std(ddof=0)) * BAND_STD if mean is not None else None
        low, high = (mean - spread, mean + spread) if mean is not None else (None,None)
        tier = "unrated"
        rank = None
        if pd.notna(value) and np.isfinite(value) and own_eligible and mean is not None:
            rank = 1 + int((peers < value).sum() if key == "tov" else (peers > value).sum())
            if low <= value <= high:
                tier = "average"
            elif (key == "tov" and value < low) or (key != "tov" and value > high):
                tier = "above"
            else:
                tier = "below"
        result["stats"].append({"key":key,"label":label,"value":round(float(value),2) if pd.notna(value) and np.isfinite(value) else None,
                                "unit":"percent" if key.endswith("_pct") else "per_game",
                                "league_average":round(mean,2) if mean is not None else None,
                                "average_low":round(low,2) if low is not None else None,
                                "average_high":round(high,2) if high is not None else None,
                                "peer_count":len(peers),"tier":tier,"lower_is_better":key == "tov",
                                "rank":rank,"rank_out_of":len(peers) if rank is not None else None,
                                "min_attempts":min_attempts})
    own_rows = frame[frame["player_id"] == player_id] if not frame.empty else pd.DataFrame()
    add_extended_stats(result, own_rows)
    return result


def add_extended_stats(result, rows):
    """Append unranked box-score measures; omit unavailable inputs rather than invent values.

    TS% and eFG%: https://www.nba.com/stats/help/glossary
    AST/TO: https://a.espncdn.com/nba/s/glossary.html
    """
    unavailable = ["USG%", "ORtg", "DRtg", "PER"]

    def numbers(columns):
        if rows.empty or not set(columns).issubset(rows.columns):
            return None
        values = rows[list(columns)].apply(pd.to_numeric, errors="coerce")
        return values if np.isfinite(values.to_numpy()).all() else None

    def append(key, label, value, unit, description):
        if value is None or not np.isfinite(value):
            unavailable.append(label)
            return
        result["stats"].append({"key":key,"label":label,"value":round(float(value),2),"unit":unit,
                                "tier":"descriptive","ranked":False,"rank":None,"rank_out_of":None,
                                "description":description})

    for key,label,description in [("dreb","DREB","Defensive rebounds per game"),
                                  ("oreb","OREB","Offensive rebounds per game"),
                                  ("ftm","FT","Free throws made per game"),
                                  ("fg3m","3PM","Three-pointers made per game"),
                                  ("pf","PF","Personal fouls per game")]:
        values=numbers([key])
        append(key,label,float(values[key].mean()) if values is not None else None,"per_game",description)
    twos=numbers(["fgm","fg3m","fga","fg3a"])
    if twos is not None and ((twos["fgm"] >= twos["fg3m"]) & (twos["fga"] >= twos["fg3a"])).all():
        makes=(twos["fgm"]-twos["fg3m"]).sum()
        attempts=(twos["fga"]-twos["fg3a"]).sum()
        append("fg2m","2PM",makes/len(twos),"per_game","Two-pointers made per game: (FGM - 3PM) / games")
        append("fg2_pct","2P%",100*makes/attempts if attempts>0 else None,"percent","100 × total 2PM / total 2PA")
    else:
        unavailable.extend(["2PM","2P%"])
    free_throws=numbers(["ftm","fta"])
    append("ft_pct","FT%",100*free_throws.ftm.sum()/free_throws.fta.sum() if free_throws is not None and free_throws.fta.sum()>0 else None,
           "percent","100 × total FTM / total FTA")
    ratio=numbers(["ast","tov"])
    append("ast_to","AST/TO",ratio.ast.sum()/ratio.tov.sum() if ratio is not None and ratio.tov.sum()>0 else None,
           "ratio","Total assists / total turnovers; undefined when turnovers are zero")
    shooting=numbers(["pts","fga","fta"])
    tsa=2*(shooting.fga.sum()+0.44*shooting.fta.sum()) if shooting is not None else 0
    append("ts_pct","TS%",100*shooting.pts.sum()/tsa if shooting is not None and tsa>0 else None,
           "percent","100 × total PTS / [2 × (total FGA + 0.44 × total FTA)]")
    effective=numbers(["fgm","fg3m","fga"])
    append("efg_pct","eFG%",100*(effective.fgm.sum()+.5*effective.fg3m.sum())/effective.fga.sum() if effective is not None and effective.fga.sum()>0 else None,
           "percent","100 × (total FGM + 0.5 × total 3PM) / total FGA")
    categories=numbers(["pts","reb","ast","stl","blk"])
    for minimum,key,label in [(2,"double_doubles","DD"),(3,"triple_doubles","TD")]:
        count=int((categories.ge(10).sum(axis=1)>=minimum).sum()) if categories is not None else None
        append(key,label,count,"total",f"Season games with at least {minimum} double-digit categories among PTS/REB/AST/STL/BLK; DD includes TD")
    result["unavailable_stats"] = unavailable
