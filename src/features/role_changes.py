"""Role profiles and observed with/without comparisons, never causal boosts."""
import re

import numpy as np
import pandas as pd

from src.collectors.injuries import normalize_text

STATS = ("min", "fga", "fta", "fg3a", "pts", "ast")
ROLE_FEATURES = ["role_context_available", "role_out_count", "role_uncertain_count", "role_unmapped_count",
                 "role_missing_minutes", "role_missing_fga", "role_missing_fta", "role_missing_fg3a",
                 "role_missing_pts", "role_missing_ast", "role_missing_fga_share", "role_missing_top2_minutes",
                 "role_joint_without_games", "role_joint_with_games", "role_joint_supported",
                 "role_joint_minutes_delta", "role_joint_fga_delta", "role_joint_pts_delta"]


def eligible_role_features(frame, min_rows=100, min_out_rows=20):
    if "role_out_count" not in frame:
        return []
    if frame.role_out_count.notna().sum() < min_rows or frame.role_out_count.gt(0).sum() < min_out_rows:
        return []
    return [c for c in ROLE_FEATURES if c in frame and frame[c].notna().sum() >= min_rows and frame[c].fillna(0).nunique() > 1]


def safe_mean(values, complete=False):
    values = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan)
    values = values.where(values >= 0)
    if not values.notna().any() or (complete and not values.notna().all()):
        return None
    return float(values.mean())


def name_aliases(name):
    words = re.sub(r"[^a-z0-9 ]", " ", normalize_text(str(name))).split()
    full = " ".join(words)
    if words and words[-1] in ("jr", "sr", "ii", "iii", "iv"):
        words = words[:-1]
    aliases = {full, " ".join(words)}
    if len(words) >= 2:
        aliases.add(words[0] + " " + words[-1])
    return aliases - {""}


def recent_profile(history, player_id, team, cutoff, lookback_days=730):
    empty = {"games": 0, "last_game_date": None, **{stat: None for stat in STATS}}
    if history is None or history.empty:
        return empty
    dates = pd.to_datetime(history.game_date, format="mixed").dt.normalize()
    cutoff = pd.Timestamp(cutoff).normalize()
    mask = history.player_id.eq(player_id) & history.team_abbreviation.eq(team) & history["min"].gt(0)
    mask &= dates.lt(cutoff) & dates.ge(cutoff - pd.Timedelta(days=lookback_days))
    rows = history.loc[mask].sort_values(["game_date", "game_id"]).drop_duplicates("game_id").tail(10)
    if rows.empty:
        return empty
    return {"games": len(rows), "last_game_date": str(rows.iloc[-1].game_date)[:10],
            **{stat: safe_mean(rows[stat]) if stat in rows else None
               for stat in STATS}}


def observed_comparison(history, participation, player_id, missing_ids, team, cutoff, as_of, min_samples=5):
    result = {"status": "insufficient_evidence", "with_games": 0, "without_games": 0,
              "unknown_games": 0, "supported": False, "with": None, "without": None,
              "delta": None, "kind": "Observed History", "minimum_per_group": min_samples}
    if not missing_ids or history is None or history.empty:
        return result
    dates = pd.to_datetime(history.game_date, format="mixed").dt.normalize()
    cutoff = pd.Timestamp(cutoff).normalize()
    own = history[history.player_id.eq(player_id) & history.team_abbreviation.eq(team) & history["min"].gt(0)
                  & dates.lt(cutoff) & dates.ge(cutoff - pd.Timedelta(days=730))]
    own = own.sort_values(["game_date", "game_id"]).drop_duplicates("game_id").tail(60).copy()
    result["unknown_games"] = len(own)
    if participation is None or participation.empty or own.empty:
        return result
    required = {"game_id", "player_id", "team_abbreviation", "game_date", "state", "known_at"}
    if not required.issubset(participation):
        return result
    evidence = participation[participation.team_abbreviation.eq(team) & participation.player_id.isin(missing_ids)].copy()
    known = pd.to_datetime(evidence.known_at, utc=True, errors="coerce")
    as_of = pd.to_datetime(as_of, utc=True, errors="coerce")
    if pd.isna(as_of):
        return result
    evidence = evidence[known.notna() & known.le(as_of)]
    evidence["game_id"] = evidence.game_id.astype(str).str.zfill(10)
    own["game_id"] = own.game_id.astype(str).str.zfill(10)
    without, with_players = set(own.game_id), set(own.game_id)
    for pid in sorted(set(missing_ids)):
        part = evidence[evidence.player_id.eq(pid)].copy()
        # Conflicting sources remain unknown; do not choose a convenient label.
        conflicts = part.groupby("game_id").state.nunique()
        part = part[~part.game_id.isin(conflicts[conflicts > 1].index)].drop_duplicates("game_id")
        joined = own[["game_id", "game_date"]].merge(part[["game_id", "game_date", "state"]], on="game_id", suffixes=("_own", "_mate"))
        valid_date = pd.to_datetime(joined.game_date_own, format="mixed").dt.normalize().eq(pd.to_datetime(joined.game_date_mate, format="mixed").dt.normalize())
        joined = joined[valid_date]
        without &= set(joined.loc[joined.state.eq("did_not_play"), "game_id"])
        with_players &= set(joined.loc[joined.state.eq("played"), "game_id"])
    result.update(with_games=len(with_players), without_games=len(without),
                  unknown_games=len(own) - len(with_players) - len(without))
    result["with"] = {stat: safe_mean(own.loc[own.game_id.isin(with_players), stat], complete=True) if stat in own else None for stat in STATS} if with_players else None
    result["without"] = {stat: safe_mean(own.loc[own.game_id.isin(without), stat], complete=True) if stat in own else None for stat in STATS} if without else None
    if not with_players or not without:
        return result
    result["delta"] = {stat: result["without"][stat] - result["with"][stat] if result["with"][stat] is not None and result["without"][stat] is not None else None for stat in STATS}
    result["supported"] = min(len(with_players), len(without)) >= min_samples
    result["status"] = "supported" if result["supported"] else "small_sample"
    return result


def features_from_context(context):
    features = {name: np.nan for name in ROLE_FEATURES}
    if not context or context.get("status") not in ("available", "partial"):
        return features
    missing = context["missing"]
    features.update(role_context_available=1., role_out_count=context["out_count"], role_uncertain_count=context["uncertain_count"],
                    role_unmapped_count=context["unmapped_count"], role_missing_fga_share=context.get("missing_fga_share"))
    for stat, suffix in (("min", "minutes"), ("fga", "fga"), ("fta", "fta"), ("fg3a", "fg3a"), ("pts", "pts"), ("ast", "ast")):
        features["role_missing_" + suffix] = missing.get(stat)
    out_minutes = [p["profile"]["min"] for p in context["teammates"] if p["status"] == "out" and p["profile"]["min"] is not None]
    features["role_missing_top2_minutes"] = sum(sorted(out_minutes, reverse=True)[:2]) if missing.get("min") is not None else np.nan
    joint = context.get("joint_comparison")
    if joint:
        features.update(role_joint_without_games=joint["without_games"], role_joint_with_games=joint["with_games"], role_joint_supported=float(joint["supported"]))
        if joint["supported"]:
            for stat, suffix in (("min", "minutes"), ("fga", "fga"), ("pts", "pts")):
                features["role_joint_" + suffix + "_delta"] = joint["delta"].get(stat)
    return features


def archived_role_features(frame, snapshots, participation):
    """Rebuild feature values only from snapshots captured before the target tip.

    Returns all NaN when archived pregame evidence is unavailable. No current
    injury report or postgame nonparticipation can create past absence inputs.
    """
    result = pd.DataFrame(np.nan, index=frame.index, columns=ROLE_FEATURES)
    if not snapshots:
        return result
    by_game = {}
    for snapshot in snapshots:
        captured = pd.to_datetime(snapshot.get("snapshot_at"), utc=True, errors="coerce")
        tip = pd.to_datetime(snapshot.get("tipoff_at"), utc=True, errors="coerce")
        report = pd.to_datetime(snapshot.get("source_report_at"), utc=True, errors="coerce")
        if pd.isna(captured) or pd.isna(tip) or pd.isna(report) or not report <= captured < tip:
            continue
        if (captured - report).total_seconds() > 21600:
            continue
        key = (str(snapshot.get("game_id", "")).zfill(10), snapshot.get("team_abbreviation"), str(snapshot.get("game_date", ""))[:10])
        players = snapshot.get("players", [])
        if not players or any(p.get("profile", {}).get("last_game_date") and str(p["profile"]["last_game_date"])[:10] >= key[2] for p in players):
            continue
        if key not in by_game or captured > pd.to_datetime(by_game[key]["snapshot_at"], utc=True):
            by_game[key] = snapshot
    for (game_id, team, game_date), snapshot in by_game.items():
        rows = frame[frame.game_id.astype(str).str.zfill(10).eq(game_id) & frame.team_abbreviation.eq(team)
                     & frame.game_date.astype(str).str[:10].eq(game_date)]
        for index, row in rows.iterrows():
            if not any(p["player_id"] == row.player_id for p in snapshot["players"]):
                continue
            teammates = [p for p in snapshot["players"] if p["player_id"] != row.player_id and p["status"] not in ("not_listed", "available", "unknown")]
            out = [p for p in teammates if p["status"] == "out"]
            missing = {stat: None if any(p["profile"].get(stat) is None for p in out)
                       else sum(p["profile"][stat] for p in out) for stat in STATS}
            joint = observed_comparison(frame, participation, row.player_id, [p["player_id"] for p in out], team, game_date, snapshot["snapshot_at"])
            denominator = snapshot.get("team_fga")
            context = {"status": "available", "out_count": len(out), "uncertain_count": len(teammates)-len(out),
                       "unmapped_count": snapshot.get("unmapped_count", 0), "missing": missing, "teammates": teammates,
                       "missing_fga_share": missing["fga"] / denominator if missing["fga"] is not None and denominator and denominator > 0 else None,
                       "joint_comparison": joint}
            result.loc[index] = pd.Series(features_from_context(context))
    return result
