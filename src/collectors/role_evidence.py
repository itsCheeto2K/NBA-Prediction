"""Small immutable archives for explicit participation and pregame role context."""
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import time
import uuid

import pandas as pd

from src.config import settings
from src.collectors.boxscore import normalize_boxscore_traditional_v3
from src.storage.datasets import atomic_json


def root_path():
    return settings.DATA_DIR / "role_evidence"


def save_pregame_snapshot(snapshot):
    if snapshot is None:
        return None
    # Deduplicate repeated line/odds requests on the same evidence; preserve the
    # first observed time rather than replacing it with a later pregame check.
    content = {k: v for k, v in snapshot.items() if k != "snapshot_at"}
    digest = hashlib.sha256(json.dumps(content, sort_keys=True, allow_nan=False).encode()).hexdigest()[:16]
    path = root_path() / "pregame" / f"{snapshot['game_id']}_{snapshot['team_abbreviation']}_{digest}.json"
    from src.collectors.sync import _os_file_mutex
    with _os_file_mutex(root_path() / "snapshot_write"):
        if not path.exists():
            atomic_json(path, snapshot)
    return path


def load_pregame_snapshots():
    records = []
    for path in (root_path() / "pregame").glob("*.json"):
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return records


def normalize_participation(frame, history, known_at):
    if frame.empty or history.empty:
        return pd.DataFrame()
    if frame.game_id.nunique() != 1:
        raise ValueError("Mixed games in participation response")
    game_id = str(frame.iloc[0].game_id).zfill(10)
    games = history[history.game_id.astype(str).str.zfill(10).eq(game_id)]
    if games.empty:
        return pd.DataFrame()
    dates = pd.to_datetime(games.game_date, format="mixed").dt.normalize().unique()
    if len(dates) != 1:
        raise ValueError("Conflicting game dates for participation evidence")
    game_date = str(pd.Timestamp(dates[0]).date())
    rows = []
    for row in frame.to_dict("records"):
        pid = row.get("player_id")
        team = row.get("team_abbreviation")
        if not pid or not team or team not in set(games.team_abbreviation):
            continue
        if row.get("is_dnp") is True or row.get("is_dnp") == 1:
            state = "did_not_play"
        elif pd.notna(row.get("min")) and row["min"] > 0:
            state = "played"
        else:
            state = "unknown"
        rows.append({"game_id": game_id, "game_date": game_date, "player_id": int(pid),
                     "team_abbreviation": team, "state": state, "known_at": known_at,
                     "source": "NBA BoxScoreTraditionalV3", "reason": str(row.get("comment") or "")})
    return pd.DataFrame(rows)


def cached_participation(history, paths=None):
    frames = []
    raw_paths = paths if paths is not None else (settings.RAW_DIR / "boxscoretraditionalv3").glob("*.json")
    for path in raw_paths:
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            raw = saved.get("raw_response")
            raw = json.loads(raw) if isinstance(raw, str) else raw
            box = (raw or {}).get("boxScoreTraditional", {})
            rows = []
            for side in ("homeTeam", "awayTeam"):
                team = box.get(side, {})
                for player in team.get("players", []):
                    rows.append({**{k: v for k, v in player.items() if k != "statistics"}, **player.get("statistics", {}),
                                 "gameId": box.get("gameId"), "teamTricode": team.get("teamTricode")})
            normalized = normalize_boxscore_traditional_v3(pd.DataFrame(rows))
            if "fetched_at" not in saved:
                continue
            frames.append(normalize_participation(normalized, history, saved["fetched_at"]))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def load_participation(history):
    # Parsing thousands of JSON archives on every application start was one of
    # the dominant cold-start costs. Keep a normalized table plus a source
    # inventory so routine starts can reuse it and new files can be appended.
    try:
        cache_dir = settings.DATA_DIR / "cache" / "role_evidence"
        cache_path = cache_dir / "participation.parquet"
        manifest_path = cache_dir / "participation_manifest.json"
        source_dirs = {
            "participation": root_path() / "participation",
            "raw": settings.RAW_DIR / "boxscoretraditionalv3",
        }
        inventory = {}
        source_paths = {}
        for kind, folder in source_dirs.items():
            try:
                files = sorted(folder.glob("*.json"), key=lambda p: p.name)
            except OSError:
                files = []
            for path in files:
                stat = path.stat()
                key = f"{kind}/{path.name}"
                inventory[key] = [stat.st_size, stat.st_mtime_ns]
                source_paths[key] = path

        previous = {}
        if manifest_path.is_file() and cache_path.is_file():
            try:
                previous = json.loads(manifest_path.read_text(encoding="utf-8"))
                if previous.get("inventory") == inventory:
                    return pd.read_parquet(cache_path)
            except (OSError, ValueError, TypeError):
                previous = {}
        elif not cache_path.exists():
            # Migrate the warm cache from the initial optimized build when no
            # source file is newer than it.
            legacy = sorted(cache_dir.glob("participation_*.parquet"),
                            key=lambda p: p.stat().st_mtime_ns, reverse=True)
            if legacy:
                candidate = legacy[0]
                cache_time = candidate.stat().st_mtime_ns
                source_is_newer = any(path.stat().st_mtime_ns > cache_time for path in source_paths.values())
                if not source_is_newer:
                    cache_dir.mkdir(parents=True, exist_ok=True)
                    import shutil
                    shutil.copy2(candidate, cache_path)
                    atomic_json(manifest_path, {"inventory": inventory})
                    return pd.read_parquet(cache_path)
    except (AttributeError, OSError, TypeError, ValueError):
        cache_path = None
        manifest_path = None
        inventory = {}
        source_paths = {}
        previous = {}

    old_inventory = previous.get("inventory", {}) if isinstance(previous, dict) else {}
    additive = bool(cache_path and cache_path.is_file() and old_inventory
                    and all(key in inventory and inventory[key] == value for key, value in old_inventory.items()))
    if additive:
        frames = [pd.read_parquet(cache_path)]
        new_raw = [source_paths[key] for key in inventory
                   if key.startswith("raw/") and key not in old_inventory]
        if new_raw:
            frames.append(cached_participation(history, new_raw))
        archive_paths = [source_paths[key] for key in inventory
                         if key.startswith("participation/") and key not in old_inventory]
    else:
        frames = [cached_participation(history)]
        archive_paths = list((root_path() / "participation").glob("*.json"))

    for path in archive_paths:
        try:
            records = json.loads(path.read_text(encoding="utf-8"))["records"]
            frames.append(pd.DataFrame(records))
        except (OSError, ValueError, KeyError):
            continue
    frames = [f for f in frames if not f.empty]
    result = pd.concat(frames, ignore_index=True).drop_duplicates() if frames else pd.DataFrame()
    if cache_path is not None:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = cache_path.with_name(cache_path.stem + f".{uuid.uuid4().hex}.tmp.parquet")
            result.to_parquet(temp_path, index=False)
            os.replace(temp_path, cache_path)
            atomic_json(manifest_path, {"inventory": inventory})
        except (OSError, ValueError, TypeError):
            pass
    return result


@lru_cache(maxsize=8192)
def _valid_archive(filename, modified, size, game_id):
    try:
        payload = json.loads(Path(filename).read_text(encoding="utf-8"))
        records = payload["records"]
        if not isinstance(records, list) or not records:
            return False
        return all(str(r["game_id"]).zfill(10) == game_id and isinstance(r["player_id"], int)
                   and r["player_id"] > 0 and r["state"] in ("played", "did_not_play", "unknown")
                   and r.get("team_abbreviation") and pd.notna(pd.to_datetime(r.get("known_at"), utc=True, errors="coerce"))
                   for r in records)
    except (OSError, ValueError, KeyError, TypeError):
        return False


def valid_participation_archive(path, game_id):
    try:
        stat = path.stat()
    except OSError:
        return False
    return _valid_archive(str(path.resolve()), stat.st_mtime_ns, stat.st_size, game_id)


def participation_catalog(history, lookback_days=None):
    if history.empty:
        return history.copy()
    dates = pd.to_datetime(history.game_date, format="mixed")
    mask = history["min"].gt(0)
    if lookback_days is not None:
        mask &= dates.ge(dates.max() - pd.Timedelta(days=lookback_days))
    return history[mask].sort_values(["game_date", "game_id"], ascending=False).drop_duplicates("game_id")


def collection_progress(history, lookback_days=None):
    games = participation_catalog(history, lookback_days)
    completed = sum(valid_participation_archive(root_path() / "participation" / f"{str(gid).zfill(10)}.json", str(gid).zfill(10)) for gid in games.game_id) if not games.empty else 0
    return {"total_games": len(games), "completed_games": completed, "remaining_games": len(games)-completed,
            "first_game_date": str(games.game_date.min())[:10] if not games.empty else None,
            "last_game_date": str(games.game_date.max())[:10] if not games.empty else None}


_COLLECTION_BREAKER = None


def collect_recent_participation(history, max_games=5, lookback_days=60, request_delay=3., stop_event=None):
    """Free NBA boxscores, bounded and fail-fast; called from async sync jobs.

    Never use a player's absence from gamelogs as a DNP label. A failed optional
    collection is reported separately and does not invalidate the main sync.
    """
    from nba_api.stats.endpoints import boxscoretraditionalv3
    from src.client import NBAClient, CircuitBreaker
    from src.collectors.sync import SyncLeaseLock
    global _COLLECTION_BREAKER
    if history.empty:
        return {"status": "NO_HISTORY", "collected_games": 0}
    games = participation_catalog(history, lookback_days)
    lease = SyncLeaseLock(root_path() / "collection_lock.json")
    run_id = "role_collect_" + uuid.uuid4().hex[:12]
    if not lease.acquire(run_id):
        return {"status": "BUSY", "collected_games": 0}
    if _COLLECTION_BREAKER is None:
        _COLLECTION_BREAKER = CircuitBreaker()
    collected = attempted = 0
    status_path = root_path() / "collection_progress.json"
    failure_path = root_path() / "collection_failures.json"
    try:
        try:
            failures = json.loads(failure_path.read_text(encoding="utf-8")) if failure_path.exists() else {}
            if not isinstance(failures, dict):
                failures = {}
        except (OSError, ValueError, TypeError):
            failures = {}
        # Keep optional archive failures isolated from the live sync breaker.
        client = NBAClient(read_timeout=10, max_attempts=1, circuit_breaker=_COLLECTION_BREAKER)
        progress = collection_progress(history, lookback_days)
        def record(status, **extra):
            payload = dict(progress, status=status, run_id=run_id, collected_games=collected,
                           attempted_games=attempted, updated_at=datetime.now(timezone.utc).isoformat(), **extra)
            atomic_json(status_path, payload)
            return payload
        for raw_id in games.game_id.astype(str):
            if stop_event is not None and stop_event.is_set():
                return record("STOPPED")
            game_id = raw_id.zfill(10)
            path = root_path() / "participation" / f"{game_id}.json"
            if valid_participation_archive(path, game_id):
                continue
            retry_at = pd.to_datetime(failures.get(game_id, {}).get("retry_at"), utc=True, errors="coerce")
            if pd.notna(retry_at) and retry_at > pd.Timestamp.now(tz="UTC"):
                continue
            if attempted >= max_games:
                break
            if attempted:
                if stop_event is not None:
                    if stop_event.wait(max(1., request_delay)):
                        return record("STOPPED")
                else:
                    time.sleep(max(1., request_delay))
            attempted += 1
            record("COLLECTING", current_game_id=game_id)
            try:
                endpoint = client.execute(boxscoretraditionalv3.BoxScoreTraditionalV3, params={"game_id": game_id})
                normalized = normalize_boxscore_traditional_v3(endpoint.player_stats.get_data_frame())
                known_at = datetime.now(timezone.utc).isoformat()
                rows = normalize_participation(normalized, history, known_at)
                expected_teams = set(history.loc[history.game_id.astype(str).str.zfill(10).eq(game_id), "team_abbreviation"])
                if rows.empty or set(rows.team_abbreviation) != expected_teams:
                    raise ValueError("Incomplete team boxscore")
                atomic_json(path, {"schema_version": 1, "records": rows.to_dict("records"), "collected_at": known_at})
                failures.pop(game_id, None)
                collected += 1
                progress["completed_games"] += 1
                progress["remaining_games"] -= 1
                record("COLLECTING", last_completed_game_id=game_id)
            except Exception as error:
                message = str(error)
                # Broken individual games are deferred so they cannot block all
                # older history. Network/rate failures stop the whole batch.
                individual = isinstance(error, ValueError) or "404" in message or "400 Client Error" in message
                retry_seconds = 86400 if individual else 600
                failures[game_id] = {"error": message, "retry_at": (pd.Timestamp.now(tz="UTC") + pd.Timedelta(seconds=retry_seconds)).isoformat()}
                atomic_json(failure_path, failures)
                if not individual:
                    return record("UNAVAILABLE", error=message, retry_after_seconds=retry_seconds)
        atomic_json(failure_path, failures)
        if progress["remaining_games"] == 0:
            return record("COMPLETE")
        if not attempted:
            return record("WAITING_RETRY", retry_after_seconds=600)
        return record("SUCCESS", deferred_games=len(failures))
    finally:
        lease.release(run_id)
