"""Current reported absences, measured lost volume and verified role history."""
from datetime import datetime, timezone

import pandas as pd

from src.features.participation import normalize_injury_status
from src.features.role_changes import STATS, features_from_context, name_aliases, observed_comparison, recent_profile, safe_mean


def build_role_context(player_id, team, history, roster, teams, injury_report, participation,
                       target_date, game_id=None, tipoff_at=None, as_of=None, roster_fresh=True):
    now = pd.Timestamp(as_of or datetime.now(timezone.utc))
    now = now.tz_localize("UTC") if now.tzinfo is None else now.tz_convert("UTC")
    cutoff = pd.Timestamp(str(target_date)[:10]).normalize()
    result = {"status": "unavailable", "reason": None, "source": "ESPN Injury Report",
              "as_of": now.isoformat(), "source_report_at": injury_report.get("fetched_at"),
              "team_abbreviation": team, "target_date": str(cutoff.date()), "game_id": game_id,
              "out_count": None, "uncertain_count": None, "unmapped_count": 0, "unknown_profile_count": 0,
              "missing": {stat: None for stat in STATS}, "missing_fga_share": None,
              "teammates": [], "unmapped": [], "joint_comparison": None, "model_applied": False,
              "comparison_kind": "Observed History", "profile_window": "Last 10 Played With Team"}
    report_at = pd.to_datetime(injury_report.get("fetched_at"), utc=True, errors="coerce")
    tip = pd.to_datetime(tipoff_at, utc=True, errors="coerce")
    if not roster_fresh or roster is None or roster.empty:
        result["reason"] = "Current Roster Unverified"
        return result, features_from_context(result), None
    if pd.notna(tip) and now >= tip:
        result["reason"] = "Pregame Injury Snapshot Required"
        return result, features_from_context(result), None
    if pd.isna(report_at) or report_at > now or (now - report_at).total_seconds() > 21600 or injury_report.get("is_stale_report", False):
        result["reason"] = "Injury Report Unavailable Or Stale"
        return result, features_from_context(result), None
    if cutoff < now.tz_localize(None).normalize():
        result["reason"] = "Pregame Injury Snapshot Required"
        return result, features_from_context(result), None
    members = roster[roster.team_abbreviation.eq(team)].drop_duplicates("player_id")
    if members.empty:
        result["reason"] = "Current Roster Unverified"
        return result, features_from_context(result), None
    team_history = history[history.team_abbreviation.eq(team)].copy() if history is not None and not history.empty else pd.DataFrame()
    aliases = {}
    players = {}
    for member in members.to_dict("records"):
        pid = int(member["player_id"])
        past = team_history[team_history.player_id.eq(pid)] if not team_history.empty else pd.DataFrame()
        names = {str(member.get("player_name", ""))}
        if not past.empty and "player_name" in past:
            names.update(past.player_name.dropna().astype(str).unique())
        name = str(member.get("player_name") or (past.iloc[-1].get("player_name", pid) if not past.empty else pid))
        players[pid] = {"player_id": pid, "player_name": name, "status": "not_listed",
                        "profile": recent_profile(team_history, pid, team, cutoff)}
        for name in names:
            for alias in name_aliases(name):
                aliases.setdefault(alias, set()).add(pid)
    for record in injury_report.get("teams", {}).get(team, []):
        status = normalize_injury_status(record.get("status", "unknown"))
        if status == "available":
            continue
        ids = set()
        for alias in name_aliases(record.get("player_name", "")):
            ids.update(aliases.get(alias, set()))
        if len(ids) != 1:
            result["unmapped"].append({"player_name": record.get("player_name", "Unknown"), "status": status})
            continue
        pid = next(iter(ids))
        # Conflicting status records do not create a confident Out label.
        if players[pid]["status"] not in ("not_listed", status):
            players[pid]["status"] = "unknown"
        else:
            players[pid]["status"] = status
    teammates = [p.copy() for pid, p in players.items() if pid != player_id and p["status"] != "not_listed"]
    teammates.sort(key=lambda p: (p["status"] != "out", -(p["profile"].get("fga") or 0), p["player_id"]))
    for mate in teammates:
        mate["comparison"] = observed_comparison(team_history, participation, player_id, [mate["player_id"]], team, cutoff, now)
    out = [p for p in teammates if p["status"] == "out"]
    unmapped_out = sum(p["status"] == "out" for p in result["unmapped"])
    unknown_profiles = sum(p["profile"]["min"] is None or p["profile"]["fga"] is None for p in out)
    missing = {stat: None if unmapped_out or any(p["profile"][stat] is None for p in out)
               else sum(p["profile"][stat] for p in out) for stat in STATS}
    team_fga = None
    if teams is not None and not teams.empty and "fga" in teams:
        dates = pd.to_datetime(teams.game_date, format="mixed").dt.normalize()
        recent = teams[teams.team_abbreviation.eq(team) & dates.lt(cutoff)].sort_values(["game_date", "game_id"]).drop_duplicates("game_id").tail(10)
        if not recent.empty and recent.fga.notna().all():
            team_fga = safe_mean(recent.fga, complete=True)
    result.update(status="partial" if result["unmapped"] or unknown_profiles else "available",
                  out_count=len(out)+unmapped_out, uncertain_count=sum(p["status"] != "out" for p in teammates)+len(result["unmapped"])-unmapped_out,
                  unmapped_count=len(result["unmapped"]), unknown_profile_count=unknown_profiles,
                  missing=missing, missing_fga_share=missing["fga"] / team_fga if missing["fga"] is not None and team_fga and team_fga > 0 else None,
                  teammates=teammates)
    if out:
        result["joint_comparison"] = observed_comparison(team_history, participation, player_id, [p["player_id"] for p in out], team, cutoff, now)
    snapshot = None
    # Archive real scheduled pregame contexts only, never fabricate a tip time.
    if game_id and pd.notna(tip) and now < tip and not result["unmapped"]:
        snapshot = {"schema_version": 1, "game_id": str(game_id).zfill(10), "game_date": str(cutoff.date()),
                    "team_abbreviation": team, "snapshot_at": now.isoformat(), "tipoff_at": tip.isoformat(),
                    "source_report_at": report_at.isoformat(), "source": result["source"], "team_fga": team_fga,
                    "unmapped_count": 0, "players": list(players.values())}
    return result, features_from_context(result), snapshot
