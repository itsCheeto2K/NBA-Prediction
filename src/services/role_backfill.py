"""Resumable background backfill for explicit historical participation evidence."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

import pandas as pd

from src.config import settings
from src.collectors.role_evidence import collect_recent_participation, collection_progress
from src.storage.datasets import atomic_json, dataset_view

logger = logging.getLogger(__name__)


class RoleBackfillManager:
    def __init__(self):
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._state = "STOPPED"
        self._last = None
        try:
            status_path = settings.DATA_DIR / "role_evidence" / "backfill_status.json"
            if status_path.exists():
                saved = json.loads(status_path.read_text(encoding="utf-8"))
                if isinstance(saved, dict):
                    self._last = saved
        except (OSError, ValueError, TypeError):
            self._last = None

    def status(self):
        with self._lock:
            payload = dict(self._last or {})
            payload.update({"state": self._state, "running": bool(self._thread and self._thread.is_alive())})
            return payload

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return self.status()
            self._stop.clear()
            self._state = "RUNNING"
            self._thread = threading.Thread(target=self._run, name="role-backfill", daemon=True)
            self._thread.start()
            return self.status()

    def stop(self):
        self._stop.set()
        with self._lock:
            self._state = "STOPPED"
        return self.status()

    def _set(self, payload):
        with self._lock:
            self._last = dict(payload or {})

    def _run(self):
        batch_size = max(1, int(os.getenv("ROLE_BACKFILL_BATCH_SIZE", "10")))
        interval = max(5, int(os.getenv("ROLE_BACKFILL_INTERVAL_SECONDS", "15")))
        retry = max(60, int(os.getenv("ROLE_BACKFILL_RETRY_SECONDS", "600")))
        while not self._stop.is_set():
            try:
                view = dataset_view()
                history = pd.read_parquet(
                    view.path("features_all_seasons.parquet"),
                    columns=["player_id", "game_id", "game_date", "team_abbreviation", "min"],
                )
                result = collect_recent_participation(
                    history, max_games=batch_size, lookback_days=None,
                    request_delay=max(1.0, float(os.getenv("ROLE_BACKFILL_REQUEST_DELAY", "3"))),
                    stop_event=self._stop,
                )
                progress = collection_progress(history, lookback_days=None)
                payload = {**progress, **result, "updated_at": datetime.now(timezone.utc).isoformat()}
                self._set(payload)
                try:
                    atomic_json(settings.DATA_DIR / "role_evidence" / "backfill_status.json", payload)
                except OSError:
                    pass
                if result.get("collected_games", 0) > 0:
                    try:
                        from src.api.main import refresh_role_evidence
                        refresh_role_evidence()
                    except Exception as exc:
                        logger.warning("Role evidence refresh after backfill failed: %s", exc)
                if result.get("status") == "COMPLETE":
                    with self._lock:
                        self._state = "COMPLETE"
                    return
                if result.get("status") in ("UNAVAILABLE", "WAITING_RETRY", "BUSY"):
                    with self._lock:
                        self._state = "WAITING_RETRY"
                    self._stop.wait(retry if result.get("status") == "UNAVAILABLE" else interval)
                    with self._lock:
                        if not self._stop.is_set():
                            self._state = "RUNNING"
                else:
                    self._stop.wait(interval)
            except Exception as exc:
                logger.exception("Role evidence backfill iteration failed")
                self._set({"status": "ERROR", "error": str(exc), "updated_at": datetime.now(timezone.utc).isoformat()})
                with self._lock:
                    self._state = "WAITING_RETRY"
                self._stop.wait(retry)


_MANAGER = RoleBackfillManager()


def get_role_backfill_manager():
    return _MANAGER


def start_role_backfill():
    return _MANAGER.start()


def stop_role_backfill():
    return _MANAGER.stop()

