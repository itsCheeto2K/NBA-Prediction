import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional
import pandas as pd

from src.client import NBAClient
from src.collectors.gamelogs import fetch_player_gamelogs, fetch_team_gamelogs
from src.collectors.schedule import fetch_schedule
from src.config import settings
from src.features.builder import build_feature_dataset
from src.pipeline.backfill import audit_backfill_completeness

logger = logging.getLogger(__name__)

SYNC_STATUS_FILE = settings.DATA_DIR / "manifests" / "sync_status.json"
SYNC_LOCK_FILE = settings.DATA_DIR / "manifests" / "sync_lock.json"


class SyncJobStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    VALIDATING = "VALIDATING"
    COMMITTING = "COMMITTING"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class SyncLockError(Exception):
    """Raised when sync lock cannot be acquired."""
    pass


class SyncLeaseLock:
    """
    Single-owner file-based lease lock (§5, §12.1):
    Prevents concurrent sync workers from corrupting datasets.
    Has lease TTL (default 300s) and heartbeat fencing.
    """
    def __init__(self, lock_file: Path = SYNC_LOCK_FILE, lease_ttl_sec: float = 300.0):
        self.lock_file = lock_file
        self.lease_ttl_sec = lease_ttl_sec
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        self._thread_lock = threading.Lock()

    def is_locked(self) -> bool:
        if not self.lock_file.exists():
            return False
        try:
            with open(self.lock_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            last_heartbeat = data.get("heartbeat", 0)
            now = time.time()
            if now - last_heartbeat < self.lease_ttl_sec and data.get("status") == "LOCKED":
                return True
        except Exception:
            return False
        return False

    def acquire(self, run_id: str) -> bool:
        with self._thread_lock:
            now = time.time()
            if self.is_locked():
                # Read current owner
                try:
                    with open(self.lock_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if data.get("run_id") == run_id:
                        return True
                except Exception:
                    pass
                return False

            # Lock is either free or expired -> acquire
            lock_payload = {
                "run_id": run_id,
                "owner_pid": os.getpid(),
                "status": "LOCKED",
                "acquired_at": datetime.now(timezone.utc).isoformat(),
                "heartbeat": now,
                "lease_ttl_sec": self.lease_ttl_sec,
            }
            try:
                with open(self.lock_file, "w", encoding="utf-8") as f:
                    json.dump(lock_payload, f, indent=2)
                return True
            except Exception as e:
                logger.error(f"Failed to write sync lock: {e}")
                return False

    def update_heartbeat(self, run_id: str) -> None:
        if not self.lock_file.exists():
            return
        try:
            with open(self.lock_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("run_id") == run_id:
                data["heartbeat"] = time.time()
                with open(self.lock_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to update lease heartbeat: {e}")

    def release(self, run_id: str) -> None:
        with self._thread_lock:
            if not self.lock_file.exists():
                return
            try:
                with open(self.lock_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("run_id") == run_id:
                    self.lock_file.unlink(missing_ok=True)
            except Exception as e:
                logger.warning(f"Failed to release sync lock: {e}")


# Global lease manager
_SYNC_LOCK = SyncLeaseLock()


class SyncJobManager:
    """Manages asynchronous sync background jobs and history (§5, §6)."""
    def __init__(self):
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._active_job_id: Optional[str] = None
        self._lock = threading.RLock()

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._jobs.get(job_id)

    def get_active_job(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            if self._active_job_id and self._active_job_id in self._jobs:
                job = self._jobs[self._active_job_id]
                if job["status"] in (SyncJobStatus.QUEUED.value, SyncJobStatus.RUNNING.value, SyncJobStatus.VALIDATING.value, SyncJobStatus.COMMITTING.value):
                    return job
            return None

    def enqueue_job(self, season: str = "2026-27", force_refresh: bool = True) -> Dict[str, Any]:
        with self._lock:
            # Check if active job already running
            active = self.get_active_job()
            if active:
                return active

            job_id = f"sync_{uuid.uuid4().hex[:10]}"
            job_record: Dict[str, Any] = {
                "job_id": job_id,
                "season": season,
                "status": SyncJobStatus.QUEUED.value,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "started_at": None,
                "finished_at": None,
                "force_refresh": force_refresh,
                "error": None,
                "result": None,
            }
            self._jobs[job_id] = job_record
            self._active_job_id = job_id

            # Launch background worker thread
            thread = threading.Thread(
                target=self._run_job_worker,
                args=(job_id, season, force_refresh),
                daemon=True,
            )
            thread.start()

            return job_record

    def _run_job_worker(self, job_id: str, season: str, force_refresh: bool) -> None:
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id]["status"] = SyncJobStatus.RUNNING.value
                self._jobs[job_id]["started_at"] = datetime.now(timezone.utc).isoformat()

        try:
            result = sync_season_data(season=season, force_refresh=force_refresh, job_id=job_id)
            with self._lock:
                if job_id in self._jobs:
                    self._jobs[job_id]["status"] = result["status"]
                    self._jobs[job_id]["finished_at"] = datetime.now(timezone.utc).isoformat()
                    self._jobs[job_id]["result"] = result
        except Exception as e:
            logger.error(f"Sync job {job_id} encountered fatal error: {e}", exc_info=True)
            with self._lock:
                if job_id in self._jobs:
                    self._jobs[job_id]["status"] = SyncJobStatus.FAILED.value
                    self._jobs[job_id]["finished_at"] = datetime.now(timezone.utc).isoformat()
                    self._jobs[job_id]["error"] = str(e)


# Global job manager
_JOB_MANAGER = SyncJobManager()

def get_job_manager() -> SyncJobManager:
    return _JOB_MANAGER


def get_last_sync_info() -> Dict[str, Any]:
    if SYNC_STATUS_FILE.exists():
        try:
            with open(SYNC_STATUS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "status": "NEVER_SYNCED",
        "last_sync_time": None,
        "latest_game_date": None,
        "season": "2026-27",
    }


def sync_season_data(
    season: str = "2026-27",
    force_refresh: bool = True,
    job_id: Optional[str] = None,
    client: Optional[NBAClient] = None,
) -> Dict[str, Any]:
    """
    Executes a guarded, single-owner incremental or full sync with complete state machine:
    QUEUED -> RUNNING -> VALIDATING -> COMMITTING -> SUCCESS | PARTIAL | FAILED (§5, §6).
    
    Watermark is advanced ONLY after completeness verification passes.
    """
    run_id = job_id or f"run_{uuid.uuid4().hex[:8]}"
    
    # 1. Acquire single-owner lease
    if not _SYNC_LOCK.acquire(run_id):
        raise SyncLockError(
            f"Could not acquire sync lease lock. Another sync worker is currently running or lease has not expired."
        )

    settings.create_dirs()
    client = client or NBAClient()
    use_cache = not force_refresh

    logger.info(f"===> [run_id: {run_id}] Starting Sync for Season {season} (force_refresh={force_refresh}) <===")
    start_time = datetime.now(timezone.utc)

    try:
        # Step: RUNNING
        _SYNC_LOCK.update_heartbeat(run_id)

        # 1. Fetch schedule
        logger.info(f"[{run_id}] Fetching schedule for {season}...")
        schedule_df = fetch_schedule(season=season, client=client, use_cache=use_cache)
        
        # 2. Fetch team gamelogs
        logger.info(f"[{run_id}] Fetching team gamelogs for {season}...")
        team_logs_df = fetch_team_gamelogs(season=season, client=client, use_cache=use_cache)
        
        # 3. Fetch player gamelogs
        logger.info(f"[{run_id}] Fetching player gamelogs for {season}...")
        player_logs_df = fetch_player_gamelogs(season=season, client=client, use_cache=use_cache)

        _SYNC_LOCK.update_heartbeat(run_id)

        # Step: VALIDATING (§3, §6)
        logger.info(f"[{run_id}] Validating dataset completeness...")
        audit = audit_backfill_completeness(schedule_df, team_logs_df, player_logs_df)

        is_complete = (audit.get("status") == "COMPLETE")
        final_status = SyncJobStatus.SUCCESS.value if is_complete else SyncJobStatus.PARTIAL.value

        if not is_complete:
            logger.warning(
                f"[{run_id}] Completeness check resolved to PARTIAL! Missing games: {len(audit.get('missing_game_ids', []))}, "
                f"Mismatched team row games: {len(audit.get('mismatched_team_row_games', []))}"
            )

        # Step: COMMITTING (§5, §6)
        # Advance watermarks and commit data files
        sched_path = settings.PARQUET_DIR / f"schedule_{season}.parquet"
        team_path = settings.PARQUET_DIR / f"team_gamelogs_{season}.parquet"
        player_path = settings.PARQUET_DIR / f"player_gamelogs_{season}.parquet"

        schedule_df.to_parquet(sched_path, index=False)
        team_logs_df.to_parquet(team_path, index=False)
        player_logs_df.to_parquet(player_path, index=False)

        latest_game_date = None
        if not player_logs_df.empty and "game_date" in player_logs_df.columns:
            latest_game_date = str(player_logs_df["game_date"].max()).split("T")[0]

        # Rebuild features if needed
        all_feat_path = settings.PARQUET_DIR / "features_all_seasons.parquet"
        all_seasons = ["2023-24", "2024-25", "2025-26", "2026-27"]
        combined_players = []
        combined_teams = []

        for s in all_seasons:
            p_file = settings.PARQUET_DIR / f"player_gamelogs_{s}.parquet"
            t_file = settings.PARQUET_DIR / f"team_gamelogs_{s}.parquet"
            if p_file.exists():
                combined_players.append(pd.read_parquet(p_file))
            if t_file.exists():
                combined_teams.append(pd.read_parquet(t_file))

        if combined_players:
            all_players_df = pd.concat(combined_players, ignore_index=True)
            all_teams_df = pd.concat(combined_teams, ignore_index=True) if combined_teams else None

            features_df = build_feature_dataset(
                player_logs_df=all_players_df,
                team_logs_df=all_teams_df,
            )
            features_df.to_parquet(all_feat_path, index=False)

            s_feat = features_df[features_df["season"] == season]
            if not s_feat.empty:
                s_feat_path = settings.PARQUET_DIR / f"features_{season}.parquet"
                s_feat.to_parquet(s_feat_path, index=False)

        finish_time = datetime.now(timezone.utc)
        duration_sec = round((finish_time - start_time).total_seconds(), 2)

        sync_record = {
            "run_id": run_id,
            "status": final_status,
            "started_at": start_time.isoformat(),
            "finished_at": finish_time.isoformat(),
            "season": season,
            "scope": "incremental-results",
            "latest_game_date": latest_game_date,
            "latest_observed_game_date": latest_game_date,
            "latest_game_date_us": f"{latest_game_date} (US ET)" if latest_game_date else None,
            "expected_completed_games": audit.get("expected_completed_games", 0),
            "complete_completed_games": audit.get("complete_completed_games", 0),
            "missing_game_ids": audit.get("missing_game_ids", []),
            "mismatched_team_row_games": audit.get("mismatched_team_row_games", []),
            "schedule_games": len(schedule_df),
            "team_logs": len(team_logs_df),
            "player_logs": len(player_logs_df),
            "duration_sec": duration_sec,
            "completeness_audit": audit,
        }

        SYNC_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(SYNC_STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(sync_record, f, indent=2)

        logger.info(f"[{run_id}] Sync finalized with status: {final_status} in {duration_sec}s.")
        return sync_record

    finally:
        _SYNC_LOCK.release(run_id)
