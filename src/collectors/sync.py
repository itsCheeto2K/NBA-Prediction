import contextlib
import json
import logging
import os
import shutil
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


@contextlib.contextmanager
def _os_file_mutex(lock_path: Path):
    """
    Cross-process OS-level file lock using msvcrt (Windows) or fcntl (POSIX) (§5, §12.1).
    Guarantees mutual exclusion across separate OS processes during lock acquisition, updates, and releases.
    """
    mutex_path = lock_path.with_name(lock_path.name + ".mutex")
    mutex_path.parent.mkdir(parents=True, exist_ok=True)
    f = None
    try:
        f = open(mutex_path, "a+")
        fd = f.fileno()
        try:
            import msvcrt
            start_wait = time.time()
            locked = False
            while time.time() - start_wait < 2.0:
                try:
                    f.seek(0)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    locked = True
                    break
                except OSError:
                    time.sleep(0.05)
            if not locked:
                f.seek(0)
                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        except (ImportError, AttributeError):
            try:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX)
            except (ImportError, AttributeError):
                pass
        yield
    finally:
        if f is not None:
            try:
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            except Exception:
                try:
                    import fcntl
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                except Exception:
                    pass
            try:
                f.close()
            except Exception:
                pass


class SyncLeaseLock:
    """
    Single-owner file-based lease lock (§5, §12.1, Issue 23):
    Prevents concurrent sync workers from corrupting datasets.
    Cross-process mutual exclusion via OS-level file locking.
    Continuous background heartbeat thread prevents expiration during long rebuild operations.
    """
    def __init__(self, lock_file: Path = SYNC_LOCK_FILE, lease_ttl_sec: float = 300.0):
        self.lock_file = lock_file
        self.lease_ttl_sec = lease_ttl_sec
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        self._thread_lock = threading.Lock()
        self._heartbeat_threads: Dict[str, threading.Event] = {}

    def is_locked(self) -> bool:
        with _os_file_mutex(self.lock_file):
            return self._is_locked_unlocked()

    def _is_locked_unlocked(self) -> bool:
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

    def is_owner(self, run_id: str, fencing_token: Optional[int] = None) -> bool:
        with _os_file_mutex(self.lock_file):
            if not self.lock_file.exists():
                return False
            try:
                with open(self.lock_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                now = time.time()
                last_hb = data.get("heartbeat", 0)
                if (now - last_hb) >= self.lease_ttl_sec:
                    return False
                if data.get("run_id") != run_id or data.get("status") != "LOCKED":
                    return False
                if fencing_token is not None and data.get("fencing_token") != fencing_token:
                    return False
                return True
            except Exception:
                return False

    def get_fencing_token(self, run_id: str) -> Optional[int]:
        with _os_file_mutex(self.lock_file):
            if not self.lock_file.exists():
                return None
            try:
                with open(self.lock_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("run_id") == run_id:
                    return data.get("fencing_token")
            except Exception:
                pass
            return None

    def validate_fence(self, run_id: str, fencing_token: Optional[int] = None) -> bool:
        """Validates that worker still owns active, non-expired lease and fencing token matches prior to commit."""
        return self.is_owner(run_id, fencing_token=fencing_token)

    @contextlib.contextmanager
    def commit_guard(self, run_id: str, fencing_token: int):
        """Hold the cross-process mutex from lease validation through publish."""
        with self._thread_lock, _os_file_mutex(self.lock_file):
            try:
                data = json.loads(self.lock_file.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise SyncLockError("Lease disappeared before publish") from exc
            if (data.get("run_id") != run_id or data.get("status") != "LOCKED"
                    or data.get("fencing_token") != fencing_token
                    or time.time() - data.get("heartbeat", 0) >= self.lease_ttl_sec):
                raise SyncLockError("Lease expired or fencing token changed before publish")
            yield

    def acquire(self, run_id: str) -> bool:
        with self._thread_lock:
            with _os_file_mutex(self.lock_file):
                now = time.time()
                if self._is_locked_unlocked():
                    try:
                        with open(self.lock_file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        if data.get("run_id") == run_id:
                            self._start_heartbeat_worker(run_id)
                            return True
                    except Exception:
                        pass
                    return False

                # Read previous fencing token if lock_file exists
                prev_token = 0
                if self.lock_file.exists():
                    try:
                        with open(self.lock_file, "r", encoding="utf-8") as f:
                            prev_token = int(json.load(f).get("fencing_token", 0))
                    except Exception:
                        pass
                fencing_token = max(int(now * 1000), prev_token + 1)

                # Lock is either free or expired -> acquire
                lock_payload = {
                    "run_id": run_id,
                    "owner_pid": os.getpid(),
                    "status": "LOCKED",
                    "acquired_at": datetime.now(timezone.utc).isoformat(),
                    "heartbeat": now,
                    "lease_ttl_sec": self.lease_ttl_sec,
                    "fencing_token": fencing_token,
                }
                try:
                    with open(self.lock_file, "w", encoding="utf-8") as f:
                        json.dump(lock_payload, f, indent=2)
                    self._start_heartbeat_worker(run_id)
                    return True
                except Exception as e:
                    logger.error(f"Failed to write sync lock: {e}")
                    return False

    def _start_heartbeat_worker(self, run_id: str) -> None:
        if run_id in self._heartbeat_threads:
            return
        stop_event = threading.Event()
        self._heartbeat_threads[run_id] = stop_event
        interval = min(15.0, max(0.02, self.lease_ttl_sec / 4.0))

        def _heartbeat_loop():
            while not stop_event.wait(interval):
                try:
                    self.update_heartbeat(run_id)
                except Exception as e:
                    logger.debug(f"Background heartbeat tick failed for {run_id}: {e}")

        hb_thread = threading.Thread(target=_heartbeat_loop, name=f"heartbeat_{run_id}", daemon=True)
        hb_thread.start()

    def update_heartbeat(self, run_id: str) -> None:
        with _os_file_mutex(self.lock_file):
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
            # Stop background heartbeat thread
            if run_id in self._heartbeat_threads:
                stop_event = self._heartbeat_threads.pop(run_id)
                stop_event.set()

            with _os_file_mutex(self.lock_file):
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

    def enqueue_job(self, season: Optional[str] = None, force_refresh: bool = True) -> Dict[str, Any]:
        season = season or settings.ACTIVE_SEASON
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

            # Hot-reload in-memory singletons and models on successful sync
            try:
                from src.features.player_history import PlayerHistoryService
                PlayerHistoryService.reset_instance()
                logger.info("PlayerHistoryService instance reset after sync.")
            except Exception as e:
                logger.warning(f"Could not reset PlayerHistoryService: {e}")

            try:
                from src.api.main import load_resources
                load_resources()
                logger.info("API resources reloaded in-memory after sync.")
            except Exception as e:
                logger.warning(f"Could not reload API resources: {e}")

            # Also refresh ESPN live injury reports
            try:
                from src.collectors.injuries import fetch_espn_injuries
                fetch_espn_injuries(force_refresh=True)
                logger.info("ESPN live injury reports refreshed after sync.")
            except Exception as e:
                logger.warning(f"Could not refresh ESPN injuries: {e}")

            if result.get("status") == SyncJobStatus.SUCCESS.value:
                try:
                    from src.collectors.role_evidence import collect_recent_participation
                    from src.storage.datasets import dataset_view
                    import pandas as pd
                    view = dataset_view()
                    history = pd.read_parquet(view.path("features_all_seasons.parquet"))
                    evidence_result = collect_recent_participation(history, max_games=5)
                    with self._lock:
                        self._jobs[job_id]["result"]["role_evidence"] = evidence_result
                    if evidence_result.get("collected_games", 0) > 0:
                        from src.api.main import refresh_role_evidence
                        refresh_role_evidence()
                    from src.services.role_backfill import start_role_backfill
                    start_role_backfill()
                except Exception as error:
                    logger.warning("Optional role evidence refresh unavailable: %s", error)
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
                data = json.load(f)
            # Ensure last_sync_time is consistently populated to prevent repeated sync triggers (Issue 19)
            if not data.get("last_sync_time"):
                data["last_sync_time"] = data.get("finished_at") or data.get("started_at")
            return data
        except Exception:
            pass
    return {
        "status": "NEVER_SYNCED",
        "last_sync_time": None,
        "latest_game_date": None,
        "season": settings.ACTIVE_SEASON,
    }


def sync_season_data(
    season: Optional[str] = None,
    force_refresh: bool = True,
    job_id: Optional[str] = None,
    client: Optional[NBAClient] = None,
) -> Dict[str, Any]:
    """
    Executes a guarded, single-owner incremental or full sync with complete state machine:
    QUEUED -> RUNNING -> VALIDATING -> COMMITTING -> SUCCESS | PARTIAL | FAILED (§5, §6).
    
    Watermark is advanced ONLY after completeness verification passes.
    Writes parquet files to staging first, validates them, and atomically replaces target parquets (Issue 22).
    """
    season = season or settings.ACTIVE_SEASON
    run_id = job_id or f"run_{uuid.uuid4().hex[:8]}"
    
    # 1. Acquire single-owner lease with cross-process OS lock and continuous heartbeat (Issue 23)
    if not _SYNC_LOCK.acquire(run_id):
        raise SyncLockError(
            f"Could not acquire sync lease lock. Another sync worker is currently running or lease has not expired."
        )
    fencing_token = _SYNC_LOCK.get_fencing_token(run_id)
    from src.storage.datasets import dataset_view, prepare_snapshot, atomic_json
    view = dataset_view(settings.PARQUET_DIR, settings.DATA_DIR)

    settings.create_dirs()
    client = client or NBAClient()
    use_cache = not force_refresh

    logger.info(f"===> [run_id: {run_id}] Starting Sync for Season {season} (force_refresh={force_refresh}) <===")
    start_time = datetime.now(timezone.utc)
    staging_dir = settings.DATA_DIR / "staging" / run_id
    staging_dir.mkdir(parents=True, exist_ok=True)

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

        # Step: VALIDATING (§3, §6, Issue 22)
        # Stage raw files first before touching any production files
        sched_stage = staging_dir / f"schedule_{season}.parquet"
        team_stage = staging_dir / f"team_gamelogs_{season}.parquet"
        player_stage = staging_dir / f"player_gamelogs_{season}.parquet"

        schedule_df.to_parquet(sched_stage, index=False)
        team_logs_df.to_parquet(team_stage, index=False)
        player_logs_df.to_parquet(player_stage, index=False)

        # Membership is independent of boxscore presence. Failure is explicit:
        # API keeps only a labeled appearance-based scenario until refreshed.
        try:
            from src.collectors.roster import fetch_current_roster
            roster = fetch_current_roster(season, client, use_cache=False)
            roster.to_parquet(staging_dir / f"roster_{season}.parquet", index=False)
        except Exception as exc:
            logger.warning(f"Current roster unavailable: {exc}")

        logger.info(f"[{run_id}] Validating dataset completeness...")
        audit = audit_backfill_completeness(schedule_df, team_logs_df, player_logs_df)

        is_complete = (audit.get("status") == "COMPLETE")
        final_status = SyncJobStatus.SUCCESS.value if is_complete else SyncJobStatus.PARTIAL.value

        if not is_complete:
            logger.warning(
                f"[{run_id}] Completeness check resolved to PARTIAL! Missing games: {len(audit.get('missing_game_ids', []))}, "
                f"Mismatched team row games: {len(audit.get('mismatched_team_row_games', []))}"
            )

        # Check lease ownership and fencing token before commit (Issue 23)
        if not _SYNC_LOCK.validate_fence(run_id, fencing_token=fencing_token):
            raise SyncLockError(
                f"Lease lock for run_id {run_id} or fencing token {fencing_token} was lost or invalidated before committing."
            )

        # Step: COMMITTING (§5, §6, Issue 22)
        sched_prod = settings.PARQUET_DIR / f"schedule_{season}.parquet"
        team_prod = settings.PARQUET_DIR / f"team_gamelogs_{season}.parquet"
        player_prod = settings.PARQUET_DIR / f"player_gamelogs_{season}.parquet"

        # Policy: Only replace existing production datasets if validation passes as COMPLETE,
        # or if initial bootstrap seed (no existing production tables).
        should_commit_to_prod = is_complete

        if should_commit_to_prod:
            # Rebuild features in staging first
            all_feat_stage = staging_dir / "features_all_seasons.parquet"
            s_feat_stage = staging_dir / f"features_{season}.parquet"

            all_seasons = settings.SEASONS_WITH_ACTIVE
            combined_players = []
            combined_teams = []

            for s in all_seasons:
                if s == season:
                    p_file = player_stage
                    t_file = team_stage
                else:
                    p_file = view.path(f"player_gamelogs_{s}.parquet")
                    t_file = view.path(f"team_gamelogs_{s}.parquet")

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
                features_df.to_parquet(all_feat_stage, index=False)

                for feature_season, season_frame in features_df.groupby("season"):
                    season_frame.to_parquet(staging_dir / f"features_{feature_season}.parquet", index=False)

            # Expensive copying happens outside the commit lock. A worker which
            # loses its lease during this step cannot publish its result.
            payload = prepare_snapshot(staging_dir, run_id, view, settings.DATA_DIR)
            payload["season"] = season
            payload["committed_at"] = datetime.now(timezone.utc).isoformat()
            with _SYNC_LOCK.commit_guard(run_id, fencing_token):
                atomic_json(settings.DATA_DIR / "snapshots" / "manifest.json", payload)
            logger.info(f"[{run_id}] Published immutable dataset snapshot.")
        else:
            logger.warning(
                f"[{run_id}] Dataset resolved to PARTIAL; existing production files preserved without overwrite."
            )

        latest_game_date = None
        if not player_logs_df.empty and "game_date" in player_logs_df.columns:
            latest_game_date = str(player_logs_df["game_date"].max()).split("T")[0]

        finish_time = datetime.now(timezone.utc)
        duration_sec = round((finish_time - start_time).total_seconds(), 2)

        prev_sync = get_last_sync_info()
        prev_last_successful = prev_sync.get("last_successful_sync_time")

        # Watermark policy: Only advance production watermark and last_successful_sync_time on COMPLETE
        last_successful = finish_time.isoformat() if is_complete else prev_last_successful
        prod_latest_game_date = latest_game_date if is_complete else prev_sync.get("latest_game_date")

        sync_record = {
            "run_id": run_id,
            "status": final_status,
            "last_sync_time": finish_time.isoformat(),
            "last_successful_sync_time": last_successful,
            "started_at": start_time.isoformat(),
            "finished_at": finish_time.isoformat(),
            "season": season,
            "scope": "incremental-results",
            "latest_game_date": prod_latest_game_date,
            "latest_observed_game_date": latest_game_date,
            "latest_game_date_us": f"{prod_latest_game_date} (US ET)" if prod_latest_game_date else None,
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

        atomic_json(SYNC_STATUS_FILE, sync_record)

        logger.info(f"[{run_id}] Sync finalized with status: {final_status} in {duration_sec}s.")
        return sync_record

    finally:
        # Clean up staging directory
        try:
            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)
        except Exception:
            pass
        _SYNC_LOCK.release(run_id)
